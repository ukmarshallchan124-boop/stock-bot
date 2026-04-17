from flask import Flask, request
import requests, os
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")

SYMBOLS = ["TSLA", "NVDA", "AMD"]

# ======================
# 📩 SEND MESSAGE
# ======================
def send(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text
        }, timeout=5)
    except:
        pass

# ======================
# 📊 GET DATA（穩定版）
# ======================
def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="2d", interval="5m")

        if df.empty:
            return None

        price = float(df["Close"].iloc[-1])

        # RSI
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        rs = gain.rolling(14).mean() / loss.rolling(14).mean()
        rsi = 100 - (100 / (1 + rs))
        rsi_val = float(rsi.iloc[-1])

        # MACD
        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9).mean()

        macd = "🟢 上升" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴 下跌"

        return {
            "price": round(price, 2),
            "rsi": round(rsi_val, 1),
            "macd": macd
        }

    except:
        return None

# ======================
# 📊 FORMAT（靚版）
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

    return f"""📊【{symbol}】

💰 價格：{d['price']}

RSI：{d['rsi']} {rsi_text}
MACD：{d['macd']}
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
        send(chat_id, """🚀 V1 Trading Bot

📊 /check → 查看市場
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
