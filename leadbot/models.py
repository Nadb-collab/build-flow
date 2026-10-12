"""Plain data types shared by the Google client, the responder and the engine.

Kept free of google-ads / anthropic imports so the core logic is testable
with fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LeadType(str, Enum):
    MESSAGE = "MESSAGE"
    PHONE_CALL = "PHONE_CALL"
    BOOKING = "BOOKING"
    UNKNOWN = "UNKNOWN"


class Participant(str, Enum):
    CONSUMER = "CONSUMER"
    ADVERTISER = "ADVERTISER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Message:
    id: str
    participant: Participant
    channel: str  # MESSAGE, SMS, EMAIL, PHONE_CALL, BOOKING, ADS_API, ...
    timestamp: str  # "YYYY-MM-DD HH:MM:SS" in the account's time zone
    text: str = ""


@dataclass
class Lead:
    resource_name: str
    id: str
    lead_type: LeadType
    status: str
    created_at: str
    consumer_name: str = ""
    phone_number: str = ""
    category_id: str = ""
    service_id: str = ""
    locale: str = ""
    messages: list[Message] = field(default_factory=list)

    @property
    def last_consumer_message(self) -> Message | None:
        """The newest consumer message, if no advertiser reply follows it."""
        ordered = sorted(self.messages, key=lambda m: (m.timestamp, m.id))
        if not ordered or ordered[-1].participant != Participant.CONSUMER:
            return None
        return ordered[-1]


class Action(str, Enum):
    REPLY = "reply"
    ESCALATE = "escalate"  # a human must take over; nothing is sent
    SKIP = "skip"  # nothing worth answering (spam, "thanks", etc.)


@dataclass(frozen=True)
class Decision:
    action: Action
    message: str
    reason: str
