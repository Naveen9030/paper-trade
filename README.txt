═══════════════════════════════════════════════════════
  AI PAPER TRADER — Mobile Setup Guide
  Access from ANY phone, ANYWHERE, 24/7
═══════════════════════════════════════════════════════

WHAT YOU GET
─────────────
→ A URL like  https://paper-trader-xyz.railway.app
→ Open it on your phone browser — works like an app
→ Real NSE + NYSE prices via Yahoo Finance
→ BUY/SELL with one tap
→ Auto stop-loss and target exit
→ Trade history saved in the cloud


STEP 1 — CREATE A FREE GITHUB ACCOUNT
───────────────────────────────────────
Go to:  https://github.com
Click "Sign up" — it's free


STEP 2 — UPLOAD THIS FOLDER TO GITHUB
───────────────────────────────────────
1. Login to GitHub
2. Click the "+" icon → "New repository"
3. Name it: paper-trader
4. Click "Create repository"
5. On the next page, click "uploading an existing file"
6. Drag and drop ALL files from this folder:
     app.py
     mobile_ui.html
     requirements.txt
     Procfile
     railway.toml
7. Click "Commit changes"


STEP 3 — DEPLOY FREE ON RAILWAY
─────────────────────────────────
1. Go to:  https://railway.app
2. Click "Login" → "Login with GitHub"
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your "paper-trader" repository
5. Railway auto-detects everything and deploys!
6. Wait 2-3 minutes for deployment to finish
7. Click "Settings" → "Domains" → "Generate Domain"
8. You'll get a URL like: https://paper-trader-xyz.up.railway.app

That's your app URL — open it on your phone!


STEP 4 — ADD TO YOUR PHONE HOME SCREEN
─────────────────────────────────────────
On Android (Chrome):
  1. Open the URL in Chrome
  2. Tap the 3-dot menu (top right)
  3. Tap "Add to Home Screen"
  4. Tap "Add"
  → Now it opens like a real app!

On iPhone (Safari):
  1. Open the URL in Safari
  2. Tap the Share button (bottom center)
  3. Tap "Add to Home Screen"
  4. Tap "Add"
  → Now it opens like a real app!


STEP 5 — USING THE APP
────────────────────────
1. Open the app on your phone
2. Wait 30-60 seconds for first price fetch
3. Go to "Signals" tab — stocks sorted by score
4. BUY signals (green) = algo recommends entry
5. Tap "Buy Now" — positions auto-managed
6. "Positions" tab shows live P&L
7. Auto-exits when target or stop loss is hit
8. "History" tab shows all closed trades

COSTS
──────
Railway Free Plan: 500 hours/month FREE
(enough for ~16 hours/day — more than NSE/NYSE hours)

Upgrade to $5/month for 24/7 uptime if needed.
Yahoo Finance: completely free, no API key needed.


ADDING MORE STOCKS
───────────────────
Open app.py, find the STOCKS list and add NSE symbols:
  "HDFCBANK.NS"   "ICICIBANK.NS"  "BAJFINANCE.NS"
  "MARUTI.NS"     "TITAN.NS"      "SUNPHARMA.NS"
  "ADANIENT.NS"   "TATASTEEL.NS"  "DRREDDY.NS"

After editing, go to GitHub → your repo → app.py
→ click the pencil icon to edit → paste new stock list
→ Commit. Railway auto-redeploys in 2 minutes.


WANT REAL-TIME DATA (no 15-min delay)?
────────────────────────────────────────
Yahoo Finance has a ~15 minute delay.
For real-time NSE data, connect Zerodha Kite API.
(Ask Claude to add Zerodha integration when ready)

═══════════════════════════════════════════════════════
