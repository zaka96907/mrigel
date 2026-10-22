"""Products, stock and per-product numbers.

Stock moves with the order: it is taken when the buyer confirms (the parcel is being prepared),
given back when a confirmed order is cancelled or sent back to the queue, and given back when a
shipped parcel comes back (returned). Delivered orders keep it taken. Every move is logged.
"""

from collections import defaultdict

from sqlalchemy import func, select

from .models import CONFIRMED_LIKE, Order, Product, StockMove

TAKES_STOCK = ("confirmed", "shipped", "delivered")


def _fold(text: str) -> str:
    return " ".join((text or "").lower().split())


def find_product(db, store_id: str, sku: str = "", name: str = "") -> Product | None:
    if sku:
        product = db.scalar(select(Product).where(Product.store_id == store_id, Product.sku == sku.strip()[:60]))
        if product:
            return product
    if name:
        folded = _fold(name)
        for product in db.scalars(select(Product).where(Product.store_id == store_id, Product.active.is_(True))):
            if _fold(product.name) == folded or _fold(product.sku) == folded:
                return product
    return None


def link_items(db, store_id: str, items: list[dict]) -> list[dict]:
    """Attach product_id (and fill a missing price) for items that match a product by SKU or name."""
    linked = []
    for item in items or []:
        item = dict(item)
        product = None
        if item.get("product_id"):
            product = db.scalar(select(Product).where(Product.store_id == store_id, Product.id == item["product_id"]))
        product = product or find_product(db, store_id, item.get("sku", ""), item.get("name", ""))
        if product:
            item["product_id"] = product.id
            item["sku"] = product.sku
            if not item.get("price_dzd"):
                item["price_dzd"] = product.price_dzd
        linked.append(item)
    return linked


def _move(db, order: Order, sign: int, reason: str) -> None:
    for item in order.items or []:
        product_id = item.get("product_id")
        if not product_id:
            continue
        product = db.get(Product, product_id)
        if not product or product.store_id != order.store_id or not product.track_stock:
            continue
        delta = sign * max(1, int(item.get("qty") or 1))
        product.stock = (product.stock or 0) + delta
        db.add(StockMove(store_id=order.store_id, product_id=product.id, order_id=order.id, delta=delta, reason=reason))


def on_stage(db, order: Order, previous: str, stage: str) -> None:
    """Called by set_stage after the stage changed."""
    if stage in TAKES_STOCK and not order.stock_applied:
        _move(db, order, -1, "confirmed")
        order.stock_applied = True
    elif stage not in TAKES_STOCK and order.stock_applied:
        _move(db, order, +1, "returned" if stage == "returned" else "released")
        order.stock_applied = False


def adjust(db, product: Product, delta: int, reason: str = "manual") -> None:
    product.stock = (product.stock or 0) + delta
    db.add(StockMove(store_id=product.store_id, product_id=product.id, delta=delta, reason=reason))


def low_stock(db, store_id: str) -> list[Product]:
    return [p for p in db.scalars(select(Product).where(Product.store_id == store_id, Product.active.is_(True),
                                                        Product.track_stock.is_(True)))
            if p.stock <= p.low_stock]


def product_rows(orders: list[Order], products: dict[str, Product] | None = None) -> list[dict]:
    """Per product: orders, confirmed, delivered, returned, confirm and return rates, money lost to returns.
    Items without a product are grouped by their name."""
    products = products or {}
    rows: dict[str, dict] = defaultdict(lambda: {"orders": 0, "confirmed": 0, "delivered": 0, "returned": 0,
                                                 "cancelled": 0, "revenue": 0, "name": "", "product_id": None})
    for order in orders:
        seen = set()
        for item in order.items or []:
            key = item.get("product_id") or "name:" + _fold(item.get("name", ""))
            if key in seen or key == "name:":
                continue
            seen.add(key)
            row = rows[key]
            product = products.get(item.get("product_id") or "")
            row["name"] = product.name if product else item.get("name", "")
            row["product_id"] = item.get("product_id")
            row["orders"] += 1
            if order.stage in CONFIRMED_LIKE:
                row["confirmed"] += 1
            if order.stage == "delivered":
                row["delivered"] += 1
                row["revenue"] += int(item.get("price_dzd") or 0) * int(item.get("qty") or 1)
            elif order.stage == "returned":
                row["returned"] += 1
            elif order.stage == "cancelled":
                row["cancelled"] += 1
    result = []
    for row in rows.values():
        closed = row["delivered"] + row["returned"]
        row["confirm_rate"] = round(100 * row["confirmed"] / row["orders"]) if row["orders"] else 0
        row["return_rate"] = round(100 * row["returned"] / closed) if closed else None
        result.append(row)
    result.sort(key=lambda r: r["orders"], reverse=True)
    return result


def stock_value(db, store_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(Product.stock * Product.cost_dzd), 0))
                         .where(Product.store_id == store_id, Product.active.is_(True), Product.stock > 0)) or 0)
