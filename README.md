# Hot Wheels Price & Availability Monitor

Monitors Amazon India and Indian Shopify stores for Hot Wheels diecast cars at MRP/base price. Sends Telegram alerts when deals are found.

## Features

- **Amazon India**: Checks specific products for price at/below MRP (+₹50 tolerance)
- **Shopify Multi-Site Gateway**: Monitors Kinder Logs and Zoomsters India via JSON API
- **Telegram Notifications**: Free mobile alerts when deals are found
- **Auto-scheduling**: Runs every 5 minutes (configurable)
- **Deduplication**: Won't alert you twice for the same deal
- **Brand Filtering**: Only carded Hot Wheels — excludes Matchbox, Majorette, loose/uncarded cars, and F1 models

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run setup wizard (configure Telegram bot)
python setup.py

# 3. Run the monitor
python monitor.py
```

## Telegram Bot Setup (Free)

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`, give it a name (e.g., "Hotwheels Alert Bot")
3. Copy the **bot token** you receive
4. Search for your new bot on Telegram, send `/start`
5. Visit `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
6. Find `"chat":{"id":123456789}` - that's your **chat ID**
7. Run `python setup.py` and paste both values

## Configuration

Edit `config.json` to customize:

```json
{
  "telegram_bot_token": "your_bot_token",
  "telegram_chat_id": "your_chat_id",
  "check_interval_minutes": 5,
  "amazon_max_price_above_mrp": 50,
  "amazon_products": [
    {
      "url": "https://www.amazon.in/dp/ASIN_HERE",
      "name": "Product Name",
      "max_price": 700
    }
  ],
  "shopify_sites": [
    {
      "name": "Store Name",
      "base_url": "https://store-url.in",
      "products_json": "https://store-url.in/collections/all/products.json",
      "search_url": "https://store-url.in/search/suggest.json?q={query}&resources[type]=product",
      "vendor_filter": "Hot Wheels",
      "exclude_keywords": ["uncarded", "key chain"]
    }
  ],
  "shopify_search_queries": ["hot wheels porsche", "hot wheels nissan"],
  "shopify_max_price": 800
}
```

## Adding More Products

### Amazon
1. Find the product on amazon.in
2. Copy the ASIN from the URL (e.g., `dp/B0FQTF35GR`)
3. Add to `config.json` under `amazon_products`

### Shopify Stores
1. The monitor searches via Shopify JSON API (`/search/suggest.json`)
2. Add more search terms in `shopify_search_queries`
3. Add more Shopify stores in `shopify_sites` with their JSON API endpoints

## Files

| File | Description |
|------|-------------|
| `monitor.py` | Main monitoring script |
| `setup.py` | Interactive setup wizard |
| `config.json` | Configuration file |
| `requirements.txt` | Python dependencies |
| `seen_deals.json` | Tracks sent alerts (auto-created) |
| `hotwheels_alerts.log` | Log file |

## Running in Background

### Windows
```bash
# Use a separate terminal/window
python monitor.py
```

### Linux/Mac
```bash
nohup python monitor.py > /dev/null 2>&1 &
```

## Troubleshooting

- **Amazon blocking requests**: The script rotates User-Agent headers. If blocked, wait 30-60 minutes.
- **Shopify search returning wrong brands**: The vendor filter and exclusion list ensure only genuine Hot Wheels products are alerted.
- **No Telegram alerts**: Verify your bot token and chat ID in config.json.
- **Check logs**: Look at `hotwheels_alerts.log` for detailed error messages.
