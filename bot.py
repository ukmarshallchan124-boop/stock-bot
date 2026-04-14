import os, json, requests, yfinance as yf, time
from flask import Flask, request

TOKEN = os.getenv("TOKEN")
NEWS_API = os.getenv("NEWS_API")

stocks = ["TSLA","NVDA","AMD"]

DATA_FILE = "data.json"

def load_data():
    try:
        return json.load(open(DATA_FILE))
    except:
        return {"wins":0,"loss":0,"positions":{},"last_push":0,"last_news":""}

def save_data(data):
    json.dump(data, open(DATA_FILE,"w"))

data_store = load_data()

# ======================
# 📊 DATA（穩定版）
# ======================
def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="1h")

        if df.empty:
            df = yf.Ticker(symbol).history(period="1mo", interval="1d")

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
# 🧠 AI（learning）
# ======================
def ai_score(rsi, macd, signal):
    score = 50

    if rsi < 30: score += 20
    elif rsi > 70: score -= 20

    if macd > signal: score += 15
    else: score -= 15

    winrate = data_store["wins"] / max(1,(data_store["wins"]+data_store["loss"]))
    score += (winrate-0.5)*20

    return max(0,min(100,score))

# ======================
# 💰 TRADE
# ======================
def trade(symbol, price, rsi, macd, signal, support):
    pos = data_store["positions"]

    if symbol not in pos:
        if rsi < 35 and macd > signal and price <= support*1.03:
            pos[symbol] = price
            save_data(data_store)
            return f"🟢 買入 @{price:.2f}"

    else:
        entry = pos[symbol]
        change = (price-entry)/entry*100

        if change >= 8:
            pos.pop(symbol)
            data_store["wins"] += 1
            save_data(data_store)
            return f"💰 止賺 +{change:.2f}%"

        elif change <= -5:
            pos.pop(symbol)
            data_store["loss"] += 1
            save_data(data_store)
            return f"🔴 止蝕 {change:.2f}%"

    return ""

# ======================
# 📰 NEWS（含IPO）
# ======================
def get_news():
    try:
        url=f"https://newsapi.org/v2/everything?q=stock market OR Nvidia OR Tesla OR AMD OR SpaceX IPO&apiKey={NEWS_API}"
        res=requests.get(url).json()

        text="\n📰 市場新聞\n"

        for a in res.get("articles",[])[:3]:
            title=a["title"]

            zh = title.replace("Tesla","特斯拉").replace("Nvidia","英偉達").replace("AMD","超微")

            text+=f"• {zh}\n"

            if "spacex" in title.lower() and "ipo" in title.lower():
                if title != data_store["last_news"]:
                    data_store["last_news"] = title
                    save_data(data_store)
                    text+="🚨 SpaceX IPO消息\n"

        return text

    except:
        return ""

# ======================
# 📦 BUILD
# ======================
def build(symbol):
    d = get_data(symbol)
    if not d:
        return f"⚠️ {symbol} 暫時無數據"

    price,rsi,macd,signal,support,resistance = d

    macd_text = "🟢 黃金交叉" if macd>signal else "🔴 死亡交叉"

    score = ai_score(rsi,macd,signal)

    trade_msg = trade(symbol,price,rsi,macd,signal,support)

    msg=f"""📊【{symbol}】

💰 價格：{price:.2f}
🧠 AI評分：{score}/100

RSI：{rsi:.1f}
MACD：{macd_text}

📉 支撐：{support:.2f}
📈 阻力：{resistance:.2f}
"""

    if score>=70:
        msg+="\n🟢 偏強"
    elif score<=30:
        msg+="\n🔴 偏弱"
    else:
        msg+="\n⚪ 中性"

    if trade_msg:
        msg+="\n"+trade_msg

    return msg

# ======================
# 📩 SEND
# ======================
def send(chat_id, text):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id":chat_id,"text":text})

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

    # 🔥 手動查詢
    if text.startswith("/check"):
        args = text.split()

        if len(args)>1:
            send(chat_id, build(args[1].upper()))
        else:
            for s in stocks:
                send(chat_id, build(s))

        send(chat_id, get_news())

    # 📊 勝率
    if text=="/stats":
        w=data_store["wins"]
        l=data_store["loss"]
        rate=w/max(1,(w+l))*100
        send(chat_id,f"📊 勝率 {rate:.1f}% ({w}W/{l}L)")

    # 🕒 自動推送（30分鐘）
    now=time.time()
    if now - data_store["last_push"] > 1800:
        data_store["last_push"]=now
        save_data(data_store)

        for s in stocks:
            send(chat_id, build(s))

    return "ok"

# ======================
# 🚀 RUN（防死server）
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
