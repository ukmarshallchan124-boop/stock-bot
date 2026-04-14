from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import time, requests, os, threading, json
from ta.momentum import RSIIndicator
from ta.trend import MACD
from flask import Flask

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

stocks = ["TSLA", "NVDA", "AMD"]

# ======================
# 📂 JSON
# ======================
def load(f):
    try:
        with open(f,"r") as x: return json.load(x)
    except: return {}

def save(f,d):
    with open(f,"w") as x: json.dump(d,x)

# ======================
# 📊 股票（穩定版）
# ======================
def get_stock(s):
    for i in range(3):
        try:
            df = yf.download(s, period="5d", interval="15m")
            df = df.dropna()

            close = df["Close"]

            p = close.iloc[-1]
            ch = ((p - close.iloc[0]) / close.iloc[0]) * 100

            rsi = RSIIndicator(close).rsi().iloc[-1]

            macd = MACD(close)
            m = macd.macd().iloc[-1]
            sig = macd.macd_signal().iloc[-1]

            return df, p, ch, rsi, m, sig

        except:
            time.sleep(3)

    raise Exception("❌ 股票數據讀取失敗")

# ======================
# 📉 支撐阻力
# ======================
def get_sr(df):
    return df["Low"].tail(50).min(), df["High"].tail(50).max()

# ======================
# 📰 新聞（簡化穩定）
# ======================
def news_score(s):
    try:
        url = f"https://newsapi.org/v2/everything?q={s}&apiKey={NEWS_API}"
        r = requests.get(url, timeout=5).json()

        score = 0

        for a in r.get("articles", [])[:2]:
            t = a["title"].lower()

            if any(w in t for w in ["growth","surge","record"]):
                score += 10
            elif any(w in t for w in ["drop","risk","warn"]):
                score -= 10

        return max(0, min(score, 20))

    except:
        return 10

# ======================
# 🧠 AI評分
# ======================
def score(rsi, macd, signal, change, news):
    sc = 0

    if rsi < 30:
        sc += 30
    elif rsi < 50:
        sc += 15

    if macd > signal:
        sc += 30

    if change > 3:
        sc += 20
    elif change > 1:
        sc += 10

    sc += news

    return int(sc)

# ======================
# 📦 建立訊息
# ======================
def build_msg(s):
    df, p, ch, rsi, macd, signal = get_stock(s)
    sup, res = get_sr(df)
    news = news_score(s)

    sc = score(rsi, macd, signal, ch, news)

    msg = f"""📊【{s}】

💰 ${p:.2f} ({ch:+.2f}%)

📉 支撐：{sup:.2f}
📈 阻力：{res:.2f}

🧠 AI評分：{sc}/100
"""

    return msg, sc, p, sup, res

# ======================
# 📤 發送
# ======================
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        print("❌ send fail")

# ======================
# 🚀 自動推送（穩定）
# ======================
def run():
    while True:
        for s in stocks:
            try:
                msg, sc, p, sup, res = build_msg(s)

                # 🔥 只推高質量
                if sc >= 70:
                    send(msg)

                # 🚀 突破提示
                if p > res:
                    send(f"🚀 {s} 突破 {res:.2f}")

                if p < sup:
                    send(f"⚠️ {s} 跌穿 {sup:.2f}")

                time.sleep(5)

            except Exception as e:
                print("❌ auto error:", e)

        time.sleep(1800)

# ======================
# 🤖 指令
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
"""🤖 AI Trading Bot

/check → 全部分析
/check TSLA → 單一股票
/best → 最強股票
/risk → 市場狀態
"""
    )

# 🔍 check（穩定）
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 分析中...")

    if context.args:
        s = context.args[0].upper()

        try:
            msg, *_ = build_msg(s)
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ {s} error: {e}")

    else:
        for s in stocks:
            try:
                msg, *_ = build_msg(s)
                await update.message.reply_text(msg)
                time.sleep(1)

            except Exception as e:
                await update.message.reply_text(f"❌ {s}: {e}")

# 🏆 best
async def best(update: Update, context: ContextTypes.DEFAULT_TYPE):
    best_stock = None
    best_score = 0

    for s in stocks:
        try:
            _, sc, *_ = build_msg(s)
            if sc > best_score:
                best_score = sc
                best_stock = s
            time.sleep(1)
        except:
            pass

    await update.message.reply_text(f"🏆 最強：{best_stock} ({best_score})")

# 🌍 risk
async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = 0

    for s in stocks:
        try:
            _, sc, *_ = build_msg(s)
            total += sc
            time.sleep(1)
        except:
            pass

    avg = total / len(stocks)

    if avg > 70:
        r = "🟢 偏強"
    elif avg > 50:
        r = "⚪ 中性"
    else:
        r = "🔴 高風險"

    await update.message.reply_text(f"🌍 市場：{r}")

# ======================
# 🌐 防 Render 睡覺
# ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

def web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ======================
# ▶️ 啟動
# ======================
def bot():
    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("check", check))
    app_bot.add_handler(CommandHandler("best", best))
    app_bot.add_handler(CommandHandler("risk", risk))

    print("🤖 Bot running...")
    app_bot.run_polling()

threading.Thread(target=run).start()
threading.Thread(target=web).start()
bot()
