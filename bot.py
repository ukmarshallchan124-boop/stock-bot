import requests
import pandas as pd
import time
import os
import threading

# =========================
# CONFIG（Render）
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

STOCKS = ["TSLA", "NVDA", "AMD"]
LONG_TERM = ["SPY", "MSFT"]

# =========================
# TELEGRAM
# =========================
def send(msg, chat_id=CHAT_ID):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg[:4000]})
    except Exception as e:
        print("send error:", e)

def get_updates(offset=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        res = requests.get(url, params={"offset": offset, "timeout": 10})
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

# =========================
# AI ANALYSIS（核心）
# =========================
def analyze_stock(symbol):
    data = get_data(symbol)
    if data is None:
        return f"{symbol} ❌ 無數據"

    price = data.iloc[-1]
    r = rsi(data)

    support = data.tail(30).min()
    resistance = data.tail(30).max()

    entry_low = support * 1.01
    entry_high = support * 1.03
    sl = support * 0.97
    tp = resistance * 0.97

    risk = ((entry_high - sl) / entry_high) * 100
    reward = ((tp - entry_high) / entry_high) * 100
    rr = reward / risk if risk else 0

    score = 0
    if price > data.mean(): score += 1
    if r < 35: score += 2
    if r > 65: score -= 2

    if score >= 3:
        sig = "🚀 強力買入"
    elif score >= 1:
        sig = "🟢 入場機會"
    elif score <= -2:
        sig = "🔴 過熱"
    else:
        sig = "🟡 觀察"

    return f"""
📊 {symbol} | 💰 {price:.2f}

💡 {sig}

📥 Entry: {entry_low:.2f}-{entry_high:.2f}
🛑 SL: {sl:.2f}
🎯 TP: {tp:.2f}

🎯 R/R: {rr:.2f}

🧱 支持: {support:.2f}
🚧 阻力: {resistance:.2f}
"""

# =========================
# NEWS
# =========================
def get_news():
    if not NEWS_API:
        return "❌ 無 NEWS API"

    try:
        url = f"https://newsapi.org/v2/top-headlines?category=business&apiKey={NEWS_API}"
        data = requests.get(url).json()
        articles = data.get("articles", [])[:3]

        msg = "📰 News\n"
        for a in articles:
            msg += f"• {a['title']}\n"

        return msg
    except:
        return "❌ News error"

# =========================
# DCA
# =========================
def dca(symbol):
    data = get_data(symbol)
    if data is None:
        return ""

    r = rsi(data)

    if r < 35:
        return f"{symbol}: 🟢 平價加碼"
    elif r > 65:
        return f"{symbol}: 🔴 停手"
    return f"{symbol}: 🟡 正常DCA"

# =========================
# ANALYZE ALL
# =========================
def full_report():
    msg = "🚀 AlphaCore v13\n\n"

    msg += "🚗 波段\n"
    for s in STOCKS:
        msg += analyze_stock(s)

    msg += "\n🟩 長線\n"
    for s in LONG_TERM:
        msg += dca(s) + "\n"

    msg += "\n" + get_news()

    msg += "\n\n📘 🟢入場 🟡觀察 🔴風險 🚀強勢"

    return msg

# =========================
# MAIN LOOP
# =========================
def run():
    offset = None
    last_push = 0

    print("🚀 BOT START")

    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")

    while True:
        try:
            updates = get_updates(offset)

            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")

                if text == "/check":
                    send("✅ Bot OK", chat_id)

                elif text == "/ai":
                    send(full_report(), chat_id)

                elif text == "/news":
                    send(get_news(), chat_id)

                elif text.startswith("/calc"):
                    try:
                        send(str(eval(text.replace("/calc",""))), chat_id)
                    except:
                        send("❌ error", chat_id)

                elif text.startswith("/position"):
                    try:
                        _, p, q = text.split()
                        send(f"💰 {float(p)*float(q)}", chat_id)
                    except:
                        send("❌ format", chat_id)

            if time.time() - last_push > 600:
                send(full_report())
                last_push = time.time()

        except Exception as e:
            print("ERROR:", e)

        time.sleep(2)

# =========================
# START
# =========================
if __name__ == "__main__":
    run()
