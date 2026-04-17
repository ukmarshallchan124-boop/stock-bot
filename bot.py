from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

# ======================
# ENV
# ======================
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}
msft_last_alert = 0

# ======================
# SEND（加debug）
# ======================
def send(chat_id, msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        res = requests.post(url, json={
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
    df = yf.Ticker(symbol).history(period="5d", interval="5m")

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
    macd_line = ema12-ema26
    signal = macd_line.ewm(span=9).mean()

    macd = "🟢" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴"

    vol = float(df["Volume"].iloc[-1]/df["Volume"].rolling(20).mean().iloc[-1])

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02
    rr = (target-entry_low)/(entry_low-stop)

    momentum = (price - df["Close"].iloc[-20]) / df["Close"].iloc[-20] * 100

    return {
        "price":round(price,2),
        "rsi":round(rsi,1),
        "macd":macd,
        "volume":round(vol,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2),
        "momentum":round(momentum,2)
    }

# ======================
# WINRATE
# ======================
def winrate(d):
    score=50
    if d["rsi"]<45: score+=10
    if d["macd"]=="🟢": score+=15
    if d["volume"]>1.2: score+=10
    if d["rr"]>2: score+=15
    if d["momentum"]>0: score+=10
    return min(95,max(10,score))

# ======================
# TIMING
# ======================
def timing(d):
    p=d["price"]
    if d["entry_low"]<=p<=d["entry_high"]:
        return "ENTRY"
    elif p>d["entry_high"]:
        return "HIGH"
    else:
        return "WAIT"

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data = requests.get(url).json()
        articles = data.get("articles", [])[:3]

        text = f"\n📰 {symbol} News\n"
        for a in articles:
            text += f"• {a['title']}\n"

        return text
    except:
        return "\n📰 No news\n"

# ======================
# FORMAT
# ======================
def format_output(symbol):
    d = get_data(symbol)
    w = winrate(d)
    t = timing(d)

    msg = f"""
📊 {symbol}

💰 價格：{d['price']}
🧠 勝率：{w}%

📉 入場：{d['entry_low']} - {d['entry_high']}
🛑 止蝕：{d['stop']}
🎯 目標：{d['target']}

RSI：{d['rsi']}
MACD：{d['macd']}

📊 R/R：{d['rr']}
"""

    msg += get_news(symbol)
    return msg

# ======================
# AUTO SIGNAL
# ======================
def loop():
    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)
                w=winrate(d)
                t=timing(d)

                if w>=70 and t=="ENTRY":
                    send(CHAT_ID,f"🚀 {s} 入場機會\n勝率：{w}%")

            time.sleep(300)
        except Exception as e:
            print("❌ loop error:", e)

threading.Thread(target=loop, daemon=True).start()

# ======================
# COMMAND
# ======================
def calc(x):
    x=float(x)
    return f"+10% {round(x*1.1,2)}\n-10% {round(x*0.9,2)}"

def position(symbol, entry):
    df=yf.Ticker(symbol).history(period="1d")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"{symbol} 盈虧：{round(pnl,2)}%"

# ======================
# WEBHOOK（重點修正）
# ======================
@app.route("/webhook", methods=["POST"])
@app.route("/webhook/", methods=["POST"])
def webhook():
    data = request.get_json()

    print("🔥 webhook:", data)

    if not data or "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    print("👉 text:", text)

    if text == "/start":
        send(chat_id, "✅ Bot 已啟動")

    elif text == "/check":
        for s in SYMBOLS:
            send(chat_id, format_output(s))

    elif text.startswith("/calc"):
        send(chat_id, calc(text.split()[1]))

    elif text.startswith("/position"):
        p=text.split()
        send(chat_id, position(p[1].upper(), float(p[2])))

    return "ok"

# ======================
# ROOT
# ======================
@app.route("/")
def home():
    return "running"

# ======================
# RUN（Render fix）
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
