import os, requests, yfinance as yf, json, time, threading
from flask import Flask, request

TOKEN = os.getenv("TOKEN")
NEWS_API = os.getenv("NEWS_API")

stocks = ["TSLA","NVDA","AMD"]

DATA_FILE = "data.json"

def load_data():
    try:
        return json.load(open(DATA_FILE))
    except:
        return {"wins":0,"loss":0,"threshold":70,"positions":{}}

def save_data(data):
    json.dump(data, open(DATA_FILE,"w"))

data_store = load_data()

# ======================
# 📊 DATA
# ======================
def get_data(symbol):
    try:
        df = yf.download(symbol, period="5d", interval="15m", progress=False).dropna()

        if df.empty:
            return None

        close = df["Close"]

        price = float(close.iloc[-1])

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

        return price, rsi, float(macd.iloc[-1]), float(signal.iloc[-1]), support, resistance

    except:
        return None

# ======================
# 🧠 AI
# ======================
def ai_score(rsi, macd, signal, price, support, resistance):
    score = 50

    if rsi < 30: score += 20
    elif rsi > 70: score -= 20

    if macd > signal: score += 15
    else: score -= 15

    if price < support*1.02: score += 10
    if price > resistance*0.98: score -= 10

    winrate = data_store["wins"] / max(1,(data_store["wins"]+data_store["loss"]))
    score += (winrate-0.5)*20

    return max(0,min(100,score))

# ======================
# 💰 trade
# ======================
def trade(symbol, price, action):
    pos = data_store["positions"]

    if action=="BUY":
        pos[symbol]=price
        save_data(data_store)
        return f"🟢 買入 {symbol} @ {price:.2f}"

    if action=="SELL" and symbol in pos:
        entry = pos.pop(symbol)
        profit = (price-entry)/entry*100

        if profit>0: data_store["wins"]+=1
        else: data_store["loss"]+=1

        save_data(data_store)
        return f"🔴 賣出 {symbol} @ {price:.2f}\n💰 Profit: {profit:.2f}%"

# ======================
# 📰 NEWS
# ======================
def get_news(symbol):
    try:
        query = f"{symbol} OR SpaceX OR Tesla"
        url=f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API}"
        res=requests.get(url).json()
        articles=res.get("articles",[])[:3]

        text="\n📰 市場新聞\n"
        for a in articles:
            text+=f"• {a['title']}\n"

        return text
    except:
        return ""

# ======================
# 📦 BUILD
# ======================
def build(symbol):
    data = get_data(symbol)

    if data is None:
        return f"⚠️ {symbol} 暫時無數據"

    price,rsi,macd,signal,support,resistance = data

    score=ai_score(rsi,macd,signal,price,support,resistance)

    msg=f"""📊【{symbol} AI交易】

💰 價格：{price:.2f}
🧠 AI評分：{score:.0f}/100

RSI：{rsi:.1f}
MACD：{"🟢" if macd > signal else "🔴"}

📉 支撐：{support:.2f}
📈 阻力：{resistance:.2f}
"""

    threshold=data_store["threshold"]

    if score>=threshold:
        msg+="\n🟢 買入訊號"
        t=trade(symbol,price,"BUY")
        if t: msg+="\n"+t

    elif score<=100-threshold:
        msg+="\n🔴 賣出訊號"
        t=trade(symbol,price,"SELL")
        if t: msg+="\n"+t

    else:
        msg+="\n⚪ 觀望"

    msg+=get_news(symbol)

    return msg

# ======================
# 📩 SEND
# ======================
def send(chat_id, text):
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id":chat_id,"text":text})

# ======================
# 🤖 AUTO PUSH（每30分鐘🔥）
# ======================
CHAT_ID = None

def auto_push():
    while True:
        try:
            if CHAT_ID:
                for s in stocks:
                    send(CHAT_ID, "⏰ 半小時更新\n" + build(s))
            time.sleep(1800)  # 🔥 30分鐘
        except:
            time.sleep(1800)

threading.Thread(target=auto_push, daemon=True).start()

# ======================
# 🌐 FLASK
# ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "running"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    global CHAT_ID

    try:
        data = request.get_json(force=True)

        if "message" not in data:
            return "ok"

        chat_id = data["message"]["chat"]["id"]
        CHAT_ID = chat_id

        text = data["message"].get("text","")

        if text == "/start":
            send(chat_id,
                 "🚀 AI交易Bot\n\n"
                 "/check → 全部分析\n"
                 "/check TSLA → 單隻\n"
                 "/stats → 勝率\n"
                 "⏰ 每30分鐘自動更新")

        elif text.startswith("/check"):
            args = text.split()

            if len(args) > 1:
                send(chat_id, build(args[1].upper()))
            else:
                for s in stocks:
                    send(chat_id, build(s))

        elif text == "/stats":
            w=data_store["wins"]
            l=data_store["loss"]
            rate=w/max(1,(w+l))*100
            send(chat_id, f"📊 勝率 {rate:.1f}% ({w}W/{l}L)")

    except Exception as e:
        print("ERROR:", e)

    return "ok"

# ======================
# 🚀 RUN
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
