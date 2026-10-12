"""One polling pass: find unanswered lead messages, decide, act, record."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from .models import Action, Decision, Lead, LeadType
from .notifier import Notifier
from .store import Store

log = logging.getLogger(__name__)


class LeadSource(Protocol):
    def fetch_open_leads(self, lookback_days: int) -> list[Lead]: ...
    def send_message(self, lead_resource_name: str, text: str) -> str: ...


class DecisionMaker(Protocol):
    def decide(self, lead: Lead) -> Decision: ...


@dataclass
class PassStats:
    replied: int = 0
    escalated: int = 0
    skipped: int = 0
    errors: int = 0


class Engine:
    def __init__(
        self,
        source: LeadSource,
        responder: DecisionMaker,
        store: Store,
        notifier: Notifier,
        lookback_days: int = 7,
        max_auto_replies_per_lead: int = 3,
        dry_run: bool = True,
    ):
        self.source = source
        self.responder = responder
        self.store = store
        self.notifier = notifier
        self.lookback_days = lookback_days
        self.max_auto_replies = max_auto_replies_per_lead
        self.dry_run = dry_run

    def run_once(self) -> PassStats:
        stats = PassStats()
        for lead in self.source.fetch_open_leads(self.lookback_days):
            try:
                self._handle(lead, stats)
            except Exception:
                stats.errors += 1
                log.exception("failed to handle lead %s; will retry next pass", lead.id)
        log.info("pass done: %s", stats)
        return stats

    def _handle(self, lead: Lead, stats: PassStats) -> None:
        if self.store.is_escalated(lead.resource_name):
            return

        if lead.lead_type != LeadType.MESSAGE:
            # Phone-call and booking leads can't be answered in a message thread;
            # the fastest win is a person calling the customer back.
            self._escalate(lead, f"{lead.lead_type.value.lower()} lead - call the customer back", None, stats)
            return

        msg = lead.last_consumer_message
        if msg is None or self.store.is_handled(lead.resource_name, msg.id, include_dry_run=self.dry_run):
            return

        if self.store.auto_reply_count(lead.resource_name) >= self.max_auto_replies:
            self._escalate(lead, f"reached {self.max_auto_replies} automatic replies", msg.id, stats)
            return

        decision = self.responder.decide(lead)

        if decision.action == Action.REPLY:
            if self.dry_run:
                log.info("[dry-run] would reply to lead %s:\n%s", lead.id, decision.message)
            else:
                self.source.send_message(lead.resource_name, decision.message)
                log.info("replied to lead %s", lead.id)
            self.store.record(lead.resource_name, msg.id, "reply", decision.message, decision.reason, self.dry_run)
            stats.replied += 1
        elif decision.action == Action.ESCALATE:
            if decision.message and not self.dry_run:
                self.source.send_message(lead.resource_name, decision.message)
            self._escalate(lead, decision.reason or "model asked for a human", msg.id, stats, decision.message)
        else:
            self.store.record(lead.resource_name, msg.id, "skip", "", decision.reason, self.dry_run)
            stats.skipped += 1

    def _escalate(
        self, lead: Lead, reason: str, message_id: str | None, stats: PassStats, holding_reply: str = ""
    ) -> None:
        stats.escalated += 1
        if self.dry_run:
            log.info("[dry-run] would escalate lead %s: %s", lead.id, reason)
            if holding_reply:
                log.info("[dry-run] would send holding reply:\n%s", holding_reply)
            if message_id:
                self.store.record(lead.resource_name, message_id, "escalate", holding_reply, reason, True)
            return
        self.notifier.escalate(lead, reason)
        if message_id:
            self.store.record(lead.resource_name, message_id, "escalate", holding_reply, reason, False)
        # Once a person owns the lead, the bot stays out of the thread.
        self.store.mark_escalated(lead.resource_name)
