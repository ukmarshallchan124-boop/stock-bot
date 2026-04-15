from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["TSLA","NVDA","AMD"]

# 防重複通知
last_alert = {}
cooldown = 3600   # 1小時

# ======================
# 📩 SEND
# ======================
def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ======================
# 📊 DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")

    price = df["Close"].iloc[-1]
    prev = df["Close"].iloc[0]
    change = (price-prev)/prev*100

    high = df["High"].max()
    low = df["Low"].min()

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))

    # MACD
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()

    # volume
    vol_ratio = df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1]

    # pullback
    pullback = (price-high)/high*100

    # entry zone
    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02

    rr = (target-entry_low)/(entry_low-stop)

    return {
        "price":round(price,2),
        "change":round(change,2),
        "rsi":round(rsi.iloc[-1],1),
        "macd":"🟢黃金交叉" if macd.iloc[-1]>signal.iloc[-1] else "🔴死亡交叉",
        "volume":vol_ratio,
        "pullback":pullback,
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2)
    }

# ======================
# 🧠 勝率
# ======================
def winrate(d):
    score = 50
    if d["rsi"] < 40: score += 10
    if "🟢" in d["macd"]: score += 15
    if d["volume"] > 1.2: score += 10
    if -6 < d["pullback"] < -2: score += 15
    if d["rr"] > 2: score += 15
    return max(10,min(95,score))

# ======================
# 🎯 Timing
# ======================
def timing(d):
    p = d["price"]
    if d["entry_low"] <= p <= d["entry_high"]:
        return "ENTRY"
    elif p > d["entry_high"]:
        return "HIGH"
    else:
        return "WAIT"

# ======================
# 🚨 SIGNAL SYSTEM
# ======================
def check_signals():
    while True:
        try:
            for s in SYMBOLS:
                d = get_data(s)
                w = winrate(d)
                t = timing(d)

                now = time.time()
                last = last_alert.get(s, 0)

                # ===== Setup Signal =====
                if w >= 75 and t != "ENTRY":
                    if now - last > cooldown:
                        send(f"""👀【{s} 高勝率 Setup】

🧠 成功率：{w}%
📊 R/R：{d['rr']}

👉 等回調至：
{d['entry_low']} - {d['entry_high']}
""")
                        last_alert[s] = now

                # ===== Entry Signal =====
                if w >= 70 and t == "ENTRY":
                    if now - last > 600:  # entry cooldown短啲
                        send(f"""🚀【{s} 入場訊號】

🧠 成功率：{w}%
⏱️ Timing：🔥 完美

入場：{d['entry_low']} - {d['entry_high']}
止蝕：{d['stop']}
目標：{d['target']}

📊 R/R：{d['rr']}
""")
                        last_alert[s] = now

            time.sleep(300)

        except:
            pass

threading.Thread(target=check_signals, daemon=True).start()

# ======================
# 📊 詳細分析
# ======================
def build(symbol):
    d = get_data(symbol)
    w = winrate(d)
    t = timing(d)

    timing_text = "🔥 入場區" if t=="ENTRY" else "❌ 唔好追" if t=="HIGH" else "🔄 等回調"

    return f"""📊【{symbol} Ultimate v8】

💰 價格：{d['price']}
📈 24H：{d['change']}%

🧠 成功率：{w}%
⏱️ Timing：{timing_text}

RSI：{d['rsi']}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

💰 策略
入場：{d['entry_low']} - {d['entry_high']}
止蝕：{d['stop']}
目標：{d['target']}

📊 R/R：{d['rr']}
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
    text = data["message"].get("text","")

    if text == "/check":
        for s in SYMBOLS:
            send(build(s))

    if text == "/start":
        send("""🚀 Ultimate v8 Bot

📊 /check → 全分析

🧠 高勝率 Setup
🚀 入場 Signal

✔ 自動等位
✔ 自動入場提示
✔ 唔追高
""")

    return "ok"

@app.route("/")
def home():
    return "running"

# ======================
# RUN
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
