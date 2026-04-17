from flask import Flask, request
import requests, os
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")

SYMBOLS = ["TSLA", "NVDA", "AMD"]

# ======================
# 📩 SEND
# ======================
def send(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=5
        )
    except:
        pass

# ======================
# 📊 DATA（V2）
# ======================
def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="5m")

        if df.empty:
            return None

        price = float(df["Close"].iloc[-1])
        high = float(df["High"].max())
        low = float(df["Low"].min())

        # RSI
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        rs = gain.rolling(14).mean() / loss.rolling(14).mean()
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        # MACD
        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9).mean()

        macd = "🟢 上升" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴 下跌"

        return {
            "price": round(price, 2),
            "rsi": round(rsi, 1),
            "macd": macd,
            "support": round(low, 2),
            "resistance": round(high, 2)
        }

    except:
        return None

# ======================
# 📊 FORMAT（V2）
# ======================
def format_output(symbol):
    d = get_data(symbol)

    if not d:
        return f"⚠️ {symbol} 暫時無數據"

    # RSI 狀態
    if d["rsi"] < 30:
        rsi_text = "🟢 超賣"
    elif d["rsi"] > 70:
        rsi_text = "🔴 超買"
    else:
        rsi_text = "⚪ 正常"

    # 簡單策略（V2）
    entry_low = round(d["support"] * 1.01, 2)
    entry_high = round(d["support"] * 1.03, 2)
    stop = round(d["support"] * 0.97, 2)
    target = d["resistance"]

    return f"""📊【{symbol}】

💰 價格：{d['price']}

RSI：{d['rsi']} {rsi_text}
MACD：{d['macd']}

📉 支撐：{d['support']}
📈 阻力：{d['resistance']}

💰 策略
👉 入場：{entry_low} - {entry_high}
👉 止蝕：{stop}
👉 目標：{target}
"""

# ======================
# 🌐 WEBHOOK
# ======================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "")

    if text == "/start":
        send(chat_id, """🚀 V2 Trading Bot

📊 /check → 即時分析
""")

    elif text == "/check":
        for s in SYMBOLS:
            send(chat_id, format_output(s))

    return "ok"

@app.route("/")
def home():
    return "running"

# ======================
# 🚀 RUN
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
