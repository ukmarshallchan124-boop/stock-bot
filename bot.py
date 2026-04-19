from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

# ======================
# ENV
# ======================
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        res = requests.post(f"{URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": msg
        })
        print("📤 send:", res.text)
    except Exception as e:
        print("❌ send error:", e)

# ======================
# DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d")

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

    if macd_line.iloc[-1] > signal.iloc[-1]:
        macd = "🟡 黃金交叉"
    else:
        macd = "🔴 死亡交叉"

    entry_low = low * 1.01
    entry_high = low * 1.03
    stop = low * 0.97
    target = high * 1.02

    rr = (target-entry_low)/(entry_low-stop)

    return {
        "price": round(price,2),
        "rsi": round(rsi,1),
        "macd": macd,
        "entry_low": round(entry_low,2),
        "entry_high": round(entry_high,2),
        "stop": round(stop,2),
        "target": round(target,2),
        "rr": round(rr,2)
    }

# ======================
# FORMAT
# ======================
def format_output(symbol):
    d = get_data(symbol)

    timing = "🟢 入場區" if d["entry_low"] <= d["price"] <= d["entry_high"] else "❌ 唔好追"

    return f"""
📊【{symbol} 波段分析】

💰 價格: {d['price']}
⏱️ Timing: {timing}

📉 RSI: {d['rsi']}
📊 MACD: {d['macd']}

👉 入場: {d['entry_low']} - {d['entry_high']}
👉 止蝕: {d['stop']}
👉 目標: {d['target']}

📊 R/R: {d['rr']}
"""

# ======================
# GOLD
# ======================
def gold_analysis():
    d = get_data("IAU")

    return f"""
🥇【Gold ETF】

💰 價格: {d['price']}
⏱️ Timing: 🟢 可分批買入

👉 入場: {d['entry_low']} - {d['entry_high']}
👉 止蝕: {d['stop']}
👉 目標: {d['target']}

📊 R/R: {d['rr']}

🧠 策略:
👉 分批買入
👉 唔好追高
👉 長線對沖
"""

# ======================
# LONG TERM
# ======================
def long_term():
    return f"""
📈【長線投資】

👉 S&P500: 每月 DCA
👉 VWRA: 全球 ETF
👉 MSFT: 等回調 5-10%

🥇 Gold:
👉 可作對沖
"""

# ======================
# LOOP（可用）
# ======================
def loop():
    while True:
        try:
            print("🔁 running loop...")
            time.sleep(300)
        except Exception as e:
            print("❌ loop error:", e)

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK（🔥重點修正）
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    print("🔥 收到:", data)

    if not data or "message" not in data:
        return "ok"

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text","")

    print("👉 text:", text)

    if text.startswith("/check"):
        send(chat_id, "✅ Bot working")

    elif text.startswith("/stock"):
        for s in SYMBOLS:
            send(chat_id, format_output(s))

    elif text.startswith("/gold"):
        send(chat_id, gold_analysis())

    elif text.startswith("/long"):
        send(chat_id, long_term())

    elif text.startswith("/position"):
        try:
            parts = text.split()
            entry = float(parts[2])
            stop = float(parts[3])

            risk = entry - stop
            size = 100 / risk

            send(chat_id, f"📊 倉位:\n股數: {round(size,2)}\n風險: £100")
        except:
            send(chat_id, "❌ 用法: /position TSLA 100 90")

    elif text.startswith("/calc"):
        try:
            result = eval(text.replace("/calc",""))
            send(chat_id, f"🧮 結果: {result}")
        except:
            send(chat_id, "❌ /calc 100+200")

    else:
        send(chat_id, "❓ 未知指令")

    return "ok"

# ======================
# ROOT
# ======================
@app.route("/")
def home():
    return "running"

# ======================
# RUN
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
