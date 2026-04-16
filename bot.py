from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

# ======================
# ENV（Render）
# ======================
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}
msft_last_alert = 0

# ======================
# SEND（加 debug）
# ======================
def send(chat_id, msg):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg[:4000]}
        )
        print("SEND:", r.text)
    except Exception as e:
        print("send error:", e)

# ======================
# DATA
# ======================
def get_data(symbol):
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

    # 支撐阻力
    support = low
    resistance = high

    # 策略
    entry_low = support*1.01
    entry_high = support*1.03
    stop = support*0.97
    target = resistance*0.97

    rr = (target-entry_low)/(entry_low-stop) if (entry_low-stop)!=0 else 0

    return {
        "price":round(price,2),
        "rsi":round(rsi,1),
        "macd":macd,
        "volume":round(vol,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2)
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
    if not NEWS_API:
        return ""

    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data = requests.get(url).json()
        articles = data.get("articles", [])[:2]

        text = "\n📰 新聞\n"
        for a in articles:
            text += f"• {a['title']}\n"

        return text
    except:
        return ""

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

    msg = f"""📊 {symbol}

💰 {d['price']}
🧠 勝率：{w}%

⏱️ {timing_text}

📥 入場：{d['entry_low']} - {d['entry_high']}
🛑 止蝕：{d['stop']}
🎯 目標：{d['target']}

📊 R/R：{d['rr']}
"""

    msg += get_news(symbol)
    return msg

# ======================
# ALERT LOOP
# ======================
def loop():
    global msft_last_alert

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
                    send(CHAT_ID,f"🚀 {s} 入場\n{d['entry_low']} - {d['entry_high']}")
                    last_alert[s]=now

            time.sleep(300)

        except Exception as e:
            print("loop error:", e)

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK（修正）
# ======================
@app.route(f"/webhook", methods=["POST"])
def webhook():
    data=request.get_json(force=True)

    if not data or "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    print("MSG:", text)

    if text=="/check":
        for s in SYMBOLS:
            send(chat_id, format_output(s))

    elif text.startswith("/calc"):
        try:
            x=float(text.split()[1])
            send(chat_id,f"+10% {round(x*1.1,2)}\n+20% {round(x*1.2,2)}")
        except:
            send(chat_id,"❌ 用法 /calc 100")

    elif text.startswith("/position"):
        try:
            _,sym,entry=text.split()
            df=yf.Ticker(sym).history(period="5d", interval="5m")
            price=df["Close"].iloc[-1]
            pnl=(price-float(entry))/float(entry)*100
            send(chat_id,f"{sym} 盈虧 {round(pnl,2)}%")
        except:
            send(chat_id,"❌ 用法 /position TSLA 300")

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
