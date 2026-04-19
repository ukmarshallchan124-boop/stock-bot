from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # group id（自動推送用）
API_KEY = os.getenv("TWELVE_API_KEY")

URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

# ======================
# CACHE
# ======================
cache = {}
CACHE_TTL = 300

# ======================
# STATE（防spam核心）
# ======================
state = {}

SETUP_COOLDOWN = 1800
ENTRY_COOLDOWN = 3600
BREAKOUT_COOLDOWN = 3600

# ======================
# MARKET HOURS
# ======================
def market_open():
    now = datetime.now(pytz.timezone("US/Eastern"))
    return now.weekday() < 5 and (9 <= now.hour < 16)

# ======================
# SEND
# ======================
def send(chat_id, text, keyboard=None):
    try:
        data = {"chat_id": chat_id, "text": text[:4000]}
        if keyboard:
            data["reply_markup"] = keyboard
        requests.post(f"{URL}/sendMessage", json=data, timeout=10)
    except Exception as e:
        print("SEND ERROR:", e)

def menu():
    return {
        "keyboard":[
            ["📊 波段分析","💰 長線投資"],
            ["🧮 計算工具","📍 持倉分析"]
        ],
        "resize_keyboard":True
    }

# ======================
# FETCH（Twelve + Yahoo）
# ======================
def fetch(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"], cache[key]["src"]

    # TwelveData
    try:
        if API_KEY:
            url = "https://api.twelvedata.com/time_series"
            params = {
                "symbol": symbol,
                "interval": interval,
                "outputsize": 100,
                "apikey": API_KEY
            }
            r = requests.get(url, params=params, timeout=5).json()

            if "values" in r:
                df = pd.DataFrame(list(reversed(r["values"])))
                df["close"] = df["close"].astype(float)
                df["high"] = df["high"].astype(float)
                df["low"] = df["low"].astype(float)
                df["volume"] = df["volume"].astype(float)

                df.rename(columns={
                    "close":"Close",
                    "high":"High",
                    "low":"Low",
                    "volume":"Volume"
                }, inplace=True)

                cache[key] = {"data": df, "time": now, "src":"twelve"}
                return df, "twelve"
    except:
        pass

    # Yahoo fallback
    try:
        df = yf.Ticker(symbol).history(period="5d", interval=interval)
        if not df.empty:
            cache[key] = {"data": df, "time": now, "src":"yahoo"}
            return df, "yahoo"
    except:
        pass

    return None, None

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
    if m > 0: return "🟢 加速"
    if m < 0: return "🔴 轉弱"
    return "⚪ 中性"

def mtf(df):
    close = df["Close"]

    t15 = close.ewm(span=9).mean().iloc[-1] > close.ewm(span=21).mean().iloc[-1]
    t1 = close.iloc[::4].iloc[-1] > close.iloc[::4].ewm(span=20).mean().iloc[-1]
    t4 = close.iloc[::16].iloc[-1] > close.iloc[::16].ewm(span=50).mean().iloc[-1]

    pullback = close.iloc[-1] < close.rolling(10).max().iloc[-1]

    return t4,t1,t15,pullback

def ai_score(df):
    score = 50
    rsi,trend = indicators(df)
    t4,t1,t15,pb = mtf(df)

    if t4: score+=10
    if t1: score+=10
    if t15: score+=5
    if pb: score+=5
    if volume_ok(df): score+=10

    if 50<rsi<65: score+=10
    if rsi>70: score-=10

    return max(0,min(100,score))

# ======================
# DATA
# ======================
def sr(df):
    return df["Low"].rolling(20).min().iloc[-1], df["High"].rolling(20).max().iloc[-1]

def get_data(symbol):
    df,src = fetch(symbol,"15min")
    if df is None or len(df)<50:
        return None

    price = df["Close"].iloc[-1]
    low,high = sr(df)

    entry_low = low
    entry_high = low*1.02
    stop = low*0.97
    target = high

    rr = round((target-entry_low)/(entry_low-stop),2)

    return df,{
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":rr,
        "src":src
    }

# ======================
# FORMAT（波段分析）
# ======================
def format_output(symbol,d,df):
    rsi,_ = indicators(df)
    score = ai_score(df)
    t4,t1,t15,pb = mtf(df)

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
🧠 AI信心：{score}

━━━━━━━━━━━━━━━
4H：{"🟢 上升" if t4 else "🔴 弱"}
1H：{"🟡 回調" if pb else "🟢 延續"}
15m：{"🟢 轉強" if t15 else "⚪ 未確認"}

RSI：{rsi}
Momentum：{momentum(df)}

━━━━━━━━━━━━━━━
👉 入場：{d['entry_low']} - {d['entry_high']}
🛑 止蝕：{d['stop']}
🎯 目標：{d['target']}

📊 R/R：{d['rr']}
"""

# ======================
# LOOP（Signal Engine FIX）
# ======================
def loop():
    while True:
        try:
            if not market_open():
                time.sleep(300)
                continue

            now = time.time()

            for s in SWING_STOCKS:
                data = get_data(s)
                if not data: continue

                df,d = data
                score = ai_score(df)

                st = state.get(s,{
                    "setup":0,
                    "entry":0,
                    "breakout":0,
                    "zone":None,
                    "in_zone":False
                })

                zone = f"{d['entry_low']}-{d['entry_high']}"
                price = d["price"]

                # ===== Setup =====
                if score>60 and d["rr"]>2:
                    if now-st["setup"]>SETUP_COOLDOWN and zone!=st["zone"]:
                        send(CHAT_ID,f"👀【{s} Setup】\n回調區：{zone}")
                        st["setup"]=now
                        st["zone"]=zone

                # ===== Entry =====
                in_zone = d["entry_low"]<=price<=d["entry_high"]

                if in_zone and not st["in_zone"] and score>70:
                    if now-st["entry"]>ENTRY_COOLDOWN:
                        send(CHAT_ID,f"🚀【{s} Entry】\n區間：{zone}")
                        st["entry"]=now

                st["in_zone"]=in_zone

                # ===== Breakout =====
                if price>d["target"] and score>75:
                    if now-st["breakout"]>BREAKOUT_COOLDOWN:
                        send(CHAT_ID,f"🚀【{s} 突破】{d['target']}")
                        st["breakout"]=now

                state[s]=st

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:",e)

threading.Thread(target=loop,daemon=True).start()

# ======================
# TOOLS
# ======================
def calc(x):
    x=float(x)
    return f"+10%→{round(x*1.1,2)}\n-10%→{round(x*0.9,2)}"

def position(symbol,entry):
    df,_=fetch(symbol,"15min")
    if df is None: return "無數據"
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"{symbol} 盈虧：{round(pnl,2)}%"

def long_term():
    return "S&P500：每月DCA\nMSFT：等回調"

# ======================
# WEBHOOK（完整修復）
# ======================
@app.route("/",methods=["POST"])
def webhook():
    data=request.get_json()
    if not data or "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text in ["/start","start"]:
        send(chat_id,"🚀 V39.7.1 完整版",menu())

    elif "波段分析" in text:
        for s in SWING_STOCKS:
            data=get_data(s)
            if data:
                df,d=data
                send(chat_id,format_output(s,d,df),menu())

    elif "長線" in text:
        send(chat_id,long_term(),menu())

    elif text.replace('.','',1).isdigit():
        send(chat_id,calc(text),menu())

    elif len(text.split())==2:
        s,p=text.split()
        send(chat_id,position(s.upper(),float(p)),menu())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
