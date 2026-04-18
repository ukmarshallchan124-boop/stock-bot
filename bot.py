from flask import Flask, request
import requests, os, time, threading, json
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD","MSFT"]

TRADE_FILE = "trades.json"
signal_state = {}

SETUP_COOLDOWN = 1800
ENTRY_COOLDOWN = 3600

# ======================
# SEND + MENU
# ======================
def send(chat_id, text, keyboard=None):
    try:
        data = {"chat_id": chat_id, "text": text[:4000]}
        if keyboard:
            data["reply_markup"] = keyboard
        requests.post(f"{URL}/sendMessage", json=data)
    except:
        pass

def menu():
    return {
        "keyboard":[
            ["📊 波段分析","💰 長線投資"],
            ["🧮 計算工具","📍 持倉分析"]
        ],
        "resize_keyboard":True
    }

# ======================
# 市場（Regime）
# ======================
def market_trend():
    try:
        spy = yf.Ticker("SPY").history(period="5d", interval="1d")
        change = (spy["Close"].iloc[-1] - spy["Close"].iloc[-3]) / spy["Close"].iloc[-3] * 100

        if change > 1:
            return "📈 美股偏強（Risk ON）", True
        elif change < -1:
            return "📉 美股偏弱（Risk OFF）", False
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
        txt = ""

        for n in news:
            title = n["title"]
            if any(w in title.lower() for w in ["beat","growth","strong","ai"]):
                score += 1
                txt += f"🟢 {title}\n"
            elif any(w in title.lower() for w in ["drop","cut","risk"]):
                score -= 1
                txt += f"🔴 {title}\n"
            else:
                txt += f"⚪ {title}\n"

        summary = "🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        return txt + f"\n🧠 新聞總結：{summary}"

    except:
        return "⚪ 無新聞"

# ======================
# 勝率
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
    trades.append({
        "symbol":symbol,
        "entry":entry,
        "stop":stop,
        "target":target,
        "result":"open"
    })
    save_trades(trades)

# ======================
# MTF（修復版）
# ======================
def mtf_trend(symbol):
    df_1h = yf.Ticker(symbol).history(period="30d", interval="1h")
    df_4h = df_1h.resample("4H").last().dropna()

    if df_4h.empty or df_1h.empty:
        return None

    ema50_4h = df_4h["Close"].ewm(span=50).mean()
    ema20_1h = df_1h["Close"].ewm(span=20).mean()

    mom_4h = df_4h["Close"].diff().iloc[-3:].mean()
    mom_1h = df_1h["Close"].diff().iloc[-3:].mean()

    trend_4h = df_4h["Close"].iloc[-1] > ema50_4h.iloc[-1] and mom_4h > 0
    trend_1h = df_1h["Close"].iloc[-1] > ema20_1h.iloc[-1]

    pullback = df_1h["Close"].iloc[-1] < df_1h["Close"].rolling(10).max().iloc[-1]

    return trend_4h, trend_1h, pullback

def entry_15m(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="15m")
    if df.empty: return False

    ema9 = df["Close"].ewm(span=9).mean()
    ema21 = df["Close"].ewm(span=21).mean()
    momentum = df["Close"].diff().iloc[-3:].mean()

    return ema9.iloc[-1] > ema21.iloc[-1] and momentum > 0

# ======================
# RSI + MACD
# ======================
def indicators(df):
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = (100-(100/(1+rs))).iloc[-1]

    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()

    macd = "🟢 上升動能" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴 下跌動能"

    return round(rsi,1), macd

# ======================
# BASE DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="15m")
    if df.empty: return None

    price = df["Close"].iloc[-1]
    high = df["High"].max()
    low = df["Low"].min()

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02
    rr = (target-entry_low)/(entry_low-stop)

    return {
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2)
    }

# ======================
# Setup 分級
# ======================
def setup_grade(d, trend_4h, pullback):
    score = 0
    if d["rr"] > 2.5: score += 2
    if trend_4h: score += 2
    if pullback: score += 1

    if score >=4: return "🟣 強"
    elif score >=2: return "🟡 中"
    else: return "🔴 弱"

# ======================
# 波段分析 UI
# ======================
def format_full(symbol, d):
    df = yf.Ticker(symbol).history(period="5d", interval="15m")
    rsi, macd = indicators(df)

    win = get_winrate(symbol)
    news = get_news(symbol)
    market_text,_ = market_trend()

    return f"""
📊【{symbol} 波段分析｜MTF】

💰 價格：{d['price']}
🧠 勝率：{win}%
🌍 市場：{market_text}

━━━━━━━━━━━━━━

RSI：{rsi}
MACD：{macd}

━━━━━━━━━━━━━━

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

🎯 策略：

👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━

📰 新聞：
{news}
"""

# ======================
# 長線 MSFT
# ======================
def msft_long():
    df_d = yf.Ticker("MSFT").history(period="1y", interval="1d")
    df_w = yf.Ticker("MSFT").history(period="5y", interval="1wk")

    ema_d = df_d["Close"].ewm(span=50).mean()
    ema_w = df_w["Close"].ewm(span=50).mean()

    trend_d = "🟢 上升" if df_d["Close"].iloc[-1] > ema_d.iloc[-1] else "🔴 轉弱"
    trend_w = "🟢 長期上升" if df_w["Close"].iloc[-1] > ema_w.iloc[-1] else "🔴 長期轉弱"

    return f"""
💰【MSFT 長線】

📊 週線：{trend_w}
📊 日線：{trend_d}

👉 策略：
✔ 長線持有
✔ 回調加倉
"""

# ======================
# LOOP（核心🔥）
# ======================
def loop():
    while True:
        try:
            now = time.time()
            market_text, market_ok = market_trend()

            for s in SWING_STOCKS:
                d = get_data(s)
                if not d: continue

                df = yf.Ticker(s).history(period="5d", interval="15m")
                rsi, macd = indicators(df)

                mtf = mtf_trend(s)
                if not mtf: continue

                trend_4h, trend_1h, pullback = mtf
                confirm = entry_15m(s)

                state = signal_state.get(s, {"setup":0,"entry":0})

                if not (trend_4h and trend_1h and market_ok):
                    continue

                grade = setup_grade(d, trend_4h, pullback)

                # SETUP
                if d["price"] > d["entry_high"] and grade != "🔴 弱":
                    if now - state["setup"] > SETUP_COOLDOWN:
                        send(CHAT_ID,f"""👀【{s} {grade} Setup】

📉 {d['entry_low']} - {d['entry_high']}

RSI：{rsi}
MACD：{macd}

👉 等 confirmation
""")
                        state["setup"] = now

                # ENTRY
                in_range = d["entry_low"] <= d["price"] <= d["entry_high"]

                if in_range and confirm:
                    if now - state["entry"] > ENTRY_COOLDOWN:
                        send(CHAT_ID,f"""🚀【{s} 入場確認】

✔ MTF一致
✔ 15m轉強
✔ 動能支持

👉 {d['entry_low']} - {d['entry_high']}
""")
                        record_trade(s,d["entry_low"],d["stop"],d["target"])
                        state["entry"] = now

                signal_state[s] = state

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop,daemon=True).start()

# ======================
# 工具
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
        send(chat_id,"🚀 V28.3 專業版",menu())

    elif text=="📊 波段分析":
        for s in SWING_STOCKS:
            d=get_data(s)
            if d:
                send(chat_id,format_full(s,d),menu())

    elif text=="💰 長線投資":
        send(chat_id,msft_long(),menu())

    elif text=="🧮 計算工具":
        send(chat_id,"輸入數字，例如 300",menu())

    elif text.replace('.','',1).isdigit():
        send(chat_id,calc(text),menu())

    elif text=="📍 持倉分析":
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
