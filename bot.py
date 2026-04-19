from flask import Flask, request
import requests, os, time, threading, datetime
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("TWELVE_API_KEY")
CHAT_ID = os.getenv("CHAT_ID")

URL = f"https://api.telegram.org/bot{TOKEN}"

SWING = ["TSLA","NVDA","AMD","XOM","JPM"]

cache = {}
CACHE_TTL = 300

state = {}
user_state = {}

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
    except Exception as e:
        print("SEND ERROR:", e)

# ======================
# MARKET TIME
# ======================
def market_open():
    now = datetime.datetime.utcnow()
    return 14 <= now.hour <= 21

# ======================
# FETCH（含 retry）
# ======================
def fetch(symbol):
    key = symbol
    now = time.time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"]

    for _ in range(3):
        try:
            if API_KEY:
                url = "https://api.twelvedata.com/time_series"
                params = {
                    "symbol": symbol,
                    "interval": "15min",
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

                    cache[key] = {"data": df, "time": now}
                    return df
        except:
            pass

        time.sleep(1)

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

    return rsi, trend, ema9.iloc[-1], ema21.iloc[-1]

def volume_ok(df):
    return df["Volume"].iloc[-1] > df["Volume"].rolling(20).mean().iloc[-1]

def momentum_ok(df):
    return df["Close"].diff().iloc[-3:].mean() > 0

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
            if any(w in title.lower() for w in ["ai","growth","beat"]):
                tag="🟢"
            elif any(w in title.lower() for w in ["risk","drop","cut"]):
                tag="🔴"
            else:
                tag="⚪"
            txt+=f"• {title} {tag}\n"
        return txt if txt else "⚪ 無新聞"
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

    rsi,trend,ema9,ema21 = indicators(df)

    return df,{
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":rr,
        "rsi":rsi,
        "trend":trend,
        "ema9":ema9,
        "ema21":ema21
    }

# ======================
# FORMAT
# ======================
def format_output(symbol,d,df):
    news = get_news(symbol)

    in_zone = d["entry_low"] <= d["price"] <= d["entry_high"]
    strong = d["ema9"] > d["ema21"] and momentum_ok(df)

    if not in_zone:
        timing = "🟡 未到位（等回調）"
    elif not strong:
        timing = "🟡 已到位但未轉強"
    else:
        timing = "🟢 可考慮入場"

    return f"""
📊【{symbol} 波段分析】

💰 現價：{d['price']}
⏱️ Timing：{timing}

━━━━━━━━━━━━━━━

📈 趨勢：{"🟢 上升" if d['trend'] else "🔴 偏弱"}
RSI：{d['rsi']}
Volume：{"🟢 放量" if volume_ok(df) else "⚪ 正常"}

━━━━━━━━━━━━━━━

💰 策略

👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}
👉 R/R：{d['rr']}

━━━━━━━━━━━━━━━

🧠 行動：

👉 {"可以考慮小注入場" if strong else "未符合入場條件"}
👉 唔好追高

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
                if not data:
                    continue

                df,d = data
                if d["rr"] < 1.5:
                    continue

                st = state.get(s,{
                    "setup":0,
                    "entry":0,
                    "breakout":0,
                    "in_zone":False
                })

                in_zone = d["entry_low"] <= d["price"] <= d["entry_high"]

                if not in_zone and now-st["setup"]>SETUP_CD:
                    send(CHAT_ID,f"👀【{s} Setup】\n回調區：{d['entry_low']}-{d['entry_high']}")
                    st["setup"]=now

                if in_zone and not st["in_zone"]:
                    if momentum_ok(df) and volume_ok(df) and now-st["entry"]>ENTRY_CD:
                        send(CHAT_ID,f"🚀【{s} 入場信號】\n入場區：{d['entry_low']}-{d['entry_high']}")
                        st["entry"]=now

                st["in_zone"]=in_zone

                if d["price"]>d["target"] and volume_ok(df):
                    if now-st["breakout"]>BREAKOUT_CD:
                        send(CHAT_ID,f"🚀【{s} 突破】{d['target']}\n👉 等回調再入")
                        st["breakout"]=now

                state[s]=st

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e)
            time.sleep(10)

threading.Thread(target=loop,daemon=True).start()

# ======================
# ROUTES
# ======================
@app.route("/",methods=["GET"])
def home():
    return "running"

@app.route("/",methods=["POST"])
def webhook():
    data=request.get_json()
    if not data: return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text=="/start":
        send(chat_id,"🚀 Bot Ready（V40.5）")

    elif text=="/check":
        for s in SWING:
            data=analyze(s)
            if data:
                df,d=data
                send(chat_id,format_output(s,d,df))

    return "ok"

# ======================
# RUN（🔥最重要）
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
