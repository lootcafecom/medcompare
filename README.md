# MedCompare India 💊

India's live medicine price comparison tool.
Compares prices across **1mg, PharmEasy, NetMeds, Apollo Pharmacy, MedKart**.

Built with **Python + FastAPI + httpx**. Zero paid APIs. Completely free.

---

## 🚀 Deploy on Railway (Free — Recommended)

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/medcompare.git
git push -u origin main
```

### Step 2 — Deploy on Railway
1. Go to **railway.app** → Sign up with GitHub
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your `medcompare` repo
4. Railway auto-detects Python and deploys
5. Go to **Settings → Domains** → Generate domain
6. Your app is live at `https://medcompare-xxx.railway.app` 🎉

---

## 🚀 Deploy on Render (Free Alternative)

1. Go to **render.com** → Sign up with GitHub
2. Click **New** → **Web Service**
3. Connect your GitHub repo
4. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Click **Deploy**

---

## 💻 Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn main:app --reload --port 8000

# Open browser
http://localhost:8000
```

---

## 🔌 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Frontend UI |
| `GET /api/health` | Health check |
| `GET /api/search?q=dolo650` | Search all 5 pharmacies |
| `GET /api/pharmacy/1mg?q=dolo650` | Search single pharmacy |

### Example Response
```json
{
  "query": "dolo650",
  "results": [
    {
      "pharmacy": "1mg",
      "products": [
        {
          "name": "Dolo 650Mg Strip Of 15 Tablets",
          "price": 30.35,
          "mrp": 33.72,
          "discount": 10,
          "link": "https://www.1mg.com/drugs/dolo-650mg-strip-of-15-tablets-44140",
          "inStock": true
        }
      ],
      "searchUrl": "https://www.1mg.com/search/all?name=dolo650",
      "error": null
    }
  ],
  "best_price": 30.35,
  "best_pharmacy": "1mg",
  "max_savings": 2.5,
  "time_taken": 4.2,
  "cached": false
}
```

---

## 📁 Project Structure

```
medcompare-python/
├── main.py                  # FastAPI app
├── requirements.txt         # Python dependencies
├── Procfile                 # Railway/Heroku start command
├── runtime.txt              # Python version
├── railway.toml             # Railway config
├── scrapers/
│   ├── __init__.py
│   └── pharmacies.py        # All 5 pharmacy scrapers
└── static/
    └── index.html           # Frontend UI
```

---

## 🔧 How Scraping Works

- Uses **httpx** for async HTTP requests (all 5 pharmacies fetched simultaneously)
- Extracts **`__NEXT_DATA__`** JSON from each pharmacy's Next.js page
- Falls back to DOM parsing for legacy sites (NetMeds)
- Results cached for **6 hours** to avoid repeated scraping
- No ScraperAPI needed — direct scraping from Railway/Render servers

---

## 💰 Cost

| Component | Cost |
|-----------|------|
| Railway hosting | Free ($5 credit/month) |
| Render hosting | Free (750 hrs/month) |
| ScraperAPI | Not needed ✅ |
| **Total** | **₹0/month** |
