from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

last_alert = {}
msft_last = 0

# ======================
# SEND
# ======================
def send(chat_id, text, keyboard=None):
    try:
        data = {"chat_id": chat_id, "text": text[:4000]}
        if keyboard:
            data["reply_markup"] = keyboard
        requests.post(f"{URL}/sendMessage", json=data)
    except:
        pass

# ======================
# UI MENU
# ======================
def menu():
    return {
        "keyboard":[
            ["📊 波段分析","💰 長線投資"],
            ["🧮 計算工具","📌 持倉分析"]
        ],
        "resize_keyboard":True
    }

# ======================
# MARKET
# ======================
def market():
    try:
        df = yf.Ticker("SPY").history(period="3mo")
        price = df["Close"].iloc[-1]
        ma50 = df["Close"].rolling(50).mean().iloc[-1]

        return "📈 市場偏強（可等回調買）" if price > ma50 else "📉 市場轉弱（減少操作）"
    except:
        return ""

# ======================
# DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")
    if df.empty: return None

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
    macd_line = ema12-ema26
    signal = macd_line.ewm(span=9).mean()

    if macd_line.iloc[-1] > signal.iloc[-1]:
        macd = "🟢 多頭延續"
    else:
        macd = "🔴 偏弱"

    momentum = (price - df["Close"].iloc[-20]) / df["Close"].iloc[-20] * 100

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02
    rr = (target-entry_low)/(entry_low-stop)

    dist = (price-entry_high)/entry_high*100

    return {
        "price":round(price,2),
        "rsi":round(rsi,1),
        "macd":macd,
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2),
        "momentum":round(momentum,2),
        "dist":round(dist,1)
    }

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        url = f"https://newsapi.org/v2/everything?q={symbol}&language=en&sortBy=publishedAt&apiKey={NEWS_API}"
        data = requests.get(url).json()
        articles = data.get("articles", [])[:3]

        text = f"\n📰【{symbol} 新聞】\n"
        score = 0

        for a in articles:
            title = a["title"]

            if any(w in title.lower() for w in ["surge","growth","beat","strong"]):
                tag = "🟢 利好"; score += 1
            elif any(w in title.lower() for w in ["drop","risk","cut","warn"]):
                tag = "🔴 利淡"; score -= 1
            else:
                tag = "⚪ 中性"

            text += f"• {title}\n{tag}\n"

        summary = "🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        text += f"\n🧠 新聞總結：{summary}\n"

        return text, score
    except:
        return "\n📰 無新聞\n",0

# ======================
# FORMAT
# ======================
def format_swing(symbol):
    d = get_data(symbol)
    if not d: return "無數據"

    news, news_score = get_news(symbol)

    if d["rsi"] < 30:
        rsi_text = "🟢 超賣"
    elif d["rsi"] > 70:
        rsi_text = "🔴 超買"
    else:
        rsi_text = "⚪ 正常"

    if d["entry_low"] <= d["price"] <= d["entry_high"]:
        timing = "🔥 入場區"
        action = "✅ 可以考慮入場"
    elif d["price"] > d["entry_high"]:
        timing = "❌ 唔好追"
        action = "❌ 太高唔好追"
    else:
        timing = "⏳ 等回調"
        action = "👀 等回調先"

    trend = "📈 偏強" if d["momentum"] > 0 else "📉 偏弱"

    win = 50
    if d["rsi"] < 45: win += 10
    if "🟢" in d["macd"]: win += 15
    if d["rr"] > 2: win += 15
    win += news_score*5
    win = max(40, min(90, win))

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
🧠 成功率：{win}%
⏱️ Timing：{timing}

{trend}

RSI：{d['rsi']} {rsi_text}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

━━━━━━━━━━━━━━━

💰 策略（重點🔥）
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━━

🌍 {market()}

━━━━━━━━━━━━━━━

🧠 總結：
👉 {action}

{news}
"""

# ======================
# LONG TERM
# ======================
def msft():
    df = yf.Ticker("MSFT").history(period="6mo")
    price = df["Close"].iloc[-1]

    m1 = (price-df["Close"].iloc[-30])/df["Close"].iloc[-30]*100
    m3 = (price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

    return f"""
💰【長線分析】

📊 MSFT：{round(price,2)}

📉 回調：
1個月：{round(m1,1)}%
3個月：{round(m3,1)}%

━━━━━━━━━━━━━━━

💡 分批策略：
🟢 第1注：而家（30%）
🟡 第2注：再跌5%
🔴 第3注：再跌10%

━━━━━━━━━━━━━━━

⏳ 時間：
1–4星期

━━━━━━━━━━━━━━━

📈 S&P500：
長線向上（VOO / SPY / VUAG）

━━━━━━━━━━━━━━━

📌 建議：
👉 可開始分批加倉
"""

# ======================
# TOOLS
# ======================
def calc(x):
    x=float(x)
    return f"+10% {round(x*1.1,2)}\n+20% {round(x*1.2,2)}\n-10% {round(x*0.9,2)}"

def position(symbol, entry):
    df=yf.Ticker(symbol).history(period="1d")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"{symbol} 盈虧：{round(pnl,2)}%"

# ======================
# LOOP
# ======================
def loop():
    global msft_last

    while True:
        try:
            for s in SWING_STOCKS:
                d = get_data(s)
                if not d: continue

                now=time.time()
                last=last_alert.get(s,0)

                if d["price"] > d["entry_high"] and now-last>3600:
                    send(CHAT_ID,f"👀【{s} Setup】\n等回調：{d['entry_low']} - {d['entry_high']}")

                if d["entry_low"] <= d["price"] <= d["entry_high"] and now-last>600:
                    send(CHAT_ID,f"🚀【{s} 入場】\n{d['entry_low']} - {d['entry_high']}")

                last_alert[s]=now

            if time.time()-msft_last>86400:
                send(CHAT_ID, msft())
                msft_last=time.time()

            time.sleep(300)
        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK
# ======================
@app.route("/", methods=["POST","GET"])
def webhook():
    data=request.get_json(silent=True)

    if not data or "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text in ["/start","start"]:
        send(chat_id,"🚀 AI Trading System",menu())

    elif text in ["📊 波段分析","/check"]:
        for s in SWING_STOCKS:
            send(chat_id,format_swing(s))

    elif text in ["💰 長線投資","/msft"]:
        send(chat_id,msft())

    elif text.startswith("/calc"):
        send(chat_id,calc(text.split()[1]))

    elif text.startswith("/position"):
        p=text.split()
        send(chat_id,position(p[1].upper(),float(p[2])))

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0",port=port)
