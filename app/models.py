from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

STATUS_NEW = "new"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUSES = (STATUS_NEW, STATUS_DONE, STATUS_CANCELLED)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    lang: Mapped[str] = mapped_column(String(8))


class CartItem(Base):
    __tablename__ = "cart_items"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    product_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    lang: Mapped[str] = mapped_column(String(8))
    customer_name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(32))
    delivery_id: Mapped[str] = mapped_column(String(32))
    delivery_name: Mapped[str] = mapped_column(String(128))
    delivery_price: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(512), default="")
    items_total: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), default=STATUS_NEW)
    bitrix_deal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(256))
    price: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="items")

    @property
    def subtotal(self) -> int:
        return self.price * self.quantity
