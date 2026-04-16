from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}
msft_last_alert = 0

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
# DATA
# ======================
def get_data(symbol):
    df = yf.Ticker(symbol).history(period="5d", interval="5m")

    price = df["Close"].iloc[-1]
    high = df["High"].max()
    low = df["Low"].min()

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = 100-(100/(1+rs))

    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()

    vol = df["Volume"].iloc[-1]/df["Volume"].rolling(20).mean().iloc[-1]

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02
    rr = (target-entry_low)/(entry_low-stop)

    momentum = (price - df["Close"].iloc[-20]) / df["Close"].iloc[-20] * 100

    return {
        "price":round(price,2),
        "rsi":round(rsi.iloc[-1],1),
        "macd":"🟢" if macd.iloc[-1]>signal.iloc[-1] else "🔴",
        "volume":vol,
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":round(rr,2),
        "momentum":round(momentum,2)
    }

# ======================
# WINRATE（升級）
# ======================
def winrate(d):
    score=50
    if d["rsi"]<45: score+=10
    if d["macd"]=="🟢": score+=15
    if d["volume"]>1.2: score+=10
    if d["rr"]>2: score+=15
    if d["momentum"]>0: score+=10
    return min(95,max(10,score))

# ======================
# TIMING（升級）
# ======================
def timing(d):
    p=d["price"]
    if d["entry_low"]<=p<=d["entry_high"]:
        return "ENTRY"
    elif p>d["entry_high"]:
        return "HIGH"
    else:
        return "WAIT"

# ======================
# SIGNAL LOOP
# ======================
def loop():
    global msft_last_alert

    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)
                w=winrate(d)
                t=timing(d)

                now=time.time()
                last=last_alert.get(s,0)

                # SETUP
                if w>=80 and t!="ENTRY":
                    if now-last>3600:
                        send(CHAT_ID,f"""👀【{s} Setup】

🧠 勝率：{w}%
👉 等回調：{d['entry_low']} - {d['entry_high']}""")
                        last_alert[s]=now

                # ENTRY
                if w>=70 and t=="ENTRY":
                    if now-last>600:
                        send(CHAT_ID,f"""🚀【{s} 入場】

🧠 勝率：{w}%

入場：{d['entry_low']} - {d['entry_high']}
止蝕：{d['stop']}
目標：{d['target']}

R/R：{d['rr']}""")
                        last_alert[s]=now

            # MSFT
            df=yf.Ticker("MSFT").history(period="6mo", interval="1d")
            price=df["Close"].iloc[-1]
            m3=(price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

            if m3<-5 and time.time()-msft_last_alert>86400:
                send(CHAT_ID,f"""💰【MSFT 加倉機會】

價格：{round(price,2)}
回調：{round(m3,1)}%

👉 可考慮加倉""")
                msft_last_alert=time.time()

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# CALC
# ======================
def calc_price(x):
    x=float(x)
    return f"""📊 計算

+10% {round(x*1.1,2)}
+20% {round(x*1.2,2)}
-10% {round(x*0.9,2)}
"""

# ======================
# POSITION（升級）
# ======================
def position(symbol, entry):
    df=yf.Ticker(symbol).history(period="5d", interval="5m")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100

    if pnl>20:
        advice="🔥 分批止賺"
    elif pnl>10:
        advice="🟢 持有 / 鎖利"
    elif pnl>0:
        advice="⚪ 觀察"
    elif pnl>-5:
        advice="⚠️ 留意"
    else:
        advice="❌ 考慮止蝕"

    return f"""📊【{symbol} 持倉】

成本：{entry}
現價：{round(price,2)}

盈虧：{round(pnl,2)}%

👉 {advice}
"""

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
            send(chat_id,str(get_data(s)))

    elif text.startswith("/calc"):
        send(chat_id,calc_price(text.split()[1]))

    elif text.startswith("/position"):
        p=text.split()
        send(chat_id,position(p[1].upper(),float(p[2])))

    elif text=="/msft":
        df=yf.Ticker("MSFT").history(period="6mo", interval="1d")
        price=df["Close"].iloc[-1]
        send(chat_id,f"MSFT 價格：{round(price,2)}")

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)
