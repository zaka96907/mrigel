"""Demo store with realistic fake orders. `python -m app.seed` or DEMO_MODE=1.

All names are invented. The demo store is flagged `demo` so its WhatsApp button never opens a
real chat: the phone numbers have a valid format and could belong to someone.
"""

import random
from datetime import timedelta

from sqlalchemy import select

from .models import Order, Store, User, utcnow
from .risk import apply_risk
from .security import hash_password
from .services import add_event, add_to_blacklist

DEMO_EMAIL = "demo@mrigel.dz"
DEMO_PASSWORD = "demo-mrigel"

FIRST = ["أمينة", "كريم", "سارة", "ياسين", "نسرين", "رياض", "إيمان", "مهدي", "ليلى", "سفيان", "هاجر", "أنيس",
         "Nadia", "Walid", "Meriem", "Sofiane", "Lina", "Amine", "Khadidja", "Bilal"]
LAST = ["بن علي", "حداد", "بوزيد", "مسعودي", "شريف", "بلقاسم", "زروقي", "عمراني", "Kaci", "Belkacem", "Haddad",
        "Mansouri", "Benali", "Ziani", "Ait Ahmed"]
PRODUCTS = [("كريم مرطب للوجه", 2500), ("سيروم فيتامين C", 3200), ("زيت الأركان", 1800), ("ساعة كلاسيك", 4800),
            ("حذاء رياضي", 5600), ("طقم أواني", 7900), ("سماعات بلوتوث", 3900), ("عباية", 6500),
            ("Parfum oriental", 4200), ("Sac à main", 5200)]
WILAYA_WEIGHTS = {16: 18, 31: 9, 25: 7, 19: 7, 9: 6, 35: 4, 6: 4, 15: 4, 23: 4, 13: 3, 5: 3, 34: 3, 7: 3,
                  17: 3, 30: 2, 39: 2, 47: 2, 1: 1, 8: 1, 11: 1, 64: 1, 63: 1}
COMMUNES = {16: ["باب الزوار", "الحراش", "بئر مراد رايس", "الشراقة"], 31: ["السانيا", "بئر الجير"],
            25: ["الخروب", "علي منجلي"], 19: ["العلمة", "عين ولمان"], 9: ["بوفاريك", "العفرون"]}


def ensure_demo(db) -> Store:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user:
        return db.get(Store, user.store_id)
    store = Store(name="Lina Beauty DZ", settings={"lang": "ar", "advance_threshold_dzd": 7000, "demo": True})
    db.add(store)
    db.flush()
    owner = User(store_id=store.id, name="Lina", email=DEMO_EMAIL, role="owner",
                 password_hash=hash_password(DEMO_PASSWORD))
    agent = User(store_id=store.id, name="Yasmine", email="agent@mrigel.dz", role="agent",
                 password_hash=hash_password(DEMO_PASSWORD))
    db.add_all([owner, agent])
    db.flush()
    rng = random.Random(42)
    codes = list(WILAYA_WEIGHTS)
    weights = list(WILAYA_WEIGHTS.values())
    now = utcnow()
    repeat_phones = ["0550001101", "0550001102"]
    orders = []
    for i in range(140):
        code = rng.choices(codes, weights)[0]
        product, price = rng.choice(PRODUCTS)
        qty = 1 if rng.random() < 0.85 else 2
        created = now - timedelta(days=rng.uniform(0, 29) if i > 10 else rng.uniform(0, 0.4),
                                  minutes=rng.randint(0, 600))
        phone = rng.choice(repeat_phones) if i % 37 == 0 else f"05500{rng.randint(10000, 99999)}"
        if i == 77:
            phone = "021 45 67 89"
        order = Order(
            store_id=store.id, external_id=f"LB-{1000 + i}", source=rng.choice(["manual", "csv", "api", "api"]),
            customer_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", phone=phone.replace(" ", ""),
            phone_valid=phone.startswith("05"), wilaya_code=code,
            commune=rng.choice(COMMUNES.get(code, [""])), address="" if rng.random() < 0.15 else "حي " + str(rng.randint(1, 500)),
            delivery_type="stopdesk" if rng.random() < 0.3 else "home",
            items=[{"name": product, "qty": qty, "price_dzd": price}], total_dzd=price * qty + 500,
            delivery_fee_dzd=500 if code in (16, 9, 35, 42) else 700, created_at=created,
        )
        db.add(order)
        orders.append(order)
    db.flush()

    rural = {30, 39, 47, 1, 8, 11, 64, 63, 17}
    for order in sorted(orders, key=lambda o: o.created_at):
        apply_risk(db, order)
        add_event(db, order, "created", order.source)
        age_hours = (now - order.created_at).total_seconds() / 3600
        if age_hours < 6:
            order.stage = rng.choice(["new", "new", "pending"])
            continue
        roll = rng.random()
        if roll < 0.70:
            order.stage, order.confirmed_at = "confirmed", order.created_at + timedelta(hours=1)
            order.confirmed_by_id = rng.choice([owner.id, agent.id, agent.id])
            order.preferred_slot = rng.choice(["morning", "afternoon", ""])
            if age_hours > 30:
                order.stage, order.shipped_at = "shipped", order.created_at + timedelta(hours=20)
                order.carrier = rng.choice(["yalidine", "zr", "maystro"])
                if age_hours > 80:
                    return_p = 0.28 if order.wilaya_code in rural else 0.12
                    order.stage = "returned" if rng.random() < return_p else "delivered"
                    order.closed_at = order.created_at + timedelta(days=3)
        elif roll < 0.84:
            order.stage, order.cancel_reason = "cancelled", rng.choice(["buyer_no", "fake", "wrong_number"])
            order.closed_at = order.created_at + timedelta(hours=2)
        elif roll < 0.92:
            order.stage = "no_answer"
            order.attempts = 3
        else:
            order.stage = "postponed"
            order.postponed_until = now + timedelta(hours=rng.choice([-2, 5, 20]))
    db.flush()
    add_to_blacklist(db, store.id, "0550001102", "رجّع زوج طلبيات", owner.id)
    return store


if __name__ == "__main__":
    from .db import init_db, session_scope

    init_db()
    with session_scope() as session:
        ensure_demo(session)
    print(f"Demo ready: {DEMO_EMAIL} / {DEMO_PASSWORD}")
