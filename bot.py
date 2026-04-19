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
GOLD = "IAU"  # iShares Gold ETF

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
# FETCH
# ======================
def fetch(symbol):
    key = symbol
    now = time.time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"]

    # Twelve
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

    # Yahoo fallback
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

def momentum_ok(df):
    return df["Close"].diff().iloc[-3:].mean() > 0

# ======================
# SR
# ======================
def sr(df):
    return df["Low"].rolling(20).min().iloc[-1], df["High"].rolling(20).max().iloc[-1]

# ======================
# GOLD ANALYSIS（新增🔥）
# ======================
def gold_analysis():
    df = fetch(GOLD)
    if df is None or len(df)<50:
        return "⚪ Gold 數據不可用"

    price = df["Close"].iloc[-1]
    low,high = sr(df)
    rsi,_ = indicators(df)

    entry_low = low
    entry_high = low*1.02
    stop = low*0.97
    target = high

    # timing 判斷
    if price < entry_low:
        timing = "🟡 等回調"
    elif entry_low <= price <= entry_high:
        timing = "🟢 可分批買入"
    else:
        timing = "❌ 唔好追高"

    return f"""
🟡【Gold ETF（IAU）】

💰 現價：{round(price,2)}
⏱️ Timing：{timing}

━━━━━━━━━━━━━━━

👉 入場：{round(entry_low,2)} - {round(entry_high,2)}
👉 止蝕：{round(stop,2)}
👉 目標：{round(target,2)}

━━━━━━━━━━━━━━━

🧠 策略：

👉 分批買入（唔all-in）
👉 唔追高
👉 長線持有（對沖風險）
"""

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
    in_zone = d["entry_low"] <= d["price"] <= d["entry_high"]

    if not in_zone:
        timing = "🟡 未到位"
    else:
        timing = "🟢 入場區"

    return f"""
📊【{symbol} 波段分析】

💰 現價：{d['price']}
⏱️ Timing：{timing}

━━━━━━━━━━━━━━━

📈 趨勢：{"🟢 上升" if d['trend'] else "🔴 弱"}
RSI：{d['rsi']}

━━━━━━━━━━━━━━━

👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}
👉 R/R：{d['rr']}
"""

# ======================
# LOOP（保持原樣）
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
                if d["rr"] < 1.5:
                    continue

                st = state.get(s,{"setup":0,"entry":0,"breakout":0,"in_zone":False})

                in_zone = d["entry_low"] <= d["price"] <= d["entry_high"]

                if not in_zone and now-st["setup"]>SETUP_CD:
                    send(CHAT_ID,f"👀【{s} Setup】\n{d['entry_low']}-{d['entry_high']}")
                    st["setup"]=now

                if in_zone and not st["in_zone"]:
                    if momentum_ok(df) and volume_ok(df) and now-st["entry"]>ENTRY_CD:
                        send(CHAT_ID,f"🚀【{s} 入場信號】\n{d['entry_low']}-{d['entry_high']}")
                        st["entry"]=now

                st["in_zone"]=in_zone

                if d["price"]>d["target"]:
                    if now-st["breakout"]>BREAKOUT_CD:
                        send(CHAT_ID,f"🚀【{s} 突破】{d['target']}")
                        st["breakout"]=now

                state[s]=st

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e)
            time.sleep(10)

threading.Thread(target=loop,daemon=True).start()

# ======================
# LONG（升級🔥）
# ======================
def long_term():
    gold_txt = gold_analysis()

    return f"""
💰【長線投資】

📊 S&P500：
👉 每月DCA

📊 VWRA：
👉 全球ETF

📊 MSFT：
👉 等回調5-10%

{gold_txt}

━━━━━━━━━━━━━━━

📦 配置：

👉 45% S&P500
👉 25% VWRA
👉 20% MSFT
👉 10% Gold
"""

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
        send(chat_id,"🚀 V40.6 Ready")

    elif text=="/check":
        for s in SWING:
            data=analyze(s)
            if data:
                df,d=data
                send(chat_id,format_output(s,d,df))

    elif text=="/long":
        send(chat_id,long_term())

    return "ok"

# ======================
# RUN
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
