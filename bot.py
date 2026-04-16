import requests
import pandas as pd
import time
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

STOCKS = ["TSLA", "NVDA", "AMD"]
LONG_TERM = ["SPY", "MSFT"]

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
def get_data(symbol, interval="5m"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval={interval}"
        data = safe_request(url)

        if not data or not data.get("chart") or not data["chart"]["result"]:
            return None

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
# ANALYSIS
# =========================
def structure(data):
    return "📈 上升結構（整體向上）" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構（轉弱）"

def trend(data):
    return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"

def multi_tf(symbol):
    try:
        s = get_data(symbol, "5m")
        l = get_data(symbol, "1h")
        if s is None or l is None:
            return "📊 多時間不足"
        if s.iloc[-1] > s.mean() and l.iloc[-1] > l.mean():
            return "🟢 多時間一致上升"
        elif s.iloc[-1] < s.mean() and l.iloc[-1] < l.mean():
            return "🔴 多時間一致下跌"
        return "🟡 分歧"
    except:
        return "📊 錯誤"

def market_state(rsi):
    if rsi > 65:
        return "📈 偏強（小心追高）"
    elif rsi < 35:
        return "📉 回調區（留意反彈）"
    return "📊 正常波動"

def breakout(data):
    try:
        high = data.max()
        low = data.min()
        price = data.iloc[-1]
        if price > high * 0.995:
            return "🚀 突破阻力"
        elif price < low * 1.005:
            return "💥 跌穿支持"
        return "📊 無突破"
    except:
        return ""

def support_resistance(data):
    try:
        return data.min(), data.max()
    except:
        return 0, 0

# =========================
# DECISION
# =========================
def entry_signal(rsi, macd, sig, drop):
    if drop <= -8 and rsi < 35 and macd > sig:
        return "🟢🟢 強力入場"
    elif drop <= -5 and rsi < 40:
        return "🟢 入場機會"
    elif rsi > 65:
        return "🔴 過熱"
    return "🟡 觀察中"

def action(signal):
    if "強力" in signal:
        return "👉 分2注（15–20%）"
    elif "入場" in signal:
        return "👉 小注（10%）"
    elif "過熱" in signal:
        return "👉 唔好追"
    return "👉 等待"

def rr():
    return 2.4, 5, 12

def rr_text(rr):
    if rr >= 2:
        return "🟢🟢 高質"
    elif rr >= 1:
        return "🟡 一般"
    return "🔴 低質"

def profit(change):
    if change >= 20:
        return "💰 +20% 鎖利"
    elif change >= 10:
        return "🟡 +10% 留意"
    return ""

def ai(rsi, struct, br):
    if "突破" in br:
        return "🚀 AI：偏強"
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
        return data.get("articles", [])[:2] if data else []
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
    try:
        if not BOT_TOKEN or not CHAT_ID:
            print("❌ TOKEN 未設")
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# =========================
# MAIN
# =========================
def run():
    msg = "🚀 AlphaCore AI v∞++（Ultimate）\n\n"

    # ===== 波段 =====
    msg += "🚗 波段交易區\n━━━━━━━━━━━━━━━\n"

    for s in STOCKS:
        data = get_data(s)

        if data is None:
            msg += f"\n📊 {s}\n⚠️ 無數據\n━━━━━━━━━━━━━━━\n"
            continue

        price = data.iloc[-1]
        rsi = calc_rsi(data)
        macd, sig = calc_macd(data)
        drop = calc_drop(data)
        change = (price - data.iloc[0]) / data.iloc[0] * 100

        struct = structure(data)
        tr = trend(data)
        mtf = multi_tf(s)
        ms = market_state(rsi)
        br = breakout(data)
        sup, res = support_resistance(data)

        signal = entry_signal(rsi, macd, sig, drop)
        rr_val, risk, reward = rr()

        msg += f"""
📊 {s} | 💰 {price:.2f}

💡 {signal}
{action(signal)}

🎯 {rr_text(rr_val)} | R/R 1:{rr_val}
👉 +{reward}% / -{risk}%

📊 {struct} | {tr}
📡 {mtf}
{ms}

{br}

🧱 支持 {sup:.2f}
🚧 阻力 {res:.2f}

🧠 {ai(rsi, struct, br)}
{profit(change)}
"""

        news = get_news(s)
        for n in news:
            msg += f"📰 {news_sentiment(n['title'])} {n['title']}\n"

        msg += "\n━━━━━━━━━━━━━━━\n"

    # ===== 長線 =====
    msg += "\n🟩 長線投資區（DCA）\n━━━━━━━━━━━━━━━\n"
    msg += """
📊 S&P500（SPY）
🟢 每月定投
👉 跌市加碼

📊 Microsoft（MSFT）
🟡 長線持有
👉 回調先加
"""

    send(msg)

# =========================
# LOOP（不死）
# =========================
while True:
    try:
        run()
    except Exception as e:
        print("主錯誤:", e)

    time.sleep(600)
