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
# CACHE（防爆 API）
# ======================
cache = {}
CACHE_TTL = 300  # 5分鐘

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
# CALC
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

        if macd_line.iloc[-1] > signal.iloc[-1] and macd_line.iloc[-2] <= signal.iloc[-2]:
            macd = "🟡 黃金交叉"
        elif macd_line.iloc[-1] < signal.iloc[-1] and macd_line.iloc[-2] >= signal.iloc[-2]:
            macd = "🔴 死亡交叉"
        elif macd_line.iloc[-1] > signal.iloc[-1]:
            macd = "🟢 多頭"
        else:
            macd = "⚪ 弱"

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
# STOCK
# ======================
def stock(symbol):
    try:
        df5 = get_df(symbol,"5m")
        df1h = get_df(symbol,"60m")

        if df5 is None or df1h is None:
            return f"{symbol} 數據錯誤"

        d5 = calc(df5)
        d1 = calc(df1h)

        if not d5 or not d1:
            return f"{symbol} 計算錯誤"

        if d5["entry_low"] <= d5["price"] <= d5["entry_high"]:
            timing = "🟢 入場區"
            summary = "👉 可以分批入"
        elif d5["price"] > d5["entry_high"]:
            timing = "❌ 唔好追"
            summary = "👉 現價太高"
        else:
            timing = "⏳ 等回調"
            summary = "👉 未到位"

        trend = "📈 偏強" if "🟢" in d1["macd"] or "🟡" in d1["macd"] else "📉 偏弱"

        return f"""
📊【{symbol} 波段分析】

💰 價格：{d5['price']}

⏱️ 短線（5m）：{timing}
📈 中線（1h）：{trend}

━━━━━━━━━━━━━━

RSI：{d5['rsi']}
MACD：{d5['macd']}

━━━━━━━━━━━━━━

🎯 入場區：{d5['entry_low']} - {d5['entry_high']}
🛑 止蝕：{d5['stop']}
🎯 目標：{d5['target']}

📊 R/R：{d5['rr']}

━━━━━━━━━━━━━━

🧾 AI結論：
{summary}
"""
    except:
        return f"{symbol} error"

# ======================
# MARKET
# ======================
def market():
    strong, weak = [], []

    for s in SYMBOLS:
        df = get_df(s,"60m")
        if not df:
            continue
        d = calc(df)
        if not d:
            continue

        if "🟢" in d["macd"] or "🟡" in d["macd"]:
            strong.append(s)
        else:
            weak.append(s)

    return f"""
🌍【市場狀態】

🟢 強勢：{", ".join(strong) or "無"}
❌ 弱勢：{", ".join(weak) or "無"}

━━━━━━━━━━━━━━

🧠 行動：

👉 🟢 做強勢股（順勢）
👉 ❌ 避弱勢股
👉 ⏳ 等回調入場
"""

# ======================
# GOLD
# ======================
def gold():
    return """
🥇【Gold 波段 / 防守分析】

👉 市場轉弱先加  
👉 對沖科技股  
👉 ❌ 唔好高追
"""

# ======================
# LONG
# ======================
def long_term():
    return """
📈【長線投資策略】

S&P500 → DCA  
MSFT → 核心  
VWRA → 分散  
Gold → 對沖
"""

# ======================
# ALERT LOOP
# ======================
def loop():
    while True:
        try:
            now = time.time()

            spy = get_df("SPY","60m")
            if spy:
                d = calc(spy)
                if d and CHAT_ID:
                    last = last_alert.get("market",0)
                    if "🔴" in d["macd"] and now-last>1800:
                        send(CHAT_ID,"🚨 市場轉弱 → 減倉 / Gold")
                        last_alert["market"]=now

            for s in SYMBOLS:
                df = get_df(s,"5m")
                if not df:
                    continue
                d = calc(df)
                if not d:
                    continue

                last = last_alert.get(s,0)

                if CHAT_ID and d["entry_low"] <= d["price"] <= d["entry_high"] and now-last>600:
                    send(CHAT_ID,f"🚀 {s} 入場區")
                    last_alert[s]=now

                elif CHAT_ID and d["price"] < d["entry_high"]*1.05 and now-last>3600:
                    send(CHAT_ID,f"👀 {s} Setup")
                    last_alert[s]=now

            time.sleep(600)

        except:
            time.sleep(600)

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not data or "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text.startswith("/check"):
        send(chat_id,"✅ Bot working")

    elif text.startswith("/stock"):
        send(chat_id,"📊 分析中...")
        for s in SYMBOLS:
            send(chat_id, stock(s))
            time.sleep(1)

    elif text.startswith("/market"):
        send(chat_id,market())

    elif text.startswith("/gold"):
        send(chat_id,gold())

    elif text.startswith("/long"):
        send(chat_id,long_term())

    else:
        send(chat_id,"/stock /market /gold /long")

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
