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
        decision = "🔴 Risk Off（跌穿結構）"

    elif breakout and volume_spike and d["trend_up"] and good_rr and d["rsi"] < 70:
        decision = "🚀 Breakout（突破 + 放量）"

    elif in_entry and d["trend_up"] and good_rsi and good_rr:
        decision = "🟢 Entry（回調入場）"

    elif near_entry:
        decision = "👀 Setup（接近入場）"

    else:
        decision = "🟡 觀望"

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
# UI FUNCTIONS
# ======================

def stock_all():
    allow, market_msg = market_filter()
    msg = f"📊【市場掃描 Pro】\n{market_msg}\n\n"

    for s in SYMBOLS[:3]:  # 最多3隻
        df = get_df(s, "5m")
        if not df:
            continue

        d = calc(df)
        if not d:
            continue

        sig = signal_engine(df, d)
        decision = sig["decision"]

        # ⭐ 評分
        score = d["rr"]
        if "Entry" in decision:
            score += 1
        if "Breakout" in decision:
            score += 1.5
        if d["macd_up"]:
            score += 0.5

        # 等級
        grade = "C"
        if score > 3:
            grade = "A"
        elif score > 2.5:
            grade = "B"

        # 🎯 操作建議
        if "Entry" in decision:
            action = "👉 可考慮入場"
        elif "Breakout" in decision:
            action = "👉 留意突破跟進"
        elif "Risk Off" in decision:
            action = "👉 避免交易"
        else:
            action = "👉 等待機會"

        # 📊 趨勢
        trend = "🟢 上升" if d["trend_up"] else "🔻 下降"
        momentum = "強" if d["macd_up"] else "弱"

        # 🧠 分析
        if "Entry" in decision:
            reason = "回調支撐 + 上升趨勢"
        elif "Breakout" in decision:
            reason = "突破前高 + 成交量"
        elif "Risk Off" in decision:
            reason = "跌穿結構"
        else:
            reason = "未有明確優勢"

        msg += f"""📈 {s} ｜ ⭐ {grade}

💰 價格：{round(d['price'],2)}
📊 RSI：{d['rsi']} ｜ RR：{round(d['rr'],2)}

📈 趨勢：{trend}
⚡ 動能：{momentum}

🎯 入場：{round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 止損：{round(d['stop'],2)}
🎯 目標：{round(d['target'],2)}

🧠 分析：{reason}
👉 信號：{decision}
{action}

━━━━━━━━━━━━━━
"""

    return msg
    
def market():
    allow, msg = market_filter()

    return f"""🌍【市場狀態 Market】

{msg}

📊 市場解讀：
👉 {"🟢 偏多（可以找入場機會）" if allow else "🔴 偏弱（建議保守或減倉）"}

⚡ 操作建議：
• {"可重點留意 Entry / Breakout" if allow else "避免追高，優先保本"}
• {"可正常交易" if allow else "降低倉位 / 暫停交易"}

━━━━━━━━━━━━━━
"""

def gold():
    return """🥇【黃金 Gold】

📌 定位：
👉 避險資產（Risk Hedge）

📊 何時考慮：
• 🔴 市場 Risk OFF
• 📉 股市轉弱
• 💸 通脹 / 不確定性上升

⚡ 操作思路：
• 唔係主力交易
• 用作資產對沖

💡 簡單理解：
👉 市場差 → 黃金有機會升

━━━━━━━━━━━━━━
"""

def long_term():
    return """📈【長線投資 Long Term】

💰 核心策略：
👉 定期投資（DCA）

📊 建議標的：
• S&P500（大盤）
• TSLA / NVDA（龍頭科技）

⏳ 投資週期：
👉 3 – 5 年以上

⚡ 操作重點：
• 唔 timing（唔估高低）
• 每月固定投入
• 長期持有

🚫 常見錯誤：
• 短線思維玩長線
• 跌就驚 / 升就追

💡 核心一句：
👉 時間 > timing

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
# LOOP（核心）
# ======================
def loop():
    while True:
        try:
            now = time.time()
            allow_trade, market_msg = market_filter()

            candidates = []

            for s in SYMBOLS:
                df = get_df(s,"5m")
                if not df:
                    continue

                d = calc(df)
                if not d:
                    continue

                sig = signal_engine(df, d)
                decision = sig["decision"]

                # 市場過濾
                if not allow_trade:
                    if "Entry" in decision:
                        decision = "❌ 禁止入場（市場弱）"
                    elif "Breakout" in decision:
                        decision = "⚠️ 假突破（市場弱）"

                # 評分
                score = d["rr"]
                if "Entry" in decision:
                    score += 1
                if "Breakout" in decision:
                    score += 1.5
                if d["macd_up"]:
                    score += 0.5
                if sig["volume_spike"]:
                    score += 0.5

                if score > 2:
                    candidates.append((s, d, score, decision))

                # Setup
                if "Setup" in decision:
                    if now - last_alert.get(s+"_setup",0) > 1800:
                        send(CHAT_ID,f"👀【Setup】{s}")
                        last_alert[s+"_setup"] = now

                # Entry
                if "Entry" in decision:
                    if now - last_alert.get(s+"_entry",0) > 1800:
                        send(CHAT_ID,f"🟢【入場】{s}")
                        last_alert[s+"_entry"] = now

                # Risk Off
                if "Risk Off" in decision:
                    if now - last_alert.get(s+"_risk",0) > 1800:
                        send(CHAT_ID,f"🔴【Risk Off】{s}")
                        last_alert[s+"_risk"] = now

            # Top signals
            if candidates:
                top = sorted(candidates,key=lambda x:x[2],reverse=True)[:2]
                msg = f"🚀【高質信號】\n{market_msg}\n\n"

                for s,d,score,decision in top:
                    grade = "C"
                    if score > 3:
                        grade = "A"
                    elif score > 2.5:
                        grade = "B"

                    if now - last_alert.get(s,0) > 600:
                        msg += f"📈 {s} ｜ 等級 {grade}\n👉 {decision}\n\n"
                        last_alert[s] = now

                send(CHAT_ID,msg)

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
        send(chat_id, """🚀【交易 Bot 已啟動】

📊 /stock → 市場掃描
🌍 /market → 市場方向
🥇 /gold → 避險分析
📈 /long → 長線策略

━━━━━━━━━━━━━━
""")

    elif text.startswith("/stock"):
        send(chat_id, stock_all())

    elif text.startswith("/market"):
        send(chat_id, market())

    elif text.startswith("/gold"):
        send(chat_id, gold())

    elif text.startswith("/long"):
        send(chat_id, long_term())

    return "ok"

@app.route("/")
def home():
    return "running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)


