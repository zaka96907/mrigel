"""Dashboard numbers. Everything is computed from the store's own orders."""

from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from . import catalog
from .models import CONFIRMED_LIKE, Order, OrderEvent, Product, User, utcnow
from .services import as_utc
from .store_settings import get_settings

ALGIERS = ZoneInfo("Africa/Algiers")


def dashboard(db, store, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    orders = db.scalars(select(Order).where(Order.store_id == store.id, Order.created_at >= since)).all()
    cfg = get_settings(store)
    return_cost = int(cfg.get("return_cost_dzd") or 450)

    by_stage: dict[str, int] = defaultdict(int)
    for order in orders:
        by_stage[order.stage] += 1

    total = len(orders)
    confirmed_like = sum(by_stage[s] for s in CONFIRMED_LIKE)
    decided = confirmed_like + by_stage["cancelled"] + by_stage["no_answer"]
    delivered, returned = by_stage["delivered"], by_stage["returned"]
    cancelled_before_ship = sum(1 for o in orders if o.stage == "cancelled" and not o.shipped_at)
    high_risk_stopped = sum(1 for o in orders if o.stage == "cancelled" and (o.risk_score or 0) >= 60)

    # orders per day (Algiers calendar days), oldest first
    per_day: dict[str, int] = defaultdict(int)
    for order in orders:
        day = as_utc(order.created_at).astimezone(ALGIERS).strftime("%m-%d")
        per_day[day] += 1
    today = utcnow().astimezone(ALGIERS).date()
    span = min(days, 30)
    series = []
    for offset in range(span - 1, -1, -1):
        day = today - timedelta(days=offset)
        series.append({"label": day.strftime("%d/%m"), "value": per_day.get(day.strftime("%m-%d"), 0)})
    peak = max((p["value"] for p in series), default=0) or 1

    wilayas: dict[int, dict] = defaultdict(lambda: {"orders": 0, "confirmed": 0, "delivered": 0, "returned": 0})
    for order in orders:
        row = wilayas[order.wilaya_code or 0]
        row["orders"] += 1
        if order.stage in CONFIRMED_LIKE:
            row["confirmed"] += 1
        if order.stage == "delivered":
            row["delivered"] += 1
        if order.stage == "returned":
            row["returned"] += 1
    wilaya_rows = []
    for code, row in wilayas.items():
        closed = row["delivered"] + row["returned"]
        wilaya_rows.append({
            "code": code, **row,
            "confirm_rate": round(100 * row["confirmed"] / row["orders"]) if row["orders"] else 0,
            "return_rate": round(100 * row["returned"] / closed) if closed else None,
        })
    wilaya_rows.sort(key=lambda r: r["orders"], reverse=True)

    agent_rows = agent_metrics(db, store, orders, since)
    products = {p.id: p for p in db.scalars(select(Product).where(Product.store_id == store.id))}
    product_rows = catalog.product_rows(orders, products)

    return {
        "days": days,
        "total": total,
        "by_stage": dict(by_stage),
        "open": sum(by_stage[s] for s in ("new", "pending", "postponed", "no_answer")),
        "confirm_rate": round(100 * confirmed_like / decided) if decided else None,
        "return_rate": round(100 * returned / (delivered + returned)) if (delivered + returned) else None,
        "delivered_revenue": sum(o.total_dzd for o in orders if o.stage == "delivered"),
        "saved_dzd": cancelled_before_ship * return_cost,
        "cancelled_before_ship": cancelled_before_ship,
        "high_risk_stopped": high_risk_stopped,
        "return_cost": return_cost,
        "series": series,
        "peak": peak,
        "wilayas": wilaya_rows[:12],
        "agents": agent_rows[:12],
        "products": product_rows[:15],
        "low_stock": [p for p in products.values() if p.active and p.is_low][:8],
    }


def agent_metrics(db, store, orders: list[Order], since) -> list[dict]:
    """Per team member over the period: orders handled, confirmed, cancelled, confirmation rate,
    messages sent, median minutes from order to confirmation, and how their confirmed orders ended."""
    members = {u.id: u for u in db.scalars(select(User).where(User.store_id == store.id))}
    rows = {uid: {"name": u.name, "role": u.role, "handled": set(), "confirmed": 0, "cancelled": 0, "messages": 0,
                  "minutes": [], "delivered": 0, "returned": 0} for uid, u in members.items()}
    events = db.scalars(select(OrderEvent).where(OrderEvent.store_id == store.id, OrderEvent.created_at >= since,
                                                 OrderEvent.user_id.is_not(None))).all()
    for event in events:
        row = rows.get(event.user_id)
        if row is None:
            continue
        if event.kind == "stage":
            row["handled"].add(event.order_id)
            if (event.data or {}).get("to") == "cancelled":
                row["cancelled"] += 1
        elif event.kind == "whatsapp":
            row["handled"].add(event.order_id)
            row["messages"] += 1
    for order in orders:
        row = rows.get(order.confirmed_by_id or "")
        if row is None or order.stage not in CONFIRMED_LIKE:
            continue
        row["handled"].add(order.id)
        row["confirmed"] += 1
        if order.confirmed_at and order.created_at:
            row["minutes"].append(max(0, (as_utc(order.confirmed_at) - as_utc(order.created_at)).total_seconds() / 60))
        if order.stage == "delivered":
            row["delivered"] += 1
        elif order.stage == "returned":
            row["returned"] += 1
    result = []
    for row in rows.values():
        handled = len(row.pop("handled"))
        if not handled:
            continue
        minutes = sorted(row.pop("minutes"))
        decided = row["confirmed"] + row["cancelled"]
        closed = row["delivered"] + row["returned"]
        result.append({**row, "handled": handled,
                       "confirm_rate": round(100 * row["confirmed"] / decided) if decided else None,
                       "median_minutes": round(minutes[len(minutes) // 2]) if minutes else None,
                       "delivery_rate": round(100 * row["delivered"] / closed) if closed else None})
    result.sort(key=lambda r: (r["confirmed"], r["handled"]), reverse=True)
    return result
