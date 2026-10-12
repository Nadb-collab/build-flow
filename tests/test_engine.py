import json
from types import SimpleNamespace

import pytest

from leadbot.config import BusinessProfile
from leadbot.engine import Engine
from leadbot.models import Action, Decision, Lead, LeadType, Message, Participant
from leadbot.notifier import Notifier
from leadbot.responder import Responder, render_transcript
from leadbot.store import Store


def msg(id, who, ts, text="hi"):
    return Message(id=id, participant=Participant(who), channel="MESSAGE", timestamp=ts, text=text)


def lead(name="customers/1/localServicesLeads/1", type=LeadType.MESSAGE, messages=()):
    return Lead(
        resource_name=name, id=name.rsplit("/", 1)[-1], lead_type=type, status="NEW",
        created_at="2026-10-12 09:00:00", consumer_name="Dana", messages=list(messages),
    )


class FakeSource:
    def __init__(self, leads):
        self.leads = leads
        self.sent = []

    def fetch_open_leads(self, lookback_days):
        return self.leads

    def send_message(self, lead_resource_name, text):
        self.sent.append((lead_resource_name, text))
        return "conv"


class FakeResponder:
    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    def decide(self, lead):
        self.calls += 1
        return self.decision


class FakeNotifier(Notifier):
    def __init__(self):
        self.escalations = []

    def escalate(self, lead, reason):
        self.escalations.append((lead.id, reason))


def make_engine(leads, decision, dry_run=False, max_replies=3):
    source, responder, notifier = FakeSource(leads), FakeResponder(decision), FakeNotifier()
    engine = Engine(source, responder, Store(":memory:"), notifier, dry_run=dry_run, max_auto_replies_per_lead=max_replies)
    return engine, source, responder, notifier


REPLY = Decision(Action.REPLY, "Hi Dana, happy to help!", "answered")


def test_replies_once_to_new_consumer_message():
    l = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00", "My sink is leaking")])
    engine, source, responder, _ = make_engine([l], REPLY)
    engine.run_once()
    engine.run_once()
    assert source.sent == [(l.resource_name, "Hi Dana, happy to help!")]
    assert responder.calls == 1


def test_ignores_thread_where_business_spoke_last():
    l = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00"), msg("2", "ADVERTISER", "2026-10-12 09:05:00")])
    engine, source, responder, _ = make_engine([l], REPLY)
    engine.run_once()
    assert responder.calls == 0 and source.sent == []


def test_answers_follow_up_message():
    l = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00")])
    engine, source, _, _ = make_engine([l], REPLY)
    engine.run_once()
    l.messages += [msg("2", "ADVERTISER", "2026-10-12 09:01:00"), msg("3", "CONSUMER", "2026-10-12 09:10:00")]
    engine.run_once()
    assert len(source.sent) == 2


def test_dry_run_sends_nothing_and_does_not_repeat():
    l = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00")])
    engine, source, responder, _ = make_engine([l], REPLY, dry_run=True)
    engine.run_once()
    engine.run_once()
    assert source.sent == [] and responder.calls == 1


def test_phone_lead_is_escalated_once():
    l = lead(type=LeadType.PHONE_CALL)
    engine, source, responder, notifier = make_engine([l], REPLY)
    engine.run_once()
    engine.run_once()
    assert len(notifier.escalations) == 1 and responder.calls == 0 and source.sent == []


def test_escalation_sends_holding_reply_and_stops_bot():
    l = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00", "Water everywhere!")])
    decision = Decision(Action.ESCALATE, "Please call us now at (512) 555-0100.", "flooding")
    engine, source, responder, notifier = make_engine([l], decision)
    engine.run_once()
    l.messages += [msg("2", "CONSUMER", "2026-10-12 09:02:00", "hello?")]
    engine.run_once()
    assert source.sent == [(l.resource_name, "Please call us now at (512) 555-0100.")]
    assert notifier.escalations == [("1", "flooding")]
    assert responder.calls == 1


def test_reply_cap_hands_off_to_human():
    l = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00")])
    engine, source, _, notifier = make_engine([l], REPLY, max_replies=1)
    engine.run_once()
    l.messages += [msg("2", "CONSUMER", "2026-10-12 09:05:00")]
    engine.run_once()
    assert len(source.sent) == 1 and len(notifier.escalations) == 1


def test_error_on_one_lead_does_not_block_others():
    good = lead("customers/1/localServicesLeads/2", messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00")])
    bad = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00")])
    engine, source, _, _ = make_engine([bad, good], REPLY)
    real_send = source.send_message
    source.send_message = lambda name, text: (_ for _ in ()).throw(RuntimeError()) if name == bad.resource_name else real_send(name, text)
    stats = engine.run_once()
    assert stats.errors == 1 and source.sent == [(good.resource_name, REPLY.message)]


# --- responder -------------------------------------------------------------

PROFILE = BusinessProfile(name="Acme Plumbing", trade="Plumber", service_area="Austin", hours="9-5", phone="555")


def fake_claude(payload, stop_reason="end_turn"):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        text = json.dumps(payload) if isinstance(payload, dict) else payload
        return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client, captured


def test_responder_parses_decision_and_sends_transcript():
    client, captured = fake_claude({"action": "reply", "message": " Hi! ", "reason": "ok"})
    l = lead(messages=[msg("1", "CONSUMER", "2026-10-12 09:00:00", "Need a drain cleaned")])
    d = Responder(PROFILE, client=client).decide(l)
    assert d == Decision(Action.REPLY, "Hi!", "ok")
    assert "Need a drain cleaned" in captured["messages"][0]["content"]
    assert "Acme Plumbing" in captured["system"][0]["text"]
    assert captured["fallbacks"] == "default"


@pytest.mark.parametrize(
    "payload,stop",
    [
        ({"action": "reply", "message": "", "reason": ""}, "end_turn"),
        ({"action": "reply", "message": "x" * 2000, "reason": ""}, "end_turn"),
        ("", "refusal"),
    ],
)
def test_responder_escalates_when_output_unusable(payload, stop):
    client, _ = fake_claude(payload, stop)
    d = Responder(PROFILE, client=client).decide(lead(messages=[msg("1", "CONSUMER", "t")]))
    assert d.action == Action.ESCALATE and d.message == ""


def test_transcript_is_chronological():
    l = lead(messages=[msg("2", "ADVERTISER", "2026-10-12 10:00:00", "B"), msg("1", "CONSUMER", "2026-10-12 09:00:00", "A")])
    t = render_transcript(l)
    assert t.index("Customer: A") < t.index("Business: B")
