"""Tables. Every row a merchant owns carries store_id; queries are scoped in the data layer."""

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

STAGES = (
    "new",          # just arrived, nobody contacted the buyer yet
    "pending",      # message sent, waiting for the buyer
    "confirmed",    # buyer said yes
    "postponed",    # buyer asked to be contacted later
    "no_answer",    # no reply after the follow-ups
    "cancelled",    # buyer said no, or the merchant cancelled
    "shipped",      # handed to the carrier
    "delivered",    # buyer paid and took it
    "returned",     # refused or not collected
)
OPEN_STAGES = ("new", "pending", "postponed", "no_answer")
CONFIRMED_LIKE = ("confirmed", "shipped", "delivered", "returned")


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stage_check(column: str) -> str:
    return f"{column} IN (" + ", ".join(f"'{s}'" for s in STAGES) + ")"


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    api_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: "mrg_" + secrets.token_urlsafe(24))
    plan: Mapped[str] = mapped_column(String(20), default="trial")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="store", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('owner', 'agent')", name="ck_users_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="owner")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    store: Mapped[Store] = relationship(back_populates="users")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("store_id", "external_id", name="uq_orders_store_external"),
        CheckConstraint(_stage_check("stage"), name="ck_orders_stage"),
        CheckConstraint("delivery_type IN ('home', 'stopdesk')", name="ck_orders_delivery_type"),
        CheckConstraint("total_dzd >= 0", name="ck_orders_total"),
        Index("ix_orders_store_stage_created", "store_id", "stage", "created_at"),
        Index("ix_orders_store_phone", "store_id", "phone"),
        Index("ix_orders_store_wilaya", "store_id", "wilaya_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    customer_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    phone_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    wilaya_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commune: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    delivery_type: Mapped[str] = mapped_column(String(10), default="home")
    items: Mapped[list] = mapped_column(JSON, default=list)
    total_dzd: Mapped[int] = mapped_column(Integer, default=0)
    delivery_fee_dzd: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")

    stage: Mapped[str] = mapped_column(String(12), default="new")
    cancel_reason: Mapped[str] = mapped_column(String(60), default="")
    preferred_slot: Mapped[str] = mapped_column(String(12), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_reasons: Mapped[list] = mapped_column(JSON, default=list)

    carrier: Mapped[str] = mapped_column(String(30), default="")
    tracking: Mapped[str] = mapped_column(String(60), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    stock_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cod_collected_dzd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carrier_fee_dzd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payout_id: Mapped[str | None] = mapped_column(ForeignKey("payouts.id", ondelete="SET NULL"), nullable=True)
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    confirmed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    postponed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    events: Mapped[list["OrderEvent"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderEvent.created_at"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="Message.created_at"
    )

    @property
    def is_open(self) -> bool:
        return self.stage in OPEN_STAGES

    @property
    def items_label(self) -> str:
        parts = []
        for item in self.items or []:
            qty = item.get("qty", 1)
            name = item.get("name", "")
            parts.append(f"{name} ×{qty}" if qty and qty != 1 else name)
        return "، ".join(p for p in parts if p)


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (Index("ix_events_store_created", "store_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # created, stage, whatsapp, note, ai, system
    text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="events")
    user: Mapped[User | None] = relationship()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("direction IN ('in', 'out')", name="ck_messages_direction"),
        UniqueConstraint("store_id", "provider_id", name="uq_messages_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="chat")  # chat, notify, campaign, otp, recovery
    direction: Mapped[str] = mapped_column(String(3))
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(20), default="")
    ai: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="logged")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order | None] = relationship(back_populates="messages")
    contact: Mapped["Contact | None"] = relationship(back_populates="messages")


class BlacklistEntry(Base):
    __tablename__ = "blacklist"
    __table_args__ = (UniqueConstraint("store_id", "phone", name="uq_blacklist_store_phone"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- catalogue and stock

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("store_id", "sku", name="uq_products_store_sku"),
        CheckConstraint("price_dzd >= 0 AND cost_dzd >= 0", name="ck_products_money"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    price_dzd: Mapped[int] = mapped_column(Integer, default=0)
    cost_dzd: Mapped[int] = mapped_column(Integer, default=0)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    track_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    low_stock: Mapped[int] = mapped_column(Integer, default=5)
    delivery_fee_dzd: Mapped[int] = mapped_column(Integer, default=0)
    upsell_product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    upsell_price_dzd: Mapped[int] = mapped_column(Integer, default=0)
    form_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_low(self) -> bool:
        return self.track_stock and self.stock <= self.low_stock


class StockMove(Base):
    __tablename__ = "stock_moves"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(30))  # confirmed, released, returned, manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- money from the carriers

class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    carrier: Mapped[str] = mapped_column(String(30), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")
    filename: Mapped[str] = mapped_column(String(200), default="")
    rows: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    collected_dzd: Mapped[int] = mapped_column(Integer, default=0)
    fees_dzd: Mapped[int] = mapped_column(Integer, default=0)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- automations

class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (CheckConstraint("event IN ('order_created', 'stage_changed')", name="ck_rules_event"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    event: Mapped[str] = mapped_column(String(20))
    conditions: Mapped[list] = mapped_column(JSON, default=list)   # [{"field", "op", "value"}]
    actions: Mapped[list] = mapped_column(JSON, default=list)      # [{"type", "value"}]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- inbox

class Contact(Base):
    """One conversation per person per channel (WhatsApp number, Messenger or Instagram id)."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("store_id", "channel", "handle", name="uq_contacts_store_channel_handle"),
        CheckConstraint("channel IN ('whatsapp', 'messenger', 'instagram')", name="ck_contacts_channel"),
        Index("ix_contacts_store_last", "store_id", "last_message_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(12))
    handle: Mapped[str] = mapped_column(String(80))   # phone display for WhatsApp, PSID / IGSID otherwise
    name: Mapped[str] = mapped_column(String(120), default="")
    unread: Mapped[int] = mapped_column(Integer, default=0)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list[Message]] = relationship(back_populates="contact", order_by="Message.created_at")


# ---------------------------------------------------------------- campaigns

class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    audience: Mapped[dict] = mapped_column(JSON, default=dict)
    recipients: Mapped[list] = mapped_column(JSON, default=list)   # [{"phone", "name", "status"}]
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft, sending, done
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def count(self, status: str) -> int:
        return sum(1 for r in self.recipients or [] if r.get("status") == status)


# ---------------------------------------------------------------- order form, carts, saved views

class Cart(Base):
    """A buyer who started the order form. Becomes an order, or an abandoned cart to recover."""

    __tablename__ = "carts"
    __table_args__ = (Index("ix_carts_store_status", "store_id", "status", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    token: Mapped[str] = mapped_column(String(48), unique=True, default=lambda: secrets.token_urlsafe(24))
    customer_name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open, otp, ordered, recovered
    otp_hash: Mapped[str] = mapped_column(String(128), default="")
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_tries: Mapped[int] = mapped_column(Integer, default=0)
    otp_sends: Mapped[int] = mapped_column(Integer, default=0)
    recovery_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    query: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
