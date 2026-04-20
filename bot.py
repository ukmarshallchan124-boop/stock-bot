from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]
last_alert = {}

# ======================
# CACHE
# ======================
cache = {}
CACHE_TTL = 300

def get_df(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in cache:
        data, ts = cache[key]
        if now - ts < CACHE_TTL:
            return data

    try:
        df = yf.Ticker(symbol).history(period="5d", interval=interval)
        if df is None or df.empty:
            return None

        cache[key] = (df, now)
        return df
    except:
        return None

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(f"{URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": msg[:4000]
        }, timeout=10)
    except:
        pass

# ======================
# INDICATORS
# ======================
def calc(df):
    try:
        price = float(df["Close"].iloc[-1])

        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        rs = gain.rolling(14).mean()/loss.rolling(14).mean()
        rsi = float((100-(100/(1+rs))).iloc[-1])

        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9).mean()

        if macd_line.iloc[-1] > signal.iloc[-1]:
            macd = "🟢 多頭"
        else:
            macd = "🔴 偏弱"

        high = float(df["High"].max())
        low = float(df["Low"].min())

        entry_low = low * 1.01
        entry_high = low * 1.03
        stop = low * 0.97
        target = high * 1.02

        rr = round((target-entry_low)/(entry_low-stop),2)

        return {
            "price": round(price,2),
            "rsi": round(rsi,1),
            "macd": macd,
            "entry_low": round(entry_low,2),
            "entry_high": round(entry_high,2),
            "stop": round(stop,2),
            "target": round(target,2),
            "rr": rr
        }
    except:
        return None

# ======================
# NEWS（簡化但穩定）
# ======================
def news(symbol):
    try:
        items = yf.Ticker(symbol).news[:2]
        out = ""
        for n in items:
            title = n.get("title","")
            if any(w in title.lower() for w in ["ai","growth","beat"]):
                tag="🟢"
            elif any(w in title.lower() for w in ["risk","cut","drop"]):
                tag="🔴"
            else:
                tag="⚪"
            out += f"• {title} {tag}\n"
        return out if out else "⚪ 無新聞"
    except:
        return "⚪ 無新聞"

# ======================
# STOCK
# ======================
def stock(symbol):
    df5 = get_df(symbol,"5m")
    df1h = get_df(symbol,"60m")

    if not df5 or not df1h:
        return f"{symbol} ⚠️ 無數據"

    d5 = calc(df5)
    d1 = calc(df1h)

    if not d5 or not d1:
        return f"{symbol} ⚠️ 計算錯誤"

    in_zone = d5["entry_low"] <= d5["price"] <= d5["entry_high"]

    if not in_zone:
        timing = "🟡 未到位（等回調）"
        action = "未入場"
    elif "🟢" in d5["macd"]:
        timing = "🟢 可考慮入場"
        action = "可以分批入"
    else:
        timing = "🟡 到位但未轉強"
        action = "等確認"

    trend = "🟢 上升" if "🟢" in d1["macd"] else "🔴 弱"

    return f"""
📊【{symbol} 波段分析】

💰 現價：{d5['price']}
⏱️ Timing：{timing}

━━━━━━━━━━━━━━━

📈 趨勢：{trend}
RSI：{d5['rsi']}
MACD：{d5['macd']}

━━━━━━━━━━━━━━━

💰 策略

👉 入場：{d5['entry_low']} - {d5['entry_high']}
👉 止蝕：{d5['stop']}
👉 目標：{d5['target']}
👉 R/R：{d5['rr']}

━━━━━━━━━━━━━━━

🧠 行動：

👉 {action}
👉 唔好追高

━━━━━━━━━━━━━━━

📰 新聞：
{news(symbol)}
"""

# ======================
# MARKET
# ======================
def market():
    strong, weak = [], []

    for s in SYMBOLS:
        df = get_df(s,"60m")
        if not df: continue
        d = calc(df)
        if not d: continue

        if "🟢" in d["macd"]:
            strong.append(s)
        else:
            weak.append(s)

    return f"""
🌍【市場狀態】

🟢 強勢：{", ".join(strong) or "無"}
❌ 弱勢：{", ".join(weak) or "無"}

━━━━━━━━━━━━━━━

👉 做強勢股
👉 避弱勢股
"""

# ======================
# GOLD
# ======================
def gold():
    df = get_df("GC=F","1h")
    if not df:
        return "Gold 無數據"

    d = calc(df)

    return f"""
🥇【Gold】

💰 現價：{d['price']}

👉 市弱加倉
👉 對沖科技股
👉 ❌ 唔好追高
"""

# ======================
# LONG
# ======================
def long_term():
    return """
📈【長線投資】

S&P500 → 核心  
VWRA → 全球  
MSFT → 增長  
Gold → 對沖  

━━━━━━━━━━━━━━━

👉 40% S&P500  
👉 25% VWRA  
👉 20% MSFT  
👉 15% Gold  
"""

# ======================
# LOOP（推送）
# ======================
def loop():
    while True:
        try:
            now = time.time()

            # risk off
            spy = get_df("SPY","60m")
            if spy:
                d = calc(spy)
                if d and "🔴" in d["macd"]:
                    last = last_alert.get("risk",0)
                    if now-last>1800:
                        send(CHAT_ID,"🚨 市場轉弱 → 減倉 / Gold")
                        last_alert["risk"]=now

            for s in SYMBOLS:
                df = get_df(s,"5m")
                if not df: continue

                d = calc(df)
                if not d: continue

                last = last_alert.get(s,0)

                if d["entry_low"] <= d["price"] <= d["entry_high"] and now-last>900:
                    send(CHAT_ID,f"🚀【{s} 入場信號】\n{d['entry_low']}-{d['entry_high']}")
                    last_alert[s]=now

                elif d["price"] < d["entry_high"]*1.03 and now-last>1800:
                    send(CHAT_ID,f"👀【{s} Setup】接近入場區")
                    last_alert[s]=now

            time.sleep(300)

        except:
            time.sleep(10)

threading.Thread(target=loop, daemon=True).start()

# ======================
# KEEP ALIVE（防Render sleep）
# ======================
def keep_alive():
    while True:
        try:
            requests.get("https://www.google.com")
        except:
            pass
        time.sleep(300)

threading.Thread(target=keep_alive, daemon=True).start()

# ======================
# WEBHOOK
# ======================
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text == "/start":
        send(chat_id,"🚀 Bot Ready\n\n/stock /market /gold /long")

    elif text == "/stock":
        for s in SYMBOLS:
            send(chat_id,stock(s))
            time.sleep(1)

    elif text == "/market":
        send(chat_id,market())

    elif text == "/gold":
        send(chat_id,gold())

    elif text == "/long":
        send(chat_id,long_term())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
