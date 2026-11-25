from __future__ import annotations

from typing import Any

import httpx

from app.models import Order

TIMEOUT_SECONDS = 10.0


class BitrixError(Exception):
    pass


def deal_comments(order: Order) -> str:
    lines = [f"{item.name} x {item.quantity} = {item.subtotal}" for item in order.items]
    lines.append(f"{order.delivery_name}: {order.delivery_price}")
    if order.address:
        lines.append(order.address)
    lines.append(f"Telegram ID: {order.user_id}")
    return "\n".join(lines)


class BitrixClient:
    def __init__(self, webhook_url: str, http: httpx.AsyncClient, shop_name: str) -> None:
        self._base = webhook_url.rstrip("/")
        self._http = http
        self._shop_name = shop_name

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self._http.post(
                f"{self._base}/{method}.json", json=payload, timeout=TIMEOUT_SECONDS
            )
        except httpx.HTTPError as exc:
            raise BitrixError(f"{method}: {type(exc).__name__}") from None
        try:
            data = response.json()
        except ValueError:
            raise BitrixError(f"{method}: HTTP {response.status_code}, invalid JSON") from None
        if not isinstance(data, dict):
            raise BitrixError(f"{method}: HTTP {response.status_code}, unexpected response")
        if "error" in data:
            description = data.get("error_description") or data["error"]
            raise BitrixError(f"{method}: {description}")
        if response.is_error or "result" not in data:
            raise BitrixError(f"{method}: HTTP {response.status_code}, no result")
        return data["result"]

    async def _create(self, method: str, fields: dict[str, Any]) -> int:
        result = await self._call(method, {"fields": fields})
        try:
            return int(result)
        except (TypeError, ValueError):
            raise BitrixError(f"{method}: unexpected result {result!r}") from None

    async def create_deal(self, order: Order) -> int:
        contact_id = await self._create(
            "crm.contact.add",
            {
                "NAME": order.customer_name,
                "OPENED": "Y",
                "PHONE": [{"VALUE": order.phone, "VALUE_TYPE": "MOBILE"}],
            },
        )
        return await self._create(
            "crm.deal.add",
            {
                "TITLE": f"{self._shop_name}: Telegram #{order.id}",
                "CONTACT_IDS": [contact_id],
                "OPENED": "Y",
                "OPPORTUNITY": order.total,
                "CURRENCY_ID": order.currency,
                "COMMENTS": deal_comments(order),
            },
        )
