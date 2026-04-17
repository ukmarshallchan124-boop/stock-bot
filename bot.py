from flask import Flask, request
import requests, os, time, threading, json
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

signal_state = {}
TRADE_FILE = "trades.json"

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
# MENU（App UI）
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
# LOAD / SAVE（勝率追蹤）
# ======================
def load_trades():
    try:
        with open(TRADE_FILE,"r") as f:
            return json.load(f)
    except:
        return []

def save_trades(data):
    with open(TRADE_FILE,"w") as f:
        json.dump(data,f)

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
# NEWS（簡易 AI）
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:2]
        txt = "\n📰【新聞】\n"
        score = 0

        for n in news:
            title = n["title"]
            if any(w in title.lower() for w in ["surge","growth","beat","strong"]):
                tag="🟢 利好"; score+=1
            elif any(w in title.lower() for w in ["drop","cut","risk"]):
                tag="🔴 利淡"; score-=1
            else:
                tag="⚪ 中性"

            txt += f"• {title}\n{tag}\n"

        summary = "🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        txt += f"\n🧠 新聞結論：{summary}\n"

        return txt, score
    except:
        return "\n📰 無新聞\n",0

# ======================
# AI 評分
# ======================
def ai_score(d, news_score):
    score = 50

    if d["rsi"] < 45: score += 10
    if "🟢" in d["macd"]: score += 15
    if "🟡" in d["macd"]: score += 20
    if d["rr"] > 2: score += 15
    if d["momentum"] > 0: score += 10

    score += news_score * 5

    return min(95,max(40,score))

# ======================
# 勝率（學習）
# ======================
def get_winrate(symbol):
    trades = load_trades()
    wins = [t for t in trades if t["symbol"]==symbol and t["result"]=="win"]
    total = [t for t in trades if t["symbol"]==symbol]

    if len(total)==0:
        return 60

    return int(len(wins)/len(total)*100)

# ======================
# FORMAT（核心🔥）
# ======================
def format_swing(symbol):
    d = get_data(symbol)
    if not d:
        return "無數據"

    news, news_score = get_news(symbol)
    score = ai_score(d, news_score)

    timing = "🔥 入場區" if d["entry_low"] <= d["price"] <= d["entry_high"] else "❌ 唔好追" if d["price"] > d["entry_high"] else "⏳ 等回調"

    action = "❌ 唔好追" if d["price"] > d["entry_high"] else "⏳ 等回調" if d["price"] < d["entry_low"] else "🔥 可考慮入場"

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
🧠 AI評分：{score}%

⏱ Timing：{timing}

━━━━━━━━━━━━━━

📉 趨勢：{"📈 偏強" if d["momentum"]>0 else "📉 偏弱"}

RSI：{d['rsi']}
MACD：{d['macd']}

📊 支撐：{d['entry_low']}
📊 阻力：{d['target']}

━━━━━━━━━━━━━━

🎯 策略（重點🔥）

👉 入場：{d['entry_low']} – {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━

📌 行動建議：
👉 {action}

⏳ 預期：
👉 2 – 5日內機會出現

━━━━━━━━━━━━━━

🧠 AI結論：
👉 {"❌ 高位風險" if d["price"]>d["entry_high"] else "⏳ 等回調先" if d["price"]<d["entry_low"] else "🔥 可入場"}

{news}
"""

# ======================
# 長線
# ======================
def format_long():
    df = yf.Ticker("MSFT").history(period="6mo")
    price = df["Close"].iloc[-1]
    m3 = (price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

    return f"""
💰【長線投資分析】

📊 MSFT：{round(price,2)}
📉 3個月：{round(m3,1)}%

━━━━━━━━━━━━━━

💡 分批策略：

🟢 現價：30%
🟡 -5%：30%
🔴 -10%：40%

━━━━━━━━━━━━━━

📈 S&P500：

VOO / SPY / VUAG

👉 每月 1–2 次
👉 跌 5% 加
👉 跌 10% 加多
👉 長期持有（5年以上）

━━━━━━━━━━━━━━

🧠 狀態：
🟢 可開始分批
"""

# ======================
# 工具
# ======================
def calc(x):
    x=float(x)
    return f"📊 計算結果\n+10% → {round(x*1.1,2)}\n-10% → {round(x*0.9,2)}"

def position(symbol, entry):
    df=yf.Ticker(symbol).history(period="1d")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"""
📍【持倉分析】

{symbol} 現價：{round(price,2)}
盈虧：{round(pnl,2)}%
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

                if d["rr"] < 2:
                    continue

                # Setup（只推一次）
                if d["price"] > d["entry_high"] and not state["setup"]:
                    send(CHAT_ID,f"👀【{s} Setup】\n{d['entry_low']} – {d['entry_high']}")
                    state["setup"]=True

                # Entry（嚴格）
                in_range = d["entry_low"] <= d["price"] <= d["entry_high"]

                if in_range and not state["entry"] and d["rsi"]<50 and ("🟢" in d["macd"] or "🟡" in d["macd"]):
                    send(CHAT_ID,f"🚀【{s} 入場確認】\n{d['entry_low']} – {d['entry_high']}")
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
    text = data["message"].get("text","").strip()

    if text in ["/start","start"]:
        send(chat_id,"🚀 AI Trading System（V21）",menu())

    elif text == "📊 波段分析":
        for s in SWING_STOCKS:
            send(chat_id,format_swing(s),menu())

    elif text == "💰 長線投資":
        send(chat_id,format_long(),menu())

    elif text == "🧮 計算工具":
        send(chat_id,"👉 輸入價格，例如：300",menu())

    elif text.replace('.','',1).isdigit():
        send(chat_id,calc(text),menu())

    elif text == "📍 持倉分析":
        send(chat_id,"👉 輸入：TSLA 300",menu())

    elif len(text.split())==2:
        s, p = text.split()
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
