"""Automation rules: "when <event> and <conditions> then <actions>".

Events:     order_created, stage_changed (the new stage is the `stage` field).
Conditions: all must match. field op value, e.g. risk_score gte 60, wilaya_code in 1,16,31.
Actions:    set_stage, assign, tag, note, message, blacklist.

A rule that moves an order can trigger other stage_changed rules; the chain stops after 3 levels
so two rules cannot ping-pong forever.
"""

from sqlalchemy import select

from .models import Order, Rule, User

FIELDS = {
    "risk_score": "int", "total_dzd": "int", "attempts": "int", "wilaya_code": "int",
    "source": "str", "delivery_type": "str", "stage": "str", "phone_valid": "bool", "tags": "list",
    "product": "str",
}
OPS = ("eq", "ne", "gte", "lte", "in", "not_in", "contains")
ACTIONS = ("set_stage", "assign", "tag", "note", "message", "blacklist")
MAX_DEPTH = 3


def _value(order: Order, field: str):
    if field == "product":
        return " | ".join(str(i.get("name", "")) + " " + str(i.get("sku", "")) for i in order.items or []).lower()
    return getattr(order, field, None)


def _as(kind: str, raw):
    if kind == "int":
        try:
            return int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return None
    if kind == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "oui", "نعم", "on")
    return str(raw).strip().lower()


def matches(order: Order, condition: dict) -> bool:
    field, op, raw = condition.get("field"), condition.get("op"), condition.get("value", "")
    kind = FIELDS.get(field)
    if not kind or op not in OPS:
        return False
    actual = _value(order, field)
    if op in ("in", "not_in"):
        wanted = {_as(kind, part) for part in str(raw).split(",") if str(part).strip()}
        found = _as(kind, actual) in wanted if kind != "list" else bool(set(map(str.lower, actual or [])) & wanted)
        return found if op == "in" else not found
    if kind == "list":
        tags = [str(t).lower() for t in actual or []]
        target = _as("str", raw)
        return (target in tags) if op in ("eq", "contains") else (target not in tags)
    actual_v, wanted_v = _as(kind, actual), _as(kind, raw)
    if actual_v is None or wanted_v is None:
        return False
    if op == "eq":
        return actual_v == wanted_v
    if op == "ne":
        return actual_v != wanted_v
    if op == "contains":
        return str(wanted_v) in str(actual_v)
    if kind != "int":
        return False
    return actual_v >= wanted_v if op == "gte" else actual_v <= wanted_v


def run(db, order: Order, event: str) -> list[str]:
    """Run the store's active rules for this event. Returns the names of the rules that fired."""
    depth = db.info.get("rule_depth", 0)
    if depth >= MAX_DEPTH:
        return []
    rules = db.scalars(select(Rule).where(Rule.store_id == order.store_id, Rule.event == event,
                                          Rule.active.is_(True)).order_by(Rule.created_at)).all()
    fired = []
    db.info["rule_depth"] = depth + 1
    try:
        for rule in rules:
            if not all(matches(order, c) for c in rule.conditions or []):
                continue
            for action in rule.actions or []:
                _do(db, order, rule, action)
            rule.runs = (rule.runs or 0) + 1
            fired.append(rule.name)
    finally:
        db.info["rule_depth"] = depth
    return fired


def _do(db, order: Order, rule: Rule, action: dict) -> None:
    from . import notify, services

    kind, value = action.get("type"), str(action.get("value", "")).strip()
    if kind == "set_stage" and value in services.TRANSITIONS.get(order.stage, set()):
        services.set_stage(db, order, value, reason=f"rule:{rule.name}"[:60])
    elif kind == "assign":
        member = db.scalar(select(User).where(User.id == value, User.store_id == order.store_id, User.active.is_(True)))
        if member:
            order.assigned_user_id = member.id
            services.add_event(db, order, "system", f"rule:{rule.name}", assigned=member.name)
    elif kind == "tag" and value:
        tags = list(order.tags or [])
        if value[:30] not in tags:
            order.tags = tags + [value[:30]]
    elif kind == "note" and value:
        services.add_event(db, order, "note", value[:1000], rule=rule.name)
    elif kind == "message" and value:
        notify.queue_text(db, order, value[:1000], kind="rule")
    elif kind == "blacklist":
        services.add_to_blacklist(db, order.store_id, order.phone, value or f"rule:{rule.name}")


def clean_rule(form: dict) -> tuple[str, list, list]:
    """Read the rule builder form: cond_field_N / cond_op_N / cond_value_N and act_type_N / act_value_N."""
    conditions, actions = [], []
    for n in range(6):
        field, op = form.get(f"cond_field_{n}", ""), form.get(f"cond_op_{n}", "")
        if field in FIELDS and op in OPS:
            conditions.append({"field": field, "op": op, "value": str(form.get(f"cond_value_{n}", ""))[:200]})
        kind = form.get(f"act_type_{n}", "")
        if kind in ACTIONS:
            actions.append({"type": kind, "value": str(form.get(f"act_value_{n}", ""))[:1000]})
    event = form.get("event", "")
    return (event if event in ("order_created", "stage_changed") else ""), conditions, actions


TEMPLATES = [
    {"key": "high_risk_tag", "event": "order_created",
     "conditions": [{"field": "risk_score", "op": "gte", "value": "60"}],
     "actions": [{"type": "tag", "value": "risk"}, {"type": "note", "value": "تحقق قبل ما تأكد: خطر عالي"}]},
    {"key": "blacklist_on_return", "event": "stage_changed",
     "conditions": [{"field": "stage", "op": "eq", "value": "returned"}],
     "actions": [{"type": "blacklist", "value": "رجّع الطلبية"}]},
    {"key": "big_order_tag", "event": "order_created",
     "conditions": [{"field": "total_dzd", "op": "gte", "value": "15000"}],
     "actions": [{"type": "tag", "value": "VIP"}]},
    {"key": "thanks_delivered", "event": "stage_changed",
     "conditions": [{"field": "stage", "op": "eq", "value": "delivered"}],
     "actions": [{"type": "message", "value": "شكراً {name} على ثقتك في {store} 🌷 إذا عجبك المنتوج ابعتلنا رأيك."}]},
]
