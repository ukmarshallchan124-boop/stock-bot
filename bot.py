from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}
msft_last = 0

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": msg})
    except:
        pass

# ======================
# 市場狀態（🔥核心）
# ======================
def market_status():
    try:
        sp = yf.Ticker("SPY").history(period="3mo")
        price = sp["Close"].iloc[-1]
        ma50 = sp["Close"].rolling(50).mean().iloc[-1]

        if price > ma50:
            trend = "📈 上升"
            advice = "可等回調買"
        else:
            trend = "📉 轉弱"
            advice = "減少操作"

        return f"""🌍【市場狀態】

📊 S&P500：{trend}

🧠 解讀：
👉 {advice}
━━━━━━━━━━━
"""
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

    entry_low = low*1.01
    entry_high = low*1.03

    dist = (price-entry_high)/entry_high*100

    return {
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "dist":round(dist,1)
    }

# ======================
# AI
# ======================
def ai_grade(price, entry_low, entry_high):
    if entry_low <= price <= entry_high:
        return "🟣 S級","🔥 可以入場"
    elif price > entry_high:
        return "🔵 A級","👀 等回調"
    else:
        return "🟡 B級","⏳ 未到位"

# ======================
# FORMAT（🔥專業版）
# ======================
def format_output(symbol):
    d = get_data(symbol)
    if not d: return "無數據"

    grade,action = ai_grade(d["price"], d["entry_low"], d["entry_high"])

    return f"""{market_status()}
📊【{symbol} 波段分析】

💰 價格：{d['price']}

🏆 等級：{grade}
🚦 行動：{action}

━━━━━━━━━━━

🎯 入場區：
{d['entry_low']} - {d['entry_high']}

📏 距離入場：
{d['dist']}%

━━━━━━━━━━━

⏳ 預期：
👉 2–5日內回調（短期）
👉 1–2星期（正常）

━━━━━━━━━━━

📌 建議：

❌ 唔好追高
✔ 等跌落區先考慮
"""

# ======================
# MSFT（🔥專業版）
# ======================
def msft_analysis():
    df = yf.Ticker("MSFT").history(period="6mo")
    price = df["Close"].iloc[-1]

    m3 = (price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

    return f"""💰【MSFT 長線分析】

💵 價格：{round(price,2)}

📉 3個月回調：
{round(m3,1)}%

━━━━━━━━━━━

💡 分批策略：

🟢 第1注：而家（30%）
🟡 第2注：再跌5%
🔴 第3注：再跌10%

━━━━━━━━━━━

⏳ 時間：
1–4星期回調期

━━━━━━━━━━━

📌 結論：
👉 可以開始分批加倉
"""

# ======================
# LOOP
# ======================
def loop():
    global msft_last

    while True:
        try:
            for s in SYMBOLS:
                d = get_data(s)
                if not d: continue

                now=time.time()
                last=last_alert.get(s,0)

                # Setup
                if d["price"] > d["entry_high"] and now-last>3600:
                    send(CHAT_ID,f"""👀【{s} Setup】

等回調：
{d['entry_low']} - {d['entry_high']}

距離：{d['dist']}%
""")
                    last_alert[s]=now

                # Entry
                if d["entry_low"] <= d["price"] <= d["entry_high"] and now-last>600:
                    send(CHAT_ID,f"""🚀【{s} 入場】

入場區：
{d['entry_low']} - {d['entry_high']}
""")
                    last_alert[s]=now

            # MSFT
            if time.time()-msft_last>86400:
                send(CHAT_ID, msft_analysis())
                msft_last=time.time()

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# WEBHOOK
# ======================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data=request.get_json()

    if "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text=="/check":
        for s in SYMBOLS:
            send(chat_id,format_output(s))

    elif text=="/msft":
        send(chat_id,msft_analysis())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
