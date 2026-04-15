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

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean() / loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))

    # MACD
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()

    # VWAP
    vwap = (df["Close"]*df["Volume"]).cumsum()/df["Volume"].cumsum()

    # Volume
    vol_ratio = df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1]

    # Pullback
    pullback = (price-high)/high*100

    # Timing
    m1 = (price - df["Close"].iloc[-12]) / df["Close"].iloc[-12] * 100
    m3 = (price - df["Close"].iloc[-36]) / df["Close"].iloc[-36] * 100
    m6 = (price - df["Close"].iloc[-72]) / df["Close"].iloc[-72] * 100

    # Strategy
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
        "support":round(low,2),
        "resistance":round(high,2),
        "vwap":round(vwap.iloc[-1],2),
        "volume":"🚀放量" if vol_ratio>1.3 else "⚠️縮量",
        "pullback":round(pullback,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2),
        "m1":round(m1,2),
        "m3":round(m3,2),
        "m6":round(m6,2)
    }

# ======================
# 🧠 勝率
# ======================
def calc_winrate(d):
    score = 50
    if d["rsi"] < 40: score += 10
    if "🟢" in d["macd"]: score += 15
    if d["price"] > d["vwap"]: score += 10
    if "🚀" in d["volume"]: score += 10
    if -6 < d["pullback"] < -2: score += 15
    if d["rr"] > 2: score += 15
    return max(10,min(95,score))

# ======================
# 🎯 Timing
# ======================
def entry_logic(d):
    p = d["price"]

    if d["entry_low"] <= p <= d["entry_high"]:
        return "🔥 入場區內（可考慮買）"

    elif p > d["entry_high"]:
        dist = (p - d["entry_high"]) / d["entry_high"] * 100
        return "⚠️ 偏高（小心追）" if dist < 2 else "❌ 唔好追"

    elif p < d["entry_low"]:
        return "🔄 等回調"

    if p > d["resistance"]:
        return "🚀 突破阻力（可追）"

    return "⚪ 正常"

# ======================
# 📰 NEWS
# ======================
def get_news(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data=requests.get(url).json()

        text=f"\n📰【{symbol} 新聞】\n"

        pos, neg = 0,0

        for a in data.get("articles",[])[:3]:
            t=a["title"]

            if any(x in t.lower() for x in ["growth","beat","surge"]):
                senti="🟢利好"; pos+=1
            elif any(x in t.lower() for x in ["fall","risk","drop"]):
                senti="🔴利淡"; neg+=1
            else:
                senti="⚪中性"

            text+=f"• {t}\n{senti}\n"

        # 總結
        if pos>neg:
            text+="👉 新聞總結：🟢 偏利好\n"
        elif neg>pos:
            text+="👉 新聞總結：🔴 偏利淡\n"
        else:
            text+="👉 新聞總結：⚪ 中性\n"

        return text
    except:
        return "\n📰 無新聞\n"

# ======================
# 📊 FORMAT
# ======================
def build(symbol):
    d=get_data(symbol)
    winrate=calc_winrate(d)
    timing=entry_logic(d)

    advice="🔥 可入場" if winrate>=70 and d["rr"]>2 else "⚪ 觀望"

    msg=f"""📊【{symbol} Ultimate v7】

💰 價格：{d['price']}
📈 24H：{d['change']}%

⏱️ 動能
1m：{d['m1']}%
3m：{d['m3']}%
6m：{d['m6']}%

⏱️ 入場判斷
{timing}

🧠 AI成功率：{winrate}%

RSI：{d['rsi']}
MACD：{d['macd']}

📊 VWAP：{d['vwap']}
📊 成交量：{d['volume']}
📉 回調：{d['pullback']}%

📉 支撐：{d['support']}
📈 阻力：{d['resistance']}

💰 策略
入場：{d['entry_low']} - {d['entry_high']}
止蝕：{d['stop']}
目標：{d['target']}

📊 R/R：{d['rr']}
📊 評級：{advice}
"""

    msg += get_news(symbol)
    return msg

# ======================
# AUTO PUSH
# ======================
def auto_push():
    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)
                winrate=calc_winrate(d)
                timing=entry_logic(d)

                if winrate>=75 and d["rr"]>2:
                    send(CHAT_ID,f"""🚀【{s} 高勝率入場】

🧠 成功率：{winrate}%
⏱️ Timing：{timing}

入場：{d['entry_low']} - {d['entry_high']}
止蝕：{d['stop']}
目標：{d['target']}

📊 R/R：{d['rr']}
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
            send(chat_id,build(s))

    return "ok"

@app.route("/")
def home():
    return "running"

# ======================
# RUN
# ======================
if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
