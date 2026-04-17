from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}
msft_last = 0

# ======================
# SEND（支援按鈕）
# ======================
def send(chat_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        data["reply_markup"] = keyboard

    requests.post(f"{URL}/sendMessage", json=data)

# ======================
# 主頁按鈕（🔥核心）
# ======================
def main_menu():
    return {
        "keyboard":[
            ["📊 波段分析","💰 長線投資"],
            ["🧮 計算工具","📌 持倉分析"]
        ],
        "resize_keyboard":True
    }

# ======================
# 市場狀態
# ======================
def market():
    try:
        df = yf.Ticker("SPY").history(period="3mo")
        price = df["Close"].iloc[-1]
        ma50 = df["Close"].rolling(50).mean().iloc[-1]

        if price > ma50:
            return "📈 市場偏強（可等回調買）"
        else:
            return "📉 市場轉弱（減少操作）"
    except:
        return ""

# ======================
# DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")
    if df.empty: return None

    price = float(df["Close"].iloc[-1])
    low = float(df["Low"].min())
    high = float(df["High"].max())

    entry_low = low*1.01
    entry_high = low*1.03

    dist = (price-entry_high)/entry_high*100

    return {
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "dist":round(dist,1),
        "target":round(high*1.02,2)
    }

# ======================
# 波段分析（靚版）
# ======================
def swing(symbol):
    d = get_data(symbol)
    if not d: return "無數據"

    timing = "🚀 入場區" if d["entry_low"]<=d["price"]<=d["entry_high"] else "❌ 唔好追"

    return f"""📊【{symbol} 波段分析】

💰 價格：{d['price']}

⏱️ Timing：{timing}

━━━━━━━━━━━

🎯 入場：
{d['entry_low']} - {d['entry_high']}

📏 距離：{d['dist']}%

🎯 目標：{d['target']}

━━━━━━━━━━━

{market()}

📌 建議：
❌ 唔好追高
✔ 等回調
"""

# ======================
# MSFT 長線
# ======================
def msft():
    df = yf.Ticker("MSFT").history(period="6mo")
    price = df["Close"].iloc[-1]

    m3 = (price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

    return f"""💰【MSFT 長線】

💵 價格：{round(price,2)}

📉 3個月回調：
{round(m3,1)}%

━━━━━━━━━━━

💡 分批策略：

🟢 而家：30%
🟡 再跌5%
🔴 再跌10%

━━━━━━━━━━━

📈 S&P500：
長線DCA（VOO / SPY / VUAG）

📌 建議：
👉 可開始分批
"""

# ======================
# 計算
# ======================
def calc(x):
    x=float(x)
    return f"+10% {round(x*1.1,2)}\n+20% {round(x*1.2,2)}"

# ======================
# 持倉
# ======================
def position(symbol, entry):
    df = yf.Ticker(symbol).history(period="1d")
    price = df["Close"].iloc[-1]
    pnl = (price-entry)/entry*100

    return f"""📊【{symbol} 持倉】

現價：{round(price,2)}
盈虧：{round(pnl,2)}%
"""

# ======================
# LOOP（自動）
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

                if d["price"] > d["entry_high"] and now-last>3600:
                    send(CHAT_ID,f"👀【{s} Setup】\n等回調：{d['entry_low']} - {d['entry_high']}")
                    last_alert[s]=now

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
# WEBHOOK（按鈕控制🔥）
# ======================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data=request.get_json()

    if "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    # 主頁
    if text=="/start":
        send(chat_id,"🚀 AI Trading System（App版）",main_menu())

    elif text=="📊 波段分析":
        for s in SYMBOLS:
            send(chat_id,swing(s))

    elif text=="💰 長線投資":
        send(chat_id,msft())

    elif text=="🧮 計算工具":
        send(chat_id,"👉 用 /calc 300")

    elif text=="📌 持倉分析":
        send(chat_id,"👉 用 /position TSLA 300")

    elif text.startswith("/calc"):
        send(chat_id,calc(text.split()[1]))

    elif text.startswith("/position"):
        p=text.split()
        send(chat_id,position(p[1],float(p[2])))

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
