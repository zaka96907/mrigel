"""WhatsApp in two modes.

assisted: Mrigel writes the message, the merchant's agent taps once and WhatsApp opens on their
          own phone with the text ready (wa.me). No Meta account, no fees, no bulk sending.
cloud:    Meta WhatsApp Cloud API with the merchant's own verified number and keys.
"""

import hashlib
import hmac
import logging
from urllib.parse import quote

import httpx

from .algeria import wilaya_label, whatsapp_number
from .config import settings
from .store_settings import get_settings

log = logging.getLogger("mrigel.whatsapp")


def _fmt_dzd(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def confirmation_text(order, store) -> str:
    cfg = get_settings(store)
    delivery = "ستوب ديسك (المكتب)" if order.delivery_type == "stopdesk" else "توصيل للدار"
    if order.commune and order.delivery_type == "home":
        delivery += f" — {order.commune}"
    fee_line = f" (منها التوصيل {_fmt_dzd(order.delivery_fee_dzd)} دج)" if order.delivery_fee_dzd else ""
    slot_line = "\n\n🕘 وكي تحب يجيك الليفرور: الصباح ولا العشية؟" if cfg["ask_slot"] else ""
    advance_line = ""
    threshold = int(cfg.get("advance_threshold_dzd") or 0)
    if threshold and order.total_dzd >= threshold:
        advance_line = (f"\n\n🔒 باش نحجزولك السلعة نطلبو عربون {_fmt_dzd(int(cfg['advance_amount_dzd']))} دج "
                        f"({cfg['advance_how']})، ينقص من المجموع.")
    values = {
        "name": (order.customer_name or "").split(" ")[0],
        "store": store.name,
        "items": order.items_label or "—",
        "total": _fmt_dzd(order.total_dzd),
        "fee_line": fee_line,
        "wilaya": wilaya_label(order.wilaya_code, "ar"),
        "delivery": delivery,
        "slot_line": slot_line,
        "advance_line": advance_line,
    }
    template = cfg.get("confirm_template") or ""
    try:
        return template.format(**values).strip()
    except (KeyError, IndexError, ValueError):
        from .store_settings import DEFAULT_TEMPLATE

        return DEFAULT_TEMPLATE.format(**values).strip()


def wa_link(phone_display: str, text: str) -> str:
    return f"https://wa.me/{whatsapp_number(phone_display)}?text={quote(text)}"


class CloudError(Exception):
    pass


def cloud_send_text(store, phone_display: str, text: str) -> str:
    """Send a free-form text (valid inside the 24 h customer-service window). Returns message id."""
    cfg = get_settings(store)
    return _cloud_post(cfg, {
        "messaging_product": "whatsapp",
        "to": whatsapp_number(phone_display),
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    })


def cloud_send_template(store, phone_display: str, params: list[str]) -> str:
    """First contact outside the 24 h window needs a template approved by Meta."""
    cfg = get_settings(store)
    if not cfg.get("wa_template_name"):
        raise CloudError("no_template")
    return _cloud_post(cfg, {
        "messaging_product": "whatsapp",
        "to": whatsapp_number(phone_display),
        "type": "template",
        "template": {
            "name": cfg["wa_template_name"],
            "language": {"code": cfg.get("wa_template_lang") or "ar"},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}],
        },
    })


def _cloud_post(cfg: dict, payload: dict) -> str:
    phone_id, token = cfg.get("wa_phone_number_id"), cfg.get("wa_access_token")
    if not phone_id or not token:
        raise CloudError("not_configured")
    url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{phone_id}/messages"
    try:
        response = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except httpx.HTTPError as exc:
        raise CloudError(f"network: {exc}") from exc
    if response.status_code >= 400:
        log.warning("WhatsApp API %s: %s", response.status_code, response.text[:300])
        raise CloudError(f"api_{response.status_code}")
    data = response.json()
    return (data.get("messages") or [{}])[0].get("id", "")


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def parse_inbound(payload: dict) -> list[dict]:
    """Flatten a Cloud API webhook into [{phone_number_id, from, id, text}] for text messages."""
    found = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id", "")
            for message in value.get("messages", []) or []:
                text = ""
                if message.get("type") == "text":
                    text = (message.get("text") or {}).get("body", "")
                elif message.get("type") == "button":
                    text = (message.get("button") or {}).get("text", "")
                elif message.get("type") == "interactive":
                    interactive = message.get("interactive") or {}
                    text = ((interactive.get("button_reply") or {}).get("title")
                            or (interactive.get("list_reply") or {}).get("title") or "")
                if text:
                    found.append({"phone_number_id": phone_number_id, "from": message.get("from", ""),
                                  "id": message.get("id", ""), "text": text})
    return found
