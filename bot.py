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
    except Exception as e:
        print("SEND ERROR:", e)

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
        if spy is None or spy.empty or len(spy)<3:
            return "⚪ 市場未知", True

        change = (spy["Close"].iloc[-1] - spy["Close"].iloc[-3]) / spy["Close"].iloc[-3] * 100

        if change > 1:
            return "📈 美股偏強（Risk ON）", True
        elif change < -1:
            return "📉 美股偏弱（Risk OFF）", False
        else:
            return "⚪ 市場震盪", True
    except Exception as e:
        print("market error:", e)
        return "⚪ 市場未知", True

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news or []
        news = news[:3]

        if not news:
            return "⚪ 無新聞"

        score = 0
        txt = ""

        for n in news:
            title = n.get("title","")
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

    except Exception as e:
        print("news error:", e)
        return "⚪ 無新聞"

# ======================
# WINRATE
# ======================
def load_trades():
    try:
        with open(TRADE_FILE,"r") as f:
            return json.load(f)
    except:
        return []

def save_trades(data):
    try:
        with open(TRADE_FILE,"w") as f:
            json.dump(data,f)
    except:
        pass

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
        "result":"open",
        "time":time.time()
    })
    save_trades(trades)

# ======================
# INDICATORS（修復）
# ======================
def indicators(df):
    try:
        if df is None or df.empty:
            return 50,"⚪ 無數據"

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
    except:
        return 50,"⚪ 無數據"

# ======================
# MTF（修復）
# ======================
def mtf_trend(symbol):
    try:
        df_1h = yf.Ticker(symbol).history(period="30d", interval="1h")

        if df_1h is None or df_1h.empty:
            return None

        df_4h = df_1h.resample("4H").last().dropna()
        if df_4h.empty:
            return None

        ema50_4h = df_4h["Close"].ewm(span=50).mean()
        ema20_1h = df_1h["Close"].ewm(span=20).mean()

        mom_4h = df_4h["Close"].diff().iloc[-3:].mean()

        trend_4h = df_4h["Close"].iloc[-1] > ema50_4h.iloc[-1] and mom_4h > 0
        trend_1h = df_1h["Close"].iloc[-1] > ema20_1h.iloc[-1]

        pullback = df_1h["Close"].iloc[-1] < df_1h["Close"].rolling(10).max().iloc[-1]

        return trend_4h, trend_1h, pullback

    except Exception as e:
        print("mtf error:", e)
        return None

# ======================
# ENTRY 15m
# ======================
def entry_15m(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")

        if df is None or df.empty:
            return False

        ema9 = df["Close"].ewm(span=9).mean()
        ema21 = df["Close"].ewm(span=21).mean()
        momentum = df["Close"].diff().iloc[-3:].mean()

        return ema9.iloc[-1] > ema21.iloc[-1] and momentum > 0

    except:
        return False

# ======================
# DATA（修復核心🔥）
# ======================
def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")

        if df is None or df.empty:
            return None

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

    except Exception as e:
        print("data error:", symbol, e)
        return None

# ======================
# FORMAT FULL
# ======================
def format_full(symbol, d):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")
        rsi, macd = indicators(df)

        mtf = mtf_trend(symbol)
        if not mtf:
            return f"{symbol} 無數據"

        trend_4h, trend_1h, pullback = mtf

        trend4 = "🟢 上升趨勢" if trend_4h else "🔴 下跌趨勢"
        trend1 = "🟡 回調中" if pullback else "🟢 延續中"
        timing = "🟢 轉強" if entry_15m(symbol) else "⚪ 未確認"

        win = get_winrate(symbol)
        news = get_news(symbol)
        market_text,_ = market_trend()

        return f"""
📊【{symbol} 波段分析｜MTF】

💰 價格：{d['price']}
🧠 勝率：{win}%
🌍 市場：{market_text}

━━━━━━━━━━━━━━

📈 大方向（4H）：{trend4}
📊 主趨勢（1H）：{trend1}
⚡ Timing（15m）：{timing}

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
    except Exception as e:
        print("format error:", e)
        return f"{symbol} error"

# ======================
# LONG TERM
# ======================
def long_term():
    return """
💰【長線投資】

📊 MSFT：
👉 回調（-5% / -10%）加倉

📈 S&P500：
👉 每月定期買（DCA）
👉 長期持有
"""

# ======================
# LOOP
# ======================
def loop():
    while True:
        try:
            now = time.time()
            _, market_ok = market_trend()

            for s in SWING_STOCKS:
                d = get_data(s)
                if not d: continue

                mtf = mtf_trend(s)
                if not mtf: continue

                trend_4h, trend_1h, pullback = mtf
                confirm = entry_15m(s)

                state = signal_state.get(s, {"setup":0,"entry":0,"zone":None})
                zone = f"{d['entry_low']}-{d['entry_high']}"

                if not (trend_4h and trend_1h and market_ok):
                    continue

                # SETUP（防重複）
                if d["price"] > d["entry_high"] and d["rr"] > 2:
                    if now - state["setup"] > SETUP_COOLDOWN and zone != state["zone"]:
                        send(CHAT_ID, f"👀 {s} Setup\n{zone}")
                        state["setup"] = now
                        state["zone"] = zone

                # ENTRY
                in_range = d["entry_low"] <= d["price"] <= d["entry_high"]

                if in_range and confirm:
                    if now - state["entry"] > ENTRY_COOLDOWN:
                        send(CHAT_ID, f"🚀 {s} Entry\n{zone}")
                        record_trade(s,d["entry_low"],d["stop"],d["target"])
                        state["entry"] = now

                if not in_range:
                    state["entry"] = 0

                signal_state[s] = state

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e)

threading.Thread(target=loop,daemon=True).start()

# ======================
# TOOLS
# ======================
def calc(x):
    x=float(x)
    return f"+10% → {round(x*1.1,2)}\n-10% → {round(x*0.9,2)}"

def position(symbol,entry):
    try:
        df=yf.Ticker(symbol).history(period="1d")
        if df.empty:
            return "無數據"
        price=df["Close"].iloc[-1]
        pnl=(price-entry)/entry*100
        return f"{symbol} 盈虧：{round(pnl,2)}%"
    except:
        return "計算錯誤"

# ======================
# WEBHOOK
# ======================
@app.route("/",methods=["POST"])
def webhook():
    try:
        data=request.get_json()

        if not data or "message" not in data:
            return "ok"

        chat_id=data["message"]["chat"]["id"]
        text=data["message"].get("text","").strip()

        if text in ["/start","start"]:
            send(chat_id,"🚀 V29.1 修復版",menu())

        elif "波段分析" in text:
            for s in SWING_STOCKS:
                d=get_data(s)
                if d:
                    send(chat_id,format_full(s,d),menu())

        elif "長線投資" in text:
            send(chat_id,long_term(),menu())

        elif "計算工具" in text:
            send(chat_id,"輸入數字，例如 300",menu())

        elif text.replace('.','',1).isdigit():
            send(chat_id,calc(text),menu())

        elif "持倉分析" in text:
            send(chat_id,"輸入：TSLA 300",menu())

        elif len(text.split())==2:
            s,p=text.split()
            send(chat_id,position(s.upper(),float(p)),menu())

        return "ok"

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
