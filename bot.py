from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import requests, os, time, asyncio
from ta.momentum import RSIIndicator
from ta.trend import MACD

# ======================
# 🔑 ENV（一定要用 Render 設定）
# ======================
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

bot = Bot(token=TOKEN)
app = Flask(__name__)

stocks = ["TSLA", "NVDA", "AMD"]

# ======================
# 📊 股票數據
# ======================
def get_stock(s):
    df = yf.download(s, period="2d", interval="5m")
    df = df.dropna()
    close = df["Close"]

    price = close.iloc[-1]
    change = ((price - close.iloc[0]) / close.iloc[0]) * 100

    rsi = RSIIndicator(close).rsi().iloc[-1]

    macd = MACD(close)
    macd_val = macd.macd().iloc[-1]
    signal = macd.macd_signal().iloc[-1]

    return df, price, change, rsi, macd_val, signal

# ======================
# 🧠 AI評分
# ======================
def ai_score(rsi, macd, signal):
    score = 50

    if rsi < 30: score += 20
    if rsi > 70: score -= 20
    if macd > signal: score += 15
    else: score -= 15

    return max(0, min(100, score))

# ======================
# 📰 中文新聞
# ======================
def translate(text):
    try:
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair=en|zh"
        return requests.get(url).json()["responseData"]["translatedText"]
    except:
        return text

def get_news(s):
    try:
        url = f"https://newsapi.org/v2/everything?q={s}&apiKey={NEWS_API}"
        data = requests.get(url).json()

        articles = data.get("articles", [])[:2]

        text = "\n📰 市場新聞：\n"
        for a in articles:
            zh = translate(a["title"])
            text += f"• {zh}\n"

        return text
    except:
        return ""

# ======================
# 📦 訊息
# ======================
def build_msg(s):
    df, price, change, rsi, macd, signal = get_stock(s)

    score = ai_score(rsi, macd, signal)

    msg = f"""📊【{s}】

💰 ${price:.2f} ({change:+.2f}%)

📈 RSI：{rsi:.1f}
📊 MACD：{"🟢" if macd>signal else "🔴"}

🧠 AI評分：{score}/100
"""

    msg += get_news(s)

    return msg

# ======================
# 🤖 指令
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
"""🤖 AI Trading Bot

/check → 分析股票
"""
)

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 分析中（幾秒）...")

    asyncio.create_task(run_analysis(update))

async def run_analysis(update):
    for s in stocks:
        try:
            msg = build_msg(s)
            await update.message.reply_text(msg)
            await asyncio.sleep(1)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

# ======================
# ⚙️ Telegram
# ======================
application = ApplicationBuilder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("check", check))

# 🔥 初始化（超重要）
async def init():
    await application.initialize()
    await application.start()

# ======================
# 🌐 Webhook（重點）
# ======================
@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)

    await application.process_update(update)

    return "ok"

@app.route("/")
def home():
    return "AI Bot Running 🚀"

# ======================
# 🚀 啟動
# ======================
if __name__ == "__main__":
    import asyncio

    asyncio.run(init())

    bot.set_webhook(f"{RENDER_URL}/{TOKEN}")

    app.run(host="0.0.0.0", port=10000)
