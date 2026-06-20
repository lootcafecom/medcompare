import asyncio
import time
import re
import json
import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from cachetools import TTLCache

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

CLIENT_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
}

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "message": "MedCompare API is running"}


# ── Search all pharmacies ─────────────────────────────────────────────────────
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
        headers=CLIENT_HEADERS
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


# ── Single pharmacy ───────────────────────────────────────────────────────────
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


# ── Debug endpoint — MUST be before catch_all ─────────────────────────────────
@app.get("/api/debug/{pharmacy_name}")
async def debug_pharmacy(pharmacy_name: str, q: str = Query(..., min_length=1)):
    """Shows raw __NEXT_DATA__ structure from pharmacy page"""

    urls = {
        "1mg":       f"https://www.1mg.com/search/all?name={q}",
        "pharmeasy": f"https://pharmeasy.in/search/all?name={q}",
        "netmeds":   f"https://www.netmeds.com/catalogsearch/result?q={q}",
        "apollo":    f"https://www.apollopharmacy.in/search-medicines/{q}",
        "medkart":   f"https://medkart.in/search?q={q}",
    }

    url = urls.get(pharmacy_name.lower())
    if not url:
        return {"error": "Unknown pharmacy. Use: 1mg, pharmeasy, netmeds, apollo, medkart"}

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=CLIENT_HEADERS
    ) as client:
        r = await client.get(url)

    html      = r.text
    html_size = len(html)

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)

    if not m:
        script_tags = re.findall(r'<script[^>]*>', html)
        return {
            "pharmacy":    pharmacy_name,
            "html_size":   html_size,
            "http_status": r.status_code,
            "next_data":   False,
            "message":     "No __NEXT_DATA__ found — site may be non-Next.js or JS-rendered",
            "script_tags": script_tags[:10],
            "html_sample": html[:1000],
        }

    try:
        nd = json.loads(m.group(1))
        pp = nd.get("props", {}).get("pageProps", {})

        def summarize(obj, depth=0):
            if depth > 2:
                return "..."
            if isinstance(obj, dict):
                out = {}
                for k, v in list(obj.items())[:15]:
                    if isinstance(v, list):
                        out[k] = f"LIST[{len(v)}] keys={list(v[0].keys())[:10] if v and isinstance(v[0], dict) else '?'}"
                    elif isinstance(v, dict):
                        out[k] = summarize(v, depth+1)
                    else:
                        out[k] = str(v)[:80]
                return out
            return str(obj)[:80]

        return {
            "pharmacy":         pharmacy_name,
            "html_size":        html_size,
            "http_status":      r.status_code,
            "next_data_size":   len(m.group(1)),
            "next_data_found":  True,
            "pageProps_keys":   list(pp.keys()),
            "pageProps_detail": summarize(pp),
        }

    except Exception as e:
        return {
            "pharmacy":   pharmacy_name,
            "html_size":  html_size,
            "error":      str(e),
            "raw_sample": m.group(1)[:300] if m else None,
        }


# ── Static files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

# ── Catch-all MUST be last — otherwise it swallows all /api/ routes ───────────
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    # Don't catch API routes
    if full_path.startswith("api/"):
        return {"error": "Not found", "path": full_path}
    return FileResponse("static/index.html")
