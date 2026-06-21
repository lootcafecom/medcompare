# MedCompare India — Phase 1 💊

Live medicine price comparison across 5 Indian pharmacies.
**No ScraperAPI. No paid tools. Completely free.**

---

## 📁 Project Structure

```
medcompare-v2/
├── main.py                    # FastAPI app — all routes
├── requirements.txt           # Python dependencies
├── Procfile                   # Railway start command
├── runtime.txt                # Python 3.11
├── railway.toml               # Railway config
├── scrapers/
│   ├── __init__.py
│   └── pharmacies.py          # All 5 pharmacy scrapers
├── services/
│   ├── __init__.py
│   └── matcher.py             # Medicine name matching engine
├── database/
│   ├── __init__.py
│   └── db.py                  # SQLite — medicine URLs + search history
└── static/
    └── index.html             # Frontend UI
```

---

## 🚀 Deploy on Railway (Free)

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "MedCompare Phase 1"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/medcompare-v2.git
git push -u origin main
```

### Step 2 — Deploy
1. Go to **railway.app** → New Project → Deploy from GitHub
2. Select `medcompare-v2` repo
3. Railway auto-detects Python and deploys
4. Settings → Domains → Generate domain
5. Live at `https://medcompare-xxx.railway.app` ✅

---

## 💻 Run Locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# Open http://localhost:8000
```

---

## 🔌 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Frontend UI |
| `GET /api/health` | Health check |
| `GET /api/compare?medicine=dolo650` | Compare all pharmacies |
| `GET /api/compare?medicine=dolo650&pincode=560001` | With pincode |
| `GET /api/pharmacy/pharmeasy?q=dolo650` | Single pharmacy |
| `GET /api/popular` | Popular searches |
| `GET /api/debug/pharmeasy?q=dolo650` | Debug scraper |
| `DELETE /api/cache` | Clear price cache |

---

## ✨ Phase 1 Features

- ✅ Live prices from 5 pharmacies simultaneously
- ✅ Medicine name matching engine (fuzzy matching)
- ✅ 30-minute price cache
- ✅ SQLite database saves pharmacy URLs
- ✅ Popular searches tracking
- ✅ Sort by price / discount / match %
- ✅ Best deal banner
- ✅ Debug endpoints
- ✅ Pincode input (UI ready, Phase 2 logic)

## 🔜 Phase 2 (Next)

- Pincode-based pricing
- PostgreSQL + Redis
- AI medicine matching
- Affiliate link tracking
- SEO pages per medicine
