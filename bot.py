from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["TSLA","NVDA","AMD"]

# ======================
# 📩 SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": msg})
    except:
        pass

# ======================
# 📊 DATA（V8 原版）
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")

    price = df["Close"].iloc[-1]
    prev = df["Close"].iloc[0]
    change = (price-prev)/prev*100

    high = df["High"].max()
    low = df["Low"].min()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean() / loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))

    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()

    vol_ratio = df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1]

    pullback = (price-high)/high*100

    entry_low = low * 1.01
    entry_high = low * 1.03
    stop = low * 0.97
    target = high * 1.02
    rr = (target-entry_low)/(entry_low-stop)

    return {
        "price":round(price,2),
        "change":round(change,2),
        "rsi":round(rsi.iloc[-1],1),
        "macd":"🟢黃金交叉" if macd.iloc[-1]>signal.iloc[-1] else "🔴死亡交叉",
        "volume":"🚀放量" if vol_ratio>1.3 else "⚠️縮量",
        "pullback":round(pullback,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2)
    }

# ======================
# 🧠 勝率（V8）
# ======================
def calc_winrate(d):
    score = 50
    if d["rsi"] < 40: score += 10
    if "🟢" in d["macd"]: score += 15
    if "🚀" in d["volume"]: score += 10
    if -6 < d["pullback"] < -2: score += 15
    if d["rr"] > 2: score += 15
    return max(10,min(95,score))

# ======================
# 🎯 Timing（V8）
# ======================
def entry_logic(d):
    p = d["price"]
    if d["entry_low"] <= p <= d["entry_high"]:
        return "🔥 入場區內"
    elif p > d["entry_high"]:
        return "❌ 唔好追"
    else:
        return "🔄 等回調"

# ======================
# 📊 BUILD（V8）
# ======================
def build(symbol):
    d=get_data(symbol)
    winrate=calc_winrate(d)
    timing=entry_logic(d)

    return f"""📊【{symbol}】

💰 價格：{d['price']}
📈 24H：{d['change']}%

🧠 成功率：{winrate}%
⏱️ Timing：{timing}

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
# 💰 MSFT DCA（查詢）
# ======================
def msft_dca():
    df = yf.Ticker("MSFT").history(period="6mo", interval="1d")
    price = df["Close"].iloc[-1]

    m1 = (price - df["Close"].iloc[-30]) / df["Close"].iloc[-30] * 100
    m3 = (price - df["Close"].iloc[-90]) / df["Close"].iloc[-90] * 100
    m6 = (price - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))
    rsi_val = rsi.iloc[-1]

    if rsi_val < 50:
        status = "🟢 可加倉"
        advice = "👉 本月可以加"
    elif rsi_val < 65:
        status = "🟡 正常DCA"
        advice = "👉 分批"
    else:
        status = "🔴 暫停"
        advice = "👉 等回調"

    return f"""💰【Microsoft DCA】

💰 價格：{round(price,2)}

📊 回調
1M：{round(m1,1)}%
3M：{round(m3,1)}%
6M：{round(m6,1)}%

RSI：{round(rsi_val,1)}

📊 狀態：{status}
{advice}
"""

# ======================
# 🔔 MSFT AUTO ALERT
# ======================
msft_last_alert = 0
msft_last_state = ""

def msft_alert():
    global msft_last_alert, msft_last_state

    df = yf.Ticker("MSFT").history(period="6mo", interval="1d")
    price = df["Close"].iloc[-1]

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))
    rsi_val = rsi.iloc[-1]

    m3 = (price - df["Close"].iloc[-90]) / df["Close"].iloc[-90] * 100

    if rsi_val < 45 or m3 < -5:
        state = "BUY"
    else:
        state = "WAIT"

    now = time.time()

    if state == "BUY":
        if now - msft_last_alert > 86400 or msft_last_state != state:
            send(CHAT_ID, f"""💰【MSFT 加倉機會】

🟢 可加倉
💰 價格：{round(price,2)}

📊 3M回調：{round(m3,1)}%
RSI：{round(rsi_val,1)}

👉 建議：可以加倉（DCA）
""")
            msft_last_alert = now
            msft_last_state = state

# ======================
# 🔁 LOOP（V8 + MSFT）
# ======================
def loop():
    while True:
        try:
            msft_alert()  # 🔥 新增

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# 🌐 WEBHOOK
# ======================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data=request.get_json()

    if "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text=="/check":
        for s in SYMBOLS:
            send(chat_id,build(s))

    elif text.lower()=="/msft":
        send(chat_id,msft_dca())

    elif text=="/start":
        send(chat_id,"🚀 Bot Ready\n/check 波段\n/msft 長線")

    return "ok"

@app.route("/")
def home():
    return "running"

# ======================
# RUN
# ======================
if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
