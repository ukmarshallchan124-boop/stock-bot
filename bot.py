from flask import Flask, request
import requests, os, time, threading, json
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

TRADE_FILE = "trades.json"
signal_state = {}

SETUP_COOLDOWN = 1800
ENTRY_COOLDOWN = 3600

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
# MARKET
# ======================
def market_trend():
    try:
        spy = yf.Ticker("SPY").history(period="5d", interval="1d")
        change = (spy["Close"].iloc[-1] - spy["Close"].iloc[-3]) / spy["Close"].iloc[-3] * 100
        if change > 1:
            return "📈 美股偏強", True
        elif change < -1:
            return "📉 美股偏弱", False
        else:
            return "⚪ 市場震盪", True
    except:
        return "⚪ 市場未知", True

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:3]
        score = 0
        text = ""
        for n in news:
            title = n["title"]
            if any(w in title.lower() for w in ["beat","growth","strong","ai"]):
                score += 1
                text += f"🟢 {title}\n"
            elif any(w in title.lower() for w in ["drop","cut","risk"]):
                score -= 1
                text += f"🔴 {title}\n"
            else:
                text += f"⚪ {title}\n"

        summary = "🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        return text + f"\n🧠 新聞總結：{summary}"
    except:
        return "⚪ 無新聞"

# ======================
# TRADE DATA
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

def get_winrate(symbol):
    trades = load_trades()
    wins = [t for t in trades if t["symbol"]==symbol and t["result"]=="win"]
    total = [t for t in trades if t["symbol"]==symbol]
    if len(total)==0:
        return 60
    return int(len(wins)/len(total)*100)

def record_trade(symbol, entry, stop, target):
    trades = load_trades()
    trades.append({"symbol":symbol,"entry":entry,"stop":stop,"target":target,"result":"open"})
    save_trades(trades)

def update_trades():
    trades = load_trades()
    for t in trades:
        if t["result"]!="open": continue
        df = yf.Ticker(t["symbol"]).history(period="1d")
        price = df["Close"].iloc[-1]
        if price>=t["target"]:
            t["result"]="win"
        elif price<=t["stop"]:
            t["result"]="loss"
    save_trades(trades)

# ======================
# DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")
    if df.empty: return None

    price = df["Close"].iloc[-1]
    high = df["High"].max()
    low = df["Low"].min()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi_val = (100-(100/(1+rs))).iloc[-1]

    if rsi_val>70:
        rsi="🔴 偏高（小心回調）"
    elif rsi_val<30:
        rsi="🟢 偏低（可能反彈）"
    else:
        rsi="⚪ 正常"

    ema12=df["Close"].ewm(span=12).mean()
    ema26=df["Close"].ewm(span=26).mean()
    macd_line=ema12-ema26
    signal=macd_line.ewm(span=9).mean()
    macd="🟢 上升趨勢" if macd_line.iloc[-1]>signal.iloc[-1] else "🔴 下跌趨勢"

    momentum=(price-df["Close"].iloc[-20])/df["Close"].iloc[-20]*100

    entry_low=low*1.01
    entry_high=low*1.03
    stop=low*0.97
    target=high*1.02
    rr=(target-entry_low)/(entry_low-stop)

    return {
        "price":round(price,2),
        "rsi":rsi,
        "macd":macd,
        "momentum":round(momentum,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2)
    }

# ======================
# FORMAT（完整版UI）
# ======================
def format_full(symbol, d):
    win = get_winrate(symbol)
    news = get_news(symbol)
    market_text,_ = market_trend()

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
🧠 成功率：{win}%
⏱ Timing：❌ 唔好追

━━━━━━━━━━━━━━

📉 趨勢：{"偏強" if "🟢" in d['macd'] else "偏弱"}

RSI：{d['rsi']}
MACD：{d['macd']}

━━━━━━━━━━━━━━

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

━━━━━━━━━━━━━━

💰 策略（重點🔥）

👉 入場：{d['entry_low']} – {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━

🌍 市場：{market_text}

━━━━━━━━━━━━━━

📌 行動建議：

👉 ❌ 太高唔好追
👉 ✔ 等回調入場

━━━━━━━━━━━━━━

🧠 AI結論：

👉 {"🟢 低風險" if win>70 else "🟡 中風險" if win>55 else "🔴 高風險"}

━━━━━━━━━━━━━━

📰【{symbol} 新聞】

{news}
"""

# ======================
# SETUP / ENTRY FORMAT
# ======================
def format_setup(symbol, d):
    return f"""
👀【{symbol} Setup】

📉 回調區：
{d['entry_low']} – {d['entry_high']}

👉 原因：
✔ 回調接近支撐
✔ R/R合理
✔ 趨勢未破壞

👉 行動：
⏳ 等入區
❌ 唔好追
"""

def format_entry(symbol, d):
    return f"""
🚀【{symbol} 入場確認】

📉 區間：
{d['entry_low']} – {d['entry_high']}

✔ 價格到位
✔ RSI安全
✔ 趨勢支持

👉 可分批入（中高信心）
"""

# ======================
# LOOP
# ======================
def loop():
    while True:
        try:
            update_trades()
            now=time.time()
            _,market_ok=market_trend()

            for s in SWING_STOCKS:
                d=get_data(s)
                if not d: continue

                state=signal_state.get(s,{"setup":0,"entry":0,"zone":None})
                zone=f"{d['entry_low']}-{d['entry_high']}"

                if d["rr"]>=2 and d["price"]>d["entry_high"] and market_ok:
                    if now-state["setup"]>SETUP_COOLDOWN and zone!=state["zone"]:
                        send(CHAT_ID, format_setup(s,d))
                        state["setup"]=now
                        state["zone"]=zone

                in_range=d["entry_low"]<=d["price"]<=d["entry_high"]

                if in_range and "🔴" not in d["rsi"] and "🟢" in d["macd"] and market_ok:
                    if now-state["entry"]>ENTRY_COOLDOWN:
                        send(CHAT_ID, format_entry(s,d))
                        record_trade(s,d["entry_low"],d["stop"],d["target"])
                        state["entry"]=now

                if not in_range:
                    state["entry"]=0

                signal_state[s]=state

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop,daemon=True).start()

# ======================
# TOOLS
# ======================
def calc(x):
    x=float(x)
    return f"+10% → {round(x*1.1,2)}\n-10% → {round(x*0.9,2)}"

def position(symbol,entry):
    df=yf.Ticker(symbol).history(period="1d")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"{symbol} 盈虧：{round(pnl,2)}%"

# ======================
# WEBHOOK
# ======================
@app.route("/",methods=["POST"])
def webhook():
    data=request.get_json()
    if not data or "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text in ["/start","start"]:
        send(chat_id,"🚀 V27 FINAL",menu())

    elif text=="📊 波段分析":
        for s in SWING_STOCKS:
            d=get_data(s)
            if d:
                send(chat_id,format_full(s,d),menu())

    elif text=="💰 長線投資":
        send(chat_id,"📈 S&P500 👉 每月定期買\nMSFT 👉 跌先加倉",menu())

    elif text=="🧮 計算工具":
        send(chat_id,"輸入價格",menu())

    elif text.replace('.','',1).isdigit():
        send(chat_id,calc(text),menu())

    elif text=="📍 持倉分析":
        send(chat_id,"輸入：TSLA 300",menu())

    elif len(text.split())==2:
        s,p=text.split()
        send(chat_id,position(s.upper(),float(p)),menu())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
