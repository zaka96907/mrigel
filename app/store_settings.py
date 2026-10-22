"""Per-store settings with defaults. Stored as JSON on the store row; third-party secrets encrypted."""

from .crypto import decrypt, encrypt

DEFAULT_TEMPLATE = (
    "السلام عليكم {name} 👋\n"
    "معاك {store}، وصلتنا طلبيتك:\n"
    "🛍️ {items}\n"
    "💰 المجموع: {total} دج{fee_line}\n"
    "📍 {wilaya} — {delivery}\n\n"
    "باش نبعتوهالك، أكّدلنا من فضلك:\n"
    "1️⃣ نعم، أكّد الطلبية\n"
    "2️⃣ لا، ألغيها"
    "{slot_line}{advance_line}"
)

DEFAULTS: dict = {
    "lang": "ar",
    "whatsapp_mode": "assisted",        # assisted | cloud
    "wa_phone_number_id": "",
    "wa_access_token": "",
    "wa_app_secret": "",
    "wa_verify_token": "",
    "wa_template_name": "",             # approved template for cloud mode first contact (optional)
    "wa_template_lang": "ar",
    "gemini_api_key": "",
    "ai_enabled": True,
    "confirm_template": DEFAULT_TEMPLATE,
    "ask_slot": True,
    "advance_threshold_dzd": 0,         # 0 = never ask for an advance
    "advance_amount_dzd": 300,
    "advance_how": "بريدي موب",
    "delivery_eta": "24 إلى 72 ساعة",    # what to tell a buyer who asks "wa9tach?"
    "return_cost_dzd": 450,             # what one returned parcel costs (outbound + return)
    "followup_minutes": 120,
    "max_attempts": 3,
    "auto_reply": False,                # cloud mode: send the AI acknowledgement without a human

    # delivery updates to the buyer
    "notify_shipped": True,
    "notify_delivered": True,
    "tpl_shipped": "{name}، طلبيتك من {store} خرجت مع {carrier} 🚚 رقم التتبع: {tracking}\nحضّر {total} دج كي يعيطلك الليفرور.",
    "tpl_out": "{name}، الليفرور راهو جايك اليوم بطلبيتك من {store} 📦 خلّي التلفون مفتوح. المبلغ: {total} دج.",
    "tpl_delivered": "شكراً {name} 🌷 وصلتك الطلبية من {store}. إذا كان عندك أي مشكل ابعتلنا هنا.",
    "wa_notify_template": "",           # approved utility template (one body variable) for updates outside 24 h
    "wa_campaign_template": "",         # approved marketing template (one body variable) for campaigns
    "wa_otp_template": "",              # approved authentication template for the order form code

    # order form, OTP and abandoned carts
    "form_otp": False,                  # ask the buyer for a WhatsApp code before the order is created
    "form_thanks": "شكراً! وصلتنا طلبيتك، غادي نعيطولك ولا نبعتولك في واتساب باش نأكدو.",
    "cart_recovery_minutes": 45,
    "cart_auto_recovery": False,        # cloud mode: send the recovery message on its own
    "tpl_recovery": "السلام عليكم {name} 👋 شفنا بلي بديت تطلب {items} من {store} وما كملتش. نكملولك الطلبية؟ جاوبنا بـ «نعم» ونتكفلو بالباقي.",

    # shops and other channels
    "shopify_secret": "",
    "woo_secret": "",
    "youcan_secret": "",
    "fb_page_id": "",
    "fb_page_token": "",
    "ig_account_id": "",
}

SECRET_KEYS = ("wa_access_token", "wa_app_secret", "gemini_api_key", "shopify_secret", "woo_secret",
               "youcan_secret", "fb_page_token")


def get_settings(store) -> dict:
    merged = dict(DEFAULTS)
    merged.update(store.settings or {})
    for key in SECRET_KEYS:
        merged[key] = decrypt(merged.get(key, ""))
    return merged


def update_settings(store, changes: dict) -> None:
    current = dict(store.settings or {})
    for key, value in changes.items():
        if key not in DEFAULTS:
            continue
        if key in SECRET_KEYS:
            if value in (None, ""):
                continue  # an empty secret field means "keep the saved one"
            value = encrypt(str(value).strip())
        current[key] = value
    store.settings = current
