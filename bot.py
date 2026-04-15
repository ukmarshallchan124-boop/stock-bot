from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

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
# 📊 DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")

    price = df["Close"].iloc[-1]
    prev = df["Close"].iloc[0]
    change = (price-prev)/prev*100

    high = df["High"].max()
    low = df["Low"].min()

    # ===== RSI =====
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean() / loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))

    # ===== MACD =====
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()

    # ===== VWAP =====
    vwap = (df["Close"]*df["Volume"]).cumsum()/df["Volume"].cumsum()

    # ===== Volume =====
    vol_ratio = df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1]

    # ===== 回調 =====
    pullback = (price-high)/high*100

    # ===== timing（1m 3m 6m）
    m1 = (df["Close"].iloc[-1] - df["Close"].iloc[-12]) / df["Close"].iloc[-12] * 100
    m3 = (df["Close"].iloc[-1] - df["Close"].iloc[-36]) / df["Close"].iloc[-36] * 100
    m6 = (df["Close"].iloc[-1] - df["Close"].iloc[-72]) / df["Close"].iloc[-72] * 100

    # ===== AI =====
    prob = 50
    if rsi.iloc[-1] < 35: prob += 15
    if macd.iloc[-1] > signal.iloc[-1]: prob += 15
    if price > vwap.iloc[-1]: prob += 10
    if vol_ratio > 1.2: prob += 10
    prob = max(5,min(95,prob))

    # ===== strategy =====
    entry = low * 1.01
    stop = low * 0.97
    target = high * 1.02
    rr = (target-entry)/(entry-stop)

    return {
        "price":round(price,2),
        "change":round(change,2),
        "rsi":round(rsi.iloc[-1],1),
        "macd":"🟢黃金交叉" if macd.iloc[-1]>signal.iloc[-1] else "🔴死亡交叉",
        "support":round(low,2),
        "resistance":round(high,2),
        "prob":round(prob,0),
        "vwap":round(vwap.iloc[-1],2),
        "volume":"🚀放量" if vol_ratio>1.3 else "⚠️縮量",
        "pullback":round(pullback,2),
        "entry":round(entry,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2),
        "m1":round(m1,2),
        "m3":round(m3,2),
        "m6":round(m6,2)
    }

# ======================
# 📰 NEWS
# ======================
def get_news(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data=requests.get(url).json()

        text=f"\n📰【{symbol} 新聞】\n"

        for a in data.get("articles",[])[:3]:
            t=a["title"]

            if "growth" in t.lower(): senti="🟢利好"
            elif "fall" in t.lower(): senti="🔴利淡"
            else: senti="⚪中性"

            text+=f"• {t}\n{senti}\n"

        return text
    except:
        return ""

# ======================
# 📊 FORMAT（Ultimate）
# ======================
def build(symbol):
    d=get_data(symbol)

    timing=""
    if d["m1"]<0 and d["m3"]<0 and d["m6"]>0:
        timing="🔥 回調中（可入場）"
    elif d["m1"]>0 and d["m3"]>0 and d["m6"]>5:
        timing="⚠️ 過熱（唔追）"
    else:
        timing="⚪ 正常"

    advice="🔥高勝率" if d["prob"]>70 and d["rr"]>2 else "⚪觀望"

    msg=f"""📊【{symbol} Ultimate 分析】

💰 價格：{d['price']}
📈 24H：{d['change']}%

⏱️ 動能
1m：{d['m1']}%
3m：{d['m3']}%
6m：{d['m6']}%
👉 {timing}

RSI：{d['rsi']}
MACD：{d['macd']}

📊 VWAP：{d['vwap']}
📊 成交量：{d['volume']}
📉 回調：{d['pullback']}%

🧠 AI：{d['prob']}%

📉 支撐：{d['support']}
📈 阻力：{d['resistance']}

💰 策略
入場：{d['entry']}
止蝕：{d['stop']}
目標：{d['target']}

📊 R/R：{d['rr']}
📊 評級：{advice}
"""

    msg+=get_news(symbol)
    return msg

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

    if text=="/start":
        send(chat_id,"🚀 Ultimate Trading Bot\n\n/check 查看分析")

    elif text.startswith("/check"):
        for s in SYMBOLS:
            send(chat_id,build(s))

    return "ok"

@app.route("/")
def home():
    return "running"

# ======================
# ⏰ AUTO PUSH（升級）
# ======================
def auto_push():
    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)

                if d["prob"]>70 and d["rr"]>2:
                    send(CHAT_ID,f"""🚀【{s} 高勝率入場】

入場：{d['entry']}
止蝕：{d['stop']}
目標：{d['target']}

R/R：{d['rr']}
AI：{d['prob']}%
""")

            time.sleep(7200)

            summary="📊【市場簡報】\n"
            for s in SYMBOLS:
                d=get_data(s)
                summary+=f"{s} {d['price']} ({d['change']}%)\n"

            send(CHAT_ID,summary)

        except:
            pass

threading.Thread(target=auto_push,daemon=True).start()

# ======================
# RUN
# ======================
if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
