from flask import Flask, request
import requests, os, time, threading, json
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

signal_state = {}
COOLDOWN = 1800  # 30分鐘

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

    if macd_line.iloc[-1] > signal.iloc[-1] and macd_line.iloc[-2] <= signal.iloc[-2]:
        macd = "🟡 黃金交叉"
    elif macd_line.iloc[-1] < signal.iloc[-1] and macd_line.iloc[-2] >= signal.iloc[-2]:
        macd = "🔴 死亡交叉"
    elif macd_line.iloc[-1] > signal.iloc[-1]:
        macd = "🟢 多頭延續"
    else:
        macd = "⚪ 空頭"

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
# NEWS
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:2]
        txt = "\n📰【新聞】\n"
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

    timing = "🔥 入場區" if d["entry_low"] <= d["price"] <= d["entry_high"] else "❌ 唔好追" if d["price"] > d["entry_high"] else "⏳ 等回調"
    action = "❌ 唔好追" if d["price"] > d["entry_high"] else "⏳ 等回調" if d["price"] < d["entry_low"] else "🔥 可考慮入場"

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
⏱ Timing：{timing}

━━━━━━━━━━━━━━

RSI：{d['rsi']}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

━━━━━━━━━━━━━━

🎯 策略：
👉 入場：{d['entry_low']} – {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━

📌 行動：
👉 {action}

{get_news(symbol)}
"""

# ======================
# LONG TERM
# ======================
def format_long():
    df = yf.Ticker("MSFT").history(period="6mo")
    price = df["Close"].iloc[-1]

    return f"""
💰【長線分析】

📊 MSFT：{round(price,2)}

🟢 現價：30%
🟡 -5%：30%
🔴 -10%：40%

📈 S&P500：
VOO / SPY / VUAG

👉 每月 DCA + 回調加倉
"""

# ======================
# TOOLS
# ======================
def calc(x):
    x=float(x)
    return f"+10% → {round(x*1.1,2)}\n-10% → {round(x*0.9,2)}"

def position(symbol, entry):
    df=yf.Ticker(symbol).history(period="1d")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"{symbol} 盈虧：{round(pnl,2)}%"

# ======================
# AUTO LOOP（🔥升級版）
# ======================
def loop():
    while True:
        try:
            now = time.time()

            for s in SWING_STOCKS:
                d = get_data(s)
                if not d:
                    continue

                state = signal_state.get(s, {
                    "setup": False,
                    "entry": False,
                    "last_setup_time": 0,
                    "last_zone": None
                })

                trend_ok = ("🟢" in d["macd"] or "🟡" in d["macd"]) and d["momentum"] > 0
                rr_ok = d["rr"] >= 2

                allow_setup = d["price"] > d["entry_high"] and trend_ok and rr_ok

                if d["rr"] >= 3 and d["momentum"] > 2:
                    grade = "🟣 強"
                elif d["rr"] >= 2:
                    grade = "🟡 中"
                else:
                    grade = "🔴 弱"

                zone = f"{d['entry_low']}-{d['entry_high']}"

                # SETUP
                if allow_setup and grade != "🔴 弱":
                    if (now - state["last_setup_time"] > COOLDOWN) or state["last_zone"] != zone:
                        send(CHAT_ID,f"""👀【{s} {grade} Setup】

📉 {d['entry_low']} – {d['entry_high']}

📊 R/R：{d['rr']}
📈 動能：{d['momentum']}%
""")

                        state["setup"] = True
                        state["last_setup_time"] = now
                        state["last_zone"] = zone

                # ENTRY
                in_range = d["entry_low"] <= d["price"] <= d["entry_high"]

                confirm = (
                    in_range and
                    d["rsi"] < 50 and
                    ("🟢" in d["macd"] or "🟡" in d["macd"]) and
                    d["momentum"] >= 0
                )

                if confirm and not state["entry"]:
                    send(CHAT_ID,f"""🚀【{s} 入場確認】

👉 {d['entry_low']} – {d['entry_high']}

✔ RSI 健康
✔ MACD 多頭
""")

                    state["entry"] = True

                if not in_range:
                    state["entry"] = False

                signal_state[s] = state

            time.sleep(300)

        except Exception as e:
            print(e)

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
        send(chat_id,"🚀 Trading System V21.1",menu())

    elif text == "📊 波段分析":
        for s in SWING_STOCKS:
            send(chat_id,format_swing(s),menu())

    elif text == "💰 長線投資":
        send(chat_id,format_long(),menu())

    elif text == "🧮 計算工具":
        send(chat_id,"輸入價格，例如 300",menu())

    elif text.replace('.','',1).isdigit():
        send(chat_id,calc(text),menu())

    elif text == "📍 持倉分析":
        send(chat_id,"輸入：TSLA 300",menu())

    elif len(text.split())==2:
        s,p=text.split()
        try:
            send(chat_id,position(s.upper(),float(p)),menu())
        except:
            pass

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
