import json
import re
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def extract_next_data(html: str) -> dict:
    """Extract __NEXT_DATA__ JSON from any Next.js page"""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {}

def safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val else default
    except Exception:
        return default

# ── 1mg ──────────────────────────────────────────────────────────────────────
async def scrape_1mg(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://www.1mg.com/search/all?name={query}"
    pharmacy = "1mg"
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        data = extract_next_data(r.text)
        pp   = data.get("props", {}).get("pageProps", {})

        # Correct path from debug: props.pageProps.productList
        product_list = pp.get("productList", [])

        products = []
        for p in product_list[:3]:
            name  = p.get("name", "")
            price = safe_float(p.get("salePriceDecimal") or p.get("pricePerUnit"))
            mrp   = safe_float(p.get("mrpDecimal") or price)
            slug  = p.get("slug", "")
            disc  = safe_float(p.get("discountPercent"))
            if name and price > 0:
                products.append({
                    "name":     name,
                    "price":    price,
                    "mrp":      mrp,
                    "discount": disc,
                    "link":     f"https://www.1mg.com/drugs/{slug}",
                    "inStock":  True,
                })

        return {"pharmacy": pharmacy, "products": products, "searchUrl": url, "error": None}

    except Exception as e:
        return {"pharmacy": pharmacy, "products": [], "searchUrl": url, "error": str(e)}


# ── PharmEasy ─────────────────────────────────────────────────────────────────
async def scrape_pharmeasy(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://pharmeasy.in/search/all?name={query}"
    pharmacy = "PharmEasy"
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        data = extract_next_data(r.text)
        pp   = data.get("props", {}).get("pageProps", {})

        # Try multiple known paths
        product_list = (
            pp.get("productList") or
            pp.get("searchResult", {}).get("products") or
            pp.get("products") or
            []
        )

        products = []
        for p in product_list[:3]:
            name  = p.get("name") or p.get("productName", "")
            price = safe_float(p.get("salePriceDecimal") or p.get("sellingPrice") or p.get("price"))
            mrp   = safe_float(p.get("mrpDecimal") or p.get("mrp") or price)
            slug  = p.get("slug") or p.get("urlKey", "")
            disc  = safe_float(p.get("discountPercent") or p.get("discount"))
            if name and price > 0:
                products.append({
                    "name":     name,
                    "price":    price,
                    "mrp":      mrp,
                    "discount": disc,
                    "link":     f"https://pharmeasy.in/medicines/all/{slug}",
                    "inStock":  True,
                })

        return {"pharmacy": pharmacy, "products": products, "searchUrl": url, "error": None}

    except Exception as e:
        return {"pharmacy": pharmacy, "products": [], "searchUrl": url, "error": str(e)}


# ── NetMeds ───────────────────────────────────────────────────────────────────
async def scrape_netmeds(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://www.netmeds.com/catalogsearch/result?q={query}"
    pharmacy = "NetMeds"
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        data = extract_next_data(r.text)
        pp   = data.get("props", {}).get("pageProps", {})

        product_list = (
            pp.get("productList") or
            pp.get("products") or
            pp.get("searchResult", {}).get("products") or
            []
        )

        products = []

        # Next.js path
        for p in product_list[:3]:
            name  = p.get("name") or p.get("productName", "")
            price = safe_float(p.get("salePriceDecimal") or p.get("sellingPrice") or p.get("selling_price") or p.get("price"))
            mrp   = safe_float(p.get("mrpDecimal") or p.get("mrp") or price)
            slug  = p.get("slug") or p.get("urlKey") or p.get("url_key", "")
            if name and price > 0:
                products.append({
                    "name":     name,
                    "price":    price,
                    "mrp":      mrp,
                    "discount": round((1 - price/mrp)*100) if mrp > price else 0,
                    "link":     f"https://www.netmeds.com/prescriptions/{slug}",
                    "inStock":  True,
                })

        # Legacy DOM fallback
        if not products:
            soup = BeautifulSoup(r.text, "lxml")
            for item in soup.select(".cat-item, .product-item")[:3]:
                name  = item.select_one(".clsgetname, [class*='name']")
                price = item.select_one(".final-price, [class*='price']")
                mrp   = item.select_one(".price-before-discount, s")
                href  = item.select_one("a")
                if name and price:
                    p_val   = safe_float(re.sub(r"[^\d.]", "", price.text))
                    mrp_val = safe_float(re.sub(r"[^\d.]", "", mrp.text)) if mrp else p_val
                    products.append({
                        "name":     name.text.strip(),
                        "price":    p_val,
                        "mrp":      mrp_val,
                        "discount": round((1 - p_val/mrp_val)*100) if mrp_val > p_val else 0,
                        "link":     href["href"] if href else url,
                        "inStock":  True,
                    })

        return {"pharmacy": pharmacy, "products": products, "searchUrl": url, "error": None}

    except Exception as e:
        return {"pharmacy": pharmacy, "products": [], "searchUrl": url, "error": str(e)}


# ── Apollo Pharmacy ───────────────────────────────────────────────────────────
async def scrape_apollo(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://www.apollopharmacy.in/search-medicines/{query}"
    pharmacy = "Apollo Pharmacy"
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        data = extract_next_data(r.text)
        pp   = data.get("props", {}).get("pageProps", {})

        product_list = (
            pp.get("productList") or
            pp.get("searchResults") or
            pp.get("initialSearchResults", {}).get("products") or
            pp.get("products") or
            []
        )

        products = []
        for p in product_list[:3]:
            name  = p.get("name") or p.get("productName", "")
            price = safe_float(p.get("salePriceDecimal") or p.get("offerPrice") or p.get("sellingPrice") or p.get("price"))
            mrp   = safe_float(p.get("mrpDecimal") or p.get("mrpPrice") or p.get("mrp") or price)
            slug  = p.get("slug") or p.get("urlKey") or str(p.get("productId", ""))
            disc  = safe_float(p.get("discountPercent") or p.get("discount"))
            if name and price > 0:
                products.append({
                    "name":     name,
                    "price":    price,
                    "mrp":      mrp,
                    "discount": disc or (round((1 - price/mrp)*100) if mrp > price else 0),
                    "link":     f"https://www.apollopharmacy.in/medicine/{slug}",
                    "inStock":  True,
                })

        return {"pharmacy": pharmacy, "products": products, "searchUrl": url, "error": None}

    except Exception as e:
        return {"pharmacy": pharmacy, "products": [], "searchUrl": url, "error": str(e)}


# ── MedKart ───────────────────────────────────────────────────────────────────
async def scrape_medkart(query: str, client: httpx.AsyncClient) -> dict:
    url = f"https://medkart.in/search?q={query}"
    pharmacy = "MedKart"
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        data = extract_next_data(r.text)
        pp   = data.get("props", {}).get("pageProps", {})

        product_list = (
            pp.get("productList") or
            pp.get("products") or
            []
        )

        products = []

        for p in product_list[:3]:
            name  = p.get("name") or p.get("title", "")
            price = safe_float(p.get("salePriceDecimal") or p.get("price") or
                               (p.get("variants", [{}])[0].get("price") if p.get("variants") else None))
            mrp   = safe_float(p.get("mrpDecimal") or p.get("compare_at_price") or price)
            slug  = p.get("slug") or p.get("handle", "")
            if name and price > 0:
                products.append({
                    "name":     name,
                    "price":    price / 100 if price > 10000 else price,  # Shopify stores paise
                    "mrp":      mrp / 100 if mrp > 10000 else mrp,
                    "discount": round((1 - price/mrp)*100) if mrp > price else 0,
                    "link":     f"https://medkart.in/products/{slug}",
                    "inStock":  True,
                })

        # Shopify JSON fallback
        if not products:
            shopify_url = f"https://medkart.in/search?q={query}&view=json"
            try:
                r2 = await client.get(shopify_url, headers=HEADERS, timeout=15)
                items = r2.json() if r2.status_code == 200 else []
                if isinstance(items, list):
                    for p in items[:3]:
                        name  = p.get("title", "")
                        price = safe_float(p.get("price", 0)) / 100
                        mrp   = safe_float(p.get("compare_at_price", 0)) / 100 or price
                        slug  = p.get("handle", "")
                        if name and price > 0:
                            products.append({
                                "name":     name,
                                "price":    price,
                                "mrp":      mrp,
                                "discount": round((1-price/mrp)*100) if mrp > price else 0,
                                "link":     f"https://medkart.in/products/{slug}",
                                "inStock":  True,
                            })
            except Exception:
                pass

        return {"pharmacy": pharmacy, "products": products, "searchUrl": url, "error": None}

    except Exception as e:
        return {"pharmacy": pharmacy, "products": [], "searchUrl": url, "error": str(e)}
