import os, json, requests, yfinance as yf, time, threading
from flask import Flask, request

TOKEN = os.getenv("TOKEN")
NEWS_API = os.getenv("NEWS_API")
CHAT_ID = os.getenv("CHAT_ID")

stocks = ["TSLA","NVDA","AMD"]

# ======================
# 📊 DATA
# ======================
def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="1h")
        if df.empty:
            df = yf.Ticker(symbol).history(period="1mo", interval="1d")

        close = df["Close"]

        price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])
        change_pct = (price - prev_close) / prev_close * 100

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100/(1+rs))).iloc[-1])

        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()

        support = float(close.tail(50).min())
        resistance = float(close.tail(50).max())

        return price, change_pct, rsi, float(macd.iloc[-1]), float(signal.iloc[-1]), support, resistance

    except:
        return None

# ======================
# 🧠 AI（機率版）
# ======================
def ai_probability(rsi, macd, signal, price, support, resistance):
    prob = 50

    if rsi < 30: prob += 20
    elif rsi > 70: prob -= 20

    if macd > signal: prob += 15
    else: prob -= 15

    if price <= support*1.03: prob += 10
    if price >= resistance*0.97: prob -= 10

    return max(5, min(95, prob))

# ======================
# 💰 波段策略
# ======================
def strategy(price, support, resistance):
    entry = support * 1.02
    stop = support * 0.97
    target = resistance * 0.98

    return entry, stop, target

# ======================
# 📰 NEWS
# ======================
def get_news():
    try:
        url=f"https://newsapi.org/v2/everything?q=Tesla OR Nvidia OR AMD OR SpaceX IPO&apiKey={NEWS_API}"
        res=requests.get(url).json()

        text="\n📰【市場新聞】\n"

        for a in res.get("articles",[])[:3]:
            title=a["title"]
            source=a["source"]["name"]

            zh = title.replace("Tesla","特斯拉")\
                      .replace("Nvidia","英偉達")\
                      .replace("AMD","超微")

            if any(x in title.lower() for x in ["surge","growth","beat"]):
                senti="🟢 利好"
            elif any(x in title.lower() for x in ["drop","fall","warn"]):
                senti="🔴 利淡"
            else:
                senti="⚪ 中性"

            text += f"• {zh}\n({source}) {senti}\n"

            if "spacex" in title.lower() and "ipo" in title.lower():
                text += "🚨 SpaceX IPO消息\n"

        return text

    except:
        return ""

# ======================
# 📊 BUILD（終極版）
# ======================
def build(symbol):
    d = get_data(symbol)
    if not d:
        return f"⚠️ {symbol} 無數據"

    price, change, rsi, macd, signal, support, resistance = d

    trend = "📈 上升" if macd > signal else "📉 下降"

    rsi_text = "🟢 超賣" if rsi<30 else "🔴 超買" if rsi>70 else "⚪ 正常"
    macd_text = "🟢 黃金交叉" if macd>signal else "🔴 死亡交叉"

    prob = ai_probability(rsi,macd,signal,price,support,resistance)

    # ===== 突破 alert =====
    alert=""
    if price > resistance:
        alert="🚀 突破阻力（可能爆升）"
    elif price < support:
        alert="⚠️ 跌穿支撐（風險高）"

    # ===== 波段策略 =====
    entry, stop, target = strategy(price,support,resistance)

    msg=f"""📊【{symbol} 即時分析】

💰 價格：${price:.2f}
📊 24H：{change:.2f}%

{trend}
RSI：{rsi:.1f} {rsi_text}
MACD：{macd_text}

🧠 上升機率：{prob}%

🎯 波段策略
入場：{entry:.2f}
止蝕：{stop:.2f}
目標：{target:.2f}

📉 支撐：{support:.2f}
📈 阻力：{resistance:.2f}
"""

    if alert:
        msg += f"\n{alert}"

    msg += "\n" + get_news()

    return msg

# ======================
# 📩 SEND
# ======================
def send(text):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id":CHAT_ID,"text":text})

# ======================
# ⏰ AUTO PUSH
# ======================
def auto_push():
    while True:
        for s in stocks:
            send(build(s))
        time.sleep(1800)

# ======================
# 🌐 WEBHOOK
# ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text.startswith("/check"):
        args = text.split()
        if len(args)>1:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          json={"chat_id":chat_id,"text":build(args[1].upper())})
        else:
            for s in stocks:
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                              json={"chat_id":chat_id,"text":build(s)})

    return "ok"

# ======================
# 🚀 RUN
# ======================
if __name__ == "__main__":
    threading.Thread(target=auto_push, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
