from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

URL = f"https://api.telegram.org/bot{TOKEN}"
SWING_STOCKS = ["TSLA","NVDA","AMD"]

last_alert = {}

# ======================
# SEND
# ======================
def send(chat_id, text):
    requests.post(f"{URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text[:4000]
    })

# ======================
# MARKET
# ======================
def market():
    try:
        df = yf.Ticker("SPY").history(period="3mo")
        price = df["Close"].iloc[-1]
        ma50 = df["Close"].rolling(50).mean().iloc[-1]
        return "📈 市場偏強（可等回調買）" if price > ma50 else "📉 市場轉弱（減少操作）"
    except:
        return ""

# ======================
# DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")
    if df.empty: return None

    price = float(df["Close"].iloc[-1])
    high = float(df["High"].max())
    low = float(df["Low"].min())

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
        macd = "🟢 多頭趨勢"
    else:
        macd = "⚪ 空頭趨勢"

    momentum = (price - df["Close"].iloc[-20]) / df["Close"].iloc[-20] * 100

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02
    rr = (target-entry_low)/(entry_low-stop)

    return {
        "price":round(price,2),
        "rsi":round(rsi,1),
        "macd":macd,
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2),
        "momentum":round(momentum,2)
    }

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data = requests.get(url).json()
        articles = data.get("articles", [])[:2]

        text = f"\n📰【{symbol} 新聞】\n"
        for a in articles:
            text += f"• {a['title']}\n"
        return text
    except:
        return "\n📰 無新聞\n"

# ======================
# FORMAT
# ======================
def format_swing(symbol):
    d = get_data(symbol)
    if not d: return "無數據"

    news = get_news(symbol)

    if d["entry_low"] <= d["price"] <= d["entry_high"]:
        timing="🔥 入場區"
        action="✅ 可考慮入場"
    elif d["price"] > d["entry_high"]:
        timing="❌ 唔好追"
        action="❌ 等回調"
    else:
        timing="⏳ 等回調"
        action="👀 等回調"

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
⏱️ Timing：{timing}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

👉 {action}

{news}
"""

# ======================
# LOOP（自動推）
# ======================
def loop():
    while True:
        try:
            for s in SWING_STOCKS:
                d = get_data(s)
                if not d: continue

                now = time.time()
                last = last_alert.get(s,0)

                if d["price"] > d["entry_high"] and now-last > 3600:
                    send(CHAT_ID,f"👀【{s} Setup】等回調 {d['entry_low']} - {d['entry_high']}")

                if d["entry_low"] <= d["price"] <= d["entry_high"] and now-last > 600:
                    send(CHAT_ID,f"🚀【{s} 入場】{d['entry_low']} - {d['entry_high']}")

                last_alert[s]=now

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK
# ======================
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()

    if not data or "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text == "/check":
        for s in SWING_STOCKS:
            send(chat_id, format_swing(s))

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
