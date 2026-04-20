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
# DATA
# ======================
def get_df(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in cache:
        data, ts = cache[key]
        if data is not None and now - ts < CACHE_TTL:
            return data

    for _ in range(3):
        try:
            df = yf.Ticker(symbol).history(period="2d", interval=interval)

            if df is None or df.empty or len(df) < 50:
                continue

            last_time = df.index[-1].to_pydatetime().timestamp()
            if time.time() - last_time > 900:
                continue

            # freeze
            if df["Close"].iloc[-3:].nunique() == 1 and df["Volume"].iloc[-3:].sum() == 0:
                continue

            cache[key] = (df.copy(), now)

            # remove oldest
            if len(cache) > 60:
                oldest = min(cache.items(), key=lambda x: x[1][1])[0]
                del cache[oldest]

            return df

        except Exception as e:
            print("DATA ERROR:", e)
            time.sleep(1)

    return None


# ======================
# SEND
# ======================
def send(chat_id, msg):
    if not chat_id or not msg.strip():
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

        gain_ema = gain.ewm(alpha=1/14, adjust=False).mean()
        loss_ema = loss_ema = loss.ewm(alpha=1/14, adjust=False).mean()

        rs = gain_ema / (loss_ema + 1e-10)
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        if math.isnan(rsi):
            return None

        rsi = round(rsi,1)

        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()

        macd_up = (ema12 - ema26).iloc[-1] > (ema12 - ema26).ewm(span=9).mean().iloc[-1]

        ma20 = df["Close"].rolling(20).mean().iloc[-1]
        trend_up = price > ma20

        high = float(df["High"].max())
        low = float(df["Low"].min())

        entry_low = low * 1.01
        entry_high = low * 1.03

        risk = entry_low - (low * 0.97)
        reward = (high * 1.02) - entry_low

        rr = reward / risk if risk > 0 else 0

        return {
            "price": price,
            "rsi": rsi,
            "macd_up": macd_up,
            "trend_up": trend_up,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "rr": rr
        }

    except Exception as e:
        print("CALC ERROR:", e)
        return None


# ======================
# COMMANDS
# ======================
def stock_all():
    msg = "📊【波段分析】\n\n"
    for s in SYMBOLS:
        df = get_df(s,"5m")
        if not df:
            msg += f"{s} ⚠️ 無數據\n\n"
            continue

        d = calc(df)
        if not d:
            msg += f"{s} ⚠️ 計算錯誤\n\n"
            continue

        status = "👉 觀察"
        if d["entry_low"] <= d["price"] <= d["entry_high"]:
            status = "👉 接近入場"

        msg += f"""{s}
💰 {round(d['price'],2)}
RSI: {d['rsi']}
🎯 {round(d['entry_low'],2)} - {round(d['entry_high'],2)}
RR: {round(d['rr'],2)}

{status}
━━━━━━━━━━━━━━
"""
    return msg


def market():
    df = get_df("SPY","60m")
    if not df:
        return "市場數據不可用"

    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]

    if math.isnan(ma20) or math.isnan(ma5):
        return "市場數據不足"

    strength = abs(ma5 - ma20) / ma20

    if strength < 0.002:
        action = "⚠️ Sideways → 等機會"
    elif ma5 < ma20:
        action = "🔻 Downtrend → 小心做"
    else:
        action = "🟢 Uptrend → 可操作"

    return f"🌍市場\nSPY\n{action}"


def gold():
    return "🥇 Gold → 對沖資產"


def long_term():
    return "📈 長線\nS&P500 / MSFT / ETF DCA"


# ======================
# LOOP
# ======================
def loop():
    while True:
        try:
            now = time.time()
            candidates = []

            # 市場 regime
            spy = get_df("SPY","5m")
            allow_trade = True

            if spy:
                ma20 = spy["Close"].rolling(20).mean().iloc[-1]
                ma5 = spy["Close"].rolling(5).mean().iloc[-1]

                if not math.isnan(ma20) and not math.isnan(ma5):
                    strength = abs(ma5 - ma20) / ma20

                    if strength < 0.002:
                        allow_trade = False

                    elif ma5 < ma20:
                        allow_trade = True  # 🔥 不再完全禁止

                        if now - last_alert.get("risk",0) > 1800:
                            send(CHAT_ID,"⚠️ 市場轉弱（小心）")
                            last_alert["risk"] = now

            if not allow_trade:
                time.sleep(300)
                continue

            # 掃描
            for s in SYMBOLS:
                df = get_df(s,"5m")
                if not df:
                    continue

                d = calc(df)
                if not d:
                    continue

                # breakout（強化）
                recent_high = df["High"].iloc[-15:-3].max()
                recent_low = df["Low"].iloc[-15:-3].min()

                # 避免死市
                if (recent_high - recent_low) / d["price"] < 0.01:
                    continue

                breakout = (
                    df["Close"].iloc[-1] > recent_high and
                    df["Close"].iloc[-2] <= recent_high and
                    df["Low"].iloc[-1] > recent_high * 0.998
                )

                # volume
                vol_ma = df["Volume"].rolling(10).mean().iloc[-1]
                vol_max = df["Volume"].rolling(20).max().iloc[-2]

                if math.isnan(vol_ma) or math.isnan(vol_max) or vol_ma == 0:
                    continue

                volume_spike = (
                    df["Volume"].iloc[-1] > vol_ma * 1.5 and
                    df["Volume"].iloc[-1] > vol_max * 0.8
                )

                # Setup
                if (
                    d["entry_low"]*0.995 < d["price"] < d["entry_high"]*1.005
                    and d["rsi"] > 50
                    and d["macd_up"]
                ):
                    if now - last_alert.get(s+"_setup",0) > 1800:
                        send(CHAT_ID,f"👀 {s} Setup\nRSI:{d['rsi']}")
                        last_alert[s+"_setup"] = now

                # Entry
                if (
                    d["entry_low"] <= d["price"] <= d["entry_high"]
                    and d["macd_up"]
                    and d["trend_up"]
                    and 55 < d["rsi"] < 68
                    and d["rr"] >= 1.5
                    and breakout
                    and volume_spike
                ):
                    score = d["rr"]*2 + (70-abs(d["rsi"]-60))

                    candidates.append((s,d,score))

            # 發送 top signals（修復空訊息）
            if candidates:
                top = sorted(candidates,key=lambda x:x[2],reverse=True)[:3]

                lines = []

                for s,d,score in top:
                    if now - last_alert.get(s,0) > 600:
                        lines.append(f"{s}\nRSI:{d['rsi']} RR:{round(d['rr'],2)}")
                        last_alert[s] = now

                if lines:
                    send(CHAT_ID,"🚀【Top Signals】\n\n" + "\n\n".join(lines))

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e)
            time.sleep(10)


# ======================
# THREAD（修復）
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
    if not data or "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text.startswith("/start"):
        send(chat_id,"🚀 Bot Ready\n/stock /market /gold /long")

    elif text.startswith("/stock"):
        send(chat_id, stock_all())

    elif text.startswith("/market"):
        send(chat_id, market())

    elif text.startswith("/gold"):
        send(chat_id, gold())

    elif text.startswith("/long"):
        send(chat_id, long_term())

    else:
        send(chat_id,"/stock /market /gold /long")

    return "ok"


@app.route("/")
def home():
    return "running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
