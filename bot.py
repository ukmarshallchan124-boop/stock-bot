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
# 新增：多時間框架 helper
# ======================
def get_trend(symbol):
    df_15 = get_df(symbol,"15m")
    if df_15 is None or df_15.empty:
        return "未知"

    ma = df_15["Close"].rolling(20).mean().iloc[-1]
    return "上升" if df_15["Close"].iloc[-1] > ma else "下降"

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
        volume_spike = vol.iloc[-1] > vol_ma * 1.5 and vol_ma > 100000

    breakout = (
        df["Close"].iloc[-1] > recent_high and
        df["Close"].iloc[-2] > recent_high
    )

    in_entry = d["entry_low"] <= price <= d["entry_high"]
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
# AUTO SIGNAL LOOP（🔥核心）
# ======================
def loop():
    try:
        now = time.time()
        allow_trade, market_msg = market_filter()
        candidates = []

        for s in SYMBOLS:
            df = get_df(s, "5m")
            df_15 = get_df(s, "15m")

            if df is None or df.empty or df_15 is None or df_15.empty:
                continue

            d = calc(df)
            if not d:
                continue

            sig = signal_engine(df, d)
            decision = sig["decision"]

            # 🔥 多時間框架
            ma20_15 = df_15["Close"].rolling(20).mean().iloc[-1]
            trend_15 = df_15["Close"].iloc[-1] > ma20_15
            if not trend_15:
                continue

            # 🔥 假突破過濾
            recent_high = df["High"].iloc[-20:-3].max()
            fake_bo = (
                df["Close"].iloc[-1] > recent_high and
                df["Close"].iloc[-2] < recent_high
            )
            if fake_bo:
                continue

            # 🔥 市場弱 → 不做
            if not allow_trade:
                continue

            # 🔥 評分系統
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

            if score < 3.5:
                continue

            candidates.append((s, d, score, decision))

            # 👀 SETUP
            if decision == "SETUP":
                if now - last_alert.get(s+"_setup", 0) > 1800:
                    send(CHAT_ID, f"""👀【SETUP】{s}
💰 {round(d['price'],2)}
🎯 {round(d['entry_low'],2)} - {round(d['entry_high'],2)}
📊 RR：{round(d['rr'],2)}
━━━━━━━━━━""")
                    last_alert[s+"_setup"] = now

            # 🟢 ENTRY
            if decision == "ENTRY":
                if now - last_alert.get(s+"_entry", 0) > 1800:
                    send(CHAT_ID, f"""🟢【ENTRY】{s}
💰 {round(d['price'],2)}
🎯 {round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 止損：{round(d['stop'],2)}
📊 RR：{round(d['rr'],2)}
━━━━━━━━━━""")
                    last_alert[s+"_entry"] = now

            # 🔴 RISK
            if decision == "RISK":
                if now - last_alert.get(s+"_risk", 0) > 1800:
                    send(CHAT_ID, f"""🔴【RISK OFF】{s}
⚠️ 結構已破
📉 趨勢轉弱
━━━━━━━━━━""")
                    last_alert[s+"_risk"] = now

        # 🚀 TOP SIGNAL
        if candidates:
            top = sorted(candidates, key=lambda x: x[2], reverse=True)[0]
            s, d, score, decision = top

            if now - last_alert.get(s, 0) > 600:
                msg = f"""🚀【TOP SIGNAL】

📈 {s}
💰 {round(d['price'],2)}
📊 RR：{round(d['rr'],2)}

🎯 入場：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 止損：{round(d['stop'],2)}

👉 信號：{decision}
⭐ Score：{round(score,1)}
━━━━━━━━━━
"""
                last_alert[s] = now
                send(CHAT_ID, msg)

    except Exception as e:
        print("LOOP ERROR:", e)
# ======================
# UI
# ======================
def stock_all():
    try:
        allow, market_msg = market_filter()

        header = "🟢 市場偏多（可進攻）" if allow else "🔴 市場偏弱（保守）"
        msg = f"""📊【市場掃描 Pro】
{market_msg}
{header}

━━━━━━━━━━━━━━
"""

        for s in SYMBOLS:
            df = get_df(s,"5m")
            if df is None or df.empty:
                continue

            d = calc(df)
            if not d:
                continue

            sig = signal_engine(df,d)
            decision = sig["decision"]

            trend_big = get_trend(s)

            mapping = {
                "ENTRY":"🟢 入場",
                "BREAKOUT":"🚀 突破",
                "SETUP":"👀 準備",
                "RISK":"🔴 風險",
                "WAIT":"🟡 觀望"
            }

            signal_ui = mapping.get(decision,"🟡")

            if not allow and decision in ["ENTRY","BREAKOUT"]:
                signal_ui = "❌ 市場弱（無效）"

            msg += f"""📈 {s}

💰 {round(d['price'],2)} ｜ RSI {d['rsi']}
📊 RR：{round(d['rr'],2)}

📈 大趨勢（15m）：{trend_big}
📉 小趨勢（5m）：{"上升" if d['trend_up'] else "下降"}

🎯 入場：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 止損：{round(d['stop'],2)}

👉 信號：{signal_ui}

━━━━━━━━━━━━━━
"""

        return msg

    except Exception as e:
        print("STOCK_ALL ERROR:", e)
        return "⚠️ stock_all error"

def market():
    df = get_df("SPY","15m")
    if df is None or df.empty:
        return "⚠️ 市場數據不足"

    price = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]

    trend = "上升" if price > ma20 else "下降"

    return f"""🌍【市場分析】

📊 S&P500（SPY）
趨勢：{trend}

📉 結構：
{"仍然健康" if trend=="上升" else "開始轉弱"}

📊 解讀：
👉 {"可做多（但控風險）" if trend=="上升" else "減倉 / 保守"}

━━━━━━━━━━━━━━
"""

def gold():
    df = get_df("GC=F","15m")  # 黃金期貨
    if df is None or df.empty:
        return "⚠️ 黃金數據不足"

    price = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]

    trend = "上升" if price > ma20 else "下降"

    return f"""🥇【黃金分析】

💰 價格：{round(price,2)}

📈 趨勢：{trend}

📊 邏輯：
• 市場風險 ↑ → 黃金 ↑
• 利率 ↓ → 黃金 ↑

👉 建議：
{"可作避險配置" if trend=="上升" else "暫時觀望"}

━━━━━━━━━━━━━━
"""

def long_term():
    spy = get_df("SPY","1d")
    msft = get_df("MSFT","1d")
    vwra = get_df("VWRA.L","1d")

    def trend(df):
        if df is None or df.empty: return "未知"
        price = df["Close"].iloc[-1]
        ma = df["Close"].rolling(50).mean().iloc[-1]
        return "上升" if price > ma else "回調"

    return f"""📈【長線投資】

📊 S&P500（SPY）：{trend(spy)}
👉 核心市場

📊 VWRA（全球）：{trend(vwra)}
👉 分散風險

📊 Microsoft：{trend(msft)}
👉 科技龍頭

💡 策略：
• 上升 → 持續DCA
• 回調 → 分段加倉

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
        text = message.get("text", "").lower().strip()

        print("TEXT:", text)

        if text.startswith("/start"):
            send(chat_id, """🚀 Bot 已啟動

📊 /stock
🌍 /market
🥇 /gold
📈 /long
""")

        elif text.startswith("/stock"):
            try:
                send(chat_id, stock_all())
            except Exception as e:
                print("STOCK ERROR:", e)
                send(chat_id, "⚠️ stock error")

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


@app.route("/scan")
def scan():
    threading.Thread(target=loop).start()
    return "scan started"
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
