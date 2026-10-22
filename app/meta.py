"""Facebook Messenger and Instagram Direct through the Meta Graph API (the merchant's own page).

Inbound: Meta posts {"object": "page" | "instagram", "entry": [{"id", "messaging": [...]}]} to
/webhooks/meta, signed with the app secret (X-Hub-Signature-256), like WhatsApp.
Outbound: POST /{page-id}/messages with the page access token. Replies are allowed inside the
24 h window that opens when the person writes to the page.
"""

import logging

import httpx

from .config import settings
from .store_settings import get_settings
from .whatsapp import CloudError

log = logging.getLogger("mrigel.meta")


def parse_inbound(payload: dict) -> list[dict]:
    """[{channel, account_id, sender, id, text}] for text messages sent TO the page/account."""
    channel = {"page": "messenger", "instagram": "instagram"}.get(payload.get("object", ""))
    if not channel:
        return []
    found = []
    for entry in payload.get("entry", []) or []:
        account_id = str(entry.get("id", ""))
        for event in entry.get("messaging", []) or []:
            message = event.get("message") or {}
            if not message or message.get("is_echo"):
                continue  # our own outgoing messages come back as echoes
            text = message.get("text") or ""
            if not text and message.get("attachments"):
                text = "[" + str((message["attachments"][0] or {}).get("type", "attachment")) + "]"
            sender = str((event.get("sender") or {}).get("id", ""))
            if text and sender:
                found.append({"channel": channel, "account_id": account_id, "sender": sender,
                              "id": message.get("mid", ""), "text": text[:4000]})
    return found


def send_text(store, channel: str, recipient_id: str, text: str) -> str:
    cfg = get_settings(store)
    page_id, token = cfg.get("fb_page_id"), cfg.get("fb_page_token")
    if not page_id or not token:
        raise CloudError("not_configured")
    url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{page_id}/messages"
    payload = {"recipient": {"id": recipient_id}, "messaging_type": "RESPONSE", "message": {"text": text[:2000]}}
    try:
        response = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except httpx.HTTPError as exc:
        raise CloudError(f"network: {exc}") from exc
    if response.status_code >= 400:
        log.warning("Graph API %s: %s", response.status_code, response.text[:300])
        raise CloudError(f"api_{response.status_code}")
    return str(response.json().get("message_id", ""))
