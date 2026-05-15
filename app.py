"""
AI Paper Trading Algo — Mobile Edition
Deploy free on Railway.app or Render.com
Access from any phone browser — no install needed
"""

import json, os, time, threading, datetime
from flask import Flask, render_template_string, jsonify, request
import yfinance as yf
import pandas as pd
import numpy as np

STOCKS = [
    "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","WIPRO.NS",
    "ICICIBANK.NS","BAJFINANCE.NS","SBIN.NS","TATAMOTORS.NS",
    "AAPL","NVDA","MSFT","TSLA","AMD",
]
STARTING_CAPITAL = 100_000
RISK_PER_TRADE   = 0.02
ATR_SL_MULT      = 1.0
ATR_TP_MULT      = 2.0
MIN_SCORE        = 70
REFRESH_SECONDS  = 60
LOG_FILE         = "trades_log.json"

app = Flask(__name__)
state = {
    "capital": STARTING_CAPITAL,
    "positions": {}, "history": [], "log": [],
    "market_data": {}, "last_refresh": "loading...", "status": "starting",
}
lock = threading.Lock()

def ema(s, p): return s.ewm(span=p, adjust=False).mean()
def rsi_calc(s, p=14):
    d=s.diff(); g=d.clip(lower=0).ewm(com=p-1,adjust=False).mean()
    l=(-d.clip(upper=0)).ewm(com=p-1,adjust=False).mean()
    r=100-100/(1+g/l.replace(0,np.nan))
    return float(r.iloc[-1]) if not r.empty else 50.0
def macd_calc(s):
    line=ema(s,12)-ema(s,26); sig=ema(line,9)
    return float(line.iloc[-1]), float(sig.iloc[-1])
def atr_calc(df, p=14):
    h,l,c=df["High"],df["Low"],df["Close"]
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return float(tr.ewm(com=p-1,adjust=False).mean().iloc[-1])

def score_stock(df):
    c=df["Close"]; v=df["Volume"]
    px=float(c.iloc[-1])
    e9,e21,e50,e200=[float(ema(c,p).iloc[-1]) for p in [9,21,50,200]]
    r=rsi_calc(c); ml,ms=macd_calc(c); a=atr_calc(df)
    avg_v=float(v.iloc[-21:-1].mean()) if len(v)>21 else float(v.mean())
    vr=float(v.iloc[-1])/avg_v if avg_v>0 else 1.0
    bb_m=c.rolling(20).mean(); bb_s=c.rolling(20).std()
    bw=float((4*bb_s).iloc[-1]); bwp=float((4*bb_s).iloc[-2]) if len(c)>21 else bw
    sc=0; rsns=[]
    if px>e200: sc+=25; rsns.append("Uptrend")
    if e9>e21>e50: sc+=20; rsns.append("EMAs aligned")
    if 40<=r<=65: sc+=15; rsns.append(f"RSI {r:.0f}")
    if ml>ms: sc+=15; rsns.append("MACD bull")
    if vr>=1.3: sc+=10; rsns.append(f"Vol {vr:.1f}x")
    if bw>bwp and px>float(bb_m.iloc[-1]): sc+=15; rsns.append("BB breakout")
    sig="BUY" if sc>=MIN_SCORE else ("WATCH" if sc>=50 else "HOLD")
    sl=px-ATR_SL_MULT*a; tgt=px+ATR_TP_MULT*a
    rr=(tgt-px)/max(px-sl,0.01)
    chg=(px-float(c.iloc[-2]))/float(c.iloc[-2])*100 if len(c)>=2 else 0
    return dict(price=round(px,2),score=sc,signal=sig,rsi=round(r,1),
                entry=round(px,2),sl=round(sl,2),target=round(tgt,2),
                rr=round(rr,2),atr=round(a,2),reasons=rsns,
                change_pct=round(chg,2),macd_bull=ml>ms,
                trend_bull=px>e200,ema_align=e9>e21>e50)

def refresh_loop():
    while True:
        try:
            with lock: state["status"]="refreshing"
            updated={}
            for sym in STOCKS:
                try:
                    df = yf.download(sym, period="6mo", interval="1d", progress=False, auto_adjust=True, timeout=30)
                    if df is None or len(df)<30: continue
                    df.columns=df.columns.get_level_values(0) if isinstance(df.columns,pd.MultiIndex) else df.columns
                    updated[sym]=score_stock(df)
                except: pass
            now=datetime.datetime.now().strftime("%d %b %H:%M")
            with lock:
                state["market_data"]=updated
                state["last_refresh"]=now
                state["status"]="live"
            _check_exits()
            print(f"[{now}] Refreshed {len(updated)} stocks")
        except Exception as e:
            print(f"Error: {e}")
            with lock: state["status"]="error"
        time.sleep(REFRESH_SECONDS)

def _check_exits():
    with lock:
        to_close=[]
        for sym,pos in state["positions"].items():
            d=state["market_data"].get(sym)
            if not d: continue
            if d["price"]<=pos["sl"]: to_close.append((sym,"Stop Loss"))
            elif d["price"]>=pos["target"]: to_close.append((sym,"Target Hit"))
        for sym,reason in to_close: _close(sym,reason)

def _close(sym,reason):
    pos=state["positions"].get(sym)
    if not pos: return
    px=state["market_data"].get(sym,{}).get("price",pos["entry"])
    pnl=pos["qty"]*px-pos["cost"]
    state["capital"]+=pos["qty"]*px
    state["history"].insert(0,dict(sym=sym,qty=pos["qty"],entry=pos["entry"],
        exit=round(px,2),pnl=round(pnl,2),reason=reason,
        time=datetime.datetime.now().strftime("%H:%M")))
    del state["positions"][sym]
    state["log"].insert(0,dict(t=datetime.datetime.now().strftime("%H:%M"),
        type="win" if pnl>=0 else "loss",
        msg=f"{reason}: {sym.replace('.NS','')} PnL:{round(pnl,2):+.0f}"))
    _save()

def _save():
    try:
        with open(LOG_FILE,"w") as f:
            json.dump({k:state[k] for k in ["capital","positions","history","log"]},f)
    except: pass

def _load():
    if not os.path.exists(LOG_FILE): return
    try:
        d=json.load(open(LOG_FILE))
        for k in ["capital","positions","history","log"]:
            if k in d: state[k]=d[k]
    except: pass

@app.route("/api/state")
def api_state():
    with lock:
        pv=sum(p["qty"]*state["market_data"].get(s,{}).get("price",p["entry"]) for s,p in state["positions"].items())
        total=state["capital"]+pv; pnl=total-STARTING_CAPITAL
        opnl=sum(p["qty"]*(state["market_data"].get(s,{}).get("price",p["entry"])-p["entry"]) for s,p in state["positions"].items())
        pos_e={}
        for sym,pos in state["positions"].items():
            px=state["market_data"].get(sym,{}).get("price",pos["entry"])
            pos_e[sym]={**pos,"cmp":round(px,2),"upnl":round(pos["qty"]*(px-pos["entry"]),2),"upct":round((px-pos["entry"])/pos["entry"]*100,2)}
        return jsonify(capital=round(state["capital"],2),pos_val=round(pv,2),
            total=round(total,2),pnl=round(pnl,2),open_pnl=round(opnl,2),
            market_data=state["market_data"],positions=pos_e,
            history=state["history"][:40],log=state["log"][:30],
            last_refresh=state["last_refresh"],status=state["status"])

@app.route("/api/buy",methods=["POST"])
def api_buy():
    sym=request.json.get("sym","")
    with lock:
        if sym in state["positions"]: return jsonify(ok=False,msg="Already holding")
        d=state["market_data"].get(sym)
        if not d: return jsonify(ok=False,msg="No data yet")
        px=d["entry"]; sl=d["sl"]; tgt=d["target"]
        risk=state["capital"]*RISK_PER_TRADE; rps=max(px-sl,0.01)
        qty=max(1,int(risk/rps)); cost=qty*px
        if cost>state["capital"]: return jsonify(ok=False,msg="Low funds")
        state["capital"]-=cost
        state["positions"][sym]=dict(qty=qty,entry=round(px,2),sl=round(sl,2),
            target=round(tgt,2),cost=round(cost,2),
            time=datetime.datetime.now().strftime("%H:%M"))
        state["log"].insert(0,dict(t=datetime.datetime.now().strftime("%H:%M"),
            type="buy",msg=f"BUY {qty}x{sym.replace('.NS','')} @ {round(px,2)} SL:{round(sl,2)} T:{round(tgt,2)}"))
        _save()
    return jsonify(ok=True,msg=f"Bought {qty} x {sym.replace('.NS','')}")

@app.route("/api/sell",methods=["POST"])
def api_sell():
    sym=request.json.get("sym","")
    with lock:
        if sym not in state["positions"]: return jsonify(ok=False,msg="Not holding")
        _close(sym,"Manual Exit")
    return jsonify(ok=True,msg=f"Exited {sym.replace('.NS','')}")

@app.route("/api/reset",methods=["POST"])
def api_reset():
    with lock:
        state.update(capital=STARTING_CAPITAL,positions={},history=[],
            log=[dict(t=datetime.datetime.now().strftime("%H:%M"),type="info",msg="Portfolio reset")])
        _save()
    return jsonify(ok=True)


@app.route("/")
def index():
    return render_template_string(open("mobile_ui.html").read())

if __name__ == "__main__":
    _load()
    t=threading.Thread(target=refresh_loop,daemon=True)
    t.start()
    port=int(os.environ.get("PORT",5050))
    print(f"Open http://localhost:{port} on your phone browser")
    app.run(host="0.0.0.0",port=port,debug=False,use_reloader=False)
