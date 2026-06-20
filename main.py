import asyncio
import time
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from cachetools import TTLCache
import httpx

from scrapers import (
    scrape_1mg,
    scrape_pharmeasy,
    scrape_netmeds,
    scrape_apollo,
    scrape_medkart,
)

app = FastAPI(title="MedCompare India API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

cache: TTLCache = TTLCache(maxsize=500, ttl=21600)

SCRAPERS = [
    ("1mg",             scrape_1mg),
    ("PharmEasy",       scrape_pharmeasy),
    ("NetMeds",         scrape_netmeds),
    ("Apollo Pharmacy", scrape_apollo),
    ("MedKart",         scrape_medkart),
]

@app.get("/api/health")
async def health():
    return {"status": "ok", "message": "MedCompare API is running"}

@app.get("/api/search")
async def search(q: str = Query(..., min_length=1)):
    q_clean = q.strip()
    q_key   = q_clean.lower()

    if q_key in cache:
        result = dict(cache[q_key])
        result["cached"] = True
        return result

    start = time.time()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=5.0),
        follow_redirects=True,
        headers={
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-IN,en;q=0.9",
            "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        }
    ) as client:
        tasks   = [fn(q_clean, client) for _, fn in SCRAPERS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    clean = []
    for (name, _), r in zip(SCRAPERS, results):
        if isinstance(r, Exception):
            clean.append({"pharmacy": name, "products": [], "searchUrl": "", "error": str(r)})
        else:
            clean.append(r)

    best_price    = None
    best_pharmacy = None
    max_price     = 0.0

    for r in clean:
        prods = r.get("products", [])
        if prods and prods[0].get("price"):
            p = float(prods[0]["price"])
            if best_price is None or p < best_price:
                best_price    = p
                best_pharmacy = r["pharmacy"]
            if p > max_price:
                max_price = p

    response = {
        "query":         q_clean,
        "results":       clean,
        "best_price":    best_price,
        "best_pharmacy": best_pharmacy,
        "max_savings":   round(max_price - best_price, 2) if best_price and max_price > best_price else 0,
        "time_taken":    round(time.time() - start, 2),
        "cached":        False,
    }

    cache[q_key] = response
    return response

@app.get("/api/pharmacy/{name}")
async def single_pharmacy(name: str, q: str = Query(..., min_length=1)):
    scraper_map = {
        "1mg":       scrape_1mg,
        "pharmeasy": scrape_pharmeasy,
        "netmeds":   scrape_netmeds,
        "apollo":    scrape_apollo,
        "medkart":   scrape_medkart,
    }
    fn = scraper_map.get(name.lower().replace(" ", "").replace("pharmacy", ""))
    if not fn:
        return {"error": f"Unknown pharmacy: {name}"}
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        return await fn(q.strip(), client)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    return FileResponse("static/index.html")


# ── Debug endpoint — shows raw __NEXT_DATA__ structure ───────────────────────
@app.get("/api/debug/{pharmacy_name}")
async def debug_pharmacy(pharmacy_name: str, q: str = Query(..., min_length=1)):
    """Shows raw JSON structure from pharmacy page for debugging"""

    urls = {
        "1mg":      f"https://www.1mg.com/search/all?name={q}",
        "pharmeasy":f"https://pharmeasy.in/search/all?name={q}",
        "netmeds":  f"https://www.netmeds.com/catalogsearch/result?q={q}",
        "apollo":   f"https://www.apollopharmacy.in/search-medicines/{q}",
        "medkart":  f"https://medkart.in/search?q={q}",
    }

    url = urls.get(pharmacy_name.lower())
    if not url:
        return {"error": "Unknown pharmacy"}

    async with httpx.AsyncClient(
        timeout=25.0,
        follow_redirects=True,
        headers={
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-IN,en;q=0.9",
        }
    ) as client:
        r = await client.get(url)

    html      = r.text
    html_size = len(html)

    import re, json

    # Extract __NEXT_DATA__
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        # Check what script tags exist
        scripts = re.findall(r'<script[^>]*>', html)
        return {
            "html_size":   html_size,
            "next_data":   False,
            "script_tags": scripts[:20],
            "html_sample": html[:2000],
        }

    try:
        nd   = json.loads(m.group(1))
        pp   = nd.get("props", {}).get("pageProps", {})

        # Show top level keys and their types/sizes
        def summarize(obj, depth=0):
            if depth > 3:
                return "..."
            if isinstance(obj, dict):
                return {k: summarize(v, depth+1) for k, v in list(obj.items())[:20]}
            elif isinstance(obj, list):
                return f"[list of {len(obj)} items] first_keys={list(obj[0].keys())[:15] if obj and isinstance(obj[0], dict) else '?'}"
            else:
                return str(obj)[:100]

        return {
            "html_size":        html_size,
            "next_data_size":   len(m.group(1)),
            "next_data_found":  True,
            "pageProps_keys":   list(pp.keys()),
            "pageProps_summary": summarize(pp),
        }
    except Exception as e:
        return {
            "html_size": html_size,
            "error":     str(e),
            "raw_sample": m.group(1)[:500] if m else None,
        }
