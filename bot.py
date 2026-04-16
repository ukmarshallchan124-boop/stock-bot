# ====== FULL CODE START ======

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

@app.route("/")
def home():
    return "AlphaCore Running"

# =========================
# TELEGRAM
# =========================
def send(msg):
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg[:4000]},
            timeout=10
        )
        print("SEND:", res.text)
    except Exception as e:
        print("send error:", e)

def get_updates(offset=None):
    try:
        res = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 10}
        )
        return res.json()
    except:
        return {}

# =========================
# DATA
# =========================
def get_data(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=5m"
        data = requests.get(url).json()

        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        return pd.Series(closes).dropna()
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
# SIGNAL SYSTEM
# =========================
def signal(rsi_v, macd_v, sig_v, drop):
    if drop < -8 and rsi_v < 35 and macd_v > sig_v:
        return "🟢🟢【強力入場】"
    elif drop < -5 and rsi_v < 45:
        return "🟢【入場機會】"
    elif rsi_v > 65:
        return "🔴【過熱】"
    return "🟡【觀察中】"

def action(sig):
    if "強力" in sig:
        return "👉 建議：分2注（15-20%）+ 可加碼"
    if "入場" in sig:
        return "👉 建議：小注（10%）"
    if "過熱" in sig:
        return "👉 建議：唔好追 / 考慮減倉"
    return "👉 建議：等待"

def rr():
    return 2.4, 5, 12

# =========================
# STRUCTURE
# =========================
def structure(data):
    return "📈 上升結構" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構"

def trend(data):
    return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"

def support_resistance(data):
    return data.min(), data.max()

def entry_zone(data):
    high = data.max()
    return high * 0.92, high * 0.97

def breakout(data):
    p = data.iloc[-1]
    if p > data.max()*0.995:
        return "🚀 突破阻力"
    if p < data.min()*1.005:
        return "💥 跌穿支持"
    return "📊 正常波動"

# =========================
# DCA SIGNAL
# =========================
def dca(data):
    r = rsi(data)
    drop = (data.iloc[-1]-data.max())/data.max()*100

    if r < 35 or drop < -6:
        return "🟢【平價】👉 可加碼"
    elif r > 65:
        return "🔴【偏高】👉 暫停"
    return "🟡【正常】👉 持續DCA"

# =========================
# NEWS
# =========================
def get_news(symbol):
    if not NEWS_API:
        return []
    try:
        data = requests.get(
            f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        ).json()
        return data.get("articles", [])[:1]
    except:
        return []

# =========================
# ANALYZE
# =========================
def analyze():
    msg = "🚀 AlphaCore v2 FINAL\n\n"

    # ===== 波段 =====
    msg += "🚗 波段交易區\n━━━━━━━━━━━━━━━\n"

    for s in STOCKS:
        data = get_data(s)
        if data is None:
            continue

        price = data.iloc[-1]
        r = rsi(data)
        m, sig_m = macd(data)
        drop = (price - data.max())/data.max()*100

        ez1, ez2 = entry_zone(data)
        sup, res = support_resistance(data)
        sig = signal(r,m,sig_m,drop)

        rr_val, risk, reward = rr()

        msg += f"""
📊 {s} | 💰 {price:.2f}

💡 信號：{sig}
{action(sig)}

🎯 勝率：{ '70-80%' if r<35 else '60%' if r<45 else '50%' }

📥 入場區：{ez1:.2f}-{ez2:.2f}

🎯 R/R：1:{rr_val}
⚠️ 風險：-{risk}% | 🎯 回報：+{reward}%

📊 {trend(data)} | {structure(data)}
🧱 支持：{sup:.2f} | 阻力：{res:.2f}

🚨 {breakout(data)}
"""

        for n in get_news(s):
            msg += f"📰 {n['title']}\n"

        msg += "\n━━━━━━━━━━━━━━━\n"

    # ===== 長線 =====
    msg += "\n🟩 長線投資（DCA）\n━━━━━━━━━━━━━━━\n"

    for s in LONG_TERM:
        data = get_data(s)
        if data is not None:
            msg += f"\n📊 {s}\n{dca(data)}\n"

    # ===== emoji 解釋 =====
    msg += """
━━━━━━━━━━━━━━━
📘 說明：
🟢 入場 / 平價
🟡 中性 / 等待
🔴 過熱 / 風險
🚀 突破
💥 跌穿
"""

    return msg

# =========================
# MAIN LOOP
# =========================
def main_loop():
    last = None
    last_push = 0

    while True:
        try:
            updates = get_updates(last)

            for u in updates.get("result", []):
                last = u["update_id"] + 1
                text = u["message"].get("text","")

                if "/check" in text:
                    send(analyze())

                elif "/start" in text:
                    send("✅ AlphaCore 已啟動")

                elif text.startswith("/calc"):
                    amt = float(text.split()[1])
                    send(f"💰 建議入場：{amt*0.1:.0f}-{amt*0.2:.0f}")

                elif "/position" in text:
                    send("📦 +20%減倉 | +10%觀察 | 未升持有")

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

# ====== FULL CODE END ======
