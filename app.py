import json, os, time, threading, datetime, requests
from flask import Flask, jsonify, request, render_template_string
import pandas as pd, numpy as np

# ── NIFTY 50 ──────────────────────────────────
NSE_STOCKS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "HINDUNILVR.NS","ITC.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS",
    "LT.NS","AXISBANK.NS","BAJFINANCE.NS","ASIANPAINT.NS","MARUTI.NS",
    "TITAN.NS","SUNPHARMA.NS","WIPRO.NS","ULTRACEMCO.NS","NESTLEIND.NS",
    "POWERGRID.NS","NTPC.NS","TATAMOTORS.NS","ADANIENT.NS","HCLTECH.NS",
    "BAJAJFINSV.NS","TECHM.NS","ONGC.NS","JSWSTEEL.NS","TATASTEEL.NS",
    "INDUSINDBK.NS","DRREDDY.NS","CIPLA.NS","BPCL.NS","DIVISLAB.NS",
    "EICHERMOT.NS","HEROMOTOCO.NS","COALINDIA.NS","GRASIM.NS","BRITANNIA.NS",
    "APOLLOHOSP.NS","ADANIPORTS.NS","SBILIFE.NS","HDFCLIFE.NS","BAJAJ-AUTO.NS",
    "TATACONSUM.NS","HINDALCO.NS","UPL.NS","SHREECEM.NS","M&M.NS"
]

# ── TOP 50 US STOCKS ──────────────────────────
US_STOCKS = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN",
    "META","TSLA","BRK-B","LLY","V",
    "JPM","UNH","XOM","MA","JNJ",
    "PG","HD","MRK","AVGO","CVX",
    "ABBV","COST","PEP","KO","AMD",
    "ADBE","CSCO","ACN","MCD","CRM",
    "NFLX","TMO","ABT","LIN","DHR",
    "TXN","NEE","PM","RTX","HON",
    "QCOM","IBM","INTU","AMGN","GE",
    "SPGI","CAT","AMAT","ISRG","ORCL"
]

ALL_STOCKS = NSE_STOCKS + US_STOCKS
CAPITAL0 = 100_000
RISK     = 0.02
SL_M     = 1.0
TP_M     = 2.0
MIN_SC   = 72
CACHE    = "cache.json"
LOG      = "log.json"

app = Flask(__name__)
S = {
    "capital": CAPITAL0, "positions": {}, "history": [], "log": [],
    "market_data": {}, "last_refresh": "loading...", "status": "starting",
    "scan_progress": 0, "scan_total": len(ALL_STOCKS),
}
LK = threading.Lock()

def ist():
    return (datetime.datetime.utcnow()+datetime.timedelta(hours=5,minutes=30)).strftime("%d %b %H:%M IST")

# ── FETCH ─────────────────────────────────────
def yf(sym):
    for h in ["query1","query2"]:
        try:
            r=requests.get(f"https://{h}.finance.yahoo.com/v8/finance/chart/{sym}",
                headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"},
                params={"interval":"1d","range":"1y"},timeout=15)
            if r.status_code!=200: continue
            res=r.json()["chart"]["result"][0]
            q=res["indicators"]["quote"][0]
            try: cl=res["indicators"]["adjclose"][0]["adjclose"]
            except: cl=q["close"]
            df=pd.DataFrame({"O":q["open"],"H":q["high"],"L":q["low"],
                "C":cl,"V":q["volume"]},
                index=pd.to_datetime(res["timestamp"],unit="s")).dropna()
            if len(df)>=50:
                return df
        except Exception as e:
            print(f"  {sym}/{h}: {e}")
    return None

# ── INDICATORS ────────────────────────────────
def ema(s,p): return s.ewm(span=p,adjust=False).mean()

def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0).ewm(com=p-1,adjust=False).mean()
    l=(-d.clip(upper=0)).ewm(com=p-1,adjust=False).mean()
    v=100-100/(1+g/l.replace(0,np.nan))
    return float(v.iloc[-1]) if not v.empty else 50.0

def macd(s):
    ln=ema(s,12)-ema(s,26); sg=ema(ln,9)
    return float(ln.iloc[-1]),float(sg.iloc[-1]),float(ln.iloc[-2]),float(sg.iloc[-2])

def atr(df,p=14):
    h,l,c=df.H,df.L,df.C
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return float(tr.ewm(com=p-1,adjust=False).mean().iloc[-1])

def supertrend(df,p=10,mult=3):
    h,l,c=df.H,df.L,df.C
    hl2=(h+l)/2
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr_s=tr.ewm(com=p-1,adjust=False).mean()
    upper=hl2+mult*atr_s; lower=hl2-mult*atr_s
    st=pd.Series(index=c.index,dtype=float)
    trend=pd.Series(index=c.index,dtype=int)
    for i in range(1,len(c)):
        if c.iloc[i]>upper.iloc[i-1]: trend.iloc[i]=1
        elif c.iloc[i]<lower.iloc[i-1]: trend.iloc[i]=-1
        else: trend.iloc[i]=trend.iloc[i-1]
        st.iloc[i]=lower.iloc[i] if trend.iloc[i]==1 else upper.iloc[i]
    return int(trend.iloc[-1]), float(st.iloc[-1]) if not pd.isna(st.iloc[-1]) else 0

def bollinger(s,p=20):
    m=s.rolling(p).mean(); sd=s.rolling(p).std()
    up=m+2*sd; dn=m-2*sd
    px=float(s.iloc[-1]); mid=float(m.iloc[-1])
    pct=(px-float(dn.iloc[-1]))/(float(up.iloc[-1])-float(dn.iloc[-1])+0.0001)
    bw_now=float(up.iloc[-1]-dn.iloc[-1])
    bw_prev=float(up.iloc[-2]-dn.iloc[-2]) if len(s)>p+1 else bw_now
    return round(pct*100,1), bw_now>bw_prev, px>mid

def volume_analysis(v):
    avg20=float(v.iloc[-21:-1].mean()) if len(v)>21 else float(v.mean())
    avg5=float(v.iloc[-6:-1].mean()) if len(v)>6 else avg20
    last=float(v.iloc[-1])
    ratio=last/avg20 if avg20>0 else 1
    trend=avg5>avg20
    return round(ratio,2), trend

# ── SCORING ───────────────────────────────────
def score_stock(df, sym):
    c=df.C; v=df.V; px=float(c.iloc[-1])
    n=len(c)

    # EMAs
    e9=float(ema(c,9).iloc[-1])
    e21=float(ema(c,21).iloc[-1])
    e50=float(ema(c,50).iloc[-1])
    e200=float(ema(c,min(200,n-1)).iloc[-1])
    e9p=float(ema(c,9).iloc[-2])
    e21p=float(ema(c,21).iloc[-2])

    # Indicators
    rs=rsi(c)
    rs_prev=rsi(c.iloc[:-1])
    ml,ms,mlp,msp=macd(c)
    at=atr(df)
    st_trend,st_line=supertrend(df)
    bb_pct,bb_expand,bb_above=bollinger(c)
    vr,vtend=volume_analysis(v)
    chg=(px-float(c.iloc[-2]))/float(c.iloc[-2])*100 if n>=2 else 0
    chg5=(px-float(c.iloc[-6]))/float(c.iloc[-6])*100 if n>=6 else 0

    sc=0; rsns=[]; details={}

    # 1. TREND FILTER — Price vs EMA200 (20 pts)
    if px>e200:
        sc+=20; rsns.append("Above EMA200")
        details["trend"]="bullish"
    else:
        details["trend"]="bearish"

    # 2. EMA ALIGNMENT — 9>21>50 (15 pts)
    if e9>e21>e50:
        sc+=15; rsns.append("EMAs aligned")
        details["ema"]="aligned"
    elif e9>e21:
        sc+=7; rsns.append("EMA9>21")
        details["ema"]="partial"
    else:
        details["ema"]="weak"

    # 3. EMA CROSSOVER — fresh cross (10 pts)
    if e9>e21 and e9p<=e21p:
        sc+=10; rsns.append("🚀 EMA crossover")
        details["cross"]="fresh"
    else:
        details["cross"]="none"

    # 4. RSI ZONE (15 pts)
    if 45<=rs<=65:
        sc+=15; rsns.append(f"RSI ideal ({rs:.0f})")
        details["rsi_zone"]="ideal"
    elif 35<=rs<45:
        sc+=10; rsns.append(f"RSI recovering ({rs:.0f})")
        details["rsi_zone"]="recovering"
    elif rs<35:
        sc+=5; rsns.append(f"RSI oversold ({rs:.0f})")
        details["rsi_zone"]="oversold"
    else:
        details["rsi_zone"]="overbought"

    # 5. RSI RISING (5 pts)
    if rs>rs_prev:
        sc+=5; rsns.append("RSI rising")
        details["rsi_dir"]="rising"
    else:
        details["rsi_dir"]="falling"

    # 6. MACD BULLISH (10 pts)
    if ml>ms:
        sc+=10; rsns.append("MACD bull")
        details["macd"]="bullish"
    else:
        details["macd"]="bearish"

    # 7. MACD CROSSOVER — fresh (8 pts)
    if ml>ms and mlp<=msp:
        sc+=8; rsns.append("🚀 MACD crossover")
        details["macd_cross"]="fresh"
    else:
        details["macd_cross"]="none"

    # 8. SUPERTREND (10 pts)
    if st_trend==1:
        sc+=10; rsns.append("Supertrend bull")
        details["supertrend"]="bullish"
    else:
        details["supertrend"]="bearish"

    # 9. VOLUME SURGE (7 pts)
    if vr>=2.0:
        sc+=7; rsns.append(f"🔥 Vol surge {vr:.1f}x")
        details["volume"]="surge"
    elif vr>=1.5:
        sc+=5; rsns.append(f"High vol {vr:.1f}x")
        details["volume"]="high"
    elif vr>=1.2:
        sc+=3
        details["volume"]="above_avg"
    else:
        details["volume"]="low"

    # 10. BOLLINGER BANDS (5 pts)
    if bb_expand and bb_above and bb_pct>50:
        sc+=5; rsns.append("BB breakout")
        details["bb"]="breakout"
    else:
        details["bb"]="normal"

    # 11. MOMENTUM — 5 day return (5 pts)
    if 0<chg5<8:
        sc+=5; rsns.append(f"Momentum +{chg5:.1f}%")
        details["momentum"]="good"
    else:
        details["momentum"]="weak"

    sl=px-SL_M*at; tg=px+TP_M*at; rr=(tg-px)/max(px-sl,.01)

    if sc>=MIN_SC: sig="BUY"
    elif sc>=52: sig="WATCH"
    else: sig="HOLD"

    return dict(
        price=round(px,2), score=sc, signal=sig,
        rsi=round(rs,1), entry=round(px,2),
        sl=round(sl,2), target=round(tg,2),
        rr=round(rr,2), atr=round(at,2),
        reasons=rsns[:4], details=details,
        change_pct=round(chg,2), change5=round(chg5,2),
        volume_ratio=vr, bb_pct=bb_pct,
        supertrend=st_trend, macd_bull=ml>ms,
        trend_bull=px>e200, ema_align=e9>e21>e50
    )

# ── REFRESH LOOP ──────────────────────────────
def do_refresh():
    print(f"[{ist()}] Starting scan of {len(ALL_STOCKS)} stocks...")
    with LK: S["status"]="refreshing"; S["scan_progress"]=0
    out={}
    for i,sym in enumerate(ALL_STOCKS):
        try:
            df=yf(sym)
            if df is not None:
                result=score_stock(df,sym)
                out[sym]=result
                print(f"  [{i+1}/{len(ALL_STOCKS)}] {sym} = {result['price']} | Score:{result['score']} | {result['signal']}")
            del df
            time.sleep(1.5)
        except Exception as e:
            print(f"  err {sym}: {e}")
        with LK: S["scan_progress"]=i+1

    now=ist()
    with LK:
        if out:
            S["market_data"]=out; S["status"]="live"
            try:
                with open(CACHE,"w") as f: json.dump(out,f)
            except: pass
        else:
            S["status"]="error"
        S["last_refresh"]=now; S["scan_progress"]=len(ALL_STOCKS)

    buys=[s for s,d in out.items() if d["signal"]=="BUY"]
    print(f"\nScan complete: {len(out)} stocks | {len(buys)} BUY signals")
    if buys:
        print("BUY signals: "+", ".join(buys))

def loop():
    print("Scanner thread started ✓")
    do_refresh()
    while True:
        time.sleep(900)  # refresh every 15 min
        do_refresh()

def load_state():
    if os.path.exists(LOG):
        try:
            d=json.load(open(LOG))
            for k in ["capital","positions","history","log"]:
                if k in d: S[k]=d[k]
        except: pass
    if os.path.exists(CACHE):
        try:
            S["market_data"]=json.load(open(CACHE))
            S["status"]="live"; S["last_refresh"]="cached"
            print(f"Cache loaded: {len(S['market_data'])} stocks")
        except: pass

def save_state():
    try:
        with open(LOG,"w") as f:
            json.dump({k:S[k] for k in ["capital","positions","history","log"]},f)
    except: pass

def close_pos(sym,reason):
    pos=S["positions"].get(sym)
    if not pos: return
    px=S["market_data"].get(sym,{}).get("price",pos["entry"])
    pnl=pos["qty"]*px-pos["cost"]
    S["capital"]+=pos["qty"]*px
    S["history"].insert(0,dict(sym=sym,qty=pos["qty"],entry=pos["entry"],
        exit=round(px,2),pnl=round(pnl,2),reason=reason,time=ist()))
    del S["positions"][sym]
    S["log"].insert(0,dict(t=ist(),type="win" if pnl>=0 else "loss",
        msg=f"{reason}: {sym.replace('.NS','')} PnL:{round(pnl,2):+.0f}"))
    save_state()

# ── API ROUTES ────────────────────────────────
@app.route("/api/state")
def api_state():
    with LK:
        md=S["market_data"]
        pv=sum(p["qty"]*md.get(s,{}).get("price",p["entry"]) for s,p in S["positions"].items())
        total=S["capital"]+pv; pnl=total-CAPITAL0
        opnl=sum(p["qty"]*(md.get(s,{}).get("price",p["entry"])-p["entry"]) for s,p in S["positions"].items())
        pos_e={}
        for sym,pos in S["positions"].items():
            px=md.get(sym,{}).get("price",pos["entry"])
            pos_e[sym]={**pos,"cmp":round(px,2),
                "upnl":round(pos["qty"]*(px-pos["entry"]),2),
                "upct":round((px-pos["entry"])/pos["entry"]*100,2)}
        return jsonify(
            capital=round(S["capital"],2), pos_val=round(pv,2),
            total=round(total,2), pnl=round(pnl,2), open_pnl=round(opnl,2),
            market_data=md, positions=pos_e,
            history=S["history"][:40], log=S["log"][:30],
            last_refresh=S["last_refresh"], status=S["status"],
            scan_progress=S["scan_progress"], scan_total=S["scan_total"],
            nse_stocks=NSE_STOCKS, us_stocks=US_STOCKS
        )

@app.route("/api/buy",methods=["POST"])
def api_buy():
    sym=request.json.get("sym","")
    with LK:
        if sym in S["positions"]: return jsonify(ok=False,msg="Already holding")
        d=S["market_data"].get(sym)
        if not d: return jsonify(ok=False,msg="No data yet")
        px=d["entry"]; sl=d["sl"]; tg=d["target"]
        qty=max(1,int(S["capital"]*RISK/max(px-sl,.01)))
        cost=qty*px
        if cost>S["capital"]: return jsonify(ok=False,msg="Insufficient funds")
        S["capital"]-=cost
        S["positions"][sym]=dict(qty=qty,entry=round(px,2),sl=round(sl,2),
            target=round(tg,2),cost=round(cost,2),time=ist())
        S["log"].insert(0,dict(t=ist(),type="buy",
            msg=f"BUY {qty}x{sym.replace('.NS','')} @ {round(px,2)} SL:{round(sl,2)} T:{round(tg,2)}"))
        save_state()
    return jsonify(ok=True,msg=f"Bought {qty}x{sym.replace('.NS','')}")

@app.route("/api/sell",methods=["POST"])
def api_sell():
    sym=request.json.get("sym","")
    with LK:
        if sym not in S["positions"]: return jsonify(ok=False,msg="Not holding")
        close_pos(sym,"Manual Exit")
    return jsonify(ok=True,msg=f"Exited {sym.replace('.NS','')}")

@app.route("/api/reset",methods=["POST"])
def api_reset():
    with LK:
        S.update(capital=CAPITAL0,positions={},history=[],
            log=[dict(t=ist(),type="info",msg="Portfolio reset")])
        save_state()
    return jsonify(ok=True)

@app.route("/")
def index():
    return render_template_string(HTML)

HTML="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0d1117">
<title>Paper Trader</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;color:#e6edf3;max-width:480px;margin:0 auto;min-height:100vh}
.hdr{background:#161b22;padding:12px 16px 0;border-bottom:1px solid #21262d;position:sticky;top:0;z-index:10}
.hdr-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.hdr-title{font-size:16px;font-weight:700;color:#58a6ff;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:#3fb950;animation:blink 1.4s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.pill{font-size:10px;padding:3px 9px;border-radius:10px;font-weight:700}
.pill-live{background:rgba(63,185,80,.15);color:#3fb950}
.pill-scan{background:rgba(59,130,246,.15);color:#58a6ff}
.pill-err{background:rgba(248,81,73,.15);color:#f85149}
.refresh-info{font-size:11px;color:#8b949e;padding-bottom:6px}
.progress-wrap{height:3px;background:#21262d;margin-bottom:0;overflow:hidden}
.progress-bar{height:100%;background:linear-gradient(90deg,#58a6ff,#3fb950);transition:width .5s;border-radius:2px}
.mkt-tabs{display:flex;border-bottom:1px solid #21262d}
.mkt-tab{flex:1;font-size:13px;font-weight:700;padding:10px;text-align:center;cursor:pointer;border:none;background:none;color:#8b949e;border-bottom:3px solid transparent}
.mkt-tab.on{color:#e6edf3;border-bottom-color:#58a6ff}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:10px 16px}
.mc{background:#161b22;border-radius:10px;padding:10px 14px;border:1px solid #21262d}
.mc.full{grid-column:1/-1}
.ml{font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;font-weight:600}
.mv{font-size:20px;font-weight:700}
.mv.sm{font-size:16px;padding-top:2px}
.g{color:#3fb950}.r{color:#f85149}.b{color:#58a6ff}.a{color:#d29922}
.tabs{display:flex;background:#161b22;border-bottom:1px solid #21262d;position:sticky;top:110px;z-index:9}
.tab{flex:1;font-size:11px;padding:10px 2px;text-align:center;cursor:pointer;border:none;background:none;color:#8b949e;font-weight:700;border-bottom:2px solid transparent}
.tab.on{color:#e6edf3;border-bottom-color:#58a6ff}
.tc{display:none}.tc.on{display:block}
.page{padding:10px 16px 100px}
.mkt-section{display:none}.mkt-section.on{display:block}
.sec-hdr{display:flex;align-items:center;gap:8px;padding:10px 0 8px;font-size:11px;font-weight:700;color:#8b949e;text-transform:uppercase;letter-spacing:.07em}
.sec-cnt{background:#21262d;padding:2px 8px;border-radius:10px;font-size:10px;color:#e6edf3}
.stock-card{background:#161b22;border-radius:14px;border:1px solid #21262d;padding:14px;margin-bottom:10px}
.stock-card.buy-sig{border-color:rgba(63,185,80,.5);background:rgba(13,31,19,.7)}
.sc-hdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
.sc-sym{font-size:17px;font-weight:700}
.sc-flag{font-size:9px;padding:1px 5px;border-radius:3px;margin-left:4px;font-weight:600}
.nse-flag{background:rgba(255,153,0,.15);color:#ff9900;border:1px solid rgba(255,153,0,.3)}
.us-flag{background:rgba(59,130,246,.15);color:#3b82f6;border:1px solid rgba(59,130,246,.3)}
.sc-badges{margin-top:4px;display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.sig-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px}
.sig-BUY{background:rgba(63,185,80,.15);color:#3fb950;border:1px solid rgba(63,185,80,.4)}
.sig-WATCH{background:rgba(210,153,34,.15);color:#d29922;border:1px solid rgba(210,153,34,.4)}
.sig-HOLD{background:rgba(100,100,100,.1);color:#8b949e;border:1px solid #30363d}
.sc-score-txt{font-size:10px;color:#8b949e}
.ind-tag{font-size:9px;padding:2px 6px;border-radius:10px;background:#21262d;color:#8b949e;display:inline-block}
.ind-tag.on{background:rgba(63,185,80,.12);color:#3fb950;border:1px solid rgba(63,185,80,.2)}
.ind-tag.warn{background:rgba(248,81,73,.08);color:#f85149}
.sc-price{font-size:19px;font-weight:700;text-align:right}
.sc-chg{font-size:11px;font-weight:600;text-align:right;margin-top:2px}
.sc-bar-bg{height:4px;background:#21262d;border-radius:2px;margin:8px 0;overflow:hidden}
.sc-bar-fill{height:100%;border-radius:2px}
.sc-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:8px}
.sc-item{background:#0d1117;border-radius:8px;padding:8px 10px}
.sc-item-l{font-size:9px;color:#8b949e;margin-bottom:2px;font-weight:600;text-transform:uppercase}
.sc-item-v{font-size:13px;font-weight:700}
.sc-reasons{font-size:10px;color:#8b949e;margin-bottom:8px;line-height:1.6}
.indicators-row{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px}
.btn-buy{width:100%;padding:13px;border-radius:12px;font-size:14px;font-weight:700;border:none;cursor:pointer;background:#238636;color:#fff}
.btn-buy:disabled{background:#21262d;color:#484f58;cursor:default}
.btn-buy:active:not(:disabled){background:#196c2e}
.pos-card{background:#161b22;border-radius:14px;border:1px solid #21262d;padding:14px;margin-bottom:10px}
.pos-card.profit{border-color:rgba(63,185,80,.4)}
.pos-card.loss{border-color:rgba(248,81,73,.4)}
.pc-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.pc-sym{font-size:16px;font-weight:700}
.pc-qty{font-size:10px;color:#8b949e;margin-left:4px}
.pc-pnl{font-size:19px;font-weight:700}
.pc-pct{font-size:11px;font-weight:600;text-align:right;margin-top:2px}
.pc-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:10px}
.pc-item{background:#0d1117;border-radius:8px;padding:8px 10px}
.pc-item-l{font-size:9px;color:#8b949e;margin-bottom:2px;font-weight:600;text-transform:uppercase}
.pc-item-v{font-size:13px;font-weight:700}
.btn-exit{width:100%;padding:12px;border-radius:12px;font-size:13px;font-weight:700;border:1px solid #f85149;background:transparent;color:#f85149;cursor:pointer}
.hist-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px}
.hist-card{background:#161b22;border-radius:12px;border-left:3px solid transparent;padding:12px 14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.hist-card.win{border-left-color:#3fb950}
.hist-card.loss{border-left-color:#f85149}
.hist-sym{font-size:14px;font-weight:700}
.hist-detail{font-size:10px;color:#8b949e;margin-top:2px;line-height:1.5}
.hist-pnl{font-size:16px;font-weight:700}
.hist-reason{font-size:10px;color:#8b949e;margin-top:2px;text-align:right}
.log-item{padding:10px 0;border-bottom:1px solid #21262d;font-size:11px}
.log-t{color:#8b949e;font-size:10px;margin-bottom:2px}
.log-buy{color:#3fb950}.log-win{color:#3fb950}.log-loss{color:#f85149}.log-info{color:#58a6ff}
.empty{text-align:center;padding:48px 20px;color:#8b949e}
.empty-icon{font-size:36px;margin-bottom:12px}
.empty-title{font-size:15px;font-weight:700;color:#c9d1d9;margin-bottom:6px}
.empty-sub{font-size:12px;line-height:1.7}
.scan-status{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:16px;margin-bottom:12px;text-align:center}
.scan-status-title{font-size:14px;font-weight:700;color:#58a6ff;margin-bottom:6px}
.scan-status-sub{font-size:12px;color:#8b949e;margin-bottom:10px}
.scan-prog-bg{height:6px;background:#21262d;border-radius:3px;overflow:hidden}
.scan-prog-fill{height:100%;background:linear-gradient(90deg,#58a6ff,#3fb950);border-radius:3px;transition:width .5s}
.toast{position:fixed;bottom:88px;left:50%;transform:translateX(-50%);background:#21262d;color:#e6edf3;padding:10px 20px;border-radius:20px;font-size:13px;font-weight:600;z-index:200;opacity:0;transition:opacity .2s;pointer-events:none;white-space:nowrap;border:1px solid #30363d}
.toast.show{opacity:1}
.btn-reset{width:100%;padding:12px;border-radius:12px;font-size:13px;font-weight:600;border:1px solid #30363d;background:transparent;color:#8b949e;cursor:pointer;margin-top:10px}
</style>
</head>
<body>
<div class="hdr">
  <div class="hdr-top">
    <div class="hdr-title"><span class="dot"></span>AI Stock Scanner</div>
    <span class="pill" id="status-pill">LOADING</span>
  </div>
  <div class="refresh-info" id="refresh-info">Scanning markets...</div>
  <div class="progress-wrap"><div class="progress-bar" id="top-prog" style="width:0%"></div></div>
  <div class="mkt-tabs">
    <button class="mkt-tab on" onclick="switchMkt('nse',this)">🇮🇳 Nifty 50</button>
    <button class="mkt-tab" onclick="switchMkt('us',this)">🇺🇸 US Top 50</button>
  </div>
</div>

<div class="metrics" id="metrics">
  <div class="mc full"><div class="ml">Portfolio Value</div><div class="mv b">Loading...</div></div>
</div>

<div class="tabs">
  <button class="tab on" onclick="sw('watch',this)">📊 Scanner</button>
  <button class="tab" onclick="sw('pos',this)">💼 Positions</button>
  <button class="tab" onclick="sw('hist',this)">📈 History</button>
  <button class="tab" onclick="sw('log',this)">📋 Log</button>
</div>

<div id="tc-watch" class="tc on">
  <div class="page">
    <div id="mkt-nse" class="mkt-section on"></div>
    <div id="mkt-us"  class="mkt-section"></div>
  </div>
</div>
<div id="tc-pos"  class="tc"><div class="page" id="pg-pos"></div></div>
<div id="tc-hist" class="tc"><div class="page" id="pg-hist"></div></div>
<div id="tc-log"  class="tc"><div class="page" id="pg-log"></div></div>
<div class="toast" id="toast"></div>

<script>
let D={}, curMkt='nse';
const C0=100000;

function showToast(msg,err){
  const t=document.getElementById('toast');
  t.textContent=msg; t.style.borderColor=err?'#f85149':'#3fb950';
  t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2500);
}
function fmt(n,d=2){return Number(n)>=1000?Number(n).toFixed(0):Number(n).toFixed(d);}
function fmtC(n){return(Number(n)>=0?'+':'')+Number(n).toFixed(2);}
function fmtINR(n){return'₹'+Number(n).toLocaleString('en-IN',{maximumFractionDigits:0});}

async function fetchState(){
  try{ const r=await fetch('/api/state'); D=await r.json(); render(); }
  catch(e){ document.getElementById('status-pill').textContent='OFFLINE'; }
}

function render(){
  const pill=document.getElementById('status-pill');
  const prog=D.scan_progress||0; const total=D.scan_total||100;
  const pct=Math.round(prog/total*100);

  if(D.status==='live'){
    pill.textContent='LIVE'; pill.className='pill pill-live';
    document.getElementById('top-prog').style.width='100%';
  } else if(D.status==='refreshing'){
    pill.textContent=`SCANNING ${pct}%`; pill.className='pill pill-scan';
    document.getElementById('top-prog').style.width=pct+'%';
  } else {
    pill.textContent='ERROR'; pill.className='pill pill-err';
  }
  document.getElementById('refresh-info').textContent='Updated: '+D.last_refresh;

  document.getElementById('metrics').innerHTML=`
    <div class="mc full"><div class="ml">Portfolio Value</div><div class="mv ${D.pnl>=0?'g':'r'}">${fmtINR(D.total)}</div></div>
    <div class="mc"><div class="ml">Cash</div><div class="mv sm b">${fmtINR(D.capital)}</div></div>
    <div class="mc"><div class="ml">Total P&L</div><div class="mv sm ${D.pnl>=0?'g':'r'}">${fmtC(D.pnl)}</div></div>`;

  renderWatch(); renderPos(); renderHist(); renderLog();
}

function indTags(d){
  const tags=[
    {label:'Trend '+(d.trend_bull?'▲':'▼'), on:d.trend_bull},
    {label:'EMA '+(d.ema_align?'✓':'✗'), on:d.ema_align},
    {label:'RSI '+d.rsi, on:d.rsi>=40&&d.rsi<=65, warn:d.rsi>70},
    {label:'MACD '+(d.macd_bull?'▲':'▼'), on:d.macd_bull},
    {label:'ST '+(d.supertrend===1?'▲':'▼'), on:d.supertrend===1},
    {label:'Vol '+d.volume_ratio+'x', on:d.volume_ratio>=1.5},
  ];
  return tags.map(t=>`<span class="ind-tag ${t.on?'on':t.warn?'warn':''}">${t.label}</span>`).join('');
}

function stockCard(sym,d){
  const haPos=!!(D.positions||{})[sym];
  const sc=d.score; const scClr=sc>=72?'#3fb950':sc>=52?'#d29922':'#f85149';
  const label=sym.replace('.NS',''); const isNSE=sym.endsWith('.NS');
  const isBuy=d.signal==='BUY';
  return `<div class="stock-card${isBuy?' buy-sig':''}">
    <div class="sc-hdr">
      <div>
        <div><span class="sc-sym">${label}</span><span class="sc-flag ${isNSE?'nse-flag':'us-flag'}">${isNSE?'NSE':'US'}</span></div>
        <div class="sc-badges">
          <span class="sig-badge sig-${d.signal}">${d.signal}</span>
          <span class="sc-score-txt">Score ${sc}/100</span>
          ${d.change5>0?`<span class="sc-score-txt g">+${d.change5}% (5d)</span>`:''}
        </div>
      </div>
      <div>
        <div class="sc-price ${d.change_pct>=0?'g':'r'}">${fmt(d.price)}</div>
        <div class="sc-chg ${d.change_pct>=0?'g':'r'}">${d.change_pct>=0?'+':''}${Number(d.change_pct).toFixed(2)}%</div>
      </div>
    </div>
    <div class="sc-bar-bg"><div class="sc-bar-fill" style="width:${sc}%;background:${scClr}"></div></div>
    <div class="indicators-row">${indTags(d)}</div>
    <div class="sc-grid">
      <div class="sc-item"><div class="sc-item-l">Entry</div><div class="sc-item-v">${fmt(d.entry)}</div></div>
      <div class="sc-item"><div class="sc-item-l">Risk:Reward</div><div class="sc-item-v ${d.rr>=2?'g':'a'}">${Number(d.rr).toFixed(1)}:1</div></div>
      <div class="sc-item"><div class="sc-item-l">Target ▲</div><div class="sc-item-v g">${fmt(d.target)}</div></div>
      <div class="sc-item"><div class="sc-item-l">Stop Loss ▼</div><div class="sc-item-v r">${fmt(d.sl)}</div></div>
    </div>
    <div class="sc-reasons">${(d.reasons||[]).join(' · ')}</div>
    <button class="btn-buy" onclick="buy('${sym}')" ${haPos||d.signal==='HOLD'?'disabled':''}>${haPos?'✓ In Portfolio':'Buy Now'}</button>
  </div>`;
}

function renderSection(stocks, md, label, emoji){
  if(!stocks.length) return '';
  return `<div class="sec-hdr">${emoji} ${label} <span class="sec-cnt">${stocks.length}</span></div>`+
    stocks.map(s=>stockCard(s,md[s])).join('');
}

function renderMarket(stockList, elId){
  const md=D.market_data||{};
  const prog=D.scan_progress||0; const total=D.scan_total||100;
  const available=stockList.filter(s=>md[s]);

  if(!available.length){
    const pct=Math.round(prog/total*100);
    document.getElementById(elId).innerHTML=`
      <div class="scan-status">
        <div class="scan-status-title">🔍 Scanning Markets</div>
        <div class="scan-status-sub">Analysing ${prog}/${total} stocks using 7 indicators...<br>Please wait 5-8 minutes for first scan</div>
        <div class="scan-prog-bg"><div class="scan-prog-fill" style="width:${pct}%"></div></div>
      </div>`;
    return;
  }

  const sorted=available.sort((a,b)=>md[b].score-md[a].score);
  const buys=sorted.filter(s=>md[s].signal==='BUY');
  const watches=sorted.filter(s=>md[s].signal==='WATCH');

  let html='';
  if(buys.length) html+=renderSection(buys,md,'BUY Signals','🔥');
  else html+=`<div class="scan-status"><div class="scan-status-title">No BUY signals right now</div><div class="scan-status-sub">Market conditions don't meet all 7 criteria.<br>Check WATCH signals below.</div></div>`;
  if(watches.length) html+=renderSection(watches,md,'Watch List','👀');
  document.getElementById(elId).innerHTML=html;
}

function renderWatch(){
  renderMarket(D.nse_stocks||[], 'mkt-nse');
  renderMarket(D.us_stocks||[], 'mkt-us');
}

function renderPos(){
  const pos=D.positions||{};
  const entries=Object.entries(pos);
  if(!entries.length){
    document.getElementById('pg-pos').innerHTML=`<div class="empty"><div class="empty-icon">💼</div><div class="empty-title">No open positions</div><div class="empty-sub">Go to Scanner tab and tap Buy Now on a BUY signal.</div></div>`;
    return;
  }
  document.getElementById('pg-pos').innerHTML=entries.map(([sym,p])=>
    `<div class="pos-card ${p.upnl>=0?'profit':'loss'}">
      <div class="pc-top">
        <div><span class="pc-sym">${sym.replace('.NS','')}</span><span class="pc-qty">${p.qty} shares</span></div>
        <div><div class="pc-pnl ${p.upnl>=0?'g':'r'}">${fmtC(p.upnl)}</div><div class="pc-pct ${p.upnl>=0?'g':'r'}">${p.upct>=0?'+':''}${Number(p.upct).toFixed(2)}%</div></div>
      </div>
      <div class="pc-grid">
        <div class="pc-item"><div class="pc-item-l">Entry</div><div class="pc-item-v">${fmt(p.entry)}</div></div>
        <div class="pc-item"><div class="pc-item-l">Current</div><div class="pc-item-v ${p.upnl>=0?'g':'r'}">${fmt(p.cmp)}</div></div>
        <div class="pc-item"><div class="pc-item-l">Target ▲</div><div class="pc-item-v g">${fmt(p.target)}</div></div>
        <div class="pc-item"><div class="pc-item-l">Stop Loss ▼</div><div class="pc-item-v r">${fmt(p.sl)}</div></div>
        <div class="pc-item"><div class="pc-item-l">Cost</div><div class="pc-item-v" style="font-size:11px">${fmtINR(p.cost)}</div></div>
        <div class="pc-item"><div class="pc-item-l">Since</div><div class="pc-item-v" style="font-size:11px">${p.time}</div></div>
      </div>
      <button class="btn-exit" onclick="sell('${sym}')">Exit Position</button>
    </div>`
  ).join('');
}

function renderHist(){
  const h=D.history||[];
  if(!h.length){
    document.getElementById('pg-hist').innerHTML=`<div class="empty"><div class="empty-icon">📊</div><div class="empty-title">No closed trades</div><div class="empty-sub">Your trade history will appear here.</div></div>`;
    return;
  }
  const wins=h.filter(x=>x.pnl>=0).length;
  const total=h.reduce((s,x)=>s+x.pnl,0);
  document.getElementById('pg-hist').innerHTML=`
    <div class="hist-stats">
      <div class="mc"><div class="ml">Win Rate</div><div class="mv ${wins/h.length>=.5?'g':'r'}" style="font-size:20px">${(wins/h.length*100).toFixed(0)}%</div></div>
      <div class="mc"><div class="ml">Trades</div><div class="mv b" style="font-size:20px">${h.length}</div></div>
      <div class="mc"><div class="ml">P&L</div><div class="mv ${total>=0?'g':'r'}" style="font-size:15px;padding-top:3px">${fmtC(total)}</div></div>
    </div>
    ${h.map(t=>`<div class="hist-card ${t.pnl>=0?'win':'loss'}">
      <div><div class="hist-sym">${t.sym.replace('.NS','')}</div><div class="hist-detail">${t.qty} shares · ${t.time}<br>${fmt(t.entry)} → ${fmt(t.exit)}</div></div>
      <div><div class="hist-pnl ${t.pnl>=0?'g':'r'}">${fmtC(t.pnl)}</div><div class="hist-reason">${t.reason}</div></div>
    </div>`).join('')}
    <button class="btn-reset" onclick="resetPortfolio()">Reset Portfolio</button>`;
}

function renderLog(){
  const log=D.log||[];
  if(!log.length){document.getElementById('pg-log').innerHTML='<div style="color:#8b949e;padding:20px 0;font-size:12px">No activity yet</div>';return;}
  document.getElementById('pg-log').innerHTML=log.map(l=>
    `<div class="log-item"><div class="log-t">${l.t}</div><div class="log-${l.type}">${l.msg}</div></div>`
  ).join('');
}

function switchMkt(mkt,btn){
  curMkt=mkt;
  document.querySelectorAll('.mkt-tab').forEach(e=>e.classList.remove('on'));
  document.querySelectorAll('.mkt-section').forEach(e=>e.classList.remove('on'));
  btn.classList.add('on');
  document.getElementById('mkt-'+mkt).classList.add('on');
}
async function buy(sym){
  const r=await fetch('/api/buy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sym})});
  const d=await r.json(); showToast(d.msg,!d.ok); if(d.ok) fetchState();
}
async function sell(sym){
  const r=await fetch('/api/sell',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sym})});
  const d=await r.json(); showToast(d.msg,!d.ok); if(d.ok) fetchState();
}
async function resetPortfolio(){
  if(!confirm('Reset all trades?')) return;
  await fetch('/api/reset',{method:'POST'}); showToast('Reset!'); fetchState();
}
function sw(name,btn){
  document.querySelectorAll('.tc').forEach(e=>e.classList.remove('on'));
  document.querySelectorAll('.tab').forEach(e=>e.classList.remove('on'));
  document.getElementById('tc-'+name).classList.add('on'); btn.classList.add('on');
}
fetchState(); setInterval(fetchState,8000);
</script>
</body>
</html>"""

if __name__=="__main__":
    load_state()
    threading.Thread(target=loop,daemon=True).start()
    port=int(os.environ.get("PORT",5050))
    print(f"Starting AI Stock Scanner on port {port}")
    print(f"Scanning {len(ALL_STOCKS)} stocks: {len(NSE_STOCKS)} NSE + {len(US_STOCKS)} US")
    app.run(host="0.0.0.0",port=port,threaded=True,debug=False,use_reloader=False)
