import requests
import pandas as pd
import time
import os
import threading
from flask import Flask

# =========================
# ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

STOCKS = ["TSLA", "NVDA", "AMD"]
LONG_TERM = ["SPY", "MSFT"]

last_alert = {}

# =========================
# 🌐 FLASK（關鍵：一定要主線）
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ AlphaCore v2 Running"

# =========================
# SAFE REQUEST
# =========================
def safe_request(url):
    try:
        return requests.get(url, timeout=10).json()
    except:
        return None

# =========================
# DATA
# =========================
def get_data(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=5m"
        data = safe_request(url)

        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        series = pd.Series(closes).dropna()

        if len(series) < 30:
            return None
        return series
    except:
        return None

# =========================
# INDICATORS
# =========================
def calc_rsi(data):
    try:
        delta = data.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / loss
        return (100 - (100 / (1 + rs))).iloc[-1]
    except:
        return 50

def calc_macd(data):
    try:
        ema12 = data.ewm(span=12).mean()
        ema26 = data.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        return macd.iloc[-1], signal.iloc[-1]
    except:
        return 0, 0

def calc_drop(data):
    try:
        return (data.iloc[-1] - data.max()) / data.max() * 100
    except:
        return 0

# =========================
# STRUCTURE / TREND
# =========================
def structure(data):
    return "📈 上升結構" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構"

def trend(data):
    return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"

def breakout(data):
    try:
        high = data.max()
        low = data.min()
        price = data.iloc[-1]

        if price > high * 0.995:
            return "🚀 突破阻力"
        elif price < low * 1.005:
            return "💥 跌穿支持"
        return "📊 正常波動"
    except:
        return "📊 無法判斷"

def support_resistance(data):
    try:
        return data.min(), data.max()
    except:
        return 0, 0

# =========================
# 🧠 AI SIGNAL（分級）
# =========================
def signal_score(rsi, macd, sig, drop, price, sup):
    score = 0

    if rsi < 35: score += 2
    elif rsi < 45: score += 1

    if macd > sig: score += 2

    if drop <= -7: score += 2
    elif drop <= -4: score += 1

    if sup > 0 and abs(price - sup)/sup < 0.03:
        score += 2

    return score

def signal_level(score):
    if score >= 6:
        return "🔥 S級（最佳入場）", "👉 分2注（15–20%）"
    elif score >= 4:
        return "🟢 A級（回調入場）", "👉 小注（10%）"
    elif score >= 2:
        return "🟡 B級（觀察）", "👉 等待"
    else:
        return "🔴 C級（高風險）", "👉 唔好入場"

# =========================
# RR
# =========================
def rr():
    return 2.4, 5, 12

def rr_text(rr):
    return "🟢 高質" if rr >= 2 else "🟡 一般"

# =========================
# NEWS
# =========================
def get_news(symbol):
    try:
        if not NEWS_API:
            return []
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data = safe_request(url)
        return data.get("articles", [])[:2] if data else []
    except:
        return []

def news_sentiment(text):
    text = text.lower()
    if any(w in text for w in ["growth","strong","beat"]):
        return "🟢"
    if any(w in text for w in ["drop","miss","cut"]):
        return "🔴"
    return "🟡"

# =========================
# SEND
# =========================
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        print("send error")

# =========================
# BOT LOOP（background）
# =========================
def bot_loop():
    while True:
        try:
            msg = "🚀 AlphaCore v2（Web穩定版）\n\n"
            msg += "🚗 波段交易區\n━━━━━━━━━━━━━━━\n"

            for s in STOCKS:
                data = get_data(s)
                if data is None:
                    continue

                price = data.iloc[-1]
                rsi = calc_rsi(data)
                macd, sig = calc_macd(data)
                drop = calc_drop(data)

                struct = structure(data)
                tr = trend(data)
                br = breakout(data)
                sup, res = support_resistance(data)

                score = signal_score(rsi, macd, sig, drop, price, sup)
                level, action = signal_level(score)

                rr_val, risk, reward = rr()

                msg += f"""
📊 {s} | 💰 {price:.2f}

🔥 {level}
{action}

📊 RSI {rsi:.1f} | MACD {'上升' if macd>sig else '下降'}

🎯 {rr_text(rr_val)} | R/R 1:{rr_val}
⚠️ -{risk}% / 🎯 +{reward}%

📊 {struct} | {tr}
📡 {br}

🧱 支持 {sup:.2f} | 阻力 {res:.2f}
"""

                for n in get_news(s):
                    msg += f"📰 {news_sentiment(n['title'])} {n['title']}\n"

                msg += "\n━━━━━━━━━━━━━━━\n"

            msg += "\n🟩 長線（DCA）\n━━━━━━━━━━━━━━━\n"
            msg += "📊 SPY 👉 每月買\n📊 MSFT 👉 回調先加\n"

            send(msg)

        except Exception as e:
            print("error:", e)

        time.sleep(600)

# =========================
# START（最重要）
# =========================
if __name__ == "__main__":
    threading.Thread(target=bot_loop).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
