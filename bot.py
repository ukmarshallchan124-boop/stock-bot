from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import time
import requests
from ta.momentum import RSIIndicator
from ta.trend import MACD
import threading
import os
from flask import Flask

# ======================
# 🔐 ENV
# ======================
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

stocks = ["TSLA", "NVDA", "AMD"]
last_signal = {}

# ======================
# 🤖 /start
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """🤖【Stock Bot 已啟動】

📊 指令：
/check → 即時分析

💡 功能：
• 技術分析 📈
• AI新聞 📰
• 買賣提示 🔔
• 跌幅警報 🚨
"""
    await update.message.reply_text(msg)

# ======================
# 🔍 /check（完整詳細版）
# ======================
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for s in stocks:
        msg = build_message(s, include_news=True)
        await update.message.reply_text(msg)

# ======================
# 📊 股票數據（防封版）
# ======================
def get_stock_data(symbol):
    for i in range(3):
        try:
            df = yf.download(symbol, period="2d", interval="5m")
            df = df.dropna()
            close = df["Close"].squeeze()
            break
        except:
            time.sleep(3)

    price = close.iloc[-1]
    prev = close.iloc[0]
    change = ((price - prev) / prev) * 100

    rsi = RSIIndicator(close).rsi().iloc[-1]

    macd = MACD(close)
    macd_val = macd.macd().iloc[-1]
    signal = macd.macd_signal().iloc[-1]

    return price, change, rsi, macd_val, signal

# ======================
# 🧠 分析
# ======================
def analyze(rsi, macd, signal):
    trend = "📈 上升" if macd > signal else "📉 下降"

    if rsi > 70:
        rsi_text = f"{rsi:.1f} 🔴 過熱"
        rating = "🔴 唔好追"
        advice = "避免買入"
    elif rsi < 30:
        rsi_text = f"{rsi:.1f} 🟢 超賣"
        rating = "🟢 可留意"
        advice = "考慮入場"
    else:
        rsi_text = f"{rsi:.1f} ⚪ 正常"
        rating = "⚪ 中性"
        advice = "觀望"

    macd_text = "🟢 黃金交叉" if macd > signal else "🔴 死亡交叉"

    return trend, rsi_text, macd_text, rating, advice

# ======================
# 📰 AI新聞（篩選）
# ======================
def get_news(symbol):
    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        res = requests.get(url, timeout=10).json()

        articles = res.get("articles", [])[:5]

        text = "\n📰【市場新聞】\n"
        score = 0
        useful = 0

        for a in articles:
            title = a["title"]
            lower = title.lower()

            if any(w in lower for w in ["beat","growth","surge","record","strong"]):
                sentiment = "🟢 利好"
                score += 1
                useful += 1
            elif any(w in lower for w in ["drop","fall","risk","warn","miss"]):
                sentiment = "🔴 利淡"
                score -= 1
                useful += 1
            else:
                continue

            text += f"• {title}\n{sentiment}\n"

        if useful == 0:
            return ""

        overall = "🟢 偏好" if score > 0 else "🔴 偏淡"
        text += f"\n🧠 AI總結：{overall}"

        return text

    except:
        return ""

# ======================
# 📦 訊息模板（統一）
# ======================
def build_message(s, include_news=False):
    price, change, rsi, macd, signal = get_stock_data(s)
    trend, rsi_text, macd_text, rating, advice = analyze(rsi, macd, signal)

    msg = f"""📊【{s} 即時分析】

💰 價格：${price:.2f}
📈 24H：{change:+.2f}%

{trend}
RSI：{rsi_text}
MACD：{macd_text}

🏷️ 評級：{rating}
💡 建議：{advice}
"""

    if include_news:
        news = get_news(s)
        if news:
            msg += news

    return msg, change, rsi, macd, signal

# ======================
# 📤 發送
# ======================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("❌ send fail")

# ======================
# 🚀 自動 Bot（核心）
# ======================
def run():
    count = 0

    while True:
        for s in stocks:
            try:
                msg, change, rsi, macd, signal = build_message(s)

                # 🔥 高頻新聞策略
                if s in ["TSLA", "NVDA"]:
                    msg += get_news(s)

                elif s == "AMD" and count % 2 == 0:
                    msg += get_news(s)

                send(msg)

                # ======================
                # 🔔 買賣訊號（防重複）
                # ======================
                signal_type = None

                if rsi < 30 and macd > signal:
                    signal_type = "BUY"
                elif rsi > 70 and macd < signal:
                    signal_type = "SELL"

                if signal_type and last_signal.get(s) != signal_type:
                    last_signal[s] = signal_type

                    if signal_type == "BUY":
                        send(f"🟢 買入訊號！{s}")
                    elif signal_type == "SELL":
                        send(f"🔴 賣出訊號！{s}")

                # ======================
                # 🚨 跌幅警報
                # ======================
                if change < -3:
                    send(f"🚨 {s} 跌超過 -3%！")

                time.sleep(5)

            except Exception as e:
                print("Error:", e)

        count += 1

        if count % 30 == 0:
            send("🤖 Bot運行正常")

        time.sleep(1800)

# ======================
# 🤖 Telegram
# ======================
def start_bot():
    while True:
        try:
            app = ApplicationBuilder().token(TOKEN).build()

            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("check", check))

            print("🤖 Bot 已啟動")
            app.run_polling()

        except Exception as e:
            print("❌ Telegram error:", e)
            time.sleep(10)

# ======================
# 🌐 Flask（防 Render sleep）
# ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ======================
# ▶️ 同時運行（重要順序）
# ======================
threading.Thread(target=run_web).start()
threading.Thread(target=run).start()
start_bot()
