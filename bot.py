import os, json, requests, yfinance as yf, time, threading
from flask import Flask, request

TOKEN = os.getenv("TOKEN")
NEWS_API = os.getenv("NEWS_API")

stocks = ["TSLA","NVDA","AMD"]

DATA_FILE = "data.json"

def load_data():
    try:
        return json.load(open(DATA_FILE))
    except:
        return {"wins":0,"loss":0,"history":[],"positions":{},"last_news":""}

def save_data(data):
    json.dump(data, open(DATA_FILE,"w"))

data_store = load_data()

# ======================
# 📊 DATA
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
# 🧠 AI
# ======================
def ai_score(symbol, rsi, macd, signal):
    score = 50

    if rsi < 30: score += 20
    elif rsi > 70: score -= 20

    if macd > signal: score += 15
    else: score -= 15

    for h in data_store["history"]:
        if h["symbol"] == symbol:
            if abs(h["rsi"] - rsi) < 5:
                score += (5 if h["result"]=="win" else -5)

    winrate = data_store["wins"] / max(1,(data_store["wins"]+data_store["loss"]))
    score += (winrate-0.5)*30

    return max(0,min(100,score))

# ======================
# 💰 TRADE
# ======================
def check_trade(symbol, price, rsi, macd, signal, support, resistance):
    pos = data_store["positions"]
    msg = ""

    if symbol not in pos:
        if rsi < 35 and macd > signal and price <= support*1.03:
            pos[symbol] = price
            msg = f"🟢 BUY @{price:.2f}"

    else:
        entry = pos[symbol]
        change = (price-entry)/entry*100

        if change >= 8:
            result="win"
            msg = f"💰 TAKE PROFIT +{change:.2f}%"

        elif change <= -5:
            result="loss"
            msg = f"🔴 STOP LOSS {change:.2f}%"

        else:
            result=None

        if result:
            pos.pop(symbol)
            data_store["history"].append({"symbol":symbol,"rsi":rsi,"result":result})
            if result=="win": data_store["wins"]+=1
            else: data_store["loss"]+=1

    save_data(data_store)
    return msg

# ======================
# 🚀 BREAKOUT
# ======================
def breakout(price, resistance):
    if price > resistance * 1.01:
        return "🚀 突破阻力"
    return ""

# ======================
# 🛰️ SpaceX IPO MONITOR（🔥）
# ======================
def check_spacex_news():
    try:
        url=f"https://newsapi.org/v2/everything?q=SpaceX IPO&apiKey={NEWS_API}"
        res=requests.get(url).json()

        for a in res.get("articles",[])[:5]:
            title = a["title"]

            # 關鍵字
            if any(k in title.lower() for k in ["ipo","listing","nasdaq","public"]):

                if title != data_store["last_news"]:
                    data_store["last_news"] = title
                    save_data(data_store)

                    # 🔥 AI分析影響
                    impact = "⚠️ 可能影響 Tesla 資金流 / AI板塊"

                    msg = f"""
🚨【SpaceX IPO ALERT】

📰 {title}

{impact}
"""
                    return msg
        return ""
    except:
        return ""

# ======================
# 📦 BUILD
# ======================
def build(symbol):
    d = get_data(symbol)
    if not d:
        return ""

    price,rsi,macd,signal,support,resistance = d

    score = ai_score(symbol,rsi,macd,signal)

    macd_text = "🟢 黃金交叉" if macd>signal else "🔴 死亡交叉"

    trade_msg = check_trade(symbol,price,rsi,macd,signal,support,resistance)
    breakout_msg = breakout(price,resistance)

    msg=f"""📊 {symbol}
💰 {price:.2f}
🧠 AI：{score:.0f}

RSI：{rsi:.1f}
MACD：{macd_text}
"""

    if breakout_msg:
        msg += f"\n{breakout_msg}"

    if trade_msg:
        msg += f"\n{trade_msg}"

    return msg if (trade_msg or breakout_msg) else ""

# ======================
# 📩 SEND
# ======================
def send(chat_id, text):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id":chat_id,"text":text})

CHAT_ID=None

# ======================
# ⏰ AUTO PUSH（智能）
# ======================
def auto_push():
    global CHAT_ID
    while True:
        try:
            if CHAT_ID:
                # 股票訊號
                for s in stocks:
                    msg = build(s)
                    if msg:
                        send(CHAT_ID, msg)

                # SpaceX IPO
                news = check_spacex_news()
                if news:
                    send(CHAT_ID, news)

        except:
            pass
        time.sleep(1800)

threading.Thread(target=auto_push, daemon=True).start()

# ======================
# 🌐 WEBHOOK
# ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "running"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    global CHAT_ID
    data = request.get_json(force=True)

    if "message" not in data:
        return "ok"

    CHAT_ID = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text == "/check":
        for s in stocks:
            send(CHAT_ID, build(s) or f"{s} 無特別信號")

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
