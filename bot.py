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
# SAFE REQUEST（防API死）
# =========================
def safe_request(url):
    try:
        res = requests.get(url, timeout=10)
        return res.json()
    except Exception as e:
        print("Request error:", e)
        return None

# =========================
# DATA（防crash）
# =========================
def get_data(symbol, interval="5m"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval={interval}"
        data = safe_request(url)

        if not data or not data.get("chart") or not data["chart"]["result"]:
            print(f"{symbol} 無數據")
            return None

        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]

        series = pd.Series(closes).dropna()

        if len(series) < 30:
            return None

        return series

    except Exception as e:
        print(f"{symbol} error:", e)
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
        return 100 - (100 / (1 + rs))
    except:
        return pd.Series([50])

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
        high = data.max()
        current = data.iloc[-1]
        return (current - high) / high * 100
    except:
        return 0

# =========================
# ANALYSIS
# =========================
def structure(data):
    try:
        return "📈 上升結構（整體向上）" if data.iloc[-1] > data.iloc[-3] else "📉 下降結構（整體轉弱）"
    except:
        return "📊 結構未知"

def trend(data):
    try:
        return "📈 上升趨勢" if data.iloc[-1] > data.mean() else "📉 下跌趨勢"
    except:
        return "📊 趨勢未知"

def multi_tf(symbol):
    try:
        short = get_data(symbol, "5m")
        long = get_data(symbol, "1h")

        if short is None or long is None:
            return "📊 多時間資料不足"

        if short.iloc[-1] > short.mean() and long.iloc[-1] > long.mean():
            return "🟢 多時間一致上升（趨勢穩定）"
        elif short.iloc[-1] < short.mean() and long.iloc[-1] < long.mean():
            return "🔴 多時間一致下跌（風險高）"
        return "🟡 分歧（短長線未一致）"
    except:
        return "📊 多時間錯誤"

def breakout(data):
    try:
        high = data.max()
        low = data.min()
        price = data.iloc[-1]

        if price > high * 0.995:
            return "🚀 突破阻力（可能加速上升）"
        elif price < low * 1.005:
            return "💥 跌穿支持（小心下跌）"
        return "📊 無突破"
    except:
        return "📊 無法判斷"

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
        return "🟢🟢 強力入場（高機會反彈）"
    elif drop <= -5 and rsi < 40:
        return "🟢 入場機會（回調反彈）"
    elif rsi > 65:
        return "🔴 過熱（小心回落）"
    return "🟡 觀察中"

def action(signal):
    if "強力" in signal:
        return "👉 分2注（15–20%）\n👉 回調再加"
    elif "入場" in signal:
        return "👉 小注（10%）\n👉 再跌再加"
    elif "過熱" in signal:
        return "👉 唔好追\n👉 可減倉"
    return "👉 等待"

def rr():
    risk = 5
    reward = 12
    return reward / risk, risk, reward

def rr_text(rr):
    if rr >= 2:
        return "🟢🟢 高質（回報大於風險）"
    elif rr >= 1:
        return "🟡 一般"
    return "🔴 低質"

def warning(rsi, drop):
    if rsi > 70:
        return "⚠️ 過熱，小心回調"
    if drop < -10:
        return "⚠️ 跌勢強，唔好接飛刀"
    return ""

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
# SEND（防死）
# =========================
def send(msg):
    try:
        if not BOT_TOKEN or not CHAT_ID:
            print("❌ BOT_TOKEN 或 CHAT_ID 未設定")
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Send error:", e)

# =========================
# MAIN
# =========================
def run():
    msg = "🚀 AlphaCore AI v∞+（不死版）\n\n🚗 波段交易區\n━━━━━━━━━━━━━━━\n"

    for s in STOCKS:
        data = get_data(s)

        if data is None:
            msg += f"\n📊 {s}\n⚠️ 無法取得數據\n━━━━━━━━━━━━━━━\n"
            continue

        try:
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
👉 回報 +{reward}%
👉 風險 -{risk}%

📊 市場情況：
{struct}
{tr}
{mtf}

🚀 關鍵：
{br}

🧱 支持：{sup:.2f}
🚧 阻力：{res:.2f}

{warning(rsi, drop)}
"""

            news = get_news(s)
            for n in news:
                msg += f"📰 {news_sentiment(n['title'])} {n['title']}\n"

            msg += "\n━━━━━━━━━━━━━━━\n"

        except Exception as e:
            msg += f"\n⚠️ {s} 分析錯誤\n"
            print("分析錯:", e)

    send(msg)

# =========================
# LOOP（永遠唔死🔥）
# =========================
while True:
    try:
        run()
    except Exception as e:
        print("主程式錯誤:", e)

    time.sleep(600)
