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
# DATA（穩定 + cache）
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
# 分析腦（UI）
# ======================
def stock_all():
    msg = "📊【市場掃描】\n\n"

    for s in SYMBOLS:
        df = get_df(s,"5m")
        if not df:
            continue

        d = calc(df)
        if not d:
            continue

        zone = "🟡 Watch"
        if d["entry_low"] <= d["price"] <= d["entry_high"]:
            zone = "🟢 Entry Zone"

        msg += f"""📌 {s}
💰 {round(d['price'],2)} ｜ RSI {d['rsi']}
Trend: {"Up" if d['trend_up'] else "Down"}

🎯 Entry {round(d['entry_low'],2)}-{round(d['entry_high'],2)}
🛑 Stop {round(d['stop'],2)}
🎯 Target {round(d['target'],2)}
📊 RR {round(d['rr'],2)}

📌 策略：
👉 {"可考慮入場" if zone=="🟢 Entry Zone" else "等待確認"}

{zone}
━━━━━━━━━━━━━━
"""
    return msg or "⚠️ 無數據"


def market():
    df = get_df("SPY","15m")
    if not df:
        return "⚠️ 市場數據錯誤"

    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]

    if ma5 < ma20:
        state = "🔻 Downtrend"
    else:
        state = "🟢 Uptrend"

    return f"🌍 市場狀態\n{state}"


def gold():
    return "🥇 Gold → Hedge"


def long_term():
    return "📈 長線 DCA"


# ======================
# 交易腦（Signal Engine）
# ======================
def loop():
    while True:
        try:
            now = time.time()
            candidates = []

            spy = get_df("SPY","15m")
            allow_trade = True

            if spy:
                ma20 = spy["Close"].rolling(20).mean().iloc[-1]
                ma5 = spy["Close"].rolling(5).mean().iloc[-1]

                if ma5 < ma20:
                    allow_trade = False

                    if now - last_alert.get("risk",0) > 1800:
                        send(CHAT_ID,"🚨【Risk Off】市場轉弱 → 減倉")
                        last_alert["risk"] = now

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

                vol = df["Volume"]
                vol_ma = vol.rolling(10).mean().iloc[-1]
                volume_spike = vol.iloc[-1] > vol_ma * 1.5

                # Setup
                if d["entry_low"]*0.995 < d["price"] < d["entry_high"]*1.005:
                    if now - last_alert.get(s+"_setup",0) > 1800:
                        send(CHAT_ID,f"👀【Setup】{s}\n接近入場區")
                        last_alert[s+"_setup"] = now

                # Breakout
                if breakout and now - last_alert.get(s+"_bo",0) > 1800:
                    send(CHAT_ID,f"📢【Breakout】{s}")
                    last_alert[s+"_bo"] = now

                # Entry
                if (
                    allow_trade
                    and breakout
                    and volume_spike
                    and d["trend_up"]
                    and 55 < d["rsi"] < 68
                    and d["rr"] > 1.5
                ):
                    score = d["rr"]*2 + (70-abs(d["rsi"]-60))

                    grade = "C"
                    if score > 10:
                        grade="A"
                    elif score > 7:
                        grade="B"

                    candidates.append((s,d,score,grade))

            if candidates:
                top = sorted(candidates,key=lambda x:x[2],reverse=True)[:3]

                msg = "🚀【Top Signals】\n\n"

                for s,d,score,grade in top:
                    if now - last_alert.get(s,0) > 600:
                        msg += f"""📈 {s} ｜ Grade {grade}

🎯 Entry {round(d['entry_low'],2)}-{round(d['entry_high'],2)}
🛑 Stop {round(d['stop'],2)}
🎯 Target {round(d['target'],2)}

📊 RR {round(d['rr'],2)}

━━━━━━━━━━━━━━
"""
                        last_alert[s] = now

                send(CHAT_ID,msg)

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
# WEBHOOK
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
    text = message.get("text","").lower()

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
