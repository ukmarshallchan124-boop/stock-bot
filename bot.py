from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

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
        requests.post(f"{URL}/sendMessage", json=data, timeout=10)
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
        spy = yf.Ticker("SPY").history(period="5d")
        change = (spy["Close"].iloc[-1] - spy["Close"].iloc[-3]) / spy["Close"].iloc[-3]*100
        if change > 1:
            return "📈 市場偏強（Risk ON）", 10
        elif change < -1:
            return "📉 市場偏弱（Risk OFF）", -10
        return "⚪ 市場震盪", 0
    except:
        return "⚪ 市場未知", 0

# ======================
# FETCH
# ======================
def fetch(symbol, interval):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval=interval)
        if df.empty:
            df = yf.Ticker(symbol).history(period="1mo")
        return df if not df.empty else None
    except:
        return None

# ======================
# TRUE SUPPORT / RESISTANCE
# ======================
def support_resistance(df):
    low = df["Low"].rolling(20).min().iloc[-1]
    high = df["High"].rolling(20).max().iloc[-1]
    return low, high

# ======================
# INDICATORS
# ======================
def indicators(df):
    close = df["Close"]

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    rs = gain.rolling(14).mean() / loss.rolling(14).mean()
    rsi = round((100 - (100/(1+rs))).iloc[-1],1)

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()

    macd_val = macd.iloc[-1] - signal.iloc[-1]

    return rsi, macd_val

# ======================
# TRUE MTF
# ======================
def mtf(symbol):
    df = fetch(symbol,"1h")
    if df is None:
        return None

    df_4h = df.resample("4H").last()

    close_4h = df_4h["Close"]
    close_1h = df["Close"]

    trend_4h = close_4h.iloc[-1] > close_4h.ewm(span=50).mean().iloc[-1]
    trend_1h = close_1h.iloc[-1] > close_1h.ewm(span=20).mean().iloc[-1]

    pullback = close_1h.iloc[-1] < close_1h.rolling(10).max().iloc[-1]

    return trend_4h, trend_1h, pullback

# ======================
# AI SCORE（加權）
# ======================
def ai_score(df, symbol):
    score = 0

    mtf_data = mtf(symbol)
    if mtf_data:
        t4, t1, pb = mtf_data
        if t4: score += 20
        if t1: score += 15
        if pb: score += 10

    rsi, macd = indicators(df)

    if 50 < rsi < 65: score += 15
    elif rsi > 70: score -= 15

    if macd > 0: score += 15
    else: score -= 5

    _, mscore = market_trend()
    score += mscore

    return max(0, min(100, score))

# ======================
# DATA
# ======================
def get_data(symbol):
    df = fetch(symbol,"15m")
    if df is None:
        return None

    price = df["Close"].iloc[-1]

    support, resistance = support_resistance(df)

    entry_low = support
    entry_high = support * 1.02
    stop = support * 0.97
    target = resistance

    rr = round((target-entry_low)/(entry_low-stop),2)

    return df, {
        "price": round(price,2),
        "entry_low": round(entry_low,2),
        "entry_high": round(entry_high,2),
        "stop": round(stop,2),
        "target": round(target,2),
        "rr": rr
    }

# ======================
# TIMING
# ======================
def timing(df):
    ema9 = df["Close"].ewm(span=9).mean()
    ema21 = df["Close"].ewm(span=21).mean()
    return ema9.iloc[-1] > ema21.iloc[-1]

# ======================
# NEWS（改善版）
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:5]

        txt = ""
        score = 0

        for n in news:
            title = n.get("title","")
            txt += f"• {title}\n"

            if any(w in title.lower() for w in ["earnings","beat","ai","growth"]):
                txt += "🟢 利好\n\n"
                score += 1
            elif any(w in title.lower() for w in ["cut","risk","drop","downgrade"]):
                txt += "🔴 利淡\n\n"
                score -= 1
            else:
                txt += "⚪ 中性\n\n"

        summary = "🟢 偏利好" if score>1 else "🔴 偏利淡" if score<-1 else "⚪ 中性"

        return txt, summary
    except:
        return "⚪ 無新聞", "⚪ 中性"

# ======================
# POSITION SIZE
# ======================
def position_size(entry, stop, capital=1000, risk_pct=1):
    risk = capital * (risk_pct/100)
    per_share = abs(entry-stop)
    return round(risk/per_share,2) if per_share else 0

# ======================
# FORMAT（最終UI）
# ======================
def format_output(symbol, d, df):
    score = ai_score(df, symbol)
    success = int(score * 0.85)

    rsi, macd_val = indicators(df)
    macd = "🟢 動能向上" if macd_val > 0 else "🔴 偏弱"

    mtf_data = mtf(symbol)
    if not mtf_data:
        return f"{symbol} 無數據"

    t4, t1, pb = mtf_data

    trend = "📈 偏強" if t4 else "📉 偏弱"
    timing_text = "🟡 等回調" if pb else "🟢 可留意"

    news_txt, news_summary = get_news(symbol)
    market, _ = market_trend()

    size = position_size(d["entry_low"], d["stop"])

    return f"""
📊【{symbol} 波段分析｜PRO】

💰 價格：{d['price']}
🎯 AI信心：{score}/100
🏆 勝率估算：{success}%
⏱️ Timing：{timing_text}

{trend}

━━━━━━━━━━━━━━━

📊 結構分析：
4H：{"🟢 上升" if t4 else "🔴 轉弱"}
1H：{"🟡 回調" if pb else "🟢 延續"}
15m：{"🟢 轉強" if timing(df) else "⚪ 未確認"}

RSI：{rsi}
MACD：{macd}

━━━━━━━━━━━━━━━

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

━━━━━━━━━━━━━━━

💰 策略🔥

👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}
💸 倉位：約 {size} 股（1%風險）

━━━━━━━━━━━━━━━

🌍 {market}

━━━━━━━━━━━━━━━

🧠 總結：

👉 {"❌ 唔好追" if not pb else "🟡 等回調"}
👉 ✔ 入區先考慮

━━━━━━━━━━━━━━━

📰【新聞】

{news_txt}
🧠 {news_summary}
"""

# ======================
# LOOP（ANTI SPAM）
# ======================
def loop():
    while True:
        try:
            now = time.time()

            for s in SWING_STOCKS:
                data = get_data(s)
                if not data:
                    continue

                df, d = data
                score = ai_score(df, s)

                state = signal_state.get(s, {"entry":0,"setup":0,"price":None})

                price = d["price"]
                price_changed = state["price"] is None or abs(price - state["price"]) / price > 0.01

                in_zone = d["entry_low"] <= price <= d["entry_high"]
                momentum = df["Close"].diff().iloc[-3:].mean()

                if score >= 75 and in_zone and timing(df) and momentum > 0:
                    if now - state["entry"] > ENTRY_COOLDOWN and price_changed:
                        send(CHAT_ID, f"🚀【{s} Entry】\n{d['entry_low']} - {d['entry_high']}")
                        state["entry"] = now
                        state["price"] = price

                signal_state[s] = state

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e)

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK
# ======================
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text in ["/start","start"]:
        send(chat_id,"🚀 V36 PRO（Trading Grade）",menu())

    elif "波段分析" in text:
        for s in SWING_STOCKS:
            data = get_data(s)
            if data:
                df, d = data
                send(chat_id, format_output(s,d,df), menu())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
