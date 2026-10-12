"""Tells a human about leads the bot will not answer on its own."""

from __future__ import annotations

import json
import logging
import urllib.request

from .models import Lead

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url: str = ""):
        self._url = webhook_url

    def escalate(self, lead: Lead, reason: str) -> None:
        text = (
            f"Google LSA lead needs a person: {reason}\n"
            f"Customer: {lead.consumer_name or 'unknown'} {lead.phone_number}\n"
            f"Type: {lead.lead_type.value}, status: {lead.status}, lead id: {lead.id}"
        )
        log.warning(text)
        if not self._url:
            return
        req = urllib.request.Request(
            self._url,
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except OSError:
            log.exception("escalation webhook failed")
