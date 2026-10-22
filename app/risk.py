"""Order risk score (0-100) from signals an Algerian COD seller actually has.

Every point added comes with a reason code, so the merchant sees why an order is risky.
The store's own history replaces the regional baseline once there is enough of it.
"""

import re
from datetime import timedelta

from sqlalchemy import func, select

from .algeria import BASELINE_RTO, is_landline, wilaya_tier
from .models import BlacklistEntry, Order, utcnow

MIN_WILAYA_HISTORY = 15


def level(score: int) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _wilaya_return_rate(db, store_id: str, code: int | None) -> tuple[float, bool]:
    """(rate, from_store_history)"""
    if code:
        rows = db.execute(
            select(Order.stage, func.count())
            .where(Order.store_id == store_id, Order.wilaya_code == code,
                   Order.stage.in_(("delivered", "returned")))
            .group_by(Order.stage)
        ).all()
        counts = dict(rows)
        closed = counts.get("delivered", 0) + counts.get("returned", 0)
        if closed >= MIN_WILAYA_HISTORY:
            return counts.get("returned", 0) / closed, True
    return BASELINE_RTO[wilaya_tier(code)], False


def _suspicious_name(name: str) -> bool:
    clean = (name or "").strip()
    if len(clean) < 3:
        return True
    if re.search(r"\d", clean):
        return True
    if re.search(r"(.)\1{3,}", clean):
        return True
    return clean.lower() in {"test", "aaa", "xxx", "client", "زبون", "تجربة"}


def score_order(db, order: Order) -> tuple[int, list[dict]]:
    reasons: list[dict] = []

    def add(points: int, code: str, **data):
        reasons.append({"code": code, "points": points, **data})

    if not order.phone_valid:
        add(15 if is_landline(order.phone) else 35, "phone_landline" if is_landline(order.phone) else "phone_invalid")

    if db.scalar(select(BlacklistEntry.id).where(
            BlacklistEntry.store_id == order.store_id, BlacklistEntry.phone == order.phone)):
        add(60, "blacklisted")

    history = dict(db.execute(
        select(Order.stage, func.count())
        .where(Order.store_id == order.store_id, Order.phone == order.phone, Order.id != order.id)
        .group_by(Order.stage)
    ).all())
    returned = history.get("returned", 0)
    cancelled = history.get("cancelled", 0)
    delivered = history.get("delivered", 0)
    if returned:
        add(min(50, 25 * returned), "past_returns", n=returned)
    if cancelled:
        add(min(20, 10 * cancelled), "past_cancels", n=cancelled)
    if delivered:
        add(-min(30, 15 * delivered), "past_delivered", n=delivered)

    since = (order.created_at or utcnow()) - timedelta(hours=24)
    duplicates = db.scalar(
        select(func.count()).select_from(Order).where(
            Order.store_id == order.store_id, Order.phone == order.phone, Order.id != order.id,
            Order.created_at >= since, Order.stage.in_(("new", "pending", "confirmed", "postponed")))
    ) or 0
    if duplicates:
        add(20, "duplicate", n=duplicates)

    rate, own = _wilaya_return_rate(db, order.store_id, order.wilaya_code)
    wilaya_points = max(0, min(20, round((rate - 0.15) * 80)))
    if wilaya_points:
        add(wilaya_points, "wilaya_returns", rate=round(rate * 100), own=own)

    if order.total_dzd >= 20000:
        add(15, "high_value")
    elif order.total_dzd >= 10000:
        add(8, "high_value")

    if _suspicious_name(order.customer_name):
        add(10, "suspicious_name")

    if order.delivery_type == "home" and len((order.address or "").strip()) < 4 and not order.commune:
        add(8, "no_address")

    score = max(0, min(100, sum(r["points"] for r in reasons)))
    return score, reasons


def apply_risk(db, order: Order) -> None:
    order.risk_score, order.risk_reasons = score_order(db, order)
