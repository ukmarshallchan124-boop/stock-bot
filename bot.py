from flask import Flask, request
import requests, os, time, threading, json
import yfinance as yf

app = Flask(__name__)

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

SYMBOLS = ["TSLA","NVDA","AMD"]

DATA_FILE = "trades.json"
last_alert = {}
msft_last = 0

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
    if df.empty: return None

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
    macd = "🟢" if ema12.iloc[-1] > ema26.iloc[-1] else "🔴"

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
# NEWS
# ======================
def get_news(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        data=requests.get(url).json()
        arts=data.get("articles",[])[:2]

        txt="\n📰【市場新聞】\n"
        score=0

        for a in arts:
            t=a["title"]
            if any(w in t.lower() for w in ["beat","growth","strong"]):
                tag="🟢 利好"; score+=1
            elif any(w in t.lower() for w in ["drop","risk","cut"]):
                tag="🔴 利淡"; score-=1
            else:
                tag="⚪ 中性"
            txt+=f"{tag} {t}\n"

        summary="🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        txt+=f"\n🧠 新聞總結：{summary}\n"

        return txt, score
    except:
        return "\n📰 無新聞\n",0

# ======================
# AI
# ======================
def ai_score(d, news_score):
    score=50

    if d["rsi"]<45: score+=10
    if d["macd"]=="🟢": score+=10
    if d["rr"]>2: score+=10

    score+=news_score*5
    return score

def ai_grade(score):
    if score>=60: return "🟣 S級","🔥 重倉"
    elif score>=50: return "🔵 A級","👉 可入"
    elif score>=40: return "🟡 B級","👀 等"
    elif score>=30: return "🟠 C級","⚠️ 小注"
    else: return "🔴 D級","❌ 放棄"

# ======================
# FORMAT（還原圖2🔥）
# ======================
def format_output(symbol):
    d=get_data(symbol)
    if not d: return "無數據"

    news, news_score = get_news(symbol)
    score=ai_score(d,news_score)
    grade,action=ai_grade(score)

    timing = "🔥 入場區" if d["entry_low"]<=d["price"]<=d["entry_high"] else "❌ 唔好追"

    return f"""📊【{symbol} 波段分析】

💰 價格：{d['price']}

🧠 AI 評分：{score}
🏆 等級：{grade}

⏱️ Timing：{timing}

RSI：{d['rsi']}
MACD：{d['macd']}

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

💰 策略（重點🔥）
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

🧠 行動：
{action}

{news}
"""

# ======================
# LOOP（Setup + Entry + MSFT + S&P）
# ======================
def loop():
    global msft_last

    while True:
        try:
            for s in SYMBOLS:
                d=get_data(s)
                if not d: continue

                news,_=get_news(s)
                score=ai_score(d,0)

                now=time.time()
                last=last_alert.get(s,0)

                # 👀 Setup
                if score>=45 and d["price"]>d["entry_high"] and now-last>3600:
                    send(CHAT_ID,f"👀【{s} Setup】\n等回調：{d['entry_low']} - {d['entry_high']}")
                    last_alert[s]=now

                # 🚀 Entry
                if score>=50 and d["entry_low"]<=d["price"]<=d["entry_high"] and now-last>600:
                    send(CHAT_ID,f"🚀【{s} 入場】\n入場：{d['entry_low']} - {d['entry_high']}")
                    last_alert[s]=now

            # 💰 MSFT + S&P
            df=yf.Ticker("MSFT").history(period="6mo")
            price=df["Close"].iloc[-1]
            m3=(price-df["Close"].iloc[-90])/df["Close"].iloc[-90]*100

            if m3<-5 and time.time()-msft_last>86400:
                send(CHAT_ID,f"""💰【長線加倉】

MSFT 回調：{round(m3,1)}%

📈 S&P500：
建議長線 DCA（VOO / SPY / VUAG）

🧠 狀態：
🟢 可開始分批
""")
                msft_last=time.time()

            time.sleep(300)

        except:
            pass

threading.Thread(target=loop, daemon=True).start()

# ======================
# TOOLS
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

    elif text=="/msft":
        send(chat_id,"💰 MSFT 長線等回調 alert")

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
