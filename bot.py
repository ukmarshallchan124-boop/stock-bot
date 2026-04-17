from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

signal_state = {}

# ======================
# SEND
# ======================
def send(chat_id, text):
    try:
        requests.post(f"{URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text[:4000]
        })
    except:
        pass

# ======================
# MARKET
# ======================
def market():
    try:
        df = yf.Ticker("SPY").history(period="3mo")
        price = df["Close"].iloc[-1]
        ma50 = df["Close"].rolling(50).mean().iloc[-1]
        return "📈 美股偏強（回調買）" if price > ma50 else "📉 市場轉弱（保守）"
    except:
        return ""

# ======================
# DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")
    if df.empty:
        return None

    price = float(df["Close"].iloc[-1])
    high = float(df["High"].max())
    low = float(df["Low"].min())

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = float((100-(100/(1+rs))).iloc[-1])

    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()

    if macd_line.iloc[-1] > signal.iloc[-1] and macd_line.iloc[-2] <= signal.iloc[-2]:
        macd = "🟡 黃金交叉"
    elif macd_line.iloc[-1] < signal.iloc[-1] and macd_line.iloc[-2] >= signal.iloc[-2]:
        macd = "🔴 死亡交叉"
    elif macd_line.iloc[-1] > signal.iloc[-1]:
        macd = "🟢 多頭趨勢"
    else:
        macd = "⚪ 空頭趨勢"

    momentum = (price - df["Close"].iloc[-20]) / df["Close"].iloc[-20] * 100

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02

    rr = (target-entry_low)/(entry_low-stop)

    return {
        "price":round(price,2),
        "rsi":round(rsi,1),
        "macd":macd,
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2),
        "momentum":round(momentum,2)
    }

# ======================
# NEWS（Yahoo）
# ======================
def get_news(symbol):
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news[:3]

        text = f"\n📰【{symbol} 新聞】\n"
        score = 0

        for n in news:
            title = n["title"]

            if any(w in title.lower() for w in ["surge","growth","beat","strong"]):
                tag="🟢 利好"; score+=1
            elif any(w in title.lower() for w in ["drop","risk","cut","warn"]):
                tag="🔴 利淡"; score-=1
            else:
                tag="⚪ 中性"

            text += f"• {title}\n{tag}\n"

        summary = "🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        text += f"\n🧠 新聞總結：{summary}\n"

        return text, score
    except:
        return "\n📰 無新聞\n",0

# ======================
# AI 評分
# ======================
def ai_score(d, news_score):
    score = 50

    if d["rsi"] < 45: score += 10
    if "🟡" in d["macd"]: score += 20
    if "🟢" in d["macd"]: score += 15
    if d["rr"] > 2: score += 15
    if d["momentum"] > 0: score += 10

    score += news_score * 5

    score = max(40, min(95, score))

    if score >= 85: grade="🟣 S級"
    elif score >= 75: grade="🟢 A級"
    elif score >= 65: grade="🟡 B級"
    else: grade="🔴 C級"

    return score, grade

# ======================
# FORMAT（專業版）
# ======================
def format_swing(symbol):
    d = get_data(symbol)
    if not d:
        return "無數據"

    news, news_score = get_news(symbol)
    score, grade = ai_score(d, news_score)

    rsi_text = "🟢 超賣" if d["rsi"]<30 else "🔴 超買" if d["rsi"]>70 else "⚪ 正常"

    if d["entry_low"] <= d["price"] <= d["entry_high"]:
        timing="🔥 入場區"
        action="✅ 可以考慮入場"
    elif d["price"] > d["entry_high"]:
        timing="❌ 唔好追"
        action="❌ 等回調"
    else:
        timing="⏳ 等回調"
        action="👀 等回調"

    # 動態時間
    dist = abs((d["price"] - d["entry_low"]) / d["entry_low"] * 100)

    if dist < 2:
        time_text = "⚡ 1–2日內"
    elif dist < 5:
        time_text = "⏳ 2–5日"
    elif dist < 10:
        time_text = "📅 1–2星期"
    else:
        time_text = "🕰️ 2–4星期"

    trend = "📈 偏強" if d["momentum"]>0 else "📉 偏弱"

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}

🧠 AI評分：{score}%（{grade}）
⏱️ Timing：{timing}

━━━━━━━━━━━━━━━

{trend}

RSI：{d['rsi']} {rsi_text}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

━━━━━━━━━━━━━━━

💰 策略
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━━

🌍 {market()}

━━━━━━━━━━━━━━━

📌 行動建議：
👉 {action}

⏳ 預期：
{time_text}

━━━━━━━━━━━━━━━

{news}
"""

# ======================
# LOOP（專業 alert）
# ======================
def loop():
    while True:
        try:
            for s in SWING_STOCKS:
                d = get_data(s)
                if not d:
                    continue

                state = signal_state.get(s, {"setup":False,"entry":False})

                # 過濾垃圾
                if d["rr"] < 1.8 or d["momentum"] < -2:
                    continue

                # Setup
                if d["price"] > d["entry_high"]:
                    if not state["setup"]:
                        send(CHAT_ID,f"""👀【{s} Setup】

📉 等回調：
{d['entry_low']} - {d['entry_high']}

📊 R/R：{d['rr']}
📈 動能：{d['momentum']}%
""")
                        state["setup"]=True
                else:
                    state["setup"]=False

                # Entry confirm
                in_range = d["entry_low"] <= d["price"] <= d["entry_high"]

                confirm = (
                    in_range and
                    d["rsi"] < 50 and
                    ("🟢" in d["macd"] or "🟡" in d["macd"])
                )

                if confirm and not state["entry"]:
                    send(CHAT_ID,f"""🚀【{s} 入場確認】

條件達成 ✅

✔ RSI 健康
✔ MACD 多頭
✔ 價格到位

👉 入場：
{d['entry_low']} - {d['entry_high']}
""")
                    state["entry"]=True

                if not in_range:
                    state["entry"]=False

                signal_state[s]=state

            time.sleep(300)
        except:
            pass

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

    if text == "/check":
        for s in SWING_STOCKS:
            send(chat_id, format_swing(s))

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
