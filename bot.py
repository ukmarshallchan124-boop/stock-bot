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
def send(chat_id, text, keyboard=None):
    try:
        data = {
            "chat_id": chat_id,
            "text": text[:4000]
        }
        if keyboard:
            data["reply_markup"] = keyboard

        requests.post(f"{URL}/sendMessage", json=data)
    except:
        pass

# ======================
# MENU
# ======================
def menu():
    return {
        "keyboard":[
            ["📊 波段分析","💰 長線投資"],
            ["🧮 計算工具","📍 持倉分析"]
        ],
        "resize_keyboard":True
    }

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

    macd = "🟢 多頭" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴 空頭"

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
        "rr":round(rr,2)
    }

# ======================
# AI 評分
# ======================
def ai_score(d):
    score = 50
    if d["rsi"] < 45: score += 10
    if "🟢" in d["macd"]: score += 15
    if d["rr"] > 2: score += 15
    return min(95, score)

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:2]
        txt = "\n📰 新聞：\n"
        for n in news:
            txt += f"• {n['title']}\n"
        return txt
    except:
        return "\n📰 無新聞\n"

# ======================
# FORMAT
# ======================
def format_swing(symbol):
    d = get_data(symbol)
    if not d:
        return "無數據"

    score = ai_score(d)

    msg = f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
🧠 成功率：{score}%

RSI：{d['rsi']}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

🎯 策略：
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}
"""
    msg += get_news(symbol)

    return msg

def format_long():
    df = yf.Ticker("MSFT").history(period="6mo")
    price = df["Close"].iloc[-1]

    return f"""
💰【長線分析】

📊 MSFT：{round(price,2)}

👉 分批加倉策略：
🟢 現價開始
🟡 -5% 加
🔴 -10% 加多

📈 S&P500：
VOO / SPY / VUAG（長線DCA）
"""

# ======================
# AUTO SIGNAL（🔥）
# ======================
def loop():
    while True:
        try:
            for s in SWING_STOCKS:
                d = get_data(s)
                if not d:
                    continue

                state = signal_state.get(s, {"setup":False,"entry":False})

                # Setup
                if d["price"] > d["entry_high"]:
                    if not state["setup"]:
                        send(CHAT_ID, f"👀【{s} Setup】\n等回調：{d['entry_low']} - {d['entry_high']}")
                        state["setup"] = True
                else:
                    state["setup"] = False

                # Entry
                in_range = d["entry_low"] <= d["price"] <= d["entry_high"]

                if in_range and not state["entry"] and d["rsi"] < 50 and "🟢" in d["macd"]:
                    send(CHAT_ID, f"🚀【{s} 入場】\n入場區：{d['entry_low']} - {d['entry_high']}")
                    state["entry"] = True

                if not in_range:
                    state["entry"] = False

                signal_state[s] = state

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
    text = data["message"].get("text","").strip()

    if text in ["/start","start"]:
        send(chat_id, "🚀 Trading System 啟動", menu())

    elif text in ["📊 波段分析"]:
        for s in SWING_STOCKS:
            send(chat_id, format_swing(s), menu())

    elif text in ["💰 長線投資"]:
        send(chat_id, format_long(), menu())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
