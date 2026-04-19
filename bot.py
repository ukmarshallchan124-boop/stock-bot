from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # 用嚟收自動 alert
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

last_alert = {}

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(f"{URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": msg[:4000]
        })
    except Exception as e:
        print("send error:", e)

# ======================
# DATA + INDICATORS
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d")
    if df is None or df.empty:
        return None

    price = float(df["Close"].iloc[-1])
    high = float(df["High"].max())
    low = float(df["Low"].min())

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = float((100-(100/(1+rs))).iloc[-1])

    # MACD（交叉判斷）
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()

    if macd_line.iloc[-1] > signal.iloc[-1] and macd_line.iloc[-2] <= signal.iloc[-2]:
        macd = "🟡 黃金交叉（轉強）"
    elif macd_line.iloc[-1] < signal.iloc[-1] and macd_line.iloc[-2] >= signal.iloc[-2]:
        macd = "🔴 死亡交叉（轉弱）"
    elif macd_line.iloc[-1] > signal.iloc[-1]:
        macd = "🟢 多頭延續"
    else:
        macd = "⚪ 偏弱"

    # 區間（簡化版）
    entry_low = low * 1.01
    entry_high = low * 1.03
    stop = low * 0.97
    target = high * 1.02
    rr = (target-entry_low)/(entry_low-stop) if (entry_low-stop)!=0 else 0

    # 動能（簡單）
    momentum = (price - df["Close"].iloc[-20]) / df["Close"].iloc[-20] * 100 if len(df) >= 20 else 0

    return {
        "price": round(price,2),
        "rsi": round(rsi,1),
        "macd": macd,
        "entry_low": round(entry_low,2),
        "entry_high": round(entry_high,2),
        "stop": round(stop,2),
        "target": round(target,2),
        "rr": round(rr,2),
        "momentum": round(momentum,2)
    }

# ======================
# NEWS（簡化情緒）
# ======================
def news_sentiment(symbol):
    if symbol in ["TSLA","NVDA","AMD"]:
        return "🟢 利好（AI / 成長）"
    elif symbol == "XOM":
        return "⚪ 中性（油價）"
    elif symbol == "JPM":
        return "⚪ 中性（利率）"
    return "⚪ 中性"

# ======================
# 勝率（簡化）
# ======================
def winrate(d):
    score = 50
    if d["rsi"] < 45: score += 10
    if "🟢" in d["macd"] or "🟡" in d["macd"]: score += 15
    if d["rr"] > 2: score += 10
    if d["momentum"] > 0: score += 10
    return min(90, max(40, score))

# ======================
# STOCK UI（專業版）
# ======================
def format_stock(symbol):
    d = get_data(symbol)
    if not d:
        return f"{symbol} 數據錯誤"

    w = winrate(d)

    if d["entry_low"] <= d["price"] <= d["entry_high"]:
        timing = "🟢 入場區"
        summary = "👉 可以考慮分批入場"
    elif d["price"] > d["entry_high"]:
        timing = "❌ 唔好追"
        summary = "👉 現價偏高，等回調"
    else:
        timing = "⏳ 等回調"
        summary = "👉 未到位，先觀望"

    trend = "📈 偏強" if d["momentum"] >= 0 else "📉 偏弱"
    rsi_txt = "🟢 超賣" if d["rsi"]<30 else "🔴 超買" if d["rsi"]>70 else "⚪ 正常"

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}

🧠 成功率：{w}%
⏱️ Timing：{timing}

━━━━━━━━━━━━━━

📈 趨勢：{trend}
RSI：{d['rsi']}（{rsi_txt}）
MACD：{d['macd']}

━━━━━━━━━━━━━━

📊 支撐：{d['entry_low']}
📊 阻力：{d['target']}

━━━━━━━━━━━━━━

🎯 策略（重點🔥）
👉 入場區：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📈 R/R：{d['rr']}

━━━━━━━━━━━━━━

📰 情緒：{news_sentiment(symbol)}

━━━━━━━━━━━━━━

🧾 AI結論：
{summary}
"""

# ======================
# MARKET（全股票分類 + 行動）
# ======================
def market():
    strong, wait, weak = [], [], []

    for s in SYMBOLS:
        d = get_data(s)
        if not d:
            continue
        if d["price"] > d["entry_high"]:
            strong.append(s)
        elif d["price"] < d["entry_low"]:
            wait.append(s)
        else:
            weak.append(s)

    return f"""
🌍【市場狀態】

📈 趨勢：{"上升（Risk ON）" if strong else "混合"}
⚠️ 風險：{"中" if strong else "偏高"}

━━━━━━━━━━━━━━

📊 波段分類：

🟢 強勢：
{", ".join(strong) if strong else "無"}

⏳ 等回調：
{", ".join(wait) if wait else "無"}

❌ 弱勢：
{", ".join(weak) if weak else "無"}

━━━━━━━━━━━━━━

🧠 行動建議：

👉 🟢 做強勢股
👉 ⏳ 等回調入
👉 ❌ 避開弱勢

━━━━━━━━━━━━━━

🥇 防守：
👉 {"暫時唔需要 Gold" if strong else "考慮轉 Gold"}
"""

# ======================
# GOLD
# ======================
def gold():
    return """
🥇【Gold 策略】

📊 狀態：防守資產

🧠 用法：
👉 市場轉弱先加
👉 唔好高追
"""

# ======================
# LONG（含 VWRA）
# ======================
def long_term():
    return """
📈【長線投資】

🇺🇸 美國核心
👉 S&P500（VUAG）：DCA
👉 MSFT：核心持倉

━━━━━━━━━━━━━━

🌍 全球分散
👉 VWRA：長線配置

━━━━━━━━━━━━━━

🥇 防守
👉 市差先加 Gold
"""

# ======================
# ALERT LOOP（Setup / Entry / Risk OFF）
# ======================
def loop():
    while True:
        try:
            now = time.time()

            # --- Market Risk OFF ---
            spy = yf.Ticker("SPY").history(period="5d")
            if not spy.empty:
                price = float(spy["Close"].iloc[-1])
                ma = float(spy["Close"].rolling(5).mean().iloc[-1])
                last = last_alert.get("MARKET", 0)
                if price < ma and now-last > 1800:
                    send(CHAT_ID, "🚨【市場轉弱】\n👉 停止新倉\n👉 減科技股\n👉 🥇 考慮 Gold")
                    last_alert["MARKET"] = now

            # --- Per stock ---
            for s in SYMBOLS:
                d = get_data(s)
                if not d:
                    continue
                last = last_alert.get(s, 0)

                # Entry
                if d["entry_low"] <= d["price"] <= d["entry_high"] and now-last>600:
                    send(CHAT_ID, f"🚀【{s} 入場】\n👉 價格進入入場區\n👉 可分批入")
                    last_alert[s] = now

                # Setup
                elif d["price"] < d["entry_high"]*1.05 and now-last>3600:
                    send(CHAT_ID, f"👀【{s} Setup】\n👉 接近入場區\n👉 準備觀察")
                    last_alert[s] = now

            time.sleep(300)

        except Exception as e:
            print("loop error:", e)
            time.sleep(300)

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return "ok"

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").lower()

    if text.startswith("/check"):
        send(chat_id, "✅ Bot working")

    elif text.startswith("/stock"):
        for s in SYMBOLS:
            send(chat_id, format_stock(s))

    elif text.startswith("/market"):
        send(chat_id, market())

    elif text.startswith("/gold"):
        send(chat_id, gold())

    elif text.startswith("/long"):
        send(chat_id, long_term())

    else:
        send(chat_id, "指令：/stock /market /gold /long")

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
