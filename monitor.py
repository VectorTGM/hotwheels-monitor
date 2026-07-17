#!/usr/bin/env python3
"""
Hotwheels Price & Availability Monitor
Checks Amazon India + Indian Shopify stores for Hotwheels at MRP/base price.
Sends Telegram notifications when deals are found.
"""

import json
import time
import random
import logging
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

CONFIG_PATH = Path(__file__).parent / "config.json"
SEEN_FILE = Path(__file__).parent / "seen_deals.json"

IMPERSONATE_LIST = ["chrome120", "chrome110", "chrome107", "safari15_5", "edge99"]

HEADERS_LIST = [
    {
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
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
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Cache-Control": "max-age=0",
    },
]

FREE_PROXY_URLS = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt",
]

proxy_pool: list = []

def fetch_free_proxies() -> list:
    """Fetch free proxies from public lists."""
    proxies = []
    for url in FREE_PROXY_URLS:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                lines = [l.strip() for l in r.text.strip().split("\n") if l.strip()]
                for line in lines:
                    if ":" in line:
                        proxy = line if line.startswith("http") else f"http://{line}"
                        proxies.append(proxy)
            logging.info(f"  Fetched {len(lines)} proxies from {url.split('/')[-1]}")
        except Exception as e:
            logging.warning(f"  Proxy fetch failed from {url.split('/')[-1]}: {e}")
    random.shuffle(proxies)
    return proxies

def get_proxy() -> Optional[dict]:
    """Get a random proxy from the pool."""
    global proxy_pool
    if not proxy_pool:
        return None
    proxy = random.choice(proxy_pool)
    return {"http": proxy, "https": proxy}

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
            logging.info("Telegram alert sent successfully!")
        else:
            logging.error(f"Telegram send failed: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Telegram error: {e}")

# --- Amazon India Scraper ---------------------------------------------------

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

def get_amazon_page(url: str, retries: int = 5) -> Optional[str]:
    """Fetch Amazon page with rotating impersonation, proxies, and exponential backoff."""
    for attempt in range(retries):
        impersonate = random.choice(IMPERSONATE_LIST)
        headers = random.choice(HEADERS_LIST).copy()
        proxy = get_proxy()
        proxy_str = f" via {proxy['https'].split('//')[1][:20]}" if proxy else " direct"
        try:
            session = cffi_requests.Session(impersonate=impersonate)
            r = session.get(url, headers=headers, proxies=proxy, timeout=25, allow_redirects=True)
            if r.status_code == 503:
                wait = (2 ** attempt) * random.uniform(10, 20)
                logging.warning(f"    503 ({impersonate}{proxy_str}), waiting {wait:.0f}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                if proxy and proxy in proxy_pool:
                    proxy_pool.remove(proxy["https"])
                continue
            if r.status_code == 429:
                wait = (2 ** attempt) * random.uniform(15, 30)
                logging.warning(f"    429 rate-limit ({impersonate}{proxy_str}), waiting {wait:.0f}s")
                time.sleep(wait)
                if proxy and proxy in proxy_pool:
                    proxy_pool.remove(proxy["https"])
                continue
            if r.status_code != 200:
                logging.warning(f"    HTTP {r.status_code} ({impersonate}{proxy_str}) for {url[:80]}")
                time.sleep(random.uniform(3, 7))
                continue
            return r.text
        except Exception as e:
            if proxy and proxy in proxy_pool:
                proxy_pool.remove(proxy["https"])
            if attempt < retries - 1:
                time.sleep(random.uniform(5, 12))
            else:
                logging.error(f"Amazon fetch error: {e}")
    return None

def parse_amazon_product(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {"price": None, "mrp": None, "title": None, "in_stock": True}

    title_el = soup.select_one("#productTitle")
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    price_el = soup.select_one(".a-price .a-offscreen")
    if price_el:
        raw = price_el.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
        try:
            result["price"] = float(raw)
        except ValueError:
            pass

    mrp_el = soup.select_one("#priceblock_ourprice, #priceblock_dealprice, .a-price.a-text-price .a-offscreen")
    if mrp_el:
        raw = mrp_el.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
        try:
            result["mrp"] = float(raw)
        except ValueError:
            pass

    if result["mrp"] is None:
        mrp_spans = soup.find_all("span", class_="a-price")
        for span in mrp_spans:
            parent = span.find_parent("td") or span.find_parent("div")
            if parent and "M.R.P" in parent.get_text():
                offscreen = span.select_one(".a-offscreen")
                if offscreen:
                    raw = offscreen.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
                    try:
                        result["mrp"] = float(raw)
                    except ValueError:
                        pass
                    break

    avail_el = soup.select_one("#availability span")
    if avail_el:
        text = avail_el.get_text(strip=True).lower()
        result["in_stock"] = "in stock" in text

    return result

def parse_amazon_search(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    cards = soup.select('[data-asin]:not([data-asin=""])')
    for card in cards:
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
        price_el = card.select_one(".a-price .a-offscreen")
        if not price_el:
            continue
        raw = price_el.get_text(strip=True).replace("\u20b9", "").replace(",", "").strip()
        try:
            price = float(raw)
        except ValueError:
            continue
        if price > 2000:
            continue
        series = is_premium_or_silver(title, price)
        if series == "mainline":
            continue
        url = f"https://www.amazon.in/dp/{asin}"
        results.append({"asin": asin, "title": title, "price": price, "url": url, "series": series})
    return results

def search_amazon_hotwheels(config: dict, seen: dict) -> list:
    alerts = []
    max_above_mrp = config.get("amazon_max_price_above_mrp", 50)
    queries = config.get("amazon_search_queries", [])
    if not queries:
        return alerts

    for query in queries:
        search_url = f"https://www.amazon.in/s?k={requests.utils.quote(query)}"
        logging.info(f"  Amazon search: {query}")
        html = get_amazon_page(search_url)
        if not html:
            time.sleep(random.uniform(10, 20))
            continue

        products = parse_amazon_search(html)
        for prod in products[:3]:
            time.sleep(random.uniform(4, 8))
            detail_html = get_amazon_page(prod["url"])
            if not detail_html:
                continue
            data = parse_amazon_product(detail_html)
            price = data["price"]
            mrp = data["mrp"]
            in_stock = data["in_stock"]
            title = data.get("title", prod["title"])
            series = prod.get("series", "silver")

            if price is None:
                continue

            logging.info(f"    [{series.upper()}] {title[:50]}: \u20b9{price}, MRP: \u20b9{mrp}")

            is_deal = False
            deal_reason = ""
            series_max = 800 if series == "premium" else 350

            if price <= series_max:
                if mrp and price <= mrp + max_above_mrp:
                    is_deal = True
                    deal_reason = f"At/near MRP \u20b9{mrp} ({series})"
                elif price <= series_max:
                    is_deal = True
                    deal_reason = f"Under \u20b9{series_max} ({series})"

            if is_deal and in_stock:
                dk = deal_key("amazon", prod["url"], price)
                if dk not in seen:
                    seen[dk] = datetime.now().isoformat()
                    alerts.append({
                        "platform": "Amazon",
                        "name": title,
                        "price": price,
                        "mrp": mrp,
                        "url": prod["url"],
                        "reason": deal_reason,
                    })

        time.sleep(random.uniform(8, 15))

    return alerts

def check_amazon_products(config: dict, seen: dict) -> list:
    alerts = []
    max_above_mrp = config.get("amazon_max_price_above_mrp", 50)

    for product in config.get("amazon_products", []):
        url = product["url"]
        name = product.get("name", url)
        max_price = product.get("max_price", 999999)

        logging.info(f"  Amazon: {name}")
        html = get_amazon_page(url)
        if not html:
            continue

        data = parse_amazon_product(html)
        price = data["price"]
        mrp = data["mrp"]
        in_stock = data["in_stock"]
        title = data.get("title", name)

        if price is None:
            logging.warning(f"    Could not parse price")
            continue

        logging.info(f"    Price: \u20b9{price}, MRP: \u20b9{mrp}, Stock: {in_stock}")

        is_deal = False
        deal_reason = ""

        if price > max_price:
            pass
        elif mrp and price <= mrp + max_above_mrp:
            if not product.get("ignore_near_mrp", False):
                is_deal = True
                deal_reason = f"At/near MRP \u20b9{mrp}"
        elif price <= max_price:
            is_deal = True
            deal_reason = f"Under \u20b9{max_price}"

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

        time.sleep(random.uniform(4, 8))

    return alerts

# --- FirstCry Scraper ------------------------------------------------------

FIRSTCRY_EXCLUDE = ["monster truck", "mainline", "5-pack", "5 pack", "multipack",
                     "matchbox", "majorette", "tomica", "track set", "track creator",
                     "color shifters", "wall track", "hot wheels id", "gift pack",
                     "stunt pack", "motor show pack", "20 pack"]

def parse_firstcry_products(html: str, query: str) -> list:
    """Parse FirstCry search results HTML."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    product_cards = soup.select(".product-card, .prod-item, [data-product-id], .product-listing .product-item, .search-product-item")
    if not product_cards:
        product_cards = soup.select("li.product, div.product, .plp-card")

    for card in product_cards:
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
        mrp = None

        price_el = card.select_one(".new-price, .selling-price, .price-new, .offer-price, .product-price")
        if price_el:
            raw = price_el.get_text(strip=True).replace("Rs.", "").replace("₹", "").replace(",", "").strip()
            try:
                price = float(raw)
            except ValueError:
                pass

        if price is None:
            all_prices = card.select(".price, .product-price span, .amt")
            for p in all_prices:
                raw = p.get_text(strip=True).replace("Rs.", "").replace("₹", "").replace(",", "").strip()
                try:
                    val = float(raw)
                    if price is None or val < price:
                        price = val
                except ValueError:
                    pass

        mrp_el = card.select_one(".old-price, .mrp, .price-old, .original-price, .list-price")
        if mrp_el:
            raw = mrp_el.get_text(strip=True).replace("Rs.", "").replace("₹", "").replace(",", "").strip()
            try:
                mrp = float(raw)
            except ValueError:
                pass

        if price is None:
            continue

        in_stock = True
        out_of_stock_el = card.select_one(".out-of-stock, .sold-out, .oos")
        if out_of_stock_el:
            in_stock = False
        add_to_cart = card.select_one(".add-to-cart, .atc-btn, button[data-action='add-to-cart']")
        if not out_of_stock_el and not add_to_cart:
            if price and price > 500:
                pass

        link_el = card.select_one("a[href*='/']", )
        url = ""
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("/"):
                url = f"https://www.firstcry.com{href}"
            elif href.startswith("http"):
                url = href

        results.append({
            "title": title,
            "price": price,
            "mrp": mrp,
            "url": url,
            "in_stock": in_stock,
            "query": query,
        })

    return results

def search_firstcry(config: dict, seen: dict) -> list:
    """Search FirstCry for Hot Wheels by name."""
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

    for query in queries:
        search_url = f"https://www.firstcry.com/search?q={requests.utils.quote(query)}&pincode={pincode}"
        logging.info(f"  FirstCry search: {query}")
        try:
            r = requests.get(search_url, headers=headers, timeout=20)
            if r.status_code != 200:
                logging.warning(f"    FirstCry HTTP {r.status_code}")
                time.sleep(random.uniform(5, 10))
                continue
            products = parse_firstcry_products(r.text, query)
            for prod in products[:3]:
                title = prod["title"]
                price = prod["price"]
                mrp = prod["mrp"]
                in_stock = prod["in_stock"]
                url = prod["url"]

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
                        deal_reason = f"At/near MRP \u20b9{mrp} ({series}, FirstCry)"
                    elif price <= series_max:
                        is_deal = True
                        deal_reason = f"Under \u20b9{series_max} ({series}, FirstCry)"

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
    """Search Crossword for Hot Wheels using Shopify JSON API."""
    alerts = []
    queries = config.get("crossword_search_queries", [])
    max_above_mrp = config.get("amazon_max_price_above_mrp", 50)

    if not queries:
        return alerts

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    for query in queries:
        search_url = f"https://www.crossword.in/search?q={requests.utils.quote(query)}"
        logging.info(f"  Crossword search: {query}")
        try:
            r = requests.get(search_url, headers=headers, timeout=20)
            if r.status_code != 200:
                logging.warning(f"    Crossword HTTP {r.status_code}")
                time.sleep(random.uniform(5, 10))
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            product_cards = soup.select(".product-card, .grid-product, .product-item, [data-product-id]")

            for card in product_cards[:3]:
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
                mrp = None

                price_el = card.select_one(".product-card__price--current, .price--current, .price, .selling-price")
                if price_el:
                    raw = price_el.get_text(strip=True).replace("Rs.", "").replace("₹", "").replace(",", "").strip()
                    try:
                        price = float(raw)
                    except ValueError:
                        pass

                mrp_el = card.select_one(".product-card__price--compare, .price--compare, .compare-price, .original-price")
                if mrp_el:
                    raw = mrp_el.get_text(strip=True).replace("Rs.", "").replace("₹", "").replace(",", "").strip()
                    try:
                        mrp = float(raw)
                    except ValueError:
                        pass

                if price is None:
                    continue

                in_stock = True
                oos = card.select_one(".sold-out, .out-of-stock, .unavailable")
                if oos:
                    in_stock = False

                link_el = card.select_one("a[href]")
                url = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("/"):
                        url = f"https://www.crossword.in{href}"
                    elif href.startswith("http"):
                        url = href

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
                        deal_reason = f"At/near MRP \u20b9{mrp} ({series}, Crossword)"
                    elif price <= series_max:
                        is_deal = True
                        deal_reason = f"Under \u20b9{series_max} ({series}, Crossword)"

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

# --- Shopify Multi-Site Gateway --------------------------------------------

EXCLUDED_BRANDS = ["matchbox", "majorette", "tomica", "hot wheels id", "disney", "marvel", "star wars"]

SILVER_SERIES_KEYWORDS = ["silver series", "hw race day", "hw street", "hw drag strip",
                          "hw modified", "hw rescue", "hw rollers", "hw screen time",
                          "hw speed graphics", "hw stunt", "hw track day", "baja blazers",
                          "experimotors", "forum fighters", "game time",
                          "hw wayne's world", "ring rusters", "rods & rods", "saturday slam",
                          "street beasts", "street shifters", "super chromes",
                          "the homies", "time creeper", "tooned", "ultra hots",
                          "muscle mania", "nightburnerz", "opening soon", "phantasy",
                          "servando", "showroom", "vw classics", "hw celebration racers",
                          "compact kings", "exotics", "hw dream garage", "hw euro",
                          "then and now", "hw moto", "hw green speed", "hw j-imports"]

PREMIUM_SERIES_KEYWORDS = ["car culture", "boulevard", "silhouettes", "fast & furious",
                           "premium", "treasure hunt", "super treasure hunt", "zamac",
                           "liberty walk", "jdm", "euro speed", "real riders",
                           "metal/metal", "timeless icons", "exotic envy",
                           "canyon warriors", "slide street", "circuit legends",
                           "team transport", "pop culture", "factory fresh"]

EXCLUDED_MAINLINE_KEYWORDS = ["color shifters", "track creator", "track set", "hot wheels id",
                               "wall track", "city", "star wars", "mario kart", "disney",
                               "barbie", "matchbox", "multipack", "5-pack", "20 pack",
                               "gift pack", "stunt pack", "motor show pack"]

def get_shopify_max_price(title: str, default_max: float) -> float:
    title_lower = title.lower()

    for kw in EXCLUDED_MAINLINE_KEYWORDS:
        if kw in title_lower:
            return 0

    for kw in PREMIUM_SERIES_KEYWORDS:
        if kw in title_lower:
            return 800.0

    for kw in SILVER_SERIES_KEYWORDS:
        if kw in title_lower:
            return 350.0

    if "premium" in title_lower:
        return 800.0

    return default_max

def is_valid_hot_wheels_product(vendor: str, title: str, vendor_filter: str, exclude_keywords: list) -> bool:
    vendor_lower = vendor.lower().strip()
    title_lower = title.lower().strip()

    if vendor_filter.lower() not in vendor_lower:
        return False

    for brand in EXCLUDED_BRANDS:
        if brand in vendor_lower or brand in title_lower:
            return False

    if any(kw in title_lower for kw in exclude_keywords):
        return False

    hw_indicators = ["hot wheels", "hotwheels", "car culture", "boulevard", "silhouettes",
                     "fast & furious", "mainline", "premium", "treasure hunt", "super treasure hunt",
                     "zamac", ".factory fresh", "j-imports", "hw green speed", "hw street",
                     "hw rescue", "baja blazers", "drag strip", "experimotors", "forum fighters",
                     "game time", "hw j-imports", "hw modified", "hw rescue", "hw rollers",
                     "hw screen time", "hw speed graphics", "hw stunt", "hw track day",
                     "hw wayne's world", "japan historics", "kings of crunch", "liberty walk",
                     "muscle mania", "nightburnerz", "opening soon", "phantasy", "ring rusters",
                     "rods & rods", "saturday slam", "scifi & fantasy", "servando", "showroom",
                     "street beasts", "street shifters", "super chromes", "the homies",
                     "time creeper", "tooned", "ultra hots", "volkswagen classics"]

    if not any(ind in title_lower for ind in hw_indicators):
        if "hot wheels" not in title_lower and "hotwheels" not in title_lower:
            return False

    return True

def shopify_search_site(site: dict, query: str, max_price: float) -> list:
    base_url = site["base_url"]
    search_url = site["search_url"].replace("{query}", requests.utils.quote(query))
    vendor_filter = site.get("vendor_filter", "Hot Wheels")
    exclude_keywords = site.get("exclude_keywords", ["uncarded"])
    products = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    try:
        r = requests.get(search_url, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            search_products = (
                data.get("resources", {})
                .get("results", {})
                .get("products", [])
            )
            for p in search_products:
                vendor = p.get("vendor", "")
                title = p.get("title", "")

                if not is_valid_hot_wheels_product(vendor, title, vendor_filter, exclude_keywords):
                    continue

                price = None
                if p.get("price"):
                    try:
                        price = float(p["price"].replace(",", ""))
                    except (ValueError, AttributeError):
                        pass

                if price:
                    product_max = get_shopify_max_price(title, max_price)
                    if price <= product_max:
                        available = p.get("available", True)
                        products.append({
                            "id": str(p.get("id", "")),
                            "title": title,
                            "price": price,
                            "url": base_url + p.get("url", ""),
                            "available": available,
                            "site": site["name"],
                        })
    except Exception as e:
        logging.debug(f"Shopify search error for {site['name']}: {e}")

    return products

def shopify_fetch_products(site: dict, max_price: float, seen: dict) -> list:
    products_json = site["products_json"]
    base_url = site["base_url"]
    vendor_filter = site.get("vendor_filter", "Hot Wheels")
    exclude_keywords = site.get("exclude_keywords", ["uncarded"])
    products = []
    page = 1

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    while page <= 10:
        try:
            url = f"{products_json}?limit=250&page={page}"
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                break

            data = r.json()
            items = data.get("products", [])
            if not items:
                break

            for item in items:
                vendor = item.get("vendor", "")
                title = item.get("title", "")

                if not is_valid_hot_wheels_product(vendor, title, vendor_filter, exclude_keywords):
                    continue

                for variant in item.get("variants", []):
                    if not variant.get("available", False):
                        continue

                    try:
                        price = float(variant.get("price", "0"))
                    except (ValueError, TypeError):
                        continue

                    product_max = get_shopify_max_price(title, max_price)
                    if price <= product_max:
                        handle = item.get("handle", "")
                        product_url = f"{base_url}/products/{handle}"
                        dk = deal_key(site["name"], str(item["id"]), price)
                        if dk not in seen:
                            seen[dk] = datetime.now().isoformat()
                            products.append({
                                "id": str(item["id"]),
                                "title": title,
                                "price": price,
                                "url": product_url,
                                "available": True,
                                "site": site["name"],
                            })

            page += 1
            time.sleep(1)

        except Exception as e:
            logging.error(f"Shopify fetch error for {site['name']}: {e}")
            break

    return products

def check_shopify_sites(config: dict, seen: dict) -> list:
    alerts = []
    max_price = config.get("shopify_max_price", 800)
    queries = config.get("shopify_search_queries", ["hotwheels"])

    for site in config.get("shopify_sites", []):
        site_name = site["name"]
        logging.info(f"  Checking {site_name}...")

        found = []

        for query in queries:
            results = shopify_search_site(site, query, max_price)
            found.extend(results)
            time.sleep(1)

        if not found:
            logging.info(f"    No deals under \u20b9{max_price} from search, trying full catalog...")
            found = shopify_fetch_products(site, max_price, seen)

        for item in found:
            dk = deal_key(site_name, item["id"], item["price"])
            if dk not in seen:
                seen[dk] = datetime.now().isoformat()
                alerts.append({
                    "platform": site_name,
                    "name": item["title"],
                    "price": item["price"],
                    "mrp": None,
                    "url": item["url"],
                    "reason": f"Under \u20b9{max_price} on {site_name}",
                })

        if alerts:
            logging.info(f"    Found {len(alerts)} deals on {site_name}")
        else:
            logging.info(f"    No new deals under \u20b9{max_price}")

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
    lines.append(f" Price: \u20b9{price:.0f}")
    if mrp:
        lines.append(f" MRP: \u20b9{mrp:.0f}")
    lines.append(f" {reason}")
    lines.append(f"")
    lines.append(f" {url}")
    return "\n".join(lines)

# --- Main Loop --------------------------------------------------------------

def run_check(config: dict, seen: dict) -> int:
    alerts = []

    logging.info("  [Amazon - Direct Products]")
    try:
        amazon_alerts = check_amazon_products(config, seen)
        alerts.extend(amazon_alerts)
    except Exception as e:
        logging.error(f"Amazon check failed: {e}")

    logging.info("  [Amazon - Search]")
    try:
        search_alerts = search_amazon_hotwheels(config, seen)
        alerts.extend(search_alerts)
    except Exception as e:
        logging.error(f"Amazon search failed: {e}")

    logging.info("  [Indian Stores - Shopify Gateway]")
    try:
        shopify_alerts = check_shopify_sites(config, seen)
        alerts.extend(shopify_alerts)
    except Exception as e:
        logging.error(f"Shopify check failed: {e}")

    logging.info("  [FirstCry]")
    try:
        firstcry_alerts = search_firstcry(config, seen)
        alerts.extend(firstcry_alerts)
    except Exception as e:
        logging.error(f"FirstCry check failed: {e}")

    logging.info("  [Crossword]")
    try:
        crossword_alerts = search_crossword(config, seen)
        alerts.extend(crossword_alerts)
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
    logging.info(f"Shopify sites: {len(config.get('shopify_sites', []))}")
    logging.info("=" * 60)

    global proxy_pool
    logging.info("Fetching free proxies...")
    proxy_pool = fetch_free_proxies()
    logging.info(f"Proxy pool: {len(proxy_pool)} proxies loaded")

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
