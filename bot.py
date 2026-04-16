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

SYMBOLS = ["TSLA","NVDA","AMD","MSFT"]

last_alert = {}

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg[:4000]}
        )
    except Exception as e:
        print("send error:", e)

# ======================
# DATA
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
        rs = gain.rolling(14).mean()/loss.rolling(14).mean()
        rsi = float((100-(100/(1+rs))).iloc[-1])

        # MACD
        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_line = ema12-ema26
        signal = macd_line.ewm(span=9).mean()
        macd = "🟢" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴"

        # Volume
        vol = float(df["Volume"].iloc[-1]/df["Volume"].rolling(20).mean().iloc[-1])

        # Support / Resistance
        support = low
        resistance = high

        # Strategy
        entry_low = support*1.01
        entry_high = support*1.03
        stop = support*0.97
        target = resistance*0.97

        rr = (target-entry_low)/(entry_low-stop) if (entry_low-stop)!=0 else 0

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

    except Exception as e:
        print("data error:", e)
        return None

# ======================
# WINRATE AI
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
# FORMAT
# ======================
def format_output(symbol):
    d = get_data(symbol)
    if not d:
        return f"{symbol} ❌ 無數據"

    w = winrate(d)
    t = timing(d)

    timing_text = "🔥 入場區" if t=="ENTRY" else "❌ 唔好追" if t=="HIGH" else "🔄 等回調"
    trend = "📈 偏強" if d["macd"]=="🟢" else "📉 偏弱"

    summary = "🔥 可以入場" if t=="ENTRY" and w>=70 else "❌ 唔好追" if t=="HIGH" else "🔄 等回調"

    msg = f"""📊【{symbol} AI分析】

💰 價格：{d['price']}
🧠 勝率：{w}%

⏱️ Timing：{timing_text}

{trend}
RSI：{d['rsi']}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

🔥 策略
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

🧠 總結：
👉 {summary}
"""
    return msg

# ======================
# AUTO SIGNAL
# ======================
def loop():
    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)
                if not d: continue

                w=winrate(d)
                t=timing(d)

                now=time.time()
                last=last_alert.get(s,0)

                if w>=70 and t=="ENTRY" and now-last>600:
                    send(CHAT_ID,f"🚀【{s} 入場】\n{d['entry_low']} - {d['entry_high']}")
                    last_alert[s]=now

            time.sleep(300)

        except Exception as e:
            print("loop error:", e)

threading.Thread(target=loop, daemon=True).start()

# ======================
# COMMAND
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        if not data or "message" not in data:
            return "ok"

        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text","")

        if text == "/check":
            for s in SYMBOLS:
                send(chat_id, format_output(s))

        elif text.startswith("/calc"):
            x=float(text.split()[1])
            send(chat_id,f"+10% {round(x*1.1,2)}\n+20% {round(x*1.2,2)}\n-10% {round(x*0.9,2)}")

        elif text.startswith("/position"):
            _,sym,entry=text.split()
            df=yf.Ticker(sym).history(period="5d", interval="5m")
            price=df["Close"].iloc[-1]
            pnl=(price-float(entry))/float(entry)*100
            send(chat_id,f"{sym} 盈虧：{round(pnl,2)}%")

        return "ok"

    except Exception as e:
        print("webhook error:", e)
        return "ok"

@app.route("/")
def home():
    return "running"
