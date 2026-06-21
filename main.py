"""
MedCompare India — Phase 1
FastAPI backend with:
- Live price fetching from 5 pharmacies
- Medicine name matching engine
- SQLite database for URL caching
- In-memory price cache (30 min TTL)
- Debug endpoints for troubleshooting
"""
import asyncio
import time
import re
import json
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from cachetools import TTLCache

from scrapers import (
    scrape_pharmeasy,
    scrape_1mg,
    scrape_netmeds,
    scrape_apollo,
    scrape_medkart,
)
from services.matcher import group_by_medicine, normalize
from database.db import init_db, save_search, save_pharmacy_url, get_popular_searches

# ── Startup ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # Create SQLite tables on startup
    yield

app = FastAPI(
    title="MedCompare India API",
    description="Live medicine price comparison across Indian pharmacies",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory cache — 30 min TTL ─────────────────────────────────────────────
price_cache: TTLCache = TTLCache(maxsize=1000, ttl=1800)  # 30 minutes

SCRAPERS = [
    ("PharmEasy",       scrape_pharmeasy),
    ("1mg",             scrape_1mg),
    ("NetMeds",         scrape_netmeds),
    ("Apollo Pharmacy", scrape_apollo),
    ("MedKart",         scrape_medkart),
]

CLIENT_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status":       "ok",
        "version":      "1.0.0",
        "cache_size":   len(price_cache),
        "pharmacies":   [name for name, _ in SCRAPERS],
    }


# ── Main search endpoint ──────────────────────────────────────────────────────
@app.get("/api/compare")
async def compare(
    medicine: str = Query(..., min_length=1, description="Medicine name to search"),
    pincode:  str = Query(None, description="Pincode for location-based pricing (Phase 2)"),
):
    """
    Compare medicine prices across all pharmacies.
    Returns matched, sorted results with best price highlighted.
    """
    q_clean  = medicine.strip()
    cache_key = f"{normalize(q_clean)}_{pincode or 'all'}"

    # Serve from cache
    if cache_key in price_cache:
        result           = dict(price_cache[cache_key])
        result["cached"] = True
        return result

    start = time.time()

    # Fetch all pharmacies concurrently
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=5.0),
        follow_redirects=True,
        headers=CLIENT_HEADERS,
    ) as client:
        tasks   = [fn(q_clean, client) for _, fn in SCRAPERS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Clean exception results
    raw_results = []
    for (name, _), r in zip(SCRAPERS, results):
        if isinstance(r, Exception):
            raw_results.append({
                "pharmacy":  name,
                "products":  [],
                "searchUrl": "",
                "error":     str(r),
            })
        else:
            raw_results.append(r)

    # Apply medicine matching — filter irrelevant results
    matched_results = group_by_medicine(raw_results, q_clean, threshold=70.0)

    # Save confirmed URLs to database
    for r in matched_results:
        if r.get("products"):
            p = r["products"][0]
            save_pharmacy_url(p["name"], r["pharmacy"], p["link"], p["name"])

    # Calculate best price stats
    best_price    = None
    best_pharmacy = None
    max_price     = 0.0
    total_found   = 0

    for r in matched_results:
        prods = r.get("products", [])
        if prods:
            total_found += 1
            price = float(prods[0]["price"])
            if best_price is None or price < best_price:
                best_price    = price
                best_pharmacy = r["pharmacy"]
            if price > max_price:
                max_price = price

    max_savings = round(max_price - best_price, 2) if best_price and max_price > best_price else 0

    response = {
        "medicine":      q_clean,
        "pincode":       pincode,
        "results":       matched_results,
        "best_price":    best_price,
        "best_pharmacy": best_pharmacy,
        "max_savings":   max_savings,
        "found_on":      total_found,
        "total":         len(SCRAPERS),
        "time_taken":    round(time.time() - start, 2),
        "cached":        False,
    }

    # Cache and save to history
    price_cache[cache_key] = response
    save_search(q_clean, matched_results, pincode)

    return response


# ── Single pharmacy endpoint ──────────────────────────────────────────────────
@app.get("/api/pharmacy/{name}")
async def single(name: str, q: str = Query(..., min_length=1)):
    """Fetch price from a single pharmacy"""
    scraper_map = {
        "pharmeasy": scrape_pharmeasy,
        "1mg":       scrape_1mg,
        "netmeds":   scrape_netmeds,
        "apollo":    scrape_apollo,
        "medkart":   scrape_medkart,
    }
    key = name.lower().replace(" ", "").replace("pharmacy", "").replace("tata", "")
    fn  = scraper_map.get(key)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown pharmacy: {name}")

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=CLIENT_HEADERS) as client:
        return await fn(q.strip(), client)


# ── Popular searches ──────────────────────────────────────────────────────────
@app.get("/api/popular")
async def popular():
    """Get most searched medicines"""
    return {"popular": get_popular_searches(limit=10)}


# ── Debug endpoint ────────────────────────────────────────────────────────────
@app.get("/api/debug/{pharmacy_name}")
async def debug(pharmacy_name: str, q: str = Query(..., min_length=1)):
    """Debug: shows raw HTML structure from pharmacy page"""
    urls = {
        "pharmeasy": f"https://pharmeasy.in/search/all?name={q}",
        "1mg":       f"https://www.1mg.com/search/all?name={q}",
        "netmeds":   f"https://www.netmeds.com/catalogsearch/result?q={q}",
        "apollo":    f"https://www.apollopharmacy.in/search-medicines/{q}",
        "medkart":   f"https://medkart.in/search?q={q}",
    }
    url = urls.get(pharmacy_name.lower())
    if not url:
        raise HTTPException(status_code=404, detail="Unknown pharmacy")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=CLIENT_HEADERS) as client:
        r = await client.get(url)

    html = r.text
    m    = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)

    if not m:
        return {
            "pharmacy":    pharmacy_name,
            "html_size":   len(html),
            "http_status": r.status_code,
            "next_data":   False,
            "message":     "No __NEXT_DATA__ — site may be non-Next.js or JS-rendered",
            "html_sample": html[:500],
        }

    try:
        nd = json.loads(m.group(1))
        pp = nd.get("props", {}).get("pageProps", {})

        def summarize(obj, depth=0):
            if depth > 2: return "..."
            if isinstance(obj, dict):
                return {
                    k: f"LIST[{len(v)}] keys={list(v[0].keys())[:8] if v and isinstance(v[0], dict) else '?'}"
                    if isinstance(v, list) else summarize(v, depth+1)
                    for k, v in list(obj.items())[:10]
                }
            return str(obj)[:80]

        return {
            "pharmacy":         pharmacy_name,
            "html_size":        len(html),
            "http_status":      r.status_code,
            "next_data_size":   len(m.group(1)),
            "pageProps_keys":   list(pp.keys()),
            "pageProps_detail": summarize(pp),
        }
    except Exception as e:
        return {"error": str(e), "raw_sample": m.group(1)[:300]}


# ── Cache management ──────────────────────────────────────────────────────────
@app.delete("/api/cache")
async def clear_cache():
    """Clear the price cache"""
    price_cache.clear()
    return {"message": "Cache cleared"}


# ── Static files — Frontend ───────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse("static/index.html")
