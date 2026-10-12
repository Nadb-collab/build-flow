"""Business profile + runtime settings, loaded from a TOML file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    customer_id: str  # Google Ads customer ID of the LSA account, digits only
    login_customer_id: str = ""  # manager (MCC) ID, if you access through one
    google_ads_config: str = "google-ads.yaml"
    db_path: str = "leadbot.db"
    lookback_days: int = 7
    poll_interval_seconds: int = 120
    max_auto_replies_per_lead: int = 3
    escalation_webhook_url: str = ""  # Slack/Teams/any JSON webhook
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    dry_run: bool = True


@dataclass
class BusinessProfile:
    name: str
    trade: str
    service_area: str
    hours: str
    phone: str
    services: list[str] = field(default_factory=list)
    not_offered: list[str] = field(default_factory=list)
    pricing_notes: str = ""
    booking_instructions: str = ""
    tone: str = "friendly, professional, concise"
    signature: str = ""
    extra_facts: list[str] = field(default_factory=list)
    escalate_when: list[str] = field(default_factory=list)

    def as_prompt(self) -> str:
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {i}" for i in items) or "- (none listed)"

        return (
            f"Business name: {self.name}\n"
            f"Trade: {self.trade}\n"
            f"Service area: {self.service_area}\n"
            f"Hours: {self.hours}\n"
            f"Phone: {self.phone}\n"
            f"Services offered:\n{bullets(self.services)}\n"
            f"Services NOT offered:\n{bullets(self.not_offered)}\n"
            f"Pricing guidance: {self.pricing_notes or '(none - do not quote prices)'}\n"
            f"How to book: {self.booking_instructions or '(ask for a good time to call)'}\n"
            f"Other facts:\n{bullets(self.extra_facts)}\n"
            f"Tone: {self.tone}\n"
            f"Sign messages as: {self.signature or self.name}\n"
            f"Hand off to a human when:\n{bullets(self.escalate_when)}"
        )


@dataclass
class Config:
    settings: Settings
    business: BusinessProfile


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    settings = Settings(**raw.get("settings", {}))
    settings.customer_id = settings.customer_id.replace("-", "")
    settings.login_customer_id = settings.login_customer_id.replace("-", "")
    return Config(settings=settings, business=BusinessProfile(**raw["business"]))
