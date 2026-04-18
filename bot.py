from flask import Flask, request
import requests, os, time, threading, json

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("TWELVE_API_KEY")

URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

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
# TWELVEDATA FETCH
# ======================
def fetch(symbol, interval):
    try:
        url = f"https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": 100,
            "apikey": API_KEY
        }
        r = requests.get(url, params=params).json()

        if "values" not in r:
            return None

        data = list(reversed(r["values"]))
        closes = [float(x["close"]) for x in data]
        highs = [float(x["high"]) for x in data]
        lows = [float(x["low"]) for x in data]

        return closes, highs, lows

    except Exception as e:
        print("FETCH ERROR:", e)
        return None

# ======================
# INDICATORS
# ======================
def ema(arr, n):
    k = 2/(n+1)
    ema = [arr[0]]
    for price in arr[1:]:
        ema.append(price*k + ema[-1]*(1-k))
    return ema

def rsi(arr, period=14):
    gains, losses = [], []
    for i in range(1,len(arr)):
        diff = arr[i]-arr[i-1]
        gains.append(max(diff,0))
        losses.append(abs(min(diff,0)))

    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period

    if avg_loss == 0:
        return 100

    rs = avg_gain/avg_loss
    return round(100 - (100/(1+rs)),1)

def macd(arr):
    ema12 = ema(arr,12)
    ema26 = ema(arr,26)
    macd_line = [a-b for a,b in zip(ema12,ema26)]
    signal = ema(macd_line,9)
    return "🟢 上升動能" if macd_line[-1] > signal[-1] else "🔴 下跌動能"

# ======================
# MTF TREND
# ======================
def mtf(symbol):
    d4 = fetch(symbol,"4h")
    d1 = fetch(symbol,"1h")
    d15 = fetch(symbol,"15min")

    if not d4 or not d1 or not d15:
        return None

    c4,_,_ = d4
    c1,_,_ = d1
    c15,_,_ = d15

    trend4 = c4[-1] > ema(c4,50)[-1]
    trend1 = c1[-1] > ema(c1,20)[-1]
    timing = c15[-1] > ema(c15,9)[-1]

    pullback = c1[-1] < max(c1[-10:])

    return trend4, trend1, timing, pullback

# ======================
# DATA
# ======================
def get_data(symbol):
    d = fetch(symbol,"15min")
    if not d:
        return None

    closes, highs, lows = d

    price = closes[-1]
    high = max(highs)
    low = min(lows)

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
        "rr":round(rr,2),
        "closes":closes
    }

# ======================
# NEWS（簡化保留）
# ======================
def get_news(symbol):
    return "🧠 使用 TwelveData（穩定數據源）"

# ======================
# FORMAT FULL
# ======================
def format_full(symbol, d):
    mt = mtf(symbol)
    if not mt:
        return f"{symbol} 無數據"

    trend4, trend1, timing, pullback = mt

    trend4_txt = "🟢 上升" if trend4 else "🔴 下跌"
    trend1_txt = "🟡 回調中" if pullback else "🟢 延續"
    timing_txt = "🟢 轉強" if timing else "⚪ 未確認"

    r = rsi(d["closes"])
    m = macd(d["closes"])

    return f"""
📊【{symbol} 波段分析｜V30】

💰 價格：{d['price']}

━━━━━━━━━━━━━━

📈 4H：{trend4_txt}
📊 1H：{trend1_txt}
⚡ 15m：{timing_txt}

━━━━━━━━━━━━━━

RSI：{r}
MACD：{m}

━━━━━━━━━━━━━━

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

🎯 策略：

👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}
"""

# ======================
# LOOP
# ======================
def loop():
    while True:
        try:
            now = time.time()

            for s in SWING_STOCKS:
                d = get_data(s)
                if not d:
                    continue

                mt = mtf(s)
                if not mt:
                    continue

                trend4, trend1, timing, pullback = mt

                state = signal_state.get(s, {"setup":0,"entry":0,"zone":None})
                zone = f"{d['entry_low']}-{d['entry_high']}"

                if not (trend4 and trend1):
                    continue

                # SETUP
                if d["price"] > d["entry_high"] and d["rr"] > 2:
                    if now - state["setup"] > SETUP_COOLDOWN and zone != state["zone"]:
                        send(CHAT_ID,f"👀 {s} Setup\n{zone}")
                        state["setup"]=now
                        state["zone"]=zone

                # ENTRY
                if d["entry_low"] <= d["price"] <= d["entry_high"] and timing:
                    if now - state["entry"] > ENTRY_COOLDOWN:
                        send(CHAT_ID,f"🚀 {s} Entry\n{zone}")
                        state["entry"]=now

                signal_state[s]=state

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
    d = get_data(symbol)
    if not d:
        return "無數據"
    price = d["price"]
    pnl = (price-entry)/entry*100
    return f"{symbol} 盈虧：{round(pnl,2)}%"

# ======================
# LONG TERM
# ======================
def long_term():
    return """
💰【長線投資】

📊 MSFT：
👉 回調加倉

📈 S&P500：
👉 每月DCA
👉 長期持有
"""

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
        send(chat_id,"🚀 V30 TwelveData",menu())

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

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
