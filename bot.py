from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

last_alert = {}
cache = {}
CACHE_TTL = 120

# ======================
# SIGNAL ENGINE
# ======================
def signal_engine(df, d):
    price = d["price"]

    recent_high = df["High"].iloc[-20:-3].max()
    recent_low = df["Low"].iloc[-20:-3].min()

    vol = df["Volume"]
    vol_ma = vol.rolling(10).mean().iloc[-1]
    volume_spike = vol.iloc[-1] > vol_ma * 1.5

    breakout = (
        df["Close"].iloc[-1] > recent_high and
        df["Close"].iloc[-2] > recent_high
    )

    in_entry = d["entry_low"] <= price <= d["entry_high"]
    near_entry = d["entry_low"]*0.999 < price < d["entry_high"]*1.001
    risk_off = price < recent_low

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
    if not df:
        return True, "⚠️ 無法判斷市場"

    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]

    if ma5 < ma20:
        return False, "🔴 Risk OFF（市場轉弱）"
    else:
        return True, "🟢 Risk ON（市場健康）"

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

        cache[key] = (df.copy(), now)
        return df

    except Exception as e:
        print("DATA ERROR:", e)
        return None

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
# UI - STOCK
# ======================
def stock_all():
    allow, market_msg = market_filter()
    msg = f"📊【市場掃描 Pro】\n{market_msg}\n\n"

    for s in SYMBOLS[:3]:
        df = get_df(s, "5m")
        if not df:
            continue

        d = calc(df)
        if not d:
            continue

        sig = signal_engine(df, d)
        decision = sig["decision"]

        if not allow:
            if decision == "ENTRY":
                decision = "BLOCK"
            elif decision == "BREAKOUT":
                decision = "FAKE"

        trend = "🟢 上升" if d["trend_up"] else "🔻 下降"

        msg += f"""📈 {s}

💰 價格：{round(d['price'],2)} ｜ RSI：{d['rsi']}
📊 RR：{round(d['rr'],2)}

📈 趨勢：{trend}

👉 信號：{decision}

━━━━━━━━━━━━━━
"""
    return msg

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
# LOOP
# ======================
def loop():
    while True:
        try:
            now = time.time()
            allow_trade, market_msg = market_filter()

            candidates = []

            for s in SYMBOLS:
                df = get_df(s, "5m")
                df_15m = get_df(s, "15m")

                if not df or not df_15m:
                    continue

                d = calc(df)
                if not d:
                    continue

                # ======================
                # 🔥 多時間框架（大方向）
                # ======================
                ma20_15m = df_15m["Close"].rolling(20).mean().iloc[-1]
                trend_15m = df_15m["Close"].iloc[-1] > ma20_15m

                if not trend_15m:
                    continue

                # ======================
                # 🔥 結構（Higher Low）
                # ======================
                low1 = df["Low"].iloc[-10:-5].min()
                low2 = df["Low"].iloc[-20:-10].min()

                if low1 <= low2:
                    continue

                sig = signal_engine(df, d)
                decision = sig["decision"]

                # ======================
                # 🔥 假突破過濾
                # ======================
                recent_high = df["High"].iloc[-20:-3].max()
                fake_bo = (
                    df["Close"].iloc[-1] > recent_high and
                    df["Close"].iloc[-2] < recent_high
                )

                if fake_bo:
                    continue

                # ======================
                # 市場弱 = 唔做
                # ======================
                if not allow_trade:
                    continue

                # ======================
                # 🔥 Scoring（只留高質）
                # ======================
                score = 0

                if decision == "ENTRY":
                    score += 2

                if decision == "BREAKOUT":
                    score += 2.5

                if d["macd_up"]:
                    score += 1

                if sig["volume_spike"]:
                    score += 1

                if d["rr"] > 2:
                    score += 1

                if score < 4:
                    continue

                candidates.append((s, d, score, decision))

                # ======================
                # 👀 SETUP UI（升級版）
                # ======================
                if decision == "SETUP":
                    if now - last_alert.get(s+"_setup",0) > 1800:
                        send(CHAT_ID, f"""👀【SETUP 準備區】{s}

💰 現價：{round(d['price'],2)}
🎯 入場區：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}

👉 未觸發，等待入場
━━━━━━━━━━━━━━
""")
                        last_alert[s+"_setup"] = now

                # ======================
                # 🟢 ENTRY UI（升級版）
                # ======================
                if decision == "ENTRY":
                    if now - last_alert.get(s+"_entry",0) > 1800:
                        send(CHAT_ID, f"""🟢【ENTRY 入場】{s}

💰 價格：{round(d['price'],2)}
🎯 入場：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 止損：{round(d['stop'],2)}

📊 RR：{round(d['rr'],2)}

👉 可考慮入場（記得止損）
━━━━━━━━━━━━━━
""")
                        last_alert[s+"_entry"] = now

                # ======================
                # 🔴 RISK OFF UI（升級版）
                # ======================
                if decision == "RISK":
                    if now - last_alert.get(s+"_risk",0) > 1800:
                        send(CHAT_ID, f"""🔴【RISK OFF 危險】{s}

💰 現價：{round(d['price'],2)}

👉 結構已破
👉 避免做多

━━━━━━━━━━━━━━
""")
                        last_alert[s+"_risk"] = now

            # ======================
            # 🚀 只出最強（Top 1）
            # ======================
            if candidates:
                top = sorted(candidates, key=lambda x: x[2], reverse=True)[:1]

                msg = f"🚀【今日最強信號】\n{market_msg}\n\n"

                for s, d, score, decision in top:
                    if now - last_alert.get(s,0) > 600:
                        msg += f"""📈 {s}

💰 價格：{round(d['price'],2)}
📊 RR：{round(d['rr'],2)}

🎯 入場：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 止損：{round(d['stop'],2)}

👉 信號：{decision}
━━━━━━━━━━━━━━
"""
                        last_alert[s] = now

                send(CHAT_ID, msg)

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e)
            time.sleep(10)

# ======================
# START
# ======================
def start_background():
    threading.Thread(target=loop, daemon=True).start()

start_background()

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
    text = message.get("text","").lower()

    if text.startswith("/start"):
        send(chat_id,"""🚀 Bot 已啟動

📊 /stock
🌍 /market
🥇 /gold
📈 /long
""")

    elif text.startswith("/stock"):
        send(chat_id, stock_all())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
