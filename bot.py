import requests
import pandas as pd
import time
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

STOCKS = ["TSLA", "NVDA", "AMD"]
last_alert = {}

# =========================
# DATA
# =========================
def get_data(symbol, interval="5m"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval={interval}"
    data = requests.get(url).json()
    closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
    return pd.Series(closes).dropna()

# =========================
# INDICATORS
# =========================
def calc_rsi(data):
    delta = data.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_macd(data):
    ema12 = data.ewm(span=12).mean()
    ema26 = data.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    return macd.iloc[-1], signal.iloc[-1]

def calc_drop(data):
    high = data.max()
    current = data.iloc[-1]
    return (current - high) / high * 100

# =========================
# ANALYSIS
# =========================
def structure(data):
    return "📈 上升結構（整體向上）" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構（整體轉弱）"

def trend(data):
    return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"

def multi_tf(symbol):
    short = get_data(symbol, "5m")
    long = get_data(symbol, "1h")

    if short.iloc[-1] > short.mean() and long.iloc[-1] > long.mean():
        return "🟢 多時間一致上升（趨勢穩定）"
    elif short.iloc[-1] < short.mean() and long.iloc[-1] < long.mean():
        return "🔴 多時間一致下跌（風險高）"
    return "🟡 分歧（短長線方向未一致）"

def breakout(data):
    high = data.max()
    low = data.min()
    price = data.iloc[-1]

    if price > high * 0.995:
        return "🚀 突破阻力（有機會加速上升）"
    elif price < low * 1.005:
        return "💥 跌穿支持（小心繼續下跌）"
    return "📊 未見明顯突破"

def support_resistance(data):
    return data.min(), data.max()

# =========================
# DECISION
# =========================
def entry_signal(rsi, macd, sig, drop):
    if drop <= -8 and rsi < 35 and macd > sig:
        return "🟢🟢 強力入場（高機會反彈）"
    elif drop <= -5 and rsi < 40:
        return "🟢 入場機會（回調後可能反彈）"
    elif rsi > 65:
        return "🔴 過熱（短期可能回落）"
    return "🟡 觀察中（未有明確方向）"

def action(signal):
    if "強力" in signal:
        return "👉 分2注（15–20%資金）\n👉 回調再加"
    elif "入場" in signal:
        return "👉 小注（約10%資金）\n👉 再跌再加"
    elif "過熱" in signal:
        return "👉 唔好追高\n👉 可考慮減倉"
    return "👉 等待更好機會"

def rr():
    risk = 5
    reward = 12
    return reward / risk, risk, reward

def rr_text(rr):
    return "🟢🟢 高質機會（回報大於風險）" if rr >= 2 else "🟡 一般機會"

def warning(rsi, drop):
    if rsi > 70:
        return "⚠️ 市場過熱，小心回調"
    if drop < -10:
        return "⚠️ 跌勢強，避免接飛刀"
    return ""

# =========================
# NEWS
# =========================
def get_news(symbol):
    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        return requests.get(url).json()["articles"][:2]
    except:
        return []

def news_sentiment(text):
    if any(w in text.lower() for w in ["growth","strong","beat"]):
        return "🟢 利好"
    if any(w in text.lower() for w in ["drop","miss","cut"]):
        return "🔴 利淡"
    return "🟡 中性"

# =========================
# SEND
# =========================
def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# =========================
# MAIN
# =========================
def run():
    msg = "🚀 AlphaCore AI v∞（清晰版）\n\n🚗 波段交易區\n━━━━━━━━━━━━━━━\n"

    for s in STOCKS:
        data = get_data(s)
        price = data.iloc[-1]

        rsi = calc_rsi(data).iloc[-1]
        macd, sig = calc_macd(data)
        drop = calc_drop(data)

        struct = structure(data)
        tr = trend(data)
        mtf = multi_tf(s)
        br = breakout(data)
        sup, res = support_resistance(data)

        signal = entry_signal(rsi, macd, sig, drop)
        rr_val, risk, reward = rr()

        msg += f"""
📊 {s} | 💰 {price:.2f}

💡 交易信號：
{signal}
{action(signal)}

🎯 交易質素：
{rr_text(rr_val)}

📊 R/R 1:{rr_val:.1f}
👉 潛在回報 +{reward}%
👉 潛在風險 -{risk}%

📊 市場情況：
{struct}
{tr}
{mtf}

🚀 關鍵信號：
{br}

🧱 支持位：{sup:.2f}
🚧 阻力位：{res:.2f}

{warning(rsi, drop)}
"""

        news = get_news(s)
        for n in news:
            msg += f"📰 {news_sentiment(n['title'])} {n['title']}\n"

        msg += "\n━━━━━━━━━━━━━━━\n"

    send(msg)

while True:
    run()
    time.sleep(600)
