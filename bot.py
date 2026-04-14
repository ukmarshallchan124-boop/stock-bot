from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import requests, os, time, json
from ta.momentum import RSIIndicator
from ta.trend import MACD

# ======================
# 🔑 ENV
# ======================
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

bot = Bot(token=TOKEN)
app = Flask(__name__)

stocks = ["TSLA","NVDA","AMD"]

# ======================
# 🧠 AI學習資料
# ======================
DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"wins":0,"loss":0,"threshold":70}
    return json.load(open(DATA_FILE))

def save_data(data):
    json.dump(data, open(DATA_FILE,"w"))

# ======================
# 📊 股票數據
# ======================
def get_stock(s):
    df = yf.download(s, period="5d", interval="15m")
    df = df.dropna()
    close = df["Close"]

    price = close.iloc[-1]
    change = ((price - close.iloc[0]) / close.iloc[0]) * 100

    rsi = RSIIndicator(close).rsi().iloc[-1]

    macd = MACD(close)
    macd_val = macd.macd().iloc[-1]
    signal = macd.macd_signal().iloc[-1]

    return df,price,change,rsi,macd_val,signal

def get_sr(df):
    return df["Low"].tail(50).min(), df["High"].tail(50).max()

# ======================
# 🧠 AI評分
# ======================
def ai_score(rsi, macd, signal, change):
    score = 50

    if rsi < 30: score += 20
    if rsi > 70: score -= 20
    if macd > signal: score += 15
    else: score -= 15
    if change > 2: score += 10
    if change < -2: score -= 10

    return max(0,min(100,score))

# ======================
# 📰 新聞 + 翻譯
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

        articles = data.get("articles", [])[:3]

        text = "\n📰 市場新聞：\n"

        for a in articles:
            title = a["title"]
            zh = translate(title)
            text += f"• {zh}\n"

        return text
    except:
        return ""

# ======================
# 📦 訊息
# ======================
def build_msg(s):
    df,p,ch,rsi,macd,signal = get_stock(s)
    sup,res = get_sr(df)

    score = ai_score(rsi,macd,signal,ch)

    msg = f"""📊【{s}】

💰 ${p:.2f} ({ch:+.2f}%)

📉 支撐：{sup:.2f}
📈 阻力：{res:.2f}

RSI：{rsi:.1f}
MACD：{"🟢" if macd>signal else "🔴"}

🧠 AI評分：{score}/100
"""

    msg += get_news(s)

    return msg, score, p

# ======================
# 💰 Profit Tracking
# ======================
last_trade = {}

def check_trade(s, price, signal_type):
    data = load_data()

    if s in last_trade:
        entry = last_trade[s]

        if signal_type == "SELL":
            if price > entry:
                data["wins"] += 1
            else:
                data["loss"] += 1

            # 🔥 自動調整門檻
            total = data["wins"] + data["loss"]
            if total > 5:
                winrate = data["wins"] / total
                if winrate > 0.6:
                    data["threshold"] = min(90, data["threshold"] + 2)
                else:
                    data["threshold"] = max(60, data["threshold"] - 2)

            save_data(data)

    if signal_type == "BUY":
        last_trade[s] = price

# ======================
# 🔔 買賣信號
# ======================
def trading_signal(score, threshold):
    if score >= threshold:
        return "BUY"
    elif score <= (100-threshold):
        return "SELL"
    return None

# ======================
# 🤖 指令
# ======================
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
"""🤖 最終AI交易Bot

/check → 分析
/best → 最強股票
/stats → 勝率
"""
)

async def check(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 分析中...")

    data = load_data()

    for s in stocks:
        msg,score,price = build_msg(s)

        signal = trading_signal(score, data["threshold"])

        if signal:
            check_trade(s,price,signal)
            msg += f"\n🔔 信號：{signal}"

        await update.message.reply_text(msg)
        time.sleep(1)

async def best(update:Update,context:ContextTypes.DEFAULT_TYPE):
    results = []

    for s in stocks:
        _,score,_ = build_msg(s)
        results.append((s,score))

    best_stock = sorted(results, key=lambda x: x[1], reverse=True)[0]

    await update.message.reply_text(f"🏆 最強：{best_stock[0]} ({best_stock[1]})")

async def stats(update:Update,context:ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total = data["wins"] + data["loss"]

    if total == 0:
        await update.message.reply_text("暫無數據")
        return

    winrate = data["wins"]/total*100

    await update.message.reply_text(
f"""📊 表現

勝：{data['wins']}
負：{data['loss']}
勝率：{winrate:.1f}%

門檻：{data['threshold']}
"""
)

# ======================
# ⚙️ Telegram
# ======================
application = ApplicationBuilder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("check", check))
application.add_handler(CommandHandler("best", best))
application.add_handler(CommandHandler("stats", stats))

# ======================
# 🌐 Webhook
# ======================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    application.update_queue.put_nowait(update)
    return "ok"

@app.route("/")
def home():
    return "AI Bot Running 🚀"

# ======================
# 🚀 啟動
# ======================
if __name__ == "__main__":
    bot.set_webhook(f"{RENDER_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=10000)
