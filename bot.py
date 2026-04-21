from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

last_alert = {}
cache = {}
CACHE_TTL = 120

# ======================
# DATA
# ======================
def get_df(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if len(cache) > 100:
        cache.clear()

    if key in cache:
        data, ts = cache[key]
        if now - ts < CACHE_TTL:
            return data

    try:
        df = yf.Ticker(symbol).history(period="2d", interval=interval)
        if df is None or df.empty or len(df) < 50:
            return None

        cache[key] = (df.copy(), now)
        return df

    except Exception as e:
        print("DATA ERROR:", e)
        return None

# ======================
# TREND
# ======================
def get_trend(symbol):
    df = get_df(symbol,"15m")
    if df is None or df.empty:
        return "未知"

    ma = df["Close"].rolling(20).mean().iloc[-1]
    return "上升" if df["Close"].iloc[-1] > ma else "下降"

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

        risk = entry_low - stop
        rr = (target - entry_low) / risk if risk > 0 else 0

        return {
            "price": price,
            "rsi": rsi,
            "trend_up": trend_up,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop": stop,
            "target": target,
            "rr": rr,
            "macd_up": macd_up
        }

    except Exception as e:
        print("CALC ERROR:", e)
        return None

# ======================
# SIGNAL ENGINE
# ======================
def signal_engine(df, d):
    price = d["price"]

    recent_high = df["High"].iloc[-20:-3].max()
    recent_low = df["Low"].iloc[-20:-3].min()

    vol = df["Volume"]
    vol_ma = vol.rolling(10).mean().iloc[-1]

    volume_spike = False
    if vol_ma is not None and not pd.isna(vol_ma):
        volume_spike = vol.iloc[-1] > vol_ma * 1.5 and vol_ma > 50000

    breakout = (
        df["Close"].iloc[-1] > recent_high and
        df["Close"].iloc[-2] > recent_high
    )

    in_entry = d["entry_low"] <= price <= d["entry_high"] and d["macd_up"]
    near_entry = d["entry_low"]*0.999 < price < d["entry_high"]*1.001

    risk_off = (
        df["Close"].iloc[-2] < recent_low and
        df["Close"].iloc[-1] < recent_low
    )

    good_rr = d["rr"] > 1.5
    good_rsi = 52 < d["rsi"] < 65

    if risk_off:
        decision = "RISK"
    elif breakout and volume_spike and d["trend_up"] and good_rr and d["rsi"] < 70:
        decision = "BREAKOUT"
    elif in_entry and d["trend_up"] and good_rsi and good_rr:
        decision = "ENTRY"
    elif near_entry:
        decision = "SETUP"
    else:
        decision = "WAIT"

    return {
        "decision": decision,
        "volume_spike": volume_spike
    }

# ======================
# MARKET FILTER
# ======================
def market_filter():
    df = get_df("SPY","15m")
    if df is None or df.empty:
        return True, "⚠️ 無法判斷市場"

    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]

    trend = df["Close"].iloc[-1] > ma20
    momentum = ma5 > ma20

    if not trend and not momentum:
        return False, "🔴 Risk OFF（轉弱）"
    else:
        return True, "🟢 Risk ON（市場健康）"

# ======================
# LOOP
# ======================
def loop():
    try:
        now = time.time()
        allow_trade, _ = market_filter()
        candidates = []

        for s in SYMBOLS:
            df = get_df(s, "5m")
            df_15 = get_df(s, "15m")

            if df is None or df.empty or df_15 is None or df_15.empty:
                continue

            if len(df) < 25:
                continue

            d = calc(df)
            if not d:
                continue

            sig = signal_engine(df, d)
            decision = sig["decision"]

            ma20_15 = df_15["Close"].rolling(20).mean().iloc[-1]
            trend_15 = df_15["Close"].iloc[-1] > ma20_15
            if not trend_15:
                continue

            recent_high = df["High"].iloc[-20:-3].max()
            fake_bo = (
                df["Close"].iloc[-1] > recent_high and
                df["Close"].iloc[-2] < recent_high
            )
            if fake_bo:
                continue

            if not allow_trade:
                continue

            score = 0
            if decision == "ENTRY": score += 2
            if decision == "BREAKOUT": score += 2.5
            if d["macd_up"]: score += 1
            if sig["volume_spike"]: score += 1
            if d["rr"] > 2: score += 1

            if score < 3.5:
                continue

            candidates.append((s, d, score, decision))

            # ENTRY alert
            if decision == "ENTRY":
                if now - last_alert.get(s+"_entry", 0) > 1800:
                    send(CHAT_ID, f"🟢 ENTRY {s} | {round(d['price'],2)}")
                    last_alert[s+"_entry"] = now

        # TOP SIGNAL
        if candidates:
            s, d, score, decision = sorted(candidates, key=lambda x: x[2], reverse=True)[0]

            if now - last_alert.get(s, 0) > 600:
                send(CHAT_ID, f"🚀 TOP {s} | Score {round(score,1)}")
                last_alert[s] = now

    except Exception as e:
        print("LOOP ERROR:", e)

# ======================
# AUTO LOOP
# ======================
def auto_loop():
    while True:
        loop()
        time.sleep(300)

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(
            f"{URL}/sendMessage",
            json={"chat_id": chat_id, "text": msg[:4000]},
            timeout=10
        )
    except Exception as e:
        print("SEND ERROR:", e)

# ======================
# WEBHOOK
# ======================
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "ok"

    message = data.get("message")
    if not message:
        return "ok"

    chat_id = message["chat"]["id"]
    text = message.get("text", "").lower()

    if "/start" in text:
        send(chat_id, "Bot Ready 🚀")
    elif "/stock" in text:
        loop()
        send(chat_id, "Scan done")

    return "ok"

@app.route("/scan")
def scan():
    loop()
    return "scan done"

# ======================
# RUN
# ======================
if __name__ == "__main__":
    threading.Thread(target=auto_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
