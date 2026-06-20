import json
import re
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}

def extract_next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {}

def safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val is not None else default
    except Exception:
        return default

def find_product_list(pp: dict) -> list:
    """
    Try every known path to find the product list in pageProps.
    Based on real debug output from pharmacies.
    """
    paths = [
        # Confirmed working path from debug output
        ["productList"],
        # Common alternate paths
        ["searchResult", "products"],
        ["searchData", "data", "products"],
        ["initialData", "data", "products"],
        ["initialSearchResults", "products"],
        ["searchResults"],
        ["products"],
        ["data", "products"],
        ["data", "searchResult", "products"],
    ]
    for path in paths:
        val = pp
        for key in path:
            if isinstance(val, dict):
                val = val.get(key)
            else:
                val = None
                break
        if val and isinstance(val, list) and len(val) > 0:
            return val
    return []

def extract_product(p: dict, pharmacy: str, fallback_url: str) -> dict | None:
    """Extract product info from a product dict — handles all pharmacy field names"""
    name = (
        p.get("name") or
        p.get("productName") or
        p.get("medicineName") or
        p.get("title") or ""
    )

    price = safe_float(
        p.get("salePriceDecimal") or   # confirmed from 1mg debug
        p.get("sellingPrice") or
        p.get("offerPrice") or
        p.get("discountedPrice") or
        p.get("price") or
        p.get("pricePerUnit")
    )

    mrp = safe_float(
        p.get("mrpDecimal") or         # confirmed from 1mg debug
        p.get("mrpPrice") or
        p.get("maxPrice") or
        p.get("mrp") or
        price
    )

    slug = (
        p.get("slug") or
        p.get("urlKey") or
        p.get("url_key") or
        p.get("handle") or
        str(p.get("productId") or p.get("id") or "")
    )

    disc = safe_float(
        p.get("discountPercent") or
        p.get("discount") or
        (round((1 - price/mrp) * 100) if mrp > price > 0 else 0)
    )

    if not name or price <= 0:
        return None

    # Build link per pharmacy
    links = {
        "1mg":             f"https://www.1mg.com/drugs/{slug}",
        "PharmEasy":       f"https://pharmeasy.in/medicines/all/{slug}",
        "NetMeds":         f"https://www.netmeds.com/prescriptions/{slug}",
        "Apollo Pharmacy": f"https://www.apollopharmacy.in/medicine/{slug}",
        "MedKart":         f"https://medkart.in/products/{slug}",
    }

    return {
        "name":     name,
        "price":    round(price, 2),
        "mrp":      round(mrp, 2),
        "discount": int(disc),
        "link":     links.get(pharmacy, fallback_url),
        "inStock":  True,
    }


# ── Generic scraper used by all Next.js pharmacies ────────────────────────────
async def scrape_nextjs_pharmacy(
    pharmacy: str,
    url: str,
    client: httpx.AsyncClient,
    fallback_url: str
) -> dict:
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)

        if r.status_code != 200:
            return {
                "pharmacy":  pharmacy,
                "products":  [],
                "searchUrl": url,
                "error":     f"HTTP {r.status_code}",
            }

        html = r.text
        data = extract_next_data(html)

        if not data:
            # Try BeautifulSoup DOM fallback
            return dom_fallback(pharmacy, html, url)

        pp   = data.get("props", {}).get("pageProps", {})
        list_ = find_product_list(pp)

        products = []
        for p in list_[:3]:
            prod = extract_product(p, pharmacy, url)
            if prod:
                products.append(prod)

        # If still empty try serverStore (some pharmacies put data there)
        if not products:
            server_store = data.get("props", {}).get("pageProps", {}).get("serverStore", {})
            search_data  = server_store.get("search", {})
            list2        = search_data.get("products", []) or search_data.get("results", [])
            for p in list2[:3]:
                prod = extract_product(p, pharmacy, url)
                if prod:
                    products.append(prod)

        if not products:
            # Last resort — DOM fallback
            return dom_fallback(pharmacy, html, url)

        return {
            "pharmacy":  pharmacy,
            "products":  products,
            "searchUrl": url,
            "error":     None,
        }

    except Exception as e:
        return {
            "pharmacy":  pharmacy,
            "products":  [],
            "searchUrl": url,
            "error":     str(e),
        }


def dom_fallback(pharmacy: str, html: str, url: str) -> dict:
    """BeautifulSoup DOM fallback for non-Next.js or heavily dynamic pages"""
    products = []
    try:
        soup = BeautifulSoup(html, "lxml")

        # Generic price extraction from any structured page
        selectors = [
            (".cat-item", ".clsgetname", ".final-price", ".price-before-discount"),
            (".product-item", "[class*='name']", "[class*='price']", "s"),
            ("[class*='ProductCard']", "[class*='name']", "[class*='price']", "s"),
            ("[class*='product-card']", "[class*='name']", "[class*='price']", "del"),
        ]

        for card_sel, name_sel, price_sel, mrp_sel in selectors:
            cards = soup.select(card_sel)
            if not cards:
                continue
            for card in cards[:3]:
                name_el  = card.select_one(name_sel)
                price_el = card.select_one(price_sel)
                mrp_el   = card.select_one(mrp_sel)
                href_el  = card.select_one("a")

                if not name_el or not price_el:
                    continue

                name  = name_el.get_text(strip=True)
                price = safe_float(re.sub(r"[^\d.]", "", price_el.get_text()))
                mrp   = safe_float(re.sub(r"[^\d.]", "", mrp_el.get_text())) if mrp_el else price
                link  = href_el.get("href", url) if href_el else url

                if name and price > 0:
                    products.append({
                        "name":     name,
                        "price":    round(price, 2),
                        "mrp":      round(mrp, 2),
                        "discount": round((1 - price/mrp)*100) if mrp > price else 0,
                        "link":     link if link.startswith("http") else url,
                        "inStock":  True,
                    })
            if products:
                break

    except Exception:
        pass

    return {
        "pharmacy":  pharmacy,
        "products":  products,
        "searchUrl": url,
        "error":     None if products else "Could not find products on page",
    }


# ── Individual pharmacy scrapers ──────────────────────────────────────────────

async def scrape_1mg(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://www.1mg.com/search/all?name={query}"
    return await scrape_nextjs_pharmacy("1mg", url, client, url)


async def scrape_pharmeasy(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://pharmeasy.in/search/all?name={query}"
    return await scrape_nextjs_pharmacy("PharmEasy", url, client, url)


async def scrape_netmeds(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://www.netmeds.com/catalogsearch/result?q={query}"
    result = await scrape_nextjs_pharmacy("NetMeds", url, client, url)

    # NetMeds extra fallback — legacy JSON in script tags
    if not result["products"]:
        try:
            r    = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
            html = r.text

            # NetMeds embeds product JSON differently
            patterns = [
                r'"name"\s*:\s*"([^"]+)"[^}]+"selling_price"\s*:\s*"?(\d+\.?\d*)"?[^}]+"mrp"\s*:\s*"?(\d+\.?\d*)"?',
                r'"product_name"\s*:\s*"([^"]+)"[^}]+"price"\s*:\s*"?(\d+\.?\d*)"?[^}]+"special_price"\s*:\s*"?(\d+\.?\d*)"?',
            ]
            for pat in patterns:
                matches = re.findall(pat, html)
                if matches:
                    name, price, mrp = matches[0]
                    result["products"] = [{
                        "name":     name,
                        "price":    round(safe_float(price), 2),
                        "mrp":      round(safe_float(mrp), 2),
                        "discount": round((1 - safe_float(price)/safe_float(mrp))*100) if safe_float(mrp) > safe_float(price) else 0,
                        "link":     url,
                        "inStock":  True,
                    }]
                    result["error"] = None
                    break
        except Exception:
            pass

    return result


async def scrape_apollo(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://www.apollopharmacy.in/search-medicines/{query}"
    return await scrape_nextjs_pharmacy("Apollo Pharmacy", url, client, url)


async def scrape_medkart(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://medkart.in/search?q={query}"
    result = await scrape_nextjs_pharmacy("MedKart", url, client, url)

    # MedKart Shopify fallback — prices stored in paise (divide by 100)
    if not result["products"]:
        try:
            shopify_url = f"https://medkart.in/search?type=product&q={query}&view=json"
            r = await client.get(shopify_url, headers=HEADERS, timeout=15, follow_redirects=True)
            if r.status_code == 200:
                items = r.json()
                if isinstance(items, list):
                    for item in items[:3]:
                        name  = item.get("title", "")
                        price = safe_float(item.get("price", 0)) / 100
                        mrp   = safe_float(item.get("compare_at_price") or item.get("price", 0)) / 100
                        slug  = item.get("handle", "")
                        if name and price > 0:
                            result["products"].append({
                                "name":     name,
                                "price":    round(price, 2),
                                "mrp":      round(mrp, 2),
                                "discount": round((1-price/mrp)*100) if mrp > price else 0,
                                "link":     f"https://medkart.in/products/{slug}",
                                "inStock":  True,
                            })
                    if result["products"]:
                        result["error"] = None
        except Exception:
            pass

    return result
