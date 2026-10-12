"""Thin wrapper over the Google Ads API for Local Services (Google Guaranteed) leads.

Reads leads + their conversations with GAQL and posts replies with
LocalServicesLeadService.AppendLeadConversation, which delivers the text to
the consumer in the same thread they started from the LSA listing.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Iterable

from google.ads.googleads.client import GoogleAdsClient

from .models import Lead, LeadType, Message, Participant

_OPEN_STATUSES = ("NEW", "ACTIVE")

_LEAD_QUERY = """
SELECT
  local_services_lead.resource_name,
  local_services_lead.id,
  local_services_lead.lead_type,
  local_services_lead.lead_status,
  local_services_lead.category_id,
  local_services_lead.service_id,
  local_services_lead.locale,
  local_services_lead.creation_date_time,
  local_services_lead.contact_details.consumer_name,
  local_services_lead.contact_details.phone_number
FROM local_services_lead
WHERE local_services_lead.creation_date_time >= '{since}'
  AND local_services_lead.lead_status IN ({statuses})
ORDER BY local_services_lead.creation_date_time DESC
"""

_CONVERSATION_QUERY = """
SELECT
  local_services_lead_conversation.id,
  local_services_lead_conversation.lead,
  local_services_lead_conversation.conversation_channel,
  local_services_lead_conversation.participant_type,
  local_services_lead_conversation.event_date_time,
  local_services_lead_conversation.message_details.text
FROM local_services_lead_conversation
WHERE local_services_lead_conversation.lead IN ({leads})
"""


class LsaClient:
    def __init__(self, client: GoogleAdsClient, customer_id: str):
        self._client = client
        self._customer_id = customer_id
        self._ga = client.get_service("GoogleAdsService")
        self._lead_service = client.get_service("LocalServicesLeadService")

    @classmethod
    def from_config(cls, path: str, customer_id: str, login_customer_id: str = "") -> "LsaClient":
        """Load credentials from the google-ads.yaml at `path`, or from GOOGLE_ADS_* env vars if it doesn't exist."""
        if os.path.exists(path):
            client = GoogleAdsClient.load_from_storage(path)
        elif os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN"):
            client = GoogleAdsClient.load_from_env()
        else:
            raise FileNotFoundError(
                f"No Google Ads credentials: create {path} (see google-ads.example.yaml) "
                "or set the GOOGLE_ADS_* environment variables"
            )
        if login_customer_id:
            client.login_customer_id = login_customer_id
        return cls(client, customer_id)

    def _search(self, query: str) -> Iterable:
        for batch in self._ga.search_stream(customer_id=self._customer_id, query=query):
            yield from batch.results

    def fetch_open_leads(self, lookback_days: int) -> list[Lead]:
        since = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d %H:%M:%S")
        statuses = ", ".join(f"'{s}'" for s in _OPEN_STATUSES)
        leads: dict[str, Lead] = {}
        for row in self._search(_LEAD_QUERY.format(since=since, statuses=statuses)):
            l = row.local_services_lead
            leads[l.resource_name] = Lead(
                resource_name=l.resource_name,
                id=str(l.id),
                lead_type=_enum(LeadType, l.lead_type.name),
                status=l.lead_status.name,
                created_at=l.creation_date_time,
                consumer_name=l.contact_details.consumer_name,
                phone_number=l.contact_details.phone_number,
                category_id=l.category_id,
                service_id=l.service_id,
                locale=l.locale,
            )
        self._attach_conversations(leads)
        return list(leads.values())

    def _attach_conversations(self, leads: dict[str, Lead], chunk: int = 200) -> None:
        names = list(leads)
        for i in range(0, len(names), chunk):
            in_list = ", ".join(f"'{n}'" for n in names[i : i + chunk])
            for row in self._search(_CONVERSATION_QUERY.format(leads=in_list)):
                c = row.local_services_lead_conversation
                lead = leads.get(c.lead)
                if lead is None:
                    continue
                lead.messages.append(
                    Message(
                        id=str(c.id),
                        participant=_enum(Participant, c.participant_type.name),
                        channel=c.conversation_channel.name,
                        timestamp=c.event_date_time,
                        text=c.message_details.text,
                    )
                )

    def send_message(self, lead_resource_name: str, text: str) -> str:
        """Append an advertiser message to the lead thread. Returns the new conversation resource name."""
        conversation = self._client.get_type("Conversation")
        conversation.local_services_lead = lead_resource_name
        conversation.text = text
        request = self._client.get_type("AppendLeadConversationRequest")
        request.customer_id = self._customer_id
        request.conversations.append(conversation)
        response = self._lead_service.append_lead_conversation(request=request)
        result = response.responses[0]
        if result.partial_failure_error.code:
            raise RuntimeError(
                f"AppendLeadConversation failed for {lead_resource_name}: "
                f"{result.partial_failure_error.message}"
            )
        return result.local_services_lead_conversation


def _enum(enum_cls, name: str):
    try:
        return enum_cls(name)
    except ValueError:
        return enum_cls.UNKNOWN
