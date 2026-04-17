from flask import Flask, request
import requests, os, time, threading
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

SYMBOLS = ["TSLA","NVDA","AMD"]

last_alert = {}
long_last_alert = 0

# ======================
# SEND
# ======================
def send(chat_id, msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=5
        )
    except:
        pass

# ======================
# DATA
# ======================
def get_data(symbol):
    try:
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
        macd_line = ema12-ema26
        signal = macd_line.ewm(span=9).mean()

        macd = "🟢" if macd_line.iloc[-1] > signal.iloc[-1] else "🔴"

        entry_low = low*1.01
        entry_high = low*1.03
        stop = low*0.97
        target = high*1.02
        rr = (target-entry_low)/(entry_low-stop)

        return {
            "price":round(price,2),
            "rsi":round(rsi,1),
            "macd":macd,
            "support":round(low,2),
            "resistance":round(high,2),
            "entry_low":round(entry_low,2),
            "entry_high":round(entry_high,2),
            "stop":round(stop,2),
            "target":round(target,2),
            "rr":round(rr,2)
        }
    except:
        return None

# ======================
# WINRATE / TIMING
# ======================
def winrate(d):
    score=50
    if d["rsi"]<40: score+=15
    if d["macd"]=="🟢": score+=15
    if d["rr"]>2: score+=10
    return min(95,max(10,score))

def timing(d):
    p=d["price"]
    if d["entry_low"]<=p<=d["entry_high"]:
        return "ENTRY"
    elif p>d["entry_high"]:
        return "HIGH"
    else:
        return "WAIT"

# ======================
# 倉位建議
# ======================
def position_size(w):
    if w>=80: return "🔥 高勝率：25%"
    elif w>=70: return "🟡 中高：15%"
    elif w>=60: return "⚪ 普通：10%"
    else: return "❌ 不建議入場"

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data=requests.get(url,timeout=5).json()
        articles=data.get("articles",[])[:2]

        txt="\n📰新聞\n"
        score=0

        for a in articles:
            t=a["title"]

            if any(w in t.lower() for w in ["growth","beat","strong","record"]):
                tag="🟢"; score+=1
            elif any(w in t.lower() for w in ["drop","cut","risk","fall"]):
                tag="🔴"; score-=1
            else:
                tag="⚪"

            txt+=f"{tag} {t}\n"

        summary="🟢利好" if score>0 else "🔴利淡" if score<0 else "⚪中性"
        txt+=f"👉 {summary}\n"

        return txt
    except:
        return "\n📰無新聞\n"

# ======================
# FORMAT
# ======================
def format_output(symbol):
    d=get_data(symbol)
    if not d:
        return f"{symbol} 無數據"

    w=winrate(d)
    t=timing(d)

    timing_text="🔥入場" if t=="ENTRY" else "❌唔好追" if t=="HIGH" else "🔄等回調"

    msg=f"""📊【{symbol}】

💰 價格：{d['price']}

🧠 勝率：{w}%
⏱️ {timing_text}

💰 倉位建議：
{position_size(w)}

📉 支撐：{d['support']}
📈 阻力：{d['resistance']}

💰 策略
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}
"""

    msg+=get_news(symbol)
    return msg

# ======================
# LOOP（Signal + 分級加倉）
# ======================
def loop():
    global long_last_alert

    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)
                if not d: continue

                w=winrate(d)
                t=timing(d)

                now=time.time()
                last=last_alert.get(s,0)

                if w>=80 and t!="ENTRY" and now-last>3600:
                    send(CHAT_ID,f"👀 {s} Setup（勝率{w}%）")
                    last_alert[s]=now

                if w>=70 and t=="ENTRY" and now-last>600:
                    send(CHAT_ID,f"🚀 {s} 入場（勝率{w}%）")
                    last_alert[s]=now

            # ======================
            # 🔥 分級加倉系統
            # ======================
            df=yf.Ticker("MSFT").history(period="6mo")
            price=df["Close"].iloc[-1]
            m3=(price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

            now=time.time()

            if now-long_last_alert>21600:  # 6小時

                if m3<=-20:
                    level="🚀 強力加倉區"
                    action="40% 資金"
                elif m3<=-15:
                    level="🔥 重倉區"
                    action="30%"
                elif m3<=-10:
                    level="🟠 正常加倉"
                    action="20%"
                elif m3<=-5:
                    level="🟡 輕倉"
                    action="10%"
                else:
                    level=None

                if level:
                    send(CHAT_ID,f"""💰【長線加倉信號】

🏢 MSFT
📉 回調：{round(m3,1)}%

🧠 判斷：
{level}

💰 建議投入：
👉 {action}

🏦 S&P 500
👉 同步分批加倉

⚠️ 提醒：
唔好一次過 All-in
""")

                    long_last_alert=now

            time.sleep(300)
        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# 工具
# ======================
def calc(x):
    x=float(x)
    return f"+10% {round(x*1.1,2)}\n+20% {round(x*1.2,2)}"

def position(symbol,entry):
    df=yf.Ticker(symbol).history(period="1d")
    price=df["Close"].iloc[-1]
    pnl=(price-entry)/entry*100
    return f"{symbol} 盈虧 {round(pnl,2)}%"

# ======================
# WEBHOOK
# ======================
@app.route(f"/{TOKEN}",methods=["POST"])
def webhook():
    data=request.get_json()

    if "message" not in data:
        return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text=="/check":
        for s in SYMBOLS:
            send(chat_id,format_output(s))

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
