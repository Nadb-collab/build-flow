# leadbot: auto-answer Google Guaranteed (Local Services Ads) leads

Leads from Google Local Services Ads go cold within minutes. `leadbot` checks your
LSA account on a timer and handles each new lead:

| Lead type | What happens |
|---|---|
| **Message lead**, customer spoke last | Claude drafts a reply that uses only facts from your business profile. The reply is posted in the same LSA thread through the Google Ads API (`LocalServicesLeadService.AppendLeadConversation`). |
| Message needing a person (emergency, complaint, "let me talk to someone", anything in your hand-off list) | An optional holding reply goes out (for example, "call us now at ..."). Your team gets a webhook ping and the bot stops replying on that lead. |
| **Phone-call / booking lead** | These can't be answered in a thread, so your team gets a ping to call the customer back. |
| Spam, or a closing "thanks" | Skipped. |

Safeguards:
- **Dry-run is the default.** Nothing is sent until you pass `--live` or set `dry_run = false`.
- Each customer message is answered **once**. This is tracked in SQLite.
- After `max_auto_replies_per_lead` replies, the lead goes to a person.
- The prompt forbids invented prices or facts and treats customer text as untrusted.
- If a draft is empty or too long, or the model refuses, the lead goes to a person instead of being sent.
- An error on one lead doesn't block the others. The lead is retried on the next pass.

## Setup

1. **Google Ads API access.** Your Local Services account must be reachable through the Google Ads API.
   - You need a developer token, OAuth client ID and secret, and a refresh token.
   - Copy `google-ads.example.yaml` to `google-ads.yaml` and fill it in. On a server, you can set the `GOOGLE_ADS_*` environment variables listed in that file instead. They're used when `google-ads.yaml` doesn't exist.
   - Setup guide: <https://developers.google.com/google-ads/api/docs/get-started/introduction>
2. **Anthropic API key.** Set `export ANTHROPIC_API_KEY=...`.
3. **Business profile.** Copy `config/business.example.toml` to `config/business.toml`.
   - Set your customer ID, services, service area, hours, pricing guidance and hand-off rules.
   - The quality of the replies depends on this file.
4. Install:

   ```bash
   python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
   ```

## Run

```bash
leadbot run                 # one pass, dry-run: logs what it would send
leadbot run --live          # one pass, really sends
leadbot run --loop --live   # keep polling every poll_interval_seconds
```

To run it unattended, use any scheduler: a cron entry running `leadbot run --live` every 2 minutes, a systemd service with `--loop`, or a Cloud Run job.

## Layout

- `leadbot/google_lsa.py`: GAQL queries for leads and conversations, and sending replies.
- `leadbot/responder.py`: the Claude prompt and structured reply / escalate / skip decision.
- `leadbot/engine.py`: one polling pass, plus dedup, reply cap and hand-off rules.
- `leadbot/store.py`: SQLite record of handled messages.
- `leadbot/notifier.py`: escalation webhook (Slack, Teams, or anything that accepts `{"text": ...}`).

## Tests

```bash
.venv/bin/python -m pytest
```
