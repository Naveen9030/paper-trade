import json, os, time, threading, datetime, requests
from flask import Flask, jsonify, request, render_template_string
import pandas as pd, numpy as np

STOCKS = ["RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","AAPL","NVDA","MSFT","TSLA"]
CAPITAL0 = 100_000
RISK     = 0.02
SL_M     = 1.0
TP_M     = 2.0
MIN_SC   = 70
CACHE    = "cache.json"
LOG      = "log.json"

app = Flask(__name__)
S = {"capital":CAPITAL0,"positions":{},"history":[],"log":[],
     "market_data":{},"last_refresh":"loading...","status":"starting"}
LK = threading.Lock()

def yf(sym):
    for h in ["query1","query2"]:
        try:
            r=requests.get(f"https://{h}.finance.yahoo.com/v8/finance/chart/{sym}",
                headers={"User-Agent":"Mozilla/5.0"},
                params={"interval":"1d","range":"3mo"},timeout=15)
            if r.status_code!=200: continue
            res=r.json()["chart"]["result"][0]
            q=res["indicators"]["quote"][0]
            try: cl=res["indicators"]["adjclose"][0]["adjclose"]
            except: cl=q["close"]
            df=pd.DataFrame({"O":q["open"],"H":q["high"],"L":q["low"],
                "C":cl,"V":q["volume"]},
                index=pd.to_datetime(res["timestamp"],unit="s")).dropna()
            if len(df)>=20:
                print(f"✓ {sym} = {round(float(df.C.iloc[-1]),2)}")
                return df
        except Exception as e:
            print(f"  {sym}/{h}: {e}")
    return None

def ema(s,p): return s.ewm(span=p,adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0).ewm(com=p-1,adjust=False).mean()
    l=(-d.clip(upper=0)).ewm(com=p-1,adjust=False).mean()
    v=100-100/(1+g/l.replace(0,np.nan))
    return float(v.iloc[-1]) if not v.empty else 50.0
def atr(df,p=14):
    h,l,c=df.H,df.L,df.C
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return float(tr.ewm(com=p-1,adjust=False).mean().iloc[-1])
def macd(s):
    ln=ema(s,12)-ema(s,26); sg=ema(ln,9)
    return float(ln.iloc[-1]),float(sg.iloc[-1])

def score(df):
    c=df.C; v=df.V; px=float(c.iloc[-1])
    e9,e21,e50=float(ema(c,9).iloc[-1]),float(ema(c,21).iloc[-1]),float(ema(c,50).iloc[-1])
    e200=float(ema(c,min(200,len(c)-1)).iloc[-1])
    rs=rsi(c); ml,ms=macd(c); at=atr(df)
    avgv=float(v.iloc[-21:-1].mean()) if len(v)>21 else float(v.mean())
    vr=float(v.iloc[-1])/avgv if avgv>0 else 1
    sc=0; rsns=[]
    if px>e200: sc+=25; rsns.append("Uptrend")
    if e9>e21>e50: sc+=20; rsns.append("EMAs aligned")
    if 40<=rs<=65: sc+=15; rsns.append(f"RSI {rs:.0f}")
    if ml>ms: sc+=15; rsns.append("MACD bull")
    if vr>=1.3: sc+=10; rsns.append(f"Vol {vr:.1f}x")
    sl=px-SL_M*at; tg=px+TP_M*at; rr=(tg-px)/max(px-sl,.01)
    chg=(px-float(c.iloc[-2]))/float(c.iloc[-2])*100 if len(c)>=2 else 0
    return dict(price=round(px,2),score=sc,
        signal="BUY" if sc>=MIN_SC else ("WATCH" if sc>=50 else "HOLD"),
        rsi=round(rs,1),entry=round(px,2),sl=round(sl,2),target=round(tg,2),
        rr=round(rr,2),atr=round(at,2),reasons=rsns,change_pct=round(chg,2))

def do_refresh():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Fetching prices...")
    with LK: S["status"]="refreshing"
    out={}
    for sym in STOCKS:
        try:
            df=yf(sym)
            if df is not None: out[sym]=score(df)
            del df
            time.sleep(2)
        except Exception as e: print(f"  err {sym}: {e}")
    now=(datetime.datetime.now()+datetime.timedelta(hours=5,minutes=30)).strftime("%d %b %H:%M IST")
    with LK:
        if out:
            S["market_data"]=out
            S["status"]="live"
            try:
                with open(CACHE,"w") as f: json.dump(out,f)
            except: pass
        else:
            S["status"]="error"
        S["last_refresh"]=now
    print(f"Done: {len(out)} stocks")

def loop():
    print("Refresh thread started ✓")
    do_refresh()
    while True:
        time.sleep(600)
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
        exit=round(px,2),pnl=round(pnl,2),reason=reason,
        time=datetime.datetime.now().strftime("%H:%M")))
    del S["positions"][sym]
    S["log"].insert(0,dict(t=datetime.datetime.now().strftime("%H:%M"),
        type="win" if pnl>=0 else "loss",
        msg=f"{reason}: {sym.replace('.NS','')} PnL:{round(pnl,2):+.0f}"))
    save_state()

@app.route("/api/state")
def api_state():
    with LK:
        pv=sum(p["qty"]*S["market_data"].get(s,{}).get("price",p["entry"]) for s,p in S["positions"].items())
        total=S["capital"]+pv; pnl=total-CAPITAL0
        opnl=sum(p["qty"]*(S["market_data"].get(s,{}).get("price",p["entry"])-p["entry"]) for s,p in S["positions"].items())
        pos_e={}
        for sym,pos in S["positions"].items():
            px=S["market_data"].get(sym,{}).get("price",pos["entry"])
            pos_e[sym]={**pos,"cmp":round(px,2),
                "upnl":round(pos["qty"]*(px-pos["entry"]),2),
                "upct":round((px-pos["entry"])/pos["entry"]*100,2)}
        return jsonify(capital=round(S["capital"],2),pos_val=round(pv,2),
            total=round(total,2),pnl=round(pnl,2),open_pnl=round(opnl,2),
            market_data=S["market_data"],positions=pos_e,
            history=S["history"][:40],log=S["log"][:30],
            last_refresh=S["last_refresh"],status=S["status"])

@app.route("/api/buy",methods=["POST"])
def api_buy():
    sym=request.json.get("sym","")
    with LK:
        if sym in S["positions"]: return jsonify(ok=False,msg="Already holding")
        d=S["market_data"].get(sym)
        if not d: return jsonify(ok=False,msg="Prices loading, please wait")
        px=d["entry"]; sl=d["sl"]; tg=d["target"]
        qty=max(1,int(S["capital"]*RISK/max(px-sl,.01)))
        cost=qty*px
        if cost>S["capital"]: return jsonify(ok=False,msg="Insufficient funds")
        S["capital"]-=cost
        S["positions"][sym]=dict(qty=qty,entry=round(px,2),sl=round(sl,2),
            target=round(tg,2),cost=round(cost,2),
            time=datetime.datetime.now().strftime("%H:%M"))
        S["log"].insert(0,dict(t=datetime.datetime.now().strftime("%H:%M"),
            type="buy",msg=f"BUY {qty}x{sym.replace('.NS','')} @ {round(px,2)}"))
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
            log=[dict(t=datetime.datetime.now().strftime("%H:%M"),
                      type="info",msg="Portfolio reset")])
        save_state()
    return jsonify(ok=True)

@app.route("/")
def index():
    return render_template_string(open("mobile_ui.html").read())

if __name__=="__main__":
    load_state()
    threading.Thread(target=loop,daemon=True).start()
    port=int(os.environ.get("PORT",5050))
    print(f"Starting on port {port}")
    app.run(host="0.0.0.0",port=port,threaded=True,debug=False,use_reloader=False)
