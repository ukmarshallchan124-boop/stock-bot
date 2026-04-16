import requests
import pandas as pd
import time
import os
import threading
from flask import Flask

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

STOCKS = ["TSLA", "NVDA", "AMD"]
LONG_TERM = ["SPY", "MSFT"]

app = Flask(__name__)
last_alert = {}

@app.route("/")
def home():
    return "✅ AlphaCore Stable Running"

# =========================
# SAFE REQUEST
# =========================
def safe_get(url, params=None):
    try:
        return requests.get(url, params=params, timeout=10).json()
    except:
        return None

# =========================
# TELEGRAM
# =========================
def send(msg):
    try:
        if not BOT_TOKEN or not CHAT_ID:
            print("❌ ENV missing")
            return
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg[:4000]}, # 防爆長度
            timeout=10
        )
    except Exception as e:
        print("send error", e)

def get_updates(offset=None):
    return safe_get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        {"offset": offset, "timeout": 10}
    ) or {}

# =========================
# DATA
# =========================
def get_data(symbol):
    try:
        data = safe_get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            {"range": "5d", "interval": "5m"}
        )
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        s = pd.Series(closes).dropna()
        return s if len(s) > 30 else None
    except:
        return None

# =========================
# INDICATORS
# =========================
def rsi(data):
    delta = data.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).iloc[-1]

def macd(data):
    ema12 = data.ewm(span=12).mean()
    ema26 = data.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    return macd.iloc[-1], signal.iloc[-1]

# =========================
# LOGIC（全部保留）
# =========================
def entry_zone(data):
    high = data.max()
    return high*0.92, high*0.97

def support_resistance(data):
    return data.min(), data.max()

def trend(data):
    return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"

def structure(data):
    return "📈 HH" if data.iloc[-1] > data.iloc[-3] else "📉 LL"

def breakout(data):
    p = data.iloc[-1]
    if p > data.max()*0.995:
        return "🚀 突破"
    if p < data.min()*1.005:
        return "💥 跌穿"
    return "📊 正常"

def signal(rsi_v, macd_v, sig_v, drop):
    if drop < -8 and rsi_v < 35 and macd_v > sig_v:
        return "🔥 S級"
    elif drop < -5 and rsi_v < 45:
        return "🟢 A級"
    elif rsi_v > 65:
        return "🔴 過熱"
    return "🟡 等待"

def action(sig):
    if "S級" in sig:
        return "👉 15–20%"
    if "A級" in sig:
        return "👉 10%"
    if "過熱" in sig:
        return "👉 唔好追"
    return "👉 等"

def winrate(rsi_v, drop):
    if rsi_v < 35 and drop < -6:
        return "70-80%"
    elif rsi_v < 45:
        return "60%"
    return "50%"

def rr():
    return 2.4, 5, 12

def dca_signal(data):
    r = rsi(data)
    drop = (data.iloc[-1]-data.max())/data.max()*100

    if r < 35 or drop < -6:
        return "🟢 加碼"
    elif r > 65:
        return "🔴 停"
    return "🟡 定投"

# =========================
# ANALYZE（防爆）
# =========================
def analyze():
    try:
        msg = "🚀 AlphaCore v2.6.1\n\n"

        for s in STOCKS:
            data = get_data(s)
            if data is None:
                continue

            price = data.iloc[-1]
            r = rsi(data)
            m, sig_m = macd(data)
            drop = (price-data.max())/data.max()*100

            sig = signal(r,m,sig_m,drop)

            msg += f"""
📊 {s} {price:.2f}
💡 {sig} {action(sig)}
🎯 勝率 {winrate(r,drop)}
"""

        msg += "\n🟩 DCA\n"
        for s in LONG_TERM:
            data = get_data(s)
            if data is not None:
                msg += f"{s}: {dca_signal(data)}\n"

        return msg

    except Exception as e:
        print("analyze error", e)
        return "❌ 分析錯誤"

# =========================
# COMMAND LOOP（修正）
# =========================
def command_loop():
    last = None
    while True:
        try:
            updates = get_updates(last)
            for u in updates.get("result", []):
                last = u["update_id"] + 1
                text = u["message"].get("text","")

                if text == "/check":
                    send(analyze())

                elif text.startswith("/calc"):
                    try:
                        amt = float(text.split()[1])
                        send(f"👉 £{amt*0.1:.0f}-{amt*0.2:.0f}")
                    except:
                        send("用法 /calc 1000")

                elif text == "/start":
                    send("✅ Bot Ready")

            time.sleep(1)

        except Exception as e:
            print("cmd error", e)
            time.sleep(5)

# =========================
# AUTO（唔會死）
# =========================
def auto():
    while True:
        try:
            send(analyze())
            time.sleep(600)
        except Exception as e:
            print("auto error", e)
            time.sleep(10)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=auto, daemon=True).start()
    threading.Thread(target=command_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
