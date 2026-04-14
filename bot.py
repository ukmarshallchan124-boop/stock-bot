from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}

# ======================
# 📩 SEND
# ======================
def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ======================
# 📊 DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="2d", interval="5m")

    price = df["Close"].iloc[-1]
    prev = df["Close"].iloc[0]
    change = (price-prev)/prev*100

    high = df["High"].max()
    low = df["Low"].min()

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean() / loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))

    # MACD
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()

    return price, change, rsi.iloc[-1], macd.iloc[-1], signal.iloc[-1], low, high

# ======================
# 🧠 AI 預測（升級版）
# ======================
def ai_predict(price, rsi, macd, signal, support, resistance):
    prob = 50

    # RSI
    if rsi < 30: prob += 25
    elif rsi > 70: prob -= 25

    # MACD
    if macd > signal: prob += 20
    else: prob -= 15

    # 支撐阻力位置
    if price <= support*1.02: prob += 10
    if price >= resistance*0.98: prob -= 10

    prob = max(5, min(95, prob))

    # 建議
    if prob >= 70:
        action = "🔥 可考慮買入"
    elif prob <= 35:
        action = "⚠️ 建議減倉"
    else:
        action = "⚪ 觀望"

    return prob, action

# ======================
# 📰 新聞 AI
# ======================
def get_news(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data=requests.get(url).json()

        text=f"\n📰【{symbol} 新聞】\n"

        for a in data.get("articles",[])[:3]:
            t=a["title"]

            # 情緒判斷
            if any(x in t.lower() for x in ["surge","beat","growth"]):
                senti="🟢利好"
            elif any(x in t.lower() for x in ["drop","fall","risk"]):
                senti="🔴利淡"
            else:
                senti="⚪中性"

            text+=f"• {t}\n{senti}\n"

        return text
    except:
        return ""

# ======================
# 📊 FORMAT
# ======================
def build(symbol):
    price, change, rsi, macd, signal, support, resistance = get_data(symbol)

    prob, action = ai_predict(price, rsi, macd, signal, support, resistance)

    trend = "📈 上升" if change>0 else "📉 下跌"
    macd_text = "🟢黃金交叉" if macd>signal else "🔴死亡交叉"

    # 突破 alert
    alert=""
    if price > resistance:
        if last_alert.get(symbol)!="break":
            alert="🚀 突破阻力（強勢）"
            send(f"🚨 {symbol} 突破阻力！")
            last_alert[symbol]="break"

    if price < support:
        if last_alert.get(symbol)!="breakdown":
            alert="⚠️ 跌穿支撐（危險）"
            send(f"🚨 {symbol} 跌穿支撐！")
            last_alert[symbol]="breakdown"

    msg=f"""📊【{symbol} AI交易】

💰 價格：{price:.2f}
📊 變幅：{change:.2f}%

{trend}
RSI：{rsi:.1f}
MACD：{macd_text}

🧠 上升機率：{prob}%
👉 {action}

📉 支撐：{support:.2f}
📈 阻力：{resistance:.2f}

💰 策略
入場：{support:.2f}
止蝕：{support*0.97:.2f}
"""

    msg += get_news(symbol)

    return msg

# ======================
# ⏰ AUTO PUSH
# ======================
def auto_push():
    while True:
        try:
            for s in SYMBOLS:
                send(build(s))
        except:
            pass
        time.sleep(1800)

threading.Thread(target=auto_push, daemon=True).start()

# ======================
# 🌐 WEBHOOK
# ======================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data=request.get_json()

    if "message" not in data:
        return "ok"

    text=data["message"].get("text","")

    if text=="/start":
        send("""🚀 AI交易Bot

/check → 全部分析
/check TSLA / NVDA / AMD

🔥 自動推送 + 突破alert
""")

    if text.startswith("/check"):
        for s in SYMBOLS:
            send(build(s))

    return "ok"

@app.route("/")
def home():
    return "running"

# ======================
# RUN
# ======================
if __name__=="__main__":
    app.run(host="0.0.0.0", port=10000)
