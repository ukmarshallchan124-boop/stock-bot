from flask import Flask, request
import requests, os, time, threading, datetime
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
URL = f"https://api.telegram.org/bot{TOKEN}"

SWING = ["TSLA","NVDA","AMD"]

cache = {}
CACHE_TTL = 300

state = {}
user_state = {}
last_use = {}

SETUP_CD = 1800
ENTRY_CD = 3600
BREAKOUT_CD = 3600

# ======================
# SEND
# ======================
def send(chat_id, text):
    try:
        requests.post(f"{URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text[:4000]
        }, timeout=10)
    except:
        pass

# ======================
# MARKET TIME
# ======================
def market_open():
    now = datetime.datetime.utcnow()
    return 14 <= now.hour <= 21  # US market

# ======================
# FETCH
# ======================
def fetch(symbol):
    key = symbol
    now = time.time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"]

    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")
        if not df.empty:
            cache[key] = {"data": df, "time": now}
            return df
    except:
        pass

    return None

# ======================
# INDICATORS
# ======================
def indicators(df):
    close = df["Close"]

    ema9 = close.ewm(span=9).mean()
    ema21 = close.ewm(span=21).mean()
    trend = ema9.iloc[-1] > ema21.iloc[-1]

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = round((100-(100/(1+rs))).iloc[-1],1)

    return rsi, trend

def volume_ok(df):
    return df["Volume"].iloc[-1] > df["Volume"].rolling(20).mean().iloc[-1]

def momentum(df):
    m = df["Close"].diff().iloc[-3:].mean()
    return m > 0

# ======================
# SR
# ======================
def sr(df):
    return df["Low"].rolling(20).min().iloc[-1], df["High"].rolling(20).max().iloc[-1]

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:2]
        txt=""
        for n in news:
            title=n.get("title","")
            txt+=f"• {title}\n"
        return txt if txt else "⚪ 無重要新聞"
    except:
        return "⚪ 無新聞"

# ======================
# ANALYSIS
# ======================
def analyze(symbol):
    df = fetch(symbol)
    if df is None or len(df)<50:
        return None

    price = df["Close"].iloc[-1]
    low,high = sr(df)

    entry_low = low
    entry_high = low*1.02
    stop = low*0.97
    target = high

    rr = round((target-entry_low)/(entry_low-stop),2)

    rsi,trend = indicators(df)

    return df,{
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":rr,
        "rsi":rsi,
        "trend":trend
    }

# ======================
# FORMAT
# ======================
def format_output(symbol,d,df):
    news = get_news(symbol)

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
📈 趨勢：{"🟢 上升" if d['trend'] else "🔴 偏弱"}

RSI：{d['rsi']}
Volume：{"🟢 放量" if volume_ok(df) else "⚪ 正常"}

━━━━━━━━━━━━━━━

👉 入場：{d['entry_low']} - {d['entry_high']}
🛑 止蝕：{d['stop']}
🎯 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━━

📰 新聞：
{news}
"""

# ======================
# LOOP
# ======================
def loop():
    while True:
        try:
            if not market_open():
                time.sleep(300)
                continue

            now=time.time()

            for s in SWING:
                data = analyze(s)
                if not data: continue

                df,d = data
                if d["rr"] < 1.5: continue

                st = state.get(s,{"setup":0,"entry":0,"breakout":0})

                # SETUP
                if d["trend"] and now-st["setup"]>SETUP_CD:
                    send(os.getenv("CHAT_ID"),
                         f"👀 {s} Setup\n區間：{d['entry_low']}-{d['entry_high']}")
                    st["setup"]=now

                # ENTRY
                if d["entry_low"]<=d["price"]<=d["entry_high"] and momentum(df):
                    if now-st["entry"]>ENTRY_CD:
                        send(os.getenv("CHAT_ID"),
                             f"🚀 {s} 入場信號\n區間：{d['entry_low']}-{d['entry_high']}")
                        st["entry"]=now

                # BREAKOUT
                if d["price"]>d["target"] and volume_ok(df):
                    if now-st["breakout"]>BREAKOUT_CD:
                        send(os.getenv("CHAT_ID"),
                             f"🚀 {s} 突破 {d['target']}")
                        st["breakout"]=now

                state[s]=st

            time.sleep(300)
        except:
            pass

threading.Thread(target=loop,daemon=True).start()

# ======================
# CALC
# ======================
def calc_flow(chat_id, text):
    if user_state.get(chat_id)!="calc":
        user_state[chat_id]="calc"
        return send(chat_id,"輸入金額，例如100")

    try:
        x=float(text)
        if x<=0: return send(chat_id,"金額需>0")
        user_state.pop(chat_id)
        send(chat_id,f"+10% {x*1.1:.2f}\n-10% {x*0.9:.2f}")
    except:
        send(chat_id,"請輸入數字")

# ======================
# POSITION
# ======================
def position_flow(chat_id, text):
    if user_state.get(chat_id)!="pos":
        user_state[chat_id]="pos"
        return send(chat_id,"輸入：NVDA 190")

    try:
        s,p=text.split()
        df=fetch(s.upper())
        price=df["Close"].iloc[-1]
        pnl=(price-float(p))/float(p)*100
        user_state.pop(chat_id)
        send(chat_id,f"{s} 盈虧 {pnl:.2f}%")
    except:
        send(chat_id,"格式錯")

# ======================
# LONG
# ======================
def long_term():
    return """
💰【長線】

S&P500：
👉 每月DCA
👉 分散風險

MSFT：
👉 AI龍頭
👉 等回調再買
"""

# ======================
# WEBHOOK
# ======================
@app.route("/",methods=["POST"])
def webhook():
    data=request.get_json()
    if not data: return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text=="/start":
        send(chat_id,"🚀 Bot 已啟動")

    elif text=="/check":
        for s in SWING:
            data=analyze(s)
            if data:
                df,d=data
                send(chat_id,format_output(s,d,df))

    elif text=="/calc":
        calc_flow(chat_id,text)

    elif text=="/position":
        position_flow(chat_id,text)

    elif text=="/long":
        send(chat_id,long_term())

    elif chat_id in user_state:
        if user_state[chat_id]=="calc":
            calc_flow(chat_id,text)
        elif user_state[chat_id]=="pos":
            position_flow(chat_id,text)

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
