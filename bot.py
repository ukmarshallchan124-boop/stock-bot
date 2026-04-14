import os, requests, yfinance as yf, json
from flask import Flask, request

# ======================
# 🔑 ENV
# ======================
TOKEN = os.getenv("TOKEN")
RENDER_URL = os.getenv("RENDER_URL")
NEWS_API = os.getenv("NEWS_API")

stocks = ["TSLA","NVDA","AMD"]

# ======================
# 📂 learning data
# ======================
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
# 📊 DATA（防爆版）
# ======================
def get_data(symbol):
    try:
        df = yf.download(symbol, period="5d", interval="15m").dropna()

        if df.empty:
            raise Exception("No data")

        close = df["Close"]

        price = close.iloc[-1]

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100/(1+rs))
        rsi = rsi.iloc[-1]

        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()

        support = close.tail(50).min()
        resistance = close.tail(50).max()

        return price, rsi, macd.iloc[-1], signal.iloc[-1], support, resistance

    except:
        return 0,50,0,0,0,0

# ======================
# 🧠 AI score
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
# 💰 trade tracking
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
# 📰 news
# ======================
def get_news(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        res=requests.get(url).json()
        articles=res.get("articles",[])[:3]

        text="\n📰 市場新聞\n"
        for a in articles:
            title=a["title"]
            text+=f"• {title}\n"

        return text
    except:
        return ""

# ======================
# 📦 message
# ======================
def build(symbol):
    price,rsi,macd,signal,support,resistance=get_data(symbol)
    score=ai_score(rsi,macd,signal,price,support,resistance)

    msg=f"""📊【{symbol} AI交易】

💰 價格：{price:.2f}
🧠 AI評分：{score:.0f}/100

RSI：{rsi:.1f}
MACD：{"🟢" if macd>signal else "🔴"}

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
# 📩 send message
# ======================
def send(chat_id, text):
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id":chat_id,"text":text})

# ======================
# 🌐 flask
# ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "running"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        if "message" not in data:
            return "ok"

        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text","")

        if text == "/start":
            send(chat_id,
                 "🚀 AI交易Bot\n\n"
                 "/check → 全部分析\n"
                 "/check TSLA → 單隻\n"
                 "/stats → 勝率")

        elif text.startswith("/check"):
            args = text.split()

            try:
                if len(args) > 1:
                    send(chat_id, build(args[1].upper()))
                else:
                    for s in stocks:
                        send(chat_id, build(s))
            except Exception as e:
                send(chat_id, f"⚠️ 錯誤：{str(e)}")

        elif text == "/stats":
            w=data_store["wins"]
            l=data_store["loss"]
            rate=w/max(1,(w+l))*100
            send(chat_id, f"📊 勝率 {rate:.1f}% ({w}W/{l}L)")

    except Exception as e:
        print("ERROR:", e)

    return "ok"

# ======================
# 🚀 run（最穩）
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
