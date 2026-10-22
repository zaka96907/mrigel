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
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(3))
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(20), default="")
    ai: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="logged")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="messages")


class BlacklistEntry(Base):
    __tablename__ = "blacklist"
    __table_args__ = (UniqueConstraint("store_id", "phone", name="uq_blacklist_store_phone"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
