from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import math

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

last_alert = {}
cache = {}
CACHE_TTL = 120
# ======================
# Signal Engine
# ======================
def signal_engine(df, d):
    try:
        price = d["price"]

        # === 結構（Structure）
        recent_high = df["High"].iloc[-20:-3].max()
        recent_low = df["Low"].iloc[-20:-3].min()

        # === Setup 判斷
        if d["trend_up"]:
            setup = "Pullback (Bullish)"
        else:
            setup = "Weak / Range"

        # === Entry 區
        entry_low = d["entry_low"]
        entry_high = d["entry_high"]

        in_entry = entry_low <= price <= entry_high

        # === Breakout
        breakout = (
            df["Close"].iloc[-1] > recent_high and
            df["Close"].iloc[-2] > recent_high
        )

        # === Risk Off（跌穿結構）
        risk_off = price < recent_low

        # === Decision（最重要）
        if breakout:
            decision = "🚀 BREAKOUT"
        elif in_entry:
            decision = "🟢 ENTRY"
        elif risk_off:
            decision = "🔴 RISK OFF"
        else:
            decision = "🟡 WAIT"

        return {
            "setup": setup,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "breakout": round(recent_high,2),
            "risk_off": round(recent_low,2),
            "decision": decision
        }

    except Exception as e:
        print("SIGNAL ERROR:", e)
        return None

# ======================
# DATA
# ======================
def get_df(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in cache:
        data, ts = cache[key]
        if now - ts < CACHE_TTL:
            return data

    try:
        df = yf.Ticker(symbol).history(period="2d", interval=interval)

        if df is None or df.empty or len(df) < 50:
            return None

        last_time = df.index[-1].to_pydatetime().timestamp()
        if time.time() - last_time > 900:
            return None

        cache[key] = (df.copy(), now)

        if len(cache) > 60:
            oldest = min(cache.items(), key=lambda x: x[1][1])[0]
            del cache[oldest]

        return df
    except Exception as e:
        print("DATA ERROR:", e)
        return None


# ======================
# SEND
# ======================
def send(chat_id, msg):
    if not chat_id or not msg or not msg.strip():
        return
    try:
        requests.post(
            f"{URL}/sendMessage",
            json={"chat_id": chat_id, "text": msg[:4000]},
            timeout=10
        )
    except Exception as e:
        print("SEND ERROR:", e)


# ======================
# CALC
# ======================
def calc(df):
    try:
        price = float(df["Close"].iloc[-1])

        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        gain_ema = gain.ewm(alpha=1/14).mean()
        loss_ema = loss.ewm(alpha=1/14).mean()

        rs = gain_ema / (loss_ema + 1e-10)
        rsi = round((100 - (100 / (1 + rs))).iloc[-1],1)

        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_up = (ema12 - ema26).iloc[-1] > (ema12 - ema26).ewm(span=9).mean().iloc[-1]

        ma20 = df["Close"].rolling(20).mean().iloc[-1]
        trend_up = price > ma20

        high = float(df["High"].max())
        low = float(df["Low"].min())

        entry_low = low * 1.01
        entry_high = low * 1.03
        stop = low * 0.97
        target = high * 1.02

        rr = (target - entry_low) / (entry_low - stop) if entry_low > stop else 0

        return {
            "price": price,
            "rsi": rsi,
            "macd_up": macd_up,
            "trend_up": trend_up,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop": stop,
            "target": target,
            "rr": rr
        }

    except Exception as e:
        print("CALC ERROR:", e)
        return None


# ======================
# COMMAND
# ======================
def stock_all():
    msg = "📊【Stock Scanner｜美股掃描】\n\n"

    for s in SYMBOLS:
        df = get_df(s,"5m")
        if not df:
            msg += f"⚠️ {s} Data Error\n\n"
            continue

        d = calc(df)
        if not d:
            msg += f"⚠️ {s} Calc Error\n\n"
            continue

        # ===== SIGNAL LOGIC（升級版）=====
        setup = "Range"
        if d["trend_up"]:
            setup = "Pullback (Uptrend)"
        else:
            setup = "Weak Structure"

        # entry 判斷
        if d["entry_low"] <= d["price"] <= d["entry_high"]:
            decision = "🟢 ENTER"
        elif d["price"] < d["entry_low"]:
            decision = "🟡 WAIT"
        else:
            decision = "⚠️ EXTENDED"

        # momentum
        momentum = "Strong" if d["macd_up"] else "Weak"

        msg += f"""📌 {s} — Intraday

💰 Price: {round(d['price'],2)}
📈 Trend: {"Uptrend" if d['trend_up'] else "Downtrend"}
⚡ Momentum: {momentum}

🧠 Setup: {setup}
🎯 Entry: {round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 Risk Off: {round(d['stop'],2)}
🚀 Target: {round(d['target'],2)}

📊 R/R: {round(d['rr'],2)}

{decision}
━━━━━━━━━━━━━━
"""

    return msg


def market():
    df = get_df("SPY","15m")
    if not df:
        return "⚠️ 市場數據錯誤"

    d = calc(df)
    if not d:
        return "⚠️ 市場計算錯誤"

    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]

    strength = abs(ma5-ma20)/ma20

    if strength < 0.002:
        state = "⚠️ Sideways"
    elif ma5 < ma20:
        state = "🔻 Downtrend"
    else:
        state = "🟢 Uptrend"

    return f"🌍 市場狀態\n{state}"


def gold():
    return "🥇 Gold → Hedge"


def long_term():
    msg = "📈【Long-Term Portfolio｜長線配置】\n\n"

    msg += analyze_long("MSFT", "Microsoft")
    msg += analyze_long("SPY", "S&P 500")
    msg += analyze_long("VT", "World Index")
    msg += analyze_long("GLD", "Gold ETF")

    return msg
# ======================
# UI（專業版）
# ======================
def analyze_long(symbol, name):
    df = get_df(symbol, "1d")
    if not df:
        return f"⚠️ {name} Data Error\n\n"

    d = calc(df)
    if not d:
        return f"⚠️ {name} Calc Error\n\n"

    price = round(d["price"],2)

    # 趨勢
    trend = "Uptrend" if d["trend_up"] else "Downtrend"

    # 狀態判斷
    if d["rsi"] > 70:
        state = "Overbought"
        decision = "⚠️ WAIT DIP"
        strategy = "Avoid chasing"
    elif d["rsi"] < 40:
        state = "Undervalued Zone"
        decision = "🟢 ACCUMULATE"
        strategy = "DCA / Buy"
    else:
        state = "Neutral"
        decision = "🟡 HOLD"
        strategy = "DCA Slowly"

    return f"""🟦 {name} ({symbol})

💰 Price: {price}
📈 Trend: {trend}
📊 RSI: {d['rsi']}

🧠 Strategy: {strategy}
📅 Plan: Weekly DCA
⚠️ State: {state}

{decision}
━━━━━━━━━━━━━━
"""
# ======================
# LOOP
# ======================
def loop():
    while True:
        try:
            now = time.time()

            for s in SYMBOLS:
                df = get_df(s,"5m")
                if not df:
                    continue

                d = calc(df)
                if not d:
                    continue

                recent_high = df["High"].iloc[-15:-3].max()

                breakout = (
                    df["Close"].iloc[-1] > recent_high and
                    df["Close"].iloc[-2] > recent_high
                )

                if breakout and now - last_alert.get(s,0) > 600:
                    send(CHAT_ID,f"📢 Breakout {s}")
                    last_alert[s] = now

            time.sleep(300)

        except Exception as e:
            print("ERROR:", e)
            time.sleep(10)


# ======================
# THREAD
# ======================
def start_background():
    if not getattr(start_background, "started", False):
        threading.Thread(target=loop, daemon=True).start()
        start_background.started = True


start_background()


# ======================
# WEBHOOK（完全修復）
# ======================
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not data:
        return "ok"

    message = data.get("message") or data.get("edited_message") or data.get("channel_post")

    if not message:
        return "ok"

    chat_id = message["chat"]["id"]
    text = message.get("text","")

    if not text:
        return "ok"

    text = text.lower()

    print("RECEIVED:", text)

    if "/start" in text:
        send(chat_id,"🚀 Bot Ready\n/stock /market /gold /long")

    elif "/stock" in text:
        send(chat_id,stock_all())

    elif "/market" in text:
        send(chat_id,market())

    elif "/gold" in text:
        send(chat_id,gold())

    elif "/long" in text:
        send(chat_id,long_term())

    return "ok"


@app.route("/")
def home():
    return "running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
