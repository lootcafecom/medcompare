"""
Pharmacy Scrapers — Phase 1
Each pharmacy has its own scraper function.
Strategy per pharmacy based on debug findings:
  PharmEasy   → __NEXT_DATA__ JSON (working)
  1mg         → Internal pharmacy_api_gateway JSON API
  NetMeds     → Fynd platform, try API endpoints + regex fallback
  Apollo      → 403 on server — try mobile UA + API endpoints
  MedKart     → Next.js App Router — try API routes + Shopify JSON
"""
import re
import json
import httpx

DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
MOBILE_UA  = "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"

HEADERS = {
    "User-Agent":      DESKTOP_UA,
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}

def safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val is not None else default
    except Exception:
        return default

def extract_next_data(html: str) -> dict:
    """Extract __NEXT_DATA__ JSON embedded in Next.js pages"""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {}

def find_product_list(pp: dict) -> list:
    """Try all known paths to find product list in pageProps"""
    paths = [
        ["productList"],
        ["searchResult", "products"],
        ["searchData", "data", "products"],
        ["initialData", "data", "products"],
        ["initialSearchResults", "products"],
        ["searchResults"],
        ["products"],
        ["data", "products"],
    ]
    for path in paths:
        val = pp
        for key in path:
            val = val.get(key) if isinstance(val, dict) else None
            if val is None:
                break
        if val and isinstance(val, list) and len(val) > 0:
            return val
    return []

def build_product(p: dict, pharmacy: str, fallback_url: str) -> dict | None:
    """Build normalized product dict from raw pharmacy data"""
    name = (
        p.get("name") or p.get("productName") or
        p.get("medicineName") or p.get("title") or ""
    ).strip()

    price = safe_float(
        p.get("salePriceDecimal") or p.get("sellingPrice") or
        p.get("offerPrice") or p.get("price") or
        p.get("selling_price") or p.get("sale_price")
    )
    mrp = safe_float(
        p.get("mrpDecimal") or p.get("mrpPrice") or
        p.get("mrp") or p.get("max_retail_price") or price
    )
    slug = (
        p.get("slug") or p.get("urlKey") or p.get("url_key") or
        p.get("handle") or str(p.get("productId") or p.get("id") or "")
    )

    if not name or price <= 0:
        return None

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
        "discount": round((1 - price/mrp) * 100) if mrp > price else 0,
        "link":     links.get(pharmacy, fallback_url),
        "inStock":  True,
    }

# ── PharmEasy — Next.js __NEXT_DATA__ ────────────────────────────────────────
async def scrape_pharmeasy(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "PharmEasy"
    url      = f"https://pharmeasy.in/search/all?name={query}"
    try:
        r    = await client.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=20)
        data = extract_next_data(r.text)
        pp   = data.get("props", {}).get("pageProps", {})
        lst  = find_product_list(pp)

        products = [p for p in (build_product(x, pharmacy, url) for x in lst[:5]) if p]
        return {"pharmacy": pharmacy, "products": products, "searchUrl": url, "error": None}
    except Exception as e:
        return {"pharmacy": pharmacy, "products": [], "searchUrl": url, "error": str(e)}


# ── 1mg — Internal pharmacy_api_gateway ───────────────────────────────────────
async def scrape_1mg(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy  = "1mg"
    search_url = f"https://www.1mg.com/search/all?name={query}"

    apis = [
        f"https://www.1mg.com/pharmacy_api_gateway/v4/drug_skus/search_by_name?name={query}&page=1&per_page=10",
        f"https://www.1mg.com/api/v7/drug_skus/search_by_name?name={query}&page=1&per_page=10",
    ]
    h = {
        **HEADERS,
        "Accept":        "application/json",
        "Referer":       "https://www.1mg.com/",
        "Origin":        "https://www.1mg.com",
        "x-app-version": "2.0.3",
    }

    for api in apis:
        try:
            r = await client.get(api, headers=h, timeout=15)
            if r.status_code == 200:
                data = r.json()
                raw  = (
                    data.get("data", {}).get("skus") or
                    data.get("data", {}).get("products") or
                    data.get("skus") or data.get("products") or
                    data.get("results") or
                    (data if isinstance(data, list) else [])
                )
                products = []
                for p in raw[:5]:
                    name  = p.get("name") or p.get("product_name") or ""
                    price = p.get("selling_price") or p.get("price") or p.get("salePriceDecimal")
                    mrp   = p.get("mrp") or p.get("mrpDecimal") or price
                    slug  = p.get("slug") or p.get("url_key") or str(p.get("sku_id") or p.get("id") or "")
                    prod  = build_product(
                        {"name": name, "salePriceDecimal": price, "mrpDecimal": mrp, "slug": slug},
                        pharmacy, search_url
                    )
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    return {"pharmacy": pharmacy, "products": [], "searchUrl": search_url, "error": "1mg API not accessible"}


# ── NetMeds — Fynd/Vue platform ───────────────────────────────────────────────
async def scrape_netmeds(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "NetMeds"
    base_url = f"https://www.netmeds.com/catalogsearch/result?q={query}"

    # Netmeds Fynd API endpoints
    apis = [
        f"https://www.netmeds.com/api/v1/listing/products?q={query}&limit=5",
        f"https://www.netmeds.com/api/search?q={query}&limit=5",
    ]
    h = {**HEADERS, "Accept": "application/json", "Referer": "https://www.netmeds.com/"}

    for api in apis:
        try:
            r = await client.get(api, headers=h, timeout=15)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data  = r.json()
                items = (
                    data.get("data", {}).get("products") or
                    data.get("products") or data.get("items") or []
                )
                products = []
                for p in items[:5]:
                    name  = p.get("name") or p.get("display_name") or ""
                    price = p.get("selling_price") or p.get("price") or 0
                    mrp   = p.get("mrp") or price
                    slug  = p.get("url_key") or p.get("slug") or ""
                    prod  = build_product(
                        {"name": name, "salePriceDecimal": price, "mrpDecimal": mrp, "slug": slug},
                        pharmacy, base_url
                    )
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    # Regex fallback on HTML
    try:
        r    = await client.get(base_url, headers=HEADERS, timeout=20)
        html = r.text
        pats = [
            r'"name"\s*:\s*"([^"]+)"[^}]{0,300}"selling_price"\s*:\s*"?(\d+\.?\d*)"?[^}]{0,100}"mrp"\s*:\s*"?(\d+\.?\d*)"?',
            r'"display_name"\s*:\s*"([^"]+)"[^}]{0,300}"effective"\s*:\s*(\d+\.?\d*)[^}]{0,100}"marked"\s*:\s*(\d+\.?\d*)',
        ]
        for pat in pats:
            matches = re.findall(pat, html, re.DOTALL)
            if matches:
                products = []
                for m in matches[:5]:
                    prod = build_product(
                        {"name": m[0], "salePriceDecimal": m[1], "mrpDecimal": m[2] if len(m) > 2 else m[1], "slug": ""},
                        pharmacy, base_url
                    )
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": base_url, "error": None}
    except Exception:
        pass

    return {"pharmacy": pharmacy, "products": [], "searchUrl": base_url, "error": "NetMeds not accessible"}


# ── Apollo — 403 on server, try mobile UA + API ───────────────────────────────
async def scrape_apollo(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "Apollo Pharmacy"
    base_url = f"https://www.apollopharmacy.in/search-medicines/{query}"

    # Try API endpoints first
    apis = [
        f"https://www.apollopharmacy.in/api/product/search?q={query}&limit=5",
        f"https://www.apollopharmacy.in/api/v1/search?q={query}",
    ]
    h_api = {**HEADERS, "Accept": "application/json", "Referer": "https://www.apollopharmacy.in/"}

    for api in apis:
        try:
            r = await client.get(api, headers=h_api, timeout=15)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data  = r.json()
                items = (
                    data.get("data", {}).get("products") or
                    data.get("products") or data.get("results") or []
                )
                products = []
                for p in items[:5]:
                    name  = p.get("productName") or p.get("name") or ""
                    price = p.get("offerPrice") or p.get("sellingPrice") or p.get("price") or 0
                    mrp   = p.get("mrpPrice") or p.get("mrp") or price
                    slug  = p.get("urlKey") or p.get("slug") or str(p.get("productId") or "")
                    prod  = build_product(
                        {"name": name, "salePriceDecimal": price, "mrpDecimal": mrp, "slug": slug},
                        pharmacy, base_url
                    )
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    # Try with mobile user agent — Apollo sometimes allows mobile
    try:
        mobile_h = {**HEADERS, "User-Agent": MOBILE_UA, "Accept": "text/html"}
        r        = await client.get(base_url, headers=mobile_h, timeout=20)
        if r.status_code == 200 and len(r.text) > 5000:
            data = extract_next_data(r.text)
            pp   = data.get("props", {}).get("pageProps", {})
            lst  = find_product_list(pp)
            products = [p for p in (build_product(x, pharmacy, base_url) for x in lst[:5]) if p]
            if products:
                return {"pharmacy": pharmacy, "products": products, "searchUrl": base_url, "error": None}
    except Exception:
        pass

    return {
        "pharmacy":  pharmacy,
        "products":  [],
        "searchUrl": base_url,
        "error":     "Apollo blocks automated requests — visit manually",
    }


# ── MedKart — Next.js App Router ─────────────────────────────────────────────
async def scrape_medkart(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "MedKart"
    base_url = f"https://medkart.in/search?q={query}"

    # Try API endpoints
    apis = [
        f"https://medkart.in/api/search?q={query}&limit=5",
        f"https://medkart.in/api/products/search?q={query}",
        f"https://medkart.in/search?type=product&q={query}&view=json",
        f"https://medkart.in/search.json?type=product&q={query}&limit=5",
    ]
    h = {**HEADERS, "Accept": "application/json", "Referer": "https://medkart.in/"}

    for api in apis:
        try:
            r = await client.get(api, headers=h, timeout=15)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data  = r.json()
                items = (
                    data.get("products") or data.get("results") or
                    (data if isinstance(data, list) else [])
                )
                products = []
                for p in items[:5]:
                    name  = p.get("title") or p.get("name") or ""
                    price = safe_float(p.get("price") or 0)
                    price = price / 100 if price > 10000 else price
                    mrp   = safe_float(p.get("compare_at_price") or price)
                    mrp   = mrp / 100 if mrp > 10000 else mrp
                    slug  = p.get("handle") or p.get("slug") or ""
                    prod  = build_product(
                        {"name": name, "salePriceDecimal": price, "mrpDecimal": mrp, "slug": slug},
                        pharmacy, base_url
                    )
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    # HTML fallback — look for Next.js inline data
    try:
        r    = await client.get(base_url, headers=HEADERS, timeout=20)
        html = r.text
        # Next.js App Router embeds data in self.__next_f
        chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
        for chunk in chunks:
            try:
                raw = chunk.encode().decode("unicode_escape")
                prices = re.findall(r'"price"\s*:\s*(\d+)', raw)
                names  = re.findall(r'"(?:name|title)"\s*:\s*"([^"]{5,100})"', raw)
                slugs  = re.findall(r'"(?:handle|slug)"\s*:\s*"([^"]+)"', raw)
                if names and prices:
                    price = safe_float(prices[0])
                    price = price / 100 if price > 10000 else price
                    slug  = slugs[0] if slugs else ""
                    prod  = build_product(
                        {"name": names[0], "salePriceDecimal": price, "mrpDecimal": price, "slug": slug},
                        pharmacy, base_url
                    )
                    if prod:
                        return {"pharmacy": pharmacy, "products": [prod], "searchUrl": base_url, "error": None}
            except Exception:
                continue
    except Exception:
        pass

    return {"pharmacy": pharmacy, "products": [], "searchUrl": base_url, "error": "MedKart API not accessible"}
