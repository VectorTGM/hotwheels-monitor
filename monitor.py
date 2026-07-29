#!/usr/bin/env python3
"""
Hotwheels Price & Availability Monitor
Checks Amazon India + FirstCry + Crossword for Hotwheels at MRP/base price.
Sends Telegram notifications when deals are found.
"""

import json
import time
import random
import logging
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

CONFIG_PATH = Path(__file__).parent / "config.json"
SEEN_FILE = Path(__file__).parent / "seen_deals.json"

BROWSER_HEADERS = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Cache-Control": "max-age=0",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    },
]

amazon_session = requests.Session()

EXCLUDED_KEYWORDS_AMAZON = ["matchbox", "majorette", "tomica", "hot wheels id", "disney",
                            "marvel", "star wars", "f1", "formula 1", "red bull f1",
                            "williams f1", "alpine f1", "bmw gold", "bugatti bolide"]

PREMIUM_SERIES = ["car culture", "boulevard", "silhouettes", "fast & furious premium",
                  "fast and furious premium", "treasure hunt", "super treasure hunt",
                  "zamac", "liberty walk", "premium", "real riders", "metal/metal",
                  "timeless icons", "exotic envy", "canyon warriors", "slide street",
                  "circuit legends", "team transport", "pop culture", "hw turbo",
                  "factory fresh", "hw green speed", "euro speed", "jdm legends",
                  "hw workshop"]

SILVER_SERIES = ["silver series", "hw race day", "hw street", "hw drag strip",
                 "hw modified", "hw rescue", "hw rollers", "hw screen time",
                 "hw speed graphics", "hw stunt", "hw track day", "baja blazers",
                 "experimotors", "forum fighters", "game time",
                 "hw wayne's world", "ring rusters", "rods & rods", "saturday slam",
                 "street beasts", "street shifters", "super chromes", "the homies",
                 "time creeper", "tooned", "ultra hots", "muscle mania",
                 "nightburnerz", "opening soon", "phantasy", "servando", "showroom",
                 "vw classics", "hw celebration racers", "compact kings",
                 "exotics", "hw dream garage", "hw euro", "hw j-imports",
                 "then and now", "hw moto", "hw green speed"]

EXCLUDED_MAINLINE = ["color shifters", "track creator", "track set", "hot wheels id",
                     "wall track", "city", "star wars", "mario kart", "disney",
                     "barbie", "matchbox", "multipack", "5-pack", "20 pack",
                     "gift pack", "stunt pack", "motor show pack"]

def is_premium_or_silver(title: str, price: float) -> str:
    title_lower = title.lower()
    for kw in EXCLUDED_MAINLINE:
        if kw in title_lower:
            return "mainline"
    for kw in PREMIUM_SERIES:
        if kw in title_lower:
            return "premium"
    for kw in SILVER_SERIES:
        if kw in title_lower:
            return "silver"
    if "premium" in title_lower:
        return "premium"
    if price >= 899:
        return "premium"
    if price >= 350:
        return "silver"
    return "mainline"

def setup_logging(log_file: str):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

def load_seen() -> dict:
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    return {}

def save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen, indent=2), encoding="utf-8")

def deal_key(platform: str, product_id: str, price: float) -> str:
    raw = f"{platform}:{product_id}:{price}"
    return hashlib.md5(raw.encode()).hexdigest()

def send_telegram(token: str, chat_id: str, message: str):
    if not token or ":" not in token or len(token.split(":")) != 2:
        logging.warning("Invalid Telegram bot token format.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            logging.info("Telegram alert sent!")
        else:
            logging.error(f"Telegram failed: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def warm_up_session():
    """Visit Amazon homepage to get cookies and establish session."""
    try:
        headers = random.choice(BROWSER_HEADERS).copy()
        r = amazon_session.get("https://www.amazon.in/", headers=headers, timeout=15)
        logging.info(f"Session warm-up: {r.status_code}")
        time.sleep(random.uniform(3, 6))
    except Exception as e:
        logging.warning(f"Warm-up failed: {e}")

def amazon_get(url: str, retries: int = 5) -> Optional[str]:
    """Fetch Amazon page with session cookies and rotating headers."""
    for attempt in range(retries):
        headers = random.choice(BROWSER_HEADERS).copy()
        headers["Referer"] = "https://www.amazon.in/"
        try:
            r = amazon_session.get(url, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code in (503, 429):
                wait = (2 ** attempt) * random.uniform(10, 20)
                logging.warning(f"    {r.status_code}, waiting {wait:.0f}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                time.sleep(random.uniform(3, 7))
                continue
            body = r.text
            body_lower = body.lower()
            is_captcha = (
                "captcha" in body_lower
                or "robot" in body_lower
                or "automated access" in body_lower
                or "please verify" in body_lower
                or "are you a robot" in body_lower
                or "sorry, we just need to make sure" in body_lower
            )
            has_product = "producttitle" in body_lower
            if is_captcha and not has_product:
                logging.warning(f"    CAPTCHA, waiting {30 + attempt * 10}s")
                time.sleep(30 + attempt * 10)
                continue
            if len(body) < 3000 and not has_product:
                logging.warning(f"    Short page ({len(body)} chars), retrying...")
                time.sleep(random.uniform(10, 20))
                continue
            return body
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(random.uniform(5, 12))
            else:
                logging.error(f"Fetch error: {e}")
    return None

def extract_prices_from_html(html: str) -> list:
    prices = []
    for m in re.finditer(r'class="a-offscreen"[^>]*>\s*(?:Rs\.?|[\u20b9])\s*([\d,]+(?:\.\d{2})?)', html):
        try:
            val = float(m.group(1).replace(",", ""))
            if 50 < val < 10000:
                prices.append(val)
        except ValueError:
            pass
    for m in re.finditer(r'(?:Rs\.?|[\u20b9])\s*([\d,]+(?:\.\d{2})?)', html):
        try:
            val = float(m.group(1).replace(",", ""))
            if 50 < val < 10000:
                prices.append(val)
        except ValueError:
            pass
    return prices

def search_amazon_hotwheels(config: dict, seen: dict) -> list:
    """Search Amazon India for Hot Wheels by keyword."""
    alerts = []
    max_above_mrp = config.get("amazon_max_price_above_mrp", 50)
    queries = config.get("amazon_search_queries", [])
    if not queries:
        return alerts

    for i, query in enumerate(queries):
        search_url = f"https://www.amazon.in/s?k={requests.utils.quote(query)}"
        logging.info(f"  Amazon search ({i+1}/{len(queries)}): {query}")
        html = amazon_get(search_url)
        if not html:
            time.sleep(random.uniform(10, 20))
            continue

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select('[data-asin]:not([data-asin=""])')

        found_any = False
        for card in cards[:5]:
            asin = card.get("data-asin", "")
            if not asin or len(asin) < 5:
                continue
            title_el = card.select_one("h2 a span, .a-size-base-plus")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            title_lower = title.lower()
            if "hot wheels" not in title_lower and "hotwheels" not in title_lower:
                continue
            if any(kw in title_lower for kw in EXCLUDED_KEYWORDS_AMAZON):
                continue

            price = None
            price_el = card.select_one(".a-price .a-offscreen")
            if price_el:
                raw = price_el.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
                try:
                    price = float(raw)
                except ValueError:
                    pass

            if price is None:
                all_prices = extract_prices_from_html(str(card))
                if all_prices:
                    price = min(all_prices)

            if price is None or price > 2000:
                continue

            series = is_premium_or_silver(title, price)
            if series == "mainline":
                continue

            url = f"https://www.amazon.in/dp/{asin}"
            series_max = 800 if series == "premium" else 350
            is_deal = False
            deal_reason = ""

            if price <= series_max:
                is_deal = True
                deal_reason = f"{chr(8377)}{price:.0f} - {series.title()} ({query})"

            if is_deal:
                dk = deal_key("amazon", url, price)
                if dk not in seen:
                    seen[dk] = datetime.now().isoformat()
                    alerts.append({
                        "platform": "Amazon",
                        "name": title,
                        "price": price,
                        "mrp": None,
                        "url": url,
                        "reason": deal_reason,
                    })
                    found_any = True

        if found_any:
            logging.info(f"    Found deals in '{query}'")
        time.sleep(random.uniform(20, 35))

    return alerts

def check_amazon_products(config: dict, seen: dict) -> list:
    """Check specific Amazon product URLs."""
    alerts = []
    max_above_mrp = config.get("amazon_max_price_above_mrp", 50)

    for product in config.get("amazon_products", []):
        url = product["url"]
        name = product.get("name", url)
        max_price = product.get("max_price", 999999)

        logging.info(f"  Amazon: {name}")
        time.sleep(random.uniform(15, 25))
        html = amazon_get(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = name
        title_el = soup.select_one("#productTitle")
        if title_el:
            title = title_el.get_text(strip=True)

        price = None
        price_el = soup.select_one(".a-price .a-offscreen, #corePrice_feature_div .a-offscreen, #corePriceDisplay_desktop_feature_div .a-offscreen")
        if price_el:
            raw = price_el.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
            try:
                price = float(raw)
            except ValueError:
                pass

        if price is None:
            for span in soup.find_all("span", class_="a-price"):
                offscreen = span.select_one(".a-offscreen")
                if offscreen:
                    raw = offscreen.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
                    try:
                        val = float(raw)
                        if val > 0:
                            price = val
                            break
                    except ValueError:
                        pass

        if price is None:
            all_prices = extract_prices_from_html(html)
            if all_prices:
                price = min(all_prices)

        if price is None:
            logging.warning(f"    Could not parse price")
            continue

        mrp = None
        mrp_el = soup.select_one(".a-price.a-text-price .a-offscreen")
        if mrp_el:
            raw = mrp_el.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
            try:
                mrp = float(raw)
            except ValueError:
                pass

        in_stock = True
        avail_el = soup.select_one("#availability span")
        if avail_el:
            in_stock = "in stock" in avail_el.get_text(strip=True).lower()

        logging.info(f"    Price: {chr(8377)}{price:.0f}, MRP: {chr(8377)}{mrp if mrp else 'N/A'}, Stock: {in_stock}")

        is_deal = False
        deal_reason = ""

        if price > max_price:
            pass
        elif mrp and price <= mrp + max_above_mrp:
            is_deal = True
            deal_reason = f"At/near MRP {chr(8377)}{mrp:.0f}"
        elif price <= max_price:
            is_deal = True
            deal_reason = f"Under {chr(8377)}{max_price}"

        if is_deal and in_stock:
            dk = deal_key("amazon", url, price)
            if dk not in seen:
                seen[dk] = datetime.now().isoformat()
                alerts.append({
                    "platform": "Amazon",
                    "name": title,
                    "price": price,
                    "mrp": mrp,
                    "url": url,
                    "reason": deal_reason,
                })

        time.sleep(random.uniform(15, 25))

    return alerts

# --- FirstCry Scraper ------------------------------------------------------

FIRSTCRY_EXCLUDE = ["monster truck", "mainline", "5-pack", "5 pack", "multipack",
                     "matchbox", "majorette", "tomica", "track set", "track creator",
                     "color shifters", "wall track", "hot wheels id", "gift pack",
                     "stunt pack", "motor show pack", "20 pack"]

def search_firstcry(config: dict, seen: dict) -> list:
    alerts = []
    pincode = config.get("firstcry_pincode", "400101")
    queries = config.get("firstcry_search_queries", [])
    max_above_mrp = config.get("amazon_max_price_above_mrp", 50)

    if not queries:
        return alerts

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    for i, query in enumerate(queries):
        search_url = f"https://www.firstcry.com/search?q={requests.utils.quote(query)}&pincode={pincode}"
        logging.info(f"  FirstCry ({i+1}/{len(queries)}): {query}")
        try:
            r = requests.get(search_url, headers=headers, timeout=20)
            if r.status_code != 200:
                logging.warning(f"    HTTP {r.status_code}")
                time.sleep(random.uniform(5, 10))
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            product_cards = soup.select(".product-card, .prod-item, [data-product-id], .plp-card, li.product, div.product")

            for card in product_cards[:5]:
                title_el = card.select_one(".product-name, .prod-name, h3, h2, .product-title, a[title]")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True) or title_el.get("title", "")
                if not title:
                    continue

                title_lower = title.lower()
                if "hot wheels" not in title_lower and "hotwheels" not in title_lower:
                    continue
                if any(kw in title_lower for kw in FIRSTCRY_EXCLUDE):
                    continue

                price = None
                price_el = card.select_one(".new-price, .selling-price, .price-new, .offer-price, .product-price")
                if price_el:
                    raw = price_el.get_text(strip=True).replace("Rs.", "").replace("\u20b9", "").replace(",", "").strip()
                    try:
                        price = float(raw)
                    except ValueError:
                        pass

                if price is None:
                    for p in card.select(".price, .product-price span, .amt"):
                        raw = p.get_text(strip=True).replace("Rs.", "").replace("\u20b9", "").replace(",", "").strip()
                        try:
                            val = float(raw)
                            if price is None or val < price:
                                price = val
                        except ValueError:
                            pass

                if price is None:
                    continue

                mrp = None
                mrp_el = card.select_one(".old-price, .mrp, .price-old, .original-price")
                if mrp_el:
                    raw = mrp_el.get_text(strip=True).replace("Rs.", "").replace("\u20b9", "").replace(",", "").strip()
                    try:
                        mrp = float(raw)
                    except ValueError:
                        pass

                in_stock = True
                if card.select_one(".out-of-stock, .sold-out, .oos"):
                    in_stock = False

                link_el = card.select_one("a[href]")
                url = ""
                if link_el:
                    href = link_el.get("href", "")
                    url = f"https://www.firstcry.com{href}" if href.startswith("/") else href

                if not in_stock:
                    continue

                series = is_premium_or_silver(title, price)
                if series == "mainline":
                    continue

                series_max = 800 if series == "premium" else 350
                is_deal = False
                deal_reason = ""

                if price <= series_max:
                    if mrp and price <= mrp + max_above_mrp:
                        is_deal = True
                        deal_reason = f"At/near MRP {chr(8377)}{mrp:.0f} ({series}, FirstCry)"
                    elif price <= series_max:
                        is_deal = True
                        deal_reason = f"{chr(8377)}{price:.0f} ({series}, FirstCry)"

                if is_deal:
                    dk = deal_key("firstcry", url or title, price)
                    if dk not in seen:
                        seen[dk] = datetime.now().isoformat()
                        alerts.append({
                            "platform": "FirstCry",
                            "name": title,
                            "price": price,
                            "mrp": mrp,
                            "url": url or search_url,
                            "reason": deal_reason,
                        })

        except Exception as e:
            logging.error(f"    FirstCry error: {e}")

        time.sleep(random.uniform(5, 10))

    return alerts

# --- Crossword Scraper (Shopify JSON API) ----------------------------------

CROSSWORD_EXCLUDE = ["monster truck", "mainline", "5-pack", "5 pack", "multipack",
                      "matchbox", "majorette", "tomica", "track set", "track creator",
                      "color shifters", "wall track", "hot wheels id", "gift pack",
                      "stunt pack", "motor show pack", "20 pack"]

def search_crossword(config: dict, seen: dict) -> list:
    alerts = []
    queries = config.get("crossword_search_queries", [])
    max_above_mrp = config.get("amazon_max_price_above_mrp", 50)

    if not queries:
        return alerts

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/html",
    }

    for i, query in enumerate(queries):
        search_url = f"https://www.crossword.in/search?q={requests.utils.quote(query)}"
        logging.info(f"  Crossword ({i+1}/{len(queries)}): {query}")
        try:
            r = requests.get(search_url, headers=headers, timeout=20)
            if r.status_code != 200:
                logging.warning(f"    HTTP {r.status_code}")
                time.sleep(random.uniform(5, 10))
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            product_cards = soup.select(".product-card, .grid-product, .product-item, [data-product-id]")

            for card in product_cards[:5]:
                title_el = card.select_one(".product-card__title, .product-title, h3, h2, a[title]")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True) or title_el.get("title", "")
                if not title:
                    continue

                title_lower = title.lower()
                if "hot wheels" not in title_lower and "hotwheels" not in title_lower:
                    continue
                if any(kw in title_lower for kw in CROSSWORD_EXCLUDE):
                    continue

                price = None
                price_el = card.select_one(".product-card__price--current, .price--current, .price, .selling-price")
                if price_el:
                    raw = price_el.get_text(strip=True).replace("Rs.", "").replace("\u20b9", "").replace(",", "").strip()
                    try:
                        price = float(raw)
                    except ValueError:
                        pass

                if price is None:
                    continue

                mrp = None
                mrp_el = card.select_one(".product-card__price--compare, .price--compare, .compare-price")
                if mrp_el:
                    raw = mrp_el.get_text(strip=True).replace("Rs.", "").replace("\u20b9", "").replace(",", "").strip()
                    try:
                        mrp = float(raw)
                    except ValueError:
                        pass

                in_stock = True
                if card.select_one(".sold-out, .out-of-stock"):
                    in_stock = False

                link_el = card.select_one("a[href]")
                url = ""
                if link_el:
                    href = link_el.get("href", "")
                    url = f"https://www.crossword.in{href}" if href.startswith("/") else href

                if not in_stock:
                    continue

                series = is_premium_or_silver(title, price)
                if series == "mainline":
                    continue

                series_max = 800 if series == "premium" else 350
                is_deal = False
                deal_reason = ""

                if price <= series_max:
                    if mrp and price <= mrp + max_above_mrp:
                        is_deal = True
                        deal_reason = f"At/near MRP {chr(8377)}{mrp:.0f} ({series}, Crossword)"
                    elif price <= series_max:
                        is_deal = True
                        deal_reason = f"{chr(8377)}{price:.0f} ({series}, Crossword)"

                if is_deal:
                    dk = deal_key("crossword", url or title, price)
                    if dk not in seen:
                        seen[dk] = datetime.now().isoformat()
                        alerts.append({
                            "platform": "Crossword",
                            "name": title,
                            "price": price,
                            "mrp": mrp,
                            "url": url or search_url,
                            "reason": deal_reason,
                        })

        except Exception as e:
            logging.error(f"    Crossword error: {e}")

        time.sleep(random.uniform(5, 10))

    return alerts

# --- Notification Formatter -------------------------------------------------

def format_alert(alert: dict) -> str:
    platform = alert["platform"]
    name = alert["name"][:60]
    price = alert["price"]
    mrp = alert.get("mrp")
    url = alert["url"]
    reason = alert["reason"]

    lines = [f" Hotwheels Deal Found!"]
    lines.append(f"")
    lines.append(f" {platform}: {name}")
    lines.append(f" Price: {chr(8377)}{price:.0f}")
    if mrp:
        lines.append(f" MRP: {chr(8377)}{mrp:.0f}")
    lines.append(f" {reason}")
    lines.append(f"")
    lines.append(f" {url}")
    return "\n".join(lines)

# --- Main Loop --------------------------------------------------------------

def run_check(config: dict, seen: dict) -> int:
    alerts = []

    logging.info("  [Amazon - Direct Products]")
    try:
        alerts.extend(check_amazon_products(config, seen))
    except Exception as e:
        logging.error(f"Amazon direct check failed: {e}")

    logging.info("  [Amazon - Search]")
    try:
        alerts.extend(search_amazon_hotwheels(config, seen))
    except Exception as e:
        logging.error(f"Amazon search failed: {e}")

    logging.info("  [FirstCry]")
    try:
        alerts.extend(search_firstcry(config, seen))
    except Exception as e:
        logging.error(f"FirstCry check failed: {e}")

    logging.info("  [Crossword]")
    try:
        alerts.extend(search_crossword(config, seen))
    except Exception as e:
        logging.error(f"Crossword check failed: {e}")

    token = config.get("telegram_bot_token", "")
    chat_id = config.get("telegram_chat_id", "")

    if alerts and token and chat_id:
        for alert in alerts:
            msg = format_alert(alert)
            send_telegram(token, chat_id, msg)
            logging.info(f"Alert: {alert['platform']} - {alert['name'][:40]}")
            time.sleep(1)

    return len(alerts)

def main():
    if not CONFIG_PATH.exists():
        print(f"Config not found: {CONFIG_PATH}")
        sys.exit(1)

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    setup_logging(config.get("log_file", "hotwheels_alerts.log"))

    logging.info("=" * 60)
    logging.info("Hotwheels Monitor Started")
    logging.info(f"Interval: {config.get('check_interval_minutes', 5)} min")
    logging.info(f"Amazon products: {len(config.get('amazon_products', []))}")
    logging.info("=" * 60)

    warm_up_session()

    seen = load_seen()
    interval = config.get("check_interval_minutes", 5) * 60

    while True:
        try:
            logging.info(f"\n--- Check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
            count = run_check(config, seen)
            save_seen(seen)
            logging.info(f"Done. New alerts: {count}")
            logging.info(f"Next check in {config.get('check_interval_minutes', 5)} min...")
        except KeyboardInterrupt:
            logging.info("Stopped.")
            break
        except Exception as e:
            logging.error(f"Error: {e}")

        time.sleep(interval)

if __name__ == "__main__":
    main()
