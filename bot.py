from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}
msft_last_alert = 0

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": msg})
    except:
        pass

# ======================
# DATA（修正 float64 問題）
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
# 📰 NEWS（Yahoo + Reuters via NewsAPI）
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
# 🎯 FORMAT（完整顯示）
# ======================
def format_output(symbol):
    d = get_data(symbol)
    w = winrate(d)
    t = timing(d)

    timing_text = "🔥 入場區" if t=="ENTRY" else "❌ 唔好追" if t=="HIGH" else "🔄 等回調"
    rsi_text = "🟢 超賣" if d["rsi"]<30 else "🔴 超買" if d["rsi"]>70 else "⚪ 正常"
    trend = "📈 偏強" if d["macd"]=="🟢" else "📉 偏弱"

    summary = "🔥 可以考慮入場" if t=="ENTRY" and w>=70 else "❌ 太高唔好追" if t=="HIGH" else "🔄 等回調先"

    msg = f"""📊【{symbol} 波段分析】

💰 價格：{d['price']}

🧠 成功率：{w}%
⏱️ Timing：{timing_text}

{trend}
RSI：{d['rsi']} {rsi_text}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

💰 策略（重點🔥）
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

🧠 總結：
👉 {summary}
"""

    msg += get_news(symbol)
    return msg

# ======================
# 🔔 SIGNAL LOOP
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
                    send(CHAT_ID,f"👀【{s} Setup】\n勝率：{w}%\n等回調：{d['entry_low']} - {d['entry_high']}")
                    last_alert[s]=now

                if w>=70 and t=="ENTRY" and now-last>600:
                    send(CHAT_ID,f"🚀【{s} 入場】\n勝率：{w}%\n入場：{d['entry_low']} - {d['entry_high']}")
                    last_alert[s]=now

            # MSFT DCA
            df=yf.Ticker("MSFT").history(period="6mo", interval="1d")
            price=df["Close"].iloc[-1]
            m3=(price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

            if m3<-5 and time.time()-msft_last_alert>86400:
                send(CHAT_ID,f"💰【MSFT 加倉】價格：{round(price,2)} 回調：{round(m3,1)}%")
                msft_last_alert=time.time()

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# CALC / POSITION
# ======================
def calc_price(x):
    x=float(x)
    return f"+10% {round(x*1.1,2)}\n+20% {round(x*1.2,2)}\n-10% {round(x*0.9,2)}"

def position(symbol, entry):
    df=yf.Ticker(symbol).history(period="5d", interval="5m")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"{symbol} 盈虧：{round(pnl,2)}%"

# ======================
# WEBHOOK
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
            send(chat_id, format_output(s))

    elif text=="/msft":
        send(chat_id, "💰 MSFT 請等自動 alert")

    elif text.startswith("/calc"):
        send(chat_id, calc_price(text.split()[1]))

    elif text.startswith("/position"):
        p=text.split()
        send(chat_id, position(p[1].upper(), float(p[2])))

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
