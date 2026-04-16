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

# =========================
# FLASK（Render 必須）
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ AlphaCore v2 FULL Running"

# =========================
# TELEGRAM
# =========================
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except Exception as e:
        print("send error:", e)

def get_updates(offset=None):
    try:
        res = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 10}
        )
        return res.json()
    except Exception as e:
        print("update error:", e)
        return {}

# =========================
# DATA
# =========================
def get_data(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=5m"
        data = requests.get(url, timeout=10).json()

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

# =========================
# CORE LOGIC
# =========================
def entry_zone(data):
    high = data.max()
    return high * 0.92, high * 0.97

def breakout(data):
    p = data.iloc[-1]
    if p > data.max()*0.995:
        return "🚀 Breakout（追勢）"
    if p < data.min()*1.005:
        return "💥 Breakdown（風險）"
    return "📊 正常波動"

def structure(data):
    return "📈 上升結構" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構"

def trend(data):
    return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"

def signal(rsi_v, macd_v, sig_v, drop):
    if drop < -8 and rsi_v < 35 and macd_v > sig_v:
        return "🔥 S級（強力反彈）"
    elif drop < -5 and rsi_v < 45:
        return "🟢 A級（回調入場）"
    elif rsi_v > 65:
        return "🔴 過熱（小心回調）"
    return "🟡 等待"

def winrate(rsi_v, drop):
    if rsi_v < 35 and drop < -6:
        return "70–80%"
    elif rsi_v < 45:
        return "60%"
    return "50%"

def rr():
    return 2.4, 5, 12

def support_resistance(data):
    return data.min(), data.max()

# =========================
# DCA（智能）
# =========================
def dca_logic(data):
    price = data.iloc[-1]
    drop = (price - data.max()) / data.max() * 100

    if drop < -10:
        return "🟢 加大（市場回調）"
    elif drop < -5:
        return "🟡 正常買入"
    return "🔴 等待回調"

# =========================
# NEWS
# =========================
def get_news(symbol):
    try:
        if not NEWS_API:
            return []
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data = requests.get(url).json()
        return data.get("articles", [])[:2]
    except:
        return []

def sentiment(text):
    text = text.lower()
    if any(w in text for w in ["strong","growth","beat"]):
        return "🟢"
    if any(w in text for w in ["drop","miss","cut"]):
        return "🔴"
    return "🟡"

# =========================
# ANALYZE
# =========================
def analyze():
    msg = "🚀 AlphaCore v2 FINAL\n\n"

    msg += "🚗 波段交易區\n━━━━━━━━━━━━━━━\n"

    for s in STOCKS:
        data = get_data(s)
        if data is None:
            msg += f"{s} ⚠️ 無數據\n"
            continue

        price = data.iloc[-1]
        r = calc_rsi(data)
        m, sig = calc_macd(data)
        drop = (price - data.max())/data.max()*100

        ez1, ez2 = entry_zone(data)
        sup, res = support_resistance(data)

        msg += f"""
📊 {s} | 💰 {price:.2f}

💡 {signal(r,m,sig,drop)}
🎯 勝率：約 {winrate(r,drop)}

📥 入場區：
{ez1:.2f} - {ez2:.2f}

🎯 R/R 1:{rr()[0]}（+{rr()[2]}% / -{rr()[1]}%）

📊 {structure(data)} | {trend(data)}
🚨 {breakout(data)}

🧱 支持 {sup:.2f}
🚧 阻力 {res:.2f}
"""

        news = get_news(s)
        for n in news:
            msg += f"📰 {sentiment(n['title'])} {n['title']}\n"

        msg += "\n━━━━━━━━━━━━━━━\n"

    msg += "\n🟩 長線 DCA\n━━━━━━━━━━━━━━━\n"

    for s in LONG_TERM:
        data = get_data(s)
        if data is None:
            continue

        msg += f"""
📊 {s}
👉 {dca_logic(data)}
"""

    return msg

# =========================
# MAIN LOOP（核心）
# =========================
def main_loop():
    print("🚀 Bot Running")

    last = None
    last_push = 0

    while True:
        try:
            updates = get_updates(last)

            for u in updates.get("result", []):
                last = u["update_id"] + 1
                text = u["message"].get("text","")

                print("📥", text)

                if "/check" in text:
                    send(analyze())

                elif "/start" in text:
                    send("✅ AlphaCore Bot Ready")

                elif text.startswith("/calc"):
                    try:
                        amt = float(text.split()[1])
                        send(f"💰 建議分注：{amt*0.1:.0f} - {amt*0.2:.0f}")
                    except:
                        send("用法：/calc 1000")

            # 自動推送
            if time.time() - last_push > 600:
                send(analyze())
                last_push = time.time()

        except Exception as e:
            print("ERROR:", e)

        time.sleep(2)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=main_loop).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
