import json
import re
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

def safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val is not None else default
    except Exception:
        return default

def extract_next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {}

def find_product_list(pp: dict) -> list:
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

def make_product(name, price, mrp, link) -> dict | None:
    price = safe_float(price)
    mrp   = safe_float(mrp) or price
    if not name or price <= 0:
        return None
    return {
        "name":     str(name).strip(),
        "price":    round(price, 2),
        "mrp":      round(mrp, 2),
        "discount": round((1 - price/mrp)*100) if mrp > price else 0,
        "link":     link,
        "inStock":  True,
    }

# ── 1mg — Custom React SPA, use internal API ──────────────────────────────────
async def scrape_1mg(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "1mg"
    base_url = f"https://www.1mg.com/search/all?name={query}"

    apis = [
        f"https://www.1mg.com/pharmacy_api_gateway/v4/drug_skus/search_by_name?name={query}&page=1&per_page=10",
        f"https://www.1mg.com/api/v7/drug_skus/search_by_name?name={query}&page=1&per_page=10",
    ]
    h = {
        **HEADERS,
        "Accept":        "application/json, text/plain, */*",
        "Referer":       "https://www.1mg.com/",
        "Origin":        "https://www.1mg.com",
        "x-app-version": "2.0.3",
    }

    for api in apis:
        try:
            r = await client.get(api, headers=h, timeout=15, follow_redirects=True)
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
                for p in raw[:3]:
                    name  = p.get("name") or p.get("product_name") or ""
                    price = p.get("selling_price") or p.get("price") or p.get("salePriceDecimal")
                    mrp   = p.get("mrp") or p.get("mrpDecimal") or price
                    slug  = p.get("slug") or p.get("url_key") or str(p.get("sku_id") or p.get("id") or "")
                    prod  = make_product(name, price, mrp, f"https://www.1mg.com/drugs/{slug}")
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    return {"pharmacy": pharmacy, "products": [], "searchUrl": base_url, "error": "1mg API blocked or changed"}


# ── PharmEasy — Next.js, working perfectly ────────────────────────────────────
async def scrape_pharmeasy(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "PharmEasy"
    url      = f"https://pharmeasy.in/search/all?name={query}"
    try:
        r    = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        data = extract_next_data(r.text)
        pp   = data.get("props", {}).get("pageProps", {})
        lst  = find_product_list(pp)

        products = []
        for p in lst[:3]:
            name  = p.get("name") or p.get("productName") or ""
            price = p.get("salePriceDecimal") or p.get("sellingPrice") or p.get("price")
            mrp   = p.get("mrpDecimal") or p.get("mrp") or price
            slug  = p.get("slug") or p.get("urlKey") or ""
            prod  = make_product(name, price, mrp, f"https://pharmeasy.in/medicines/all/{slug}")
            if prod:
                products.append(prod)

        return {"pharmacy": pharmacy, "products": products, "searchUrl": url, "error": None if products else "No products found"}
    except Exception as e:
        return {"pharmacy": pharmacy, "products": [], "searchUrl": url, "error": str(e)}


# ── NetMeds — Fynd/Vue platform, use their search API ────────────────────────
async def scrape_netmeds(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "NetMeds"
    base_url = f"https://www.netmeds.com/catalogsearch/result?q={query}"

    # Netmeds uses Fynd platform — try their API endpoints
    apis = [
        f"https://www.netmeds.com/api/v1/listing/products?q={query}&limit=5&page_no=1",
        f"https://api.netmeds.com/api/v1/catalog/listing?q={query}&limit=5",
        f"https://www.netmeds.com/api/search?q={query}&limit=5",
        # Fynd API pattern
        f"https://www.netmeds.com/ext/api/v1.0/search/?q={query}&category=pharmacy",
    ]

    h = {**HEADERS, "Accept": "application/json", "Referer": "https://www.netmeds.com/"}

    for api in apis:
        try:
            r = await client.get(api, headers=h, timeout=15, follow_redirects=True)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data  = r.json()
                items = (
                    data.get("data", {}).get("products") or
                    data.get("products") or
                    data.get("items") or
                    data.get("results") or []
                )
                products = []
                for p in items[:3]:
                    name  = p.get("name") or p.get("display_name") or p.get("title") or ""
                    price = p.get("selling_price") or p.get("price") or p.get("effective", {}).get("effective") or 0
                    mrp   = p.get("mrp") or p.get("marked") or price
                    slug  = p.get("url_key") or p.get("slug") or p.get("sku") or ""
                    prod  = make_product(name, price, mrp, f"https://www.netmeds.com/prescriptions/{slug}")
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    # HTML regex fallback — NetMeds embeds JSON in script tags
    try:
        r    = await client.get(base_url, headers=HEADERS, timeout=20, follow_redirects=True)
        html = r.text

        # Try to find product JSON blocks
        patterns = [
            r'"name"\s*:\s*"([^"]+)"[^}]{0,200}"selling_price"\s*:\s*"?(\d+\.?\d*)"?[^}]{0,100}"mrp"\s*:\s*"?(\d+\.?\d*)"?',
            r'"display_name"\s*:\s*"([^"]+)"[^}]{0,200}"effective"\s*:\s*(\d+\.?\d*)[^}]{0,100}"marked"\s*:\s*(\d+\.?\d*)',
            r'"product_name"\s*:\s*"([^"]+)"[^}]{0,200}"price"\s*:\s*(\d+\.?\d*)',
        ]
        for pat in patterns:
            matches = re.findall(pat, html)
            if matches:
                products = []
                for m in matches[:3]:
                    name  = m[0]
                    price = m[1]
                    mrp   = m[2] if len(m) > 2 else m[1]
                    prod  = make_product(name, price, mrp, base_url)
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": base_url, "error": None}
    except Exception:
        pass

    return {"pharmacy": pharmacy, "products": [], "searchUrl": base_url, "error": "NetMeds API not reachable"}


# ── Apollo — Returns 403, use alternate endpoint ──────────────────────────────
async def scrape_apollo(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "Apollo Pharmacy"
    base_url = f"https://www.apollopharmacy.in/search-medicines/{query}"

    # Apollo blocks direct requests — try their CDN/API endpoints
    apis = [
        # Apollo uses these internal endpoints
        f"https://www.apollopharmacy.in/api/product/search?q={query}&limit=5",
        f"https://apollopharmacy.in/api/v1/search?q={query}",
        # Apollo 247 is their alternate domain — less strict
        f"https://www.apollo247.com/api/search?q={query}&limit=5",
        f"https://api.apollo247.com/api/v1/search/products?q={query}",
    ]

    h = {
        **HEADERS,
        "Accept":  "application/json",
        "Referer": "https://www.apollopharmacy.in/",
        "Origin":  "https://www.apollopharmacy.in",
    }

    for api in apis:
        try:
            r = await client.get(api, headers=h, timeout=15, follow_redirects=True)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data  = r.json()
                items = (
                    data.get("data", {}).get("products") or
                    data.get("products") or data.get("results") or
                    data.get("data") or []
                )
                if isinstance(items, dict):
                    items = items.get("products") or []
                products = []
                for p in items[:3]:
                    name  = p.get("name") or p.get("productName") or p.get("title") or ""
                    price = p.get("offerPrice") or p.get("sellingPrice") or p.get("price") or 0
                    mrp   = p.get("mrpPrice") or p.get("mrp") or price
                    slug  = p.get("urlKey") or p.get("slug") or str(p.get("productId") or "")
                    prod  = make_product(name, price, mrp, f"https://www.apollopharmacy.in/medicine/{slug}")
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    # Try with mobile user agent — Apollo sometimes allows mobile
    try:
        mobile_headers = {
            **HEADERS,
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept":     "text/html,application/xhtml+xml,*/*;q=0.8",
        }
        r    = await client.get(base_url, headers=mobile_headers, timeout=20, follow_redirects=True)
        html = r.text
        if r.status_code == 200 and len(html) > 1000:
            data = extract_next_data(html)
            pp   = data.get("props", {}).get("pageProps", {})
            lst  = find_product_list(pp)
            products = []
            for p in lst[:3]:
                name  = p.get("name") or p.get("productName") or ""
                price = p.get("offerPrice") or p.get("sellingPrice") or p.get("price")
                mrp   = p.get("mrpPrice") or p.get("mrp") or price
                slug  = p.get("urlKey") or p.get("slug") or str(p.get("productId") or "")
                prod  = make_product(name, price, mrp, f"https://www.apollopharmacy.in/medicine/{slug}")
                if prod:
                    products.append(prod)
            if products:
                return {"pharmacy": pharmacy, "products": products, "searchUrl": base_url, "error": None}
    except Exception:
        pass

    return {"pharmacy": pharmacy, "products": [], "searchUrl": base_url, "error": "Apollo blocks server requests (403)"}


# ── MedKart — Next.js App Router, use their search API ───────────────────────
async def scrape_medkart(query: str, client: httpx.AsyncClient) -> dict:
    pharmacy = "MedKart"
    base_url = f"https://medkart.in/search?q={query}"

    # MedKart uses Next.js App Router — try their API routes
    apis = [
        # Next.js App Router API routes
        f"https://medkart.in/api/search?q={query}&limit=5",
        f"https://medkart.in/api/products/search?q={query}",
        # Shopify-style endpoints
        f"https://medkart.in/search?type=product&q={query}&view=json",
        f"https://medkart.in/search.json?type=product&q={query}&limit=5",
        # Generic product search
        f"https://medkart.in/api/v1/products/search?name={query}",
    ]

    h = {**HEADERS, "Accept": "application/json", "Referer": "https://medkart.in/"}

    for api in apis:
        try:
            r = await client.get(api, headers=h, timeout=15, follow_redirects=True)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "json" not in ct:
                    continue
                data  = r.json()
                items = (
                    data.get("products") or data.get("results") or
                    data.get("data") or
                    (data if isinstance(data, list) else [])
                )
                if isinstance(items, dict):
                    items = items.get("products") or []
                products = []
                for p in items[:3]:
                    name  = p.get("title") or p.get("name") or ""
                    price = safe_float(p.get("price") or p.get("sellingPrice") or 0)
                    price = price / 100 if price > 10000 else price
                    mrp   = safe_float(p.get("compare_at_price") or p.get("mrp") or price)
                    mrp   = mrp / 100 if mrp > 10000 else mrp
                    slug  = p.get("handle") or p.get("slug") or ""
                    prod  = make_product(name, price, mrp, f"https://medkart.in/products/{slug}")
                    if prod:
                        products.append(prod)
                if products:
                    return {"pharmacy": pharmacy, "products": products, "searchUrl": api, "error": None}
        except Exception:
            continue

    # Try fetching HTML and look for inline JSON
    try:
        r    = await client.get(base_url, headers=HEADERS, timeout=20, follow_redirects=True)
        html = r.text
        # Look for inline product data in script tags
        m = re.search(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
        if m:
            raw = m.group(1).encode().decode('unicode_escape')
            # Try to extract price patterns
            prices = re.findall(r'"price"\s*:\s*(\d+)', raw)
            names  = re.findall(r'"name"\s*:\s*"([^"]+)"', raw)
            if names and prices:
                price = safe_float(prices[0])
                price = price / 100 if price > 10000 else price
                prod  = make_product(names[0], price, price, base_url)
                if prod:
                    return {"pharmacy": pharmacy, "products": [prod], "searchUrl": base_url, "error": None}
    except Exception:
        pass

    return {"pharmacy": pharmacy, "products": [], "searchUrl": base_url, "error": "MedKart API not accessible"}
