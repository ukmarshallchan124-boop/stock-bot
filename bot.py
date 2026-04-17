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
# SEND（加 debug）
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
        url = f"https://newsapi.org/v2/everything?q={symbol}&language=en&sortBy=publishedAt&apiKey={NEWS_API}"
        data = requests.get(url).json()

        articles = data.get("articles", [])[:3]

        news_text = f"\n📰【{symbol} 新聞】\n"
        score = 0

        for a in articles:
            title = a["title"]

            if any(w in title.lower() for w in ["surge","growth","beat","strong","record"]):
                sentiment = "🟢 利好"; score+=1
            elif any(w in title.lower() for w in ["fall","risk","cut","warn","drop"]):
                sentiment = "🔴 利淡"; score-=1
            else:
                sentiment = "⚪ 中性"

            news_text += f"• {title}\n{sentiment}\n"

        summary = "🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        news_text += f"\n🧠 新聞總結：{summary}\n"

        return news_text

    except:
        return "\n📰 無新聞\n"

# ======================
# FORMAT
# ======================
def format_output(symbol):
    d = get_data(symbol)
    w = winrate(d)
    t = timing(d)

    timing_text = "🔥 入場區" if t=="ENTRY" else "❌ 唔好追" if t=="HIGH" else "🔄 等回調"
    rsi_text = "🟢 超賣" if d["rsi"]<30 else "🔴 超買" if d["rsi"]>70 else "⚪ 正常"
    trend = "📈 偏強" if d["macd"]=="🟢" else "📉 偏弱"

    summary = "🔥 可以入場" if t=="ENTRY" and w>=70 else "❌ 太高" if t=="HIGH" else "🔄 等"

    msg = f"""📊【{symbol} 波段分析】

💰 價格：{d['price']}
🧠 勝率：{w}%
⏱️ Timing：{timing_text}

{trend}
RSI：{d['rsi']} {rsi_text}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

👉 總結：{summary}
"""

    msg += get_news(symbol)
    return msg

# ======================
# AUTO LOOP
# ======================
def loop():
    global msft_last_alert

    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)
                w=winrate(d)
                t=timing(d)

                now=time.time()
                last=last_alert.get(s,0)

                if w>=80 and t!="ENTRY" and now-last>3600:
                    send(CHAT_ID,f"👀【{s} Setup】勝率{w}%")
                    last_alert[s]=now

                if w>=70 and t=="ENTRY" and now-last>600:
                    send(CHAT_ID,f"🚀【{s} 入場】勝率{w}%")
                    last_alert[s]=now

            time.sleep(300)

        except Exception as e:
            print("❌ loop error:", e)

threading.Thread(target=loop, daemon=True).start()

# ======================
# COMMANDS（🔥 ROOT webhook）
# ======================
@app.route("/", methods=["GET","POST"])
def root():
    data = request.get_json(silent=True)
    print("🔥 webhook:", data)

    if not data:
        return "ok"

    if "message" not in data:
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
        x=float(text.split()[1])
        send(chat_id, f"+10% {round(x*1.1,2)}")

    elif text.startswith("/position"):
        p=text.split()
        df=yf.Ticker(p[1]).history(period="1d")
        price=df["Close"].iloc[-1]
        pnl=(price-float(p[2]))/float(p[2])*100
        send(chat_id, f"盈虧 {round(pnl,2)}%")

    return "ok"

# ======================
# RUN
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
