# Telegram shop bot template

A Telegram shop bot for small businesses (cafes, flower shops, clothing, cosmetics). One codebase, one `client.yaml` and one `.env` per client.

## What the bot does

For customers:

- `/start` with a choice of Russian or Kazakh. Every bot text lives in `locales/ru.yaml` and `locales/kk.yaml`.
- Catalog on inline keyboards: categories, then products with photo, price and description.
- Cart: add, remove, change quantity, see the total. `/cart` and `/catalog` open them directly.
- Checkout: name, phone (Telegram contact button or typed), delivery option, address, confirmation.

For the shop owner:

- Every order is saved to SQLite, sent to the owner chat as a formatted message and, when `CRM_ENABLED=true`, created in Bitrix24 as a contact plus a deal.
- `/orders` shows the last 10 orders.
- `/status <id> <new|done|cancelled>` changes an order status and tells the customer.
- Owner commands work only in the chat set in `owner_chat_id`.

If Bitrix24 is down or rejects the request, the order is still saved, the error is logged and the owner still gets the message, with a warning to enter the order by hand.

Orders placed outside working hours are accepted. The customer is told the order will be handled during working hours.

## Launch for a new client

You need Docker with Docker Compose and a bot token from [@BotFather](https://t.me/BotFather).

1. Clone the repository.

   ```bash
   git clone https://github.com/seerofeem/fablebottemplate.git shop-bot
   cd shop-bot
   ```

2. Create `.env` from the example and set `BOT_TOKEN`.

   ```bash
   cp .env.example .env
   ```

   ```dotenv
   BOT_TOKEN=1234567890:AA...
   BITRIX_WEBHOOK_URL=
   CRM_ENABLED=false
   ```

3. Find the owner chat ID. The owner sends any message to [@userinfobot](https://t.me/userinfobot) and copies the `Id` value. For a group chat, add the bot to the group and use the group ID (a negative number).

4. Edit `client.yaml`: shop name, welcome text, `owner_chat_id`, working hours, delivery options, categories and products. See the reference below.

5. Start the bot.

   ```bash
   docker compose up -d --build
   ```

6. Check the log. The line `Run polling for bot @your_bot` means the bot is running. A config mistake stops the bot at start and the log names the wrong field.

   ```bash
   docker compose logs -f bot
   ```

7. The owner opens the bot and presses **Start**. Telegram does not let a bot write to a person who has never opened it.

8. Place a test order from another account. Check the owner message, then `/orders` and `/status 1 done` in the owner chat.

9. Optional: connect Bitrix24 (see below).

After any change to `client.yaml` or `.env`:

```bash
docker compose up -d --force-recreate
```

Orders are stored in `./data/shop.db`. Back up this file. Carts and orders survive restarts. An unfinished checkout dialog does not: the customer opens the cart and starts checkout again.

## client.yaml reference

The file is validated at start. Unknown fields, missing translations, duplicate IDs and wrong formats stop the bot with a clear message.

| Field | Type | Rules |
| --- | --- | --- |
| `shop.name` | text | 1 to 64 characters |
| `shop.welcome` | texts by language | Shown after the language choice |
| `shop.languages` | list | `ru`, `kk` or both. The first one is the default and the language of owner messages |
| `shop.currency` | text | ISO code such as `KZT`. Also sent to Bitrix24 as the deal currency |
| `shop.timezone` | text | IANA name, default `Asia/Almaty` |
| `owner_chat_id` | number | Telegram chat that receives orders and may use owner commands |
| `working_hours` | map | All seven keys `mon` to `sun`. Value is `"HH:MM-HH:MM"` or `closed` |
| `delivery[].id` | ID | Unique |
| `delivery[].name` | texts by language | |
| `delivery[].price` | whole number | 0 or more, in currency units. 0 is shown as free |
| `delivery[].needs_address` | true or false | Default `true`. With `false` the bot does not ask for an address |
| `categories[].id` | ID | Unique |
| `categories[].name` | texts by language | |
| `categories[].products[].id` | ID | Unique across all categories |
| `categories[].products[].name` | texts by language | |
| `categories[].products[].price` | whole number | More than 0 |
| `categories[].products[].photo_url` | URL | Optional. Public `https` link to a JPG or PNG. If Telegram cannot load it, the product is sent as text |
| `categories[].products[].description` | texts by language | |

An ID is 1 to 32 characters of `a-z`, `0-9` and `_`.

"Texts by language" is a map with one entry per language listed in `shop.languages`:

```yaml
name:
  ru: "25 красных роз"
  kk: "25 қызыл раушан"
```

Prices are whole numbers without decimals. Keep product IDs stable: carts refer to products by ID, and a product removed from the file disappears from customers' carts.

The shipped `client.yaml` is a complete example for a fictional flower shop in Almaty.

## .env reference

| Variable | Required | Meaning |
| --- | --- | --- |
| `BOT_TOKEN` | yes | Token from @BotFather |
| `CRM_ENABLED` | no | `true` sends orders to Bitrix24. Default `false`: orders go only to the owner chat |
| `BITRIX_WEBHOOK_URL` | when `CRM_ENABLED=true` | Inbound webhook URL, must start with `https://` |

Never commit `.env`. The webhook URL is a secret: anyone who has it can write to the CRM.

## Bitrix24 webhook setup

1. In Bitrix24 open **Developer resources** (Разработчикам), then **Other** (Другое), then **Inbound webhook** (Входящий вебхук). On some plans the path is **Applications**, then **Developer resources**.
2. In access permissions choose **CRM (crm)**.
3. Save and copy the webhook URL. It looks like `https://yourcompany.bitrix24.kz/rest/1/abc123xyz/`.
4. Put it into `.env` and turn the CRM on.

   ```dotenv
   BITRIX_WEBHOOK_URL=https://yourcompany.bitrix24.kz/rest/1/abc123xyz/
   CRM_ENABLED=true
   ```

5. Apply the change with `docker compose up -d --force-recreate` and place a test order.

For each order the bot calls:

- `crm.contact.add` with the customer name and phone;
- `crm.deal.add` with the title `<shop name>: Telegram #<order id>`, the contact, the order total, the currency, and a comment listing the items, delivery option and address.

The owner message shows the deal number, or a warning if the deal was not created. The reason is in `docker compose logs bot`.

## Changing bot texts

Edit `locales/ru.yaml` and `locales/kk.yaml`. Both files must have the same keys. Words in `{braces}` are placeholders and must stay. Texts use Telegram HTML (`<b>`, `<i>`, `<code>`). Rebuild after a change: `docker compose up -d --build`.

## Development

Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy app
pytest
```

To run without Docker, create `.env` and run `python -m app.main`.

GitHub Actions runs the same checks on every pull request.

## Project layout

```text
app/config.py      settings from .env and client.yaml validation
app/cart.py        cart storage and math
app/orders.py      order creation, CRM call, owner notification
app/bitrix.py      Bitrix24 webhook client
app/texts.py       message formatting
app/keyboards.py   inline and reply keyboards
app/handlers/      start, catalog, cart, checkout, owner commands
locales/           bot texts in Russian and Kazakh
tests/             config, cart, orders with mocked Bitrix24, full bot flow
client.yaml        per-client configuration
```
