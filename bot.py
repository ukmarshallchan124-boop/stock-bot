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
# FLASK
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ AlphaCore Debug Running"

# =========================
# TELEGRAM（加強debug）
# =========================
def send(msg):
    try:
        if not BOT_TOKEN or not CHAT_ID:
            print("❌ ENV missing")
            return

        res = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg[:4000]},
            timeout=10
        )

        print("📤 SEND STATUS:", res.text)

    except Exception as e:
        print("❌ send error:", e)

def get_updates(offset=None):
    try:
        res = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 10},
            timeout=15
        )
        data = res.json()
        return data
    except Exception as e:
        print("❌ update error:", e)
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
    except Exception as e:
        print(f"❌ data error {symbol}:", e)
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
        return "🚀 Breakout"
    if p < data.min()*1.005:
        return "💥 Breakdown"
    return "📊 正常"

def structure(data):
    return "📈 上升結構" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構"

def trend(data):
    return "📈 上升" if data.iloc[-1] > data.mean() else "📉 下跌"

def signal(rsi_v, macd_v, sig_v, drop):
    if drop < -8 and rsi_v < 35 and macd_v > sig_v:
        return "🔥 S級"
    elif drop < -5 and rsi_v < 45:
        return "🟢 A級"
    elif rsi_v > 65:
        return "🔴 過熱"
    return "🟡 等待"

def winrate(rsi_v, drop):
    if rsi_v < 35 and drop < -6:
        return "70-80%"
    elif rsi_v < 45:
        return "60%"
    return "50%"

def rr():
    return 2.4, 5, 12

def support_resistance(data):
    return data.min(), data.max()

# =========================
# DCA
# =========================
def dca_logic(data):
    price = data.iloc[-1]
    drop = (price - data.max()) / data.max() * 100

    if drop < -10:
        return "🟢 加大"
    elif drop < -5:
        return "🟡 正常買"
    return "🔴 等回調"

# =========================
# NEWS
# =========================
def get_news(symbol):
    try:
        if not NEWS_API:
            return []
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data = requests.get(url, timeout=10).json()
        return data.get("articles", [])[:1]
    except:
        return []

# =========================
# ANALYZE
# =========================
def analyze():
    print("📊 analyze running")

    msg = "🚀 AlphaCore Debug\n\n"

    for s in STOCKS:
        data = get_data(s)

        if data is None:
            msg += f"{s} ❌ 無數據\n"
            continue

        price = data.iloc[-1]
        r = calc_rsi(data)
        m, sig = calc_macd(data)
        drop = (price - data.max())/data.max()*100

        msg += f"""
📊 {s} {price:.2f}
💡 {signal(r,m,sig,drop)}
🎯 勝率 {winrate(r,drop)}
"""

    msg += "\n🟩 DCA\n"

    for s in LONG_TERM:
        data = get_data(s)
        if data:
            msg += f"{s}: {dca_logic(data)}\n"

    return msg

# =========================
# MAIN LOOP（關鍵）
# =========================
def main_loop():
    print("🚀 BOT STARTED")

    last = None
    last_push = 0

    while True:
        try:
            updates = get_updates(last)

            for u in updates.get("result", []):
                last = u["update_id"] + 1
                text = u["message"].get("text", "")

                print("📥 收到:", text)

                if "/check" in text:
                    print("👉 trigger check")
                    send(analyze())

                elif "/start" in text:
                    send("✅ Bot Ready")

            # auto push
            if time.time() - last_push > 600:
                print("⏰ auto push")
                send(analyze())
                last_push = time.time()

        except Exception as e:
            print("❌ LOOP ERROR:", e)

        time.sleep(2)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=main_loop).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
