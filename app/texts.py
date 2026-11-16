from __future__ import annotations

from collections.abc import Iterable
from zoneinfo import ZoneInfo

from app.cart import Cart
from app.config import ClientConfig, DeliveryOption, pick
from app.i18n import Markup, Translator, join_lines
from app.models import Order

CURRENCY_SYMBOLS = {"KZT": "₸", "RUB": "₽", "USD": "$", "EUR": "€"}
EMPTY = "—"

ItemRow = tuple[str, int, int]


def format_money(amount: int, currency: str) -> str:
    grouped = f"{amount:,}".replace(",", " ")
    return f"{grouped} {CURRENCY_SYMBOLS.get(currency, currency)}"


def items_text(translator: Translator, lang: str, rows: Iterable[ItemRow], currency: str) -> Markup:
    return join_lines(
        [
            translator.t(
                lang,
                "cart_line",
                index=index,
                name=name,
                quantity=quantity,
                price=format_money(price, currency),
                subtotal=format_money(price * quantity, currency),
            )
            for index, (name, quantity, price) in enumerate(rows, start=1)
        ]
    )


def cart_rows(cart: Cart, lang: str) -> list[ItemRow]:
    return [
        (pick(line.product.name, lang), line.quantity, line.product.price) for line in cart.lines
    ]


def order_rows(order: Order) -> list[ItemRow]:
    return [(item.name, item.quantity, item.price) for item in order.items]


def delivery_label(translator: Translator, lang: str, option: DeliveryOption, currency: str) -> str:
    name = pick(option.name, lang)
    if option.price == 0:
        return translator.plain(lang, "delivery_free", name=name)
    return translator.plain(
        lang, "delivery_paid", name=name, price=format_money(option.price, currency)
    )


def cart_text(translator: Translator, lang: str, cart: Cart, currency: str) -> Markup:
    if cart.is_empty:
        return translator.t(lang, "cart_empty")
    return translator.t(
        lang,
        "cart",
        items=items_text(translator, lang, cart_rows(cart, lang), currency),
        total=format_money(cart.total, currency),
    )


def details_text(
    translator: Translator,
    lang: str,
    name: str,
    phone: str,
    delivery: str,
    delivery_price: int,
    address: str,
    currency: str,
) -> Markup:
    return translator.t(
        lang,
        "order_details",
        name=name,
        phone=phone,
        delivery=delivery,
        delivery_price=format_money(delivery_price, currency),
        address=address or EMPTY,
    )


def confirmation_text(
    translator: Translator,
    lang: str,
    config: ClientConfig,
    cart: Cart,
    name: str,
    phone: str,
    option: DeliveryOption,
    address: str,
) -> Markup:
    currency = config.shop.currency
    return translator.t(
        lang,
        "confirm_order",
        items=items_text(translator, lang, cart_rows(cart, lang), currency),
        details=details_text(
            translator, lang, name, phone, pick(option.name, lang), option.price, address, currency
        ),
        total=format_money(cart.total + option.price, currency),
    )


def owner_order_text(
    translator: Translator, lang: str, order: Order, crm_enabled: bool, crm_failed: bool
) -> Markup:
    if not crm_enabled:
        crm = Markup("")
    elif crm_failed or order.bitrix_deal_id is None:
        crm = translator.t(lang, "owner_crm_failed")
    else:
        crm = translator.t(lang, "owner_crm_ok", deal_id=order.bitrix_deal_id)
    text = translator.t(
        lang,
        "owner_new_order",
        id=order.id,
        items=items_text(translator, lang, order_rows(order), order.currency),
        details=details_text(
            translator,
            lang,
            order.customer_name,
            order.phone,
            order.delivery_name,
            order.delivery_price,
            order.address,
            order.currency,
        ),
        total=format_money(order.total, order.currency),
        user_id=order.user_id,
    )
    return join_lines([text, crm]) if crm else text


def status_label(translator: Translator, lang: str, status: str) -> str:
    return translator.plain(lang, f"status_{status}")


def orders_list_text(
    translator: Translator, lang: str, orders: list[Order], timezone: str
) -> Markup:
    if not orders:
        return translator.t(lang, "orders_empty")
    zone = ZoneInfo(timezone)
    lines = [translator.t(lang, "orders_title")]
    for order in orders:
        lines.append(
            translator.t(
                lang,
                "orders_line",
                id=order.id,
                created=order.created_at.astimezone(zone).strftime("%d.%m %H:%M"),
                name=order.customer_name,
                phone=order.phone,
                total=format_money(order.total, order.currency),
                status=status_label(translator, lang, order.status),
            )
        )
    return join_lines(lines)
