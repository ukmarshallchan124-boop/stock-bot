from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import time
import requests
from ta.momentum import RSIIndicator
from ta.trend import MACD
import threading
import os
import random

# ======================
# 🔑 ENV（⚠️ 記得去 Render 設）
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
• 技術分析
• AI新聞（中文）
• 買賣提示
"""
    await update.message.reply_text(msg)

# ======================
# 🔍 /check
# ======================
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for s in stocks:
        msg = build_message(s, include_news=True)
        await update.message.reply_text(msg)

# ======================
# 📊 股票數據（防 rate limit）
# ======================
def get_stock_data(symbol):
    for i in range(3):
        try:
            time.sleep(random.uniform(1, 3))  # 🔥 防封
            df = yf.download(symbol, period="2d", interval="5m")
            df = df.dropna()

            close = df["Close"].squeeze()

            price = close.iloc[-1]
            prev = close.iloc[0]
            change = ((price - prev) / prev) * 100

            rsi = RSIIndicator(close).rsi().iloc[-1]

            macd = MACD(close)
            macd_val = macd.macd().iloc[-1]
            signal = macd.macd_signal().iloc[-1]

            return price, change, rsi, macd_val, signal

        except:
            time.sleep(5)

    raise Exception("❌ 無法取得數據")

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
# 📰 新聞（已解決亂碼）
# ======================
def get_news(symbol):
    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        res = requests.get(url).json()

        articles = res.get("articles", [])[:3]

        text = "\n📰【市場新聞】\n"
        score = 0

        for a in articles:
            title = a["title"]

            lower = title.lower()

            if any(w in lower for w in ["beat", "growth", "surge", "record"]):
                sentiment = "🟢 利好"
                score += 1
            elif any(w in lower for w in ["drop", "fall", "risk", "warn"]):
                sentiment = "🔴 利淡"
                score -= 1
            else:
                sentiment = "⚪ 中性"

            text += f"• {title}\n{sentiment}\n"

        overall = "🟢 偏好" if score > 0 else "🔴 偏淡" if score < 0 else "⚪ 中性"
        text += f"\n🧠 AI總結：{overall}"

        return text

    except:
        return ""

# ======================
# 📦 訊息格式（已修復 emoji）
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

    return msg

# ======================
# 📤 發送（🔥關鍵：用 json）
# ======================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": msg
            }
        )

    except Exception as e:
        print("❌ send error:", e)

# ======================
# 🚀 自動推送
# ======================
def run():
    count = 0

    while True:
        for s in stocks:
            try:
                msg = build_message(s)

                # TSLA + NVDA 高頻新聞
                if s in ["TSLA", "NVDA"]:
                    msg += get_news(s)

                send(msg)

                # 🔔 訊號
                price, change, rsi, macd, signal = get_stock_data(s)

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

            except Exception as e:
                print("Error:", e)

        count += 1

        if count % 24 == 0:
            send("🤖 Bot 運行正常")

        time.sleep(3600)  # 🔥 1小時

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
# 🌐 Flask（防 sleep）
# ======================
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot running!"

def run_web():
    app.run(host="0.0.0.0", port=10000)

# ======================
# ▶️ 啟動
# ======================
threading.Thread(target=run).start()
threading.Thread(target=run_web).start()
start_bot()
