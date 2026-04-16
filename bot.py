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
    return "✅ AlphaCore v2.6 Running"

# =========================
# TELEGRAM
# =========================
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        print("send error")

def get_updates(offset=None):
    try:
        return requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset}
        ).json()
    except:
        return {}

# =========================
# DATA
# =========================
def get_data(symbol):
    try:
        data = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=5m"
        ).json()
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
# CORE ENGINE
# =========================
def entry_zone(data):
    high = data.max()
    return high * 0.92, high * 0.97

def support_resistance(data):
    return data.min(), data.max()

def trend(data):
    return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"

def structure(data):
    return "📈 Higher High" if data.iloc[-1] > data.iloc[-3] else "📉 Lower Low"

def breakout(data):
    p = data.iloc[-1]
    if p > data.max()*0.995:
        return "🚀 突破阻力（追勢）"
    if p < data.min()*1.005:
        return "💥 跌穿支持（風險）"
    return "📊 正常波動"

def signal(rsi_v, macd_v, sig_v, drop):
    if drop < -8 and rsi_v < 35 and macd_v > sig_v:
        return "🔥 S級（強力反彈位）"
    elif drop < -5 and rsi_v < 45:
        return "🟢 A級（健康回調）"
    elif rsi_v > 65:
        return "🔴 過熱（小心回落）"
    return "🟡 等待中"

def action(sig):
    if "S級" in sig:
        return "👉 分2注（15–20%）+ 可加碼"
    if "A級" in sig:
        return "👉 小注（10%）+ 等確認"
    if "過熱" in sig:
        return "👉 唔好追 / 可減倉"
    return "👉 等待機會"

def winrate(rsi_v, drop):
    if rsi_v < 35 and drop < -6:
        return "70-80%"
    elif rsi_v < 45:
        return "60%"
    return "50%"

def rr():
    return 2.4, 5, 12

# =========================
# 🧠 智能 DCA（新）
# =========================
def dca_signal(data):
    r = rsi(data)
    drop = (data.iloc[-1] - data.max()) / data.max() * 100

    if r < 35 or drop < -6:
        return "🟢 平價區（可加碼） 👉 DCA + 加注"
    elif r > 65:
        return "🔴 偏高（暫停） 👉 等回調"
    else:
        return "🟡 正常區 👉 持續定投"

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
# ALERT CONTROL
# =========================
def should_alert(symbol, sig):
    key = f"{symbol}_{sig}"
    if key in last_alert:
        return False
    last_alert[key] = True
    return True

# =========================
# ANALYZE
# =========================
def analyze():
    msg = "🚀 AlphaCore v2.6 FINAL\n\n"

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

        if not should_alert(s, sig):
            continue

        rr_val, risk, reward = rr()

        msg += f"""
📊 {s} | 💰 {price:.2f}

💡 {sig}
{action(sig)}
🎯 勝率：約 {winrate(r,drop)}

📥 入場區：{ez1:.2f} - {ez2:.2f}

🎯 R/R 1:{rr_val}
⚠️ -{risk}% | 🎯 +{reward}%

📊 {trend(data)} | {structure(data)}
🧱 支持 {sup:.2f} | 阻力 {res:.2f}

🚨 {breakout(data)}
"""

        for n in get_news(s):
            msg += f"📰 {n['title']}\n"

        msg += "\n━━━━━━━━━━━━━━━\n"

    # ===== 長線 DCA =====
    msg += "\n🟩 長線投資（智能DCA）\n━━━━━━━━━━━━━━━\n"

    for s in LONG_TERM:
        data = get_data(s)
        if data is None:
            continue

        msg += f"""
📊 {s}
{dca_signal(data)}
"""

    return msg

# =========================
# COMMAND
# =========================
def command_loop():
    last = None
    while True:
        updates = get_updates(last)
        for u in updates.get("result", []):
            last = u["update_id"] + 1
            text = u["message"].get("text","")

            if text == "/start":
                send("✅ AlphaCore 已啟動")

            elif text == "/check":
                send(analyze())

            elif text.startswith("/calc"):
                try:
                    amt = float(text.split()[1])
                    send(f"👉 建議入場：£{amt*0.1:.0f} - £{amt*0.2:.0f}")
                except:
                    send("用法：/calc 1000")

            elif text == "/position":
                send("📦 +20% 減倉｜+10% 留意｜未升持有")

        time.sleep(2)

# =========================
# AUTO LOOP
# =========================
def auto():
    while True:
        send(analyze())
        time.sleep(600)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=auto).start()
    threading.Thread(target=command_loop).start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
