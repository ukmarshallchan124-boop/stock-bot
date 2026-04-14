import os, json, requests, yfinance as yf
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ========= ENV =========
TOKEN = os.getenv("TOKEN")
RENDER_URL = os.getenv("RENDER_URL")
NEWS_API = os.getenv("NEWS_API")

bot = Bot(token=TOKEN)

stocks = ["TSLA","NVDA","AMD"]

# ========= DATA =========
DATA_FILE = "data.json"

def load_data():
    try:
        return json.load(open(DATA_FILE))
    except:
        return {"wins":0,"loss":0,"threshold":70,"positions":{}}

def save_data(d):
    json.dump(d, open(DATA_FILE,"w"))

data_store = load_data()

# ========= STOCK =========
def get_data(symbol):
    df = yf.download(symbol, period="5d", interval="15m").dropna()
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

# ========= AI =========
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

# ========= TRADE =========
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
        return f"🔴 賣出 {symbol} @ {price:.2f}\n💰 Profit {profit:.2f}%"

# ========= NEWS =========
def get_news(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        res=requests.get(url).json()
        articles=res.get("articles",[])[:2]

        text="\n📰 新聞：\n"
        for a in articles:
            text+=f"• {a['title']}\n"
        return text
    except:
        return ""

# ========= BUILD =========
def build(symbol):
    price,rsi,macd,signal,support,resistance=get_data(symbol)
    score=ai_score(rsi,macd,signal,price,support,resistance)

    msg=f"""📊 {symbol}

💰 價格 {price:.2f}
🧠 AI評分 {score:.0f}

RSI {rsi:.1f}
MACD {"🟢" if macd>signal else "🔴"}

支撐 {support:.2f}
阻力 {resistance:.2f}
"""

    th=data_store["threshold"]

    if score>=th:
        msg+="\n🟢 BUY"
        msg+= "\n"+ (trade(symbol,price,"BUY") or "")
    elif score<=100-th:
        msg+="\n🔴 SELL"
        msg+= "\n"+ (trade(symbol,price,"SELL") or "")
    else:
        msg+="\n⚪ WAIT"

    msg+=get_news(symbol)
    return msg

# ========= TELEGRAM =========
app_tg = ApplicationBuilder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 AI交易Bot已啟動\n/check 查看")

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args=context.args
    if args:
        await update.message.reply_text(build(args[0].upper()))
    else:
        for s in stocks:
            await update.message.reply_text(build(s))

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w=data_store["wins"]
    l=data_store["loss"]
    rate=w/max(1,(w+l))*100
    await update.message.reply_text(f"📊 勝率 {rate:.1f}% ({w}W/{l}L)")

app_tg.add_handler(CommandHandler("start", start))
app_tg.add_handler(CommandHandler("check", check))
app_tg.add_handler(CommandHandler("stats", stats))

# ========= FLASK =========
app = Flask(__name__)

@app.route("/")
def home():
    return "alive"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)

    import asyncio
    asyncio.run(app_tg.process_update(update))

    return "ok"

# ========= RUN =========
def start_bot():
    import asyncio

    async def setup():
        await app_tg.initialize()
        await app_tg.start()
        await bot.set_webhook(f"{RENDER_URL}/{TOKEN}")
        print("✅ webhook ready")

    asyncio.run(setup())

if __name__ == "__main__":
    start_bot()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
