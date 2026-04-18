from flask import Flask, request
import requests, os, time, threading, json
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("TWELVE_API_KEY")

URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

cache = {}
signal_state = {}

SETUP_COOLDOWN = 1800
ENTRY_COOLDOWN = 3600

# ======================
# SEND
# ======================
def send(chat_id, text, keyboard=None):
    try:
        data = {"chat_id": chat_id, "text": text[:4000]}
        if keyboard:
            data["reply_markup"] = keyboard
        requests.post(f"{URL}/sendMessage", json=data)
    except Exception as e:
        print("SEND ERROR:", e)

def menu():
    return {
        "keyboard":[
            ["📊 波段分析","💰 長線投資"],
            ["🧮 計算工具","📍 持倉分析"]
        ],
        "resize_keyboard":True
    }

# ======================
# MARKET
# ======================
def market_trend():
    try:
        spy = yf.Ticker("SPY").history(period="5d", interval="1d")
        if spy.empty:
            return "⚪ 市場未知", True

        change = (spy["Close"].iloc[-1] - spy["Close"].iloc[-3]) / spy["Close"].iloc[-3] * 100

        if change > 1:
            return "📈 美股偏強（Risk ON）", True
        elif change < -1:
            return "📉 美股偏弱（Risk OFF）", False
        else:
            return "⚪ 市場震盪", True
    except:
        return "⚪ 市場未知", True

# ======================
# HYBRID FETCH
# ======================
def fetch_twelve(symbol, interval):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": 100,
            "apikey": API_KEY
        }

        r = requests.get(url, params=params).json()

        if "status" in r and r["status"] == "error":
            return None

        if "values" not in r:
            return None

        data = list(reversed(r["values"]))

        closes = [float(x["close"]) for x in data]
        highs = [float(x["high"]) for x in data]
        lows = [float(x["low"]) for x in data]

        if len(closes) < 20:
            return None

        return closes, highs, lows
    except:
        return None


def fetch_yahoo(symbol, interval):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval=interval)
        if df.empty:
            return None

        return df["Close"].tolist(), df["High"].tolist(), df["Low"].tolist()
    except:
        return None


def fetch(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in cache and now - cache[key]["time"] < 300:
        return cache[key]["data"], False

    data = fetch_twelve(symbol, interval)
    fallback = False

    if not data:
        data = fetch_yahoo(symbol, interval)
        fallback = True

    if data:
        cache[key] = {"data": data, "time": now}

    return data, fallback

# ======================
# INDICATORS
# ======================
def indicators(closes):
    try:
        df = pd.Series(closes)

        delta = df.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        rs = gain.rolling(14).mean()/loss.rolling(14).mean()
        rsi = 100-(100/(1+rs))

        ema12 = df.ewm(span=12).mean()
        ema26 = df.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal = macd_line.ewm(span=9).mean()

        macd = "🟢 上升動能" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴 下跌動能"

        return round(rsi.iloc[-1],1), macd
    except:
        return "N/A", "N/A"

# ======================
# MTF
# ======================
def mtf(symbol):
    data, fb = fetch(symbol,"1h")
    if not data:
        return None, False

    closes = data[0]
    df = pd.Series(closes)

    # ❗修復：唔用 resample
    df_4h = df.iloc[::4]

    ema50_4h = df_4h.ewm(span=50).mean()
    ema20_1h = df.ewm(span=20).mean()

    trend_4h = df_4h.iloc[-1] > ema50_4h.iloc[-1]
    trend_1h = df.iloc[-1] > ema20_1h.iloc[-1]

    pullback = df.iloc[-1] < df.rolling(10).max().iloc[-1]

    return (trend_4h, trend_1h, pullback), fb

# ======================
# ENTRY
# ======================
def entry(symbol):
    data, _ = fetch(symbol,"15min")
    if not data:
        return False

    df = pd.Series(data[0])

    ema9 = df.ewm(span=9).mean()
    ema21 = df.ewm(span=21).mean()

    momentum = df.diff().iloc[-3:].mean()

    return ema9.iloc[-1] > ema21.iloc[-1] and momentum > 0

# ======================
# BASE DATA
# ======================
def get_data(symbol):
    data, fb = fetch(symbol,"15min")
    if not data:
        return None, False

    closes, highs, lows = data

    price = closes[-1]
    high = max(highs)
    low = min(lows)

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02
    rr = (target-entry_low)/(entry_low-stop)

    return {
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2)
    }, fb

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:3]
        return "\n".join([f"• {n['title']}" for n in news]) or "⚪ 無新聞"
    except:
        return "⚪ 無新聞"

# ======================
# FORMAT
# ======================
def format_full(symbol, d, fallback):
    mtf_data,_ = mtf(symbol)
    if not mtf_data:
        return "⚠️ 數據錯誤"

    trend_4h, trend_1h, pullback = mtf_data

    trend4 = "🟢 上升" if trend_4h else "🔴 下跌"
    trend1 = "🟡 回調中" if pullback else "🟢 延續"
    timing = "🟢 轉強" if entry(symbol) else "⚪ 未確認"

    data,_ = fetch(symbol,"15min")
    rsi, macd = indicators(data[0]) if data else ("N/A","N/A")

    market_text,_ = market_trend()
    news = get_news(symbol)

    fb_text = "\n⚠️ 使用備用數據（Yahoo）\n" if fallback else ""

    return f"""
📊【{symbol} 波段分析｜MTF】
{fb_text}
💰 價格：{d['price']}
🌍 市場：{market_text}

━━━━━━━━━━━━━━
📈 4H：{trend4}
📊 1H：{trend1}
⚡ 15m：{timing}

RSI：{rsi}
MACD：{macd}

━━━━━━━━━━━━━━
📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

👉 入場：{d['entry_low']} - {d['entry_high']}
🛑 止蝕：{d['stop']}
🎯 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━
📰 新聞：
{news}
"""

# ======================
# LONG TERM
# ======================
def long_term():
    return """
💰【長線投資】

📊 MSFT：
👉 回調（-5% / -10%）加倉

📈 S&P500：
👉 每月定期買（DCA）
👉 長期持有
"""

# ======================
# ANALYSIS THREAD
# ======================
def run_analysis(chat_id):
    try:
        sent = False

        for s in SWING_STOCKS:
            d, fb = get_data(s)

            if d:
                send(chat_id, format_full(s,d,fb))
                sent = True

        if not sent:
            send(chat_id,"⚠️ 暫時無數據 / API限制")

    except Exception as e:
        print("ANALYSIS ERROR:", e)
        send(chat_id,"❌ 系統錯誤")

# ======================
# WEBHOOK
# ======================
@app.route("/",methods=["POST"])
def webhook():
    try:
        data=request.get_json()
        if not data or "message" not in data:
            return "ok"

        chat_id=data["message"]["chat"]["id"]
        text=data["message"].get("text","").strip()

        if text in ["/start","start"]:
            send(chat_id,"🚀 V30.3 穩定版",menu())

        elif "波段分析" in text:
            send(chat_id,"⏳ 分析中...",menu())
            threading.Thread(target=run_analysis,args=(chat_id,)).start()

        elif "長線投資" in text:
            send(chat_id,long_term(),menu())

        return "ok"

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
