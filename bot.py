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
# AUTO SIGNAL LOOP（🔥核心）
# ======================
def loop():
    while True:
        try:
            now = time.time()
            allow_trade, market_msg = market_filter()

            for s in SYMBOLS:
                df = get_df(s,"5m")
                if not df:
                    continue

                d = calc(df)
                if not d:
                    continue

                sig = signal_engine(df, d)
                decision = sig["decision"]

                # 👀 SETUP
                if decision == "SETUP":
                    if now - last_alert.get(s+"_setup",0) > 1800:
                        send(CHAT_ID, f"""👀【SETUP 準備區】{s}

💰 價格：{round(d['price'],2)}
🎯 入場區：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}

📊 RR：{round(d['rr'],2)}

👉 等回調確認
━━━━━━━━━━━━━━
""")
                        last_alert[s+"_setup"] = now

                # 🟢 ENTRY
                if decision == "ENTRY" and allow_trade:
                    if now - last_alert.get(s+"_entry",0) > 1800:
                        send(CHAT_ID, f"""🟢【ENTRY 入場】{s}

💰 價格：{round(d['price'],2)}

🎯 入場：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 止損：{round(d['stop'],2)}
🎯 目標：{round(d['target'],2)}

📊 RR：{round(d['rr'],2)}

👉 可考慮入場（記得控風險）
━━━━━━━━━━━━━━
""")
                        last_alert[s+"_entry"] = now

                # 🚀 BREAKOUT
                if decision == "BREAKOUT" and allow_trade:
                    if now - last_alert.get(s+"_bo",0) > 1800:
                        send(CHAT_ID, f"""🚀【BREAKOUT 突破】{s}

💰 價格：{round(d['price'],2)}

📈 動能突破 + 放量
📊 RR：{round(d['rr'],2)}

👉 可順勢跟進（勿追高）
━━━━━━━━━━━━━━
""")
                        last_alert[s+"_bo"] = now

                # 🔴 RISK OFF
                if decision == "RISK":
                    if now - last_alert.get(s+"_risk",0) > 1800:
                        send(CHAT_ID, f"""🔴【RISK OFF】{s}

💰 價格：{round(d['price'],2)}

⚠️ 跌穿結構
📉 趨勢轉弱

👉 停止做多 / 考慮止蝕
━━━━━━━━━━━━━━
""")
                        last_alert[s+"_risk"] = now

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e)
            time.sleep(10)
# ======================
# UI
# ======================
def stock_all():
    allow, market_msg = market_filter()

    header = "🟢 市場偏多" if allow else "🔴 市場偏弱"

    msg = f"""📊【市場掃描】
{market_msg}
{header}

━━━━━━━━━━━━━━
"""

    for s in SYMBOLS[:3]:
        df = get_df(s, "5m")
        if not df:
            continue

        d = calc(df)
        if not d:
            continue

        sig = signal_engine(df, d)
        decision = sig["decision"]

        if decision == "ENTRY":
            signal_ui = "🟢 入場"
        elif decision == "BREAKOUT":
            signal_ui = "🚀 突破"
        elif decision == "SETUP":
            signal_ui = "👀 準備"
        elif decision == "RISK":
            signal_ui = "🔴 風險"
        else:
            signal_ui = "🟡 觀望"

        if not allow and decision in ["ENTRY","BREAKOUT"]:
            signal_ui = "❌ 市場弱（無效）"

        msg += f"""📈 {s}
💰 {round(d['price'],2)} ｜ RSI {d['rsi']}
📊 RR：{round(d['rr'],2)}

👉 {signal_ui}

━━━━━━━━━━━━━━
"""

    return msg

def market():
    allow, msg = market_filter()
    return f"""🌍【市場狀態】

{msg}

👉 {"🟢 偏多" if allow else "🔴 偏弱"}

━━━━━━━━━━━━━━
"""

def gold():
    return """🥇【黃金】

避險資產
市場差先考慮

━━━━━━━━━━━━━━
"""

def long_term():
    return """📈【長線】

DCA 投資
S&P500 / TSLA / NVDA

━━━━━━━━━━━━━━
"""

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
            allow_trade, _ = market_filter()

            for s in SYMBOLS:
                df = get_df(s, "5m")
                if not df:
                    continue

                d = calc(df)
                if not d:
                    continue

                sig = signal_engine(df, d)

                if sig["decision"] == "ENTRY" and allow_trade:
                    send(CHAT_ID, f"🟢 ENTRY {s} @{round(d['price'],2)}")

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
    try:
        data = request.get_json()
        print("IN:", data)

        if not data:
            return "ok"

        message = data.get("message")
        if not message:
            return "ok"

        chat_id = message["chat"]["id"]
        text = message.get("text","").lower().strip()

        if text.startswith("/start"):
            send(chat_id, """🚀 Bot 已啟動

📊 /stock
🌍 /market
🥇 /gold
📈 /long
""")

        elif text.startswith("/stock"):
            send(chat_id, stock_all())

        elif text.startswith("/market"):
            send(chat_id, market())

        elif text.startswith("/gold"):
            send(chat_id, gold())

        elif text.startswith("/long"):
            send(chat_id, long_term())

        else:
            send(chat_id, "❓ 未知指令")

        return "ok"

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
