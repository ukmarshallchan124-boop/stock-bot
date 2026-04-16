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
# FLASK（Render 必備）
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ AlphaCore AI v15 Running"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

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
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=5m"
    data = safe_request(url)

    try:
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
    delta = data.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).iloc[-1]

def calc_macd(data):
    ema12 = data.ewm(span=12).mean()
    ema26 = data.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    return macd.iloc[-1], signal.iloc[-1]

def calc_drop(data):
    return (data.iloc[-1] - data.max()) / data.max() * 100

# =========================
# STRUCTURE / TREND
# =========================
def structure(data):
    return "📈 上升結構" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構"

def trend(data):
    return "📈 上升" if data.iloc[-1] > data.mean() else "📉 下跌"

def breakout(data):
    high = data.max()
    low = data.min()
    price = data.iloc[-1]

    if price > high * 0.995:
        return "🚀 突破阻力（向上爆）"
    elif price < low * 1.005:
        return "💥 跌穿支持（向下爆）"
    return "📊 正常波動"

def support_resistance(data):
    return data.min(), data.max()

# =========================
# DECISION ENGINE
# =========================
def entry_signal(rsi, macd, sig, drop):
    if drop <= -8 and rsi < 35 and macd > sig:
        return "🟢🟢 強力入場（超跌反彈）"
    elif drop <= -5 and rsi < 40:
        return "🟢 入場機會（回調）"
    elif rsi > 65:
        return "🔴 過熱（小心回落）"
    return "🟡 觀察中"

def action(signal):
    if "強力" in signal:
        return "👉 分2注（15–20%）\n👉 再跌再加"
    elif "入場" in signal:
        return "👉 小注（10%）\n👉 再跌再加"
    elif "過熱" in signal:
        return "👉 唔好追\n👉 可減倉鎖利"
    return "👉 等待機會"

def rr():
    risk = 5
    reward = 12
    return reward / risk, risk, reward

def rr_text(rr):
    if rr >= 2:
        return "🟢🟢 高質（賺＞蝕）"
    elif rr >= 1.5:
        return "🟢 可以"
    return "🟡 一般"

def profit(change):
    if change >= 20:
        return "💰 +20%（建議鎖利）"
    elif change >= 10:
        return "🟡 +10%（留意回調）"
    return ""

def ai(rsi, struct, breakout):
    if "突破" in breakout:
        return "🚀 AI：偏強（Momentum）"
    if rsi > 70:
        return "⚠️ AI：過熱"
    if "下降" in struct:
        return "📉 AI：偏弱"
    return "📊 AI：中性"

# =========================
# NEWS
# =========================
def get_news(symbol):
    try:
        if not NEWS_API:
            return []
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data = safe_request(url)
        return data.get("articles", [])[:2]
    except:
        return []

def news_sentiment(text):
    if any(w in text.lower() for w in ["growth","strong","beat"]):
        return "🟢 利好"
    if any(w in text.lower() for w in ["drop","miss","cut"]):
        return "🔴 利淡"
    return "🟡 中性"

# =========================
# ALERT CONTROL
# =========================
def should_alert(symbol, signal):
    key = f"{symbol}_{signal}"
    if key in last_alert:
        return False
    last_alert[key] = True
    return True

# =========================
# SEND
# =========================
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("send error")

# =========================
# MAIN LOOP
# =========================
def bot_loop():
    while True:
        try:
            msg = "🚀 AlphaCore AI v15（FULL）\n\n"

            # ===== 波段 =====
            msg += "🚗 波段交易區\n━━━━━━━━━━━━━━━\n"

            for s in STOCKS:
                data = get_data(s)

                if data is None:
                    msg += f"{s} ⚠️ 無數據\n"
                    continue

                price = data.iloc[-1]
                rsi = calc_rsi(data)
                macd, sig = calc_macd(data)
                drop = calc_drop(data)

                struct = structure(data)
                tr = trend(data)
                br = breakout(data)
                sup, res = support_resistance(data)

                signal = entry_signal(rsi, macd, sig, drop)

                if not should_alert(s, signal):
                    continue

                rr_val, risk, reward = rr()

                msg += f"""
📊 {s} | 💰 {price:.2f}

💡 {signal}
{action(signal)}

🎯 {rr_text(rr_val)} | R/R 1:{rr_val:.1f}
⚠️ 風險 -{risk}% | 目標 +{reward}%

📊 {struct} | {tr}
📡 {br}

🧱 支持 {sup:.2f} | 阻力 {res:.2f}

🧠 {ai(rsi, struct, br)}
{profit(drop)}
"""

                news = get_news(s)
                for n in news:
                    msg += f"📰 {news_sentiment(n['title'])} {n['title']}\n"

                msg += "\n━━━━━━━━━━━━━━━\n"

            # ===== 長線 =====
            msg += "\n🟩 長線投資（DCA）\n━━━━━━━━━━━━━━━\n"
            msg += """
📊 S&P500（SPY）
👉 每月固定買（DCA）
👉 跌市加碼（加速累積）

📊 Microsoft（MSFT）
👉 長線持有
👉 回調先加倉（唔好追高）
"""

            send(msg)

        except Exception as e:
            print("main error:", e)

        time.sleep(600)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=bot_loop).start()
    run_server()
