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
        data=requests.get(url,timeout=5).json()
        articles=data.get("articles",[])[:2]

        txt="\n📰【市場新聞】\n"
        score=0

        for a in articles:
            t=a["title"]

            if any(w in t.lower() for w in ["growth","beat","strong","record"]):
                tag="🟢 利好"; score+=1
            elif any(w in t.lower() for w in ["drop","cut","risk","fall"]):
                tag="🔴 利淡"; score-=1
            else:
                tag="⚪ 中性"

            txt+=f"{tag} {t}\n"

        summary="🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"
        txt+=f"\n🧠 新聞結論：{summary}\n"

        return txt, score
    except:
        return "\n📰 無新聞\n", 0

# ======================
# STORAGE
# ======================
def load_trades():
    try:
        with open(DATA_FILE,"r") as f:
            return json.load(f)
    except:
        return []

def save_trades(trades):
    with open(DATA_FILE,"w") as f:
        json.dump(trades,f)

def add_trade(trade):
    trades=load_trades()
    trades.append(trade)
    save_trades(trades)

# ======================
# AUTO RESULT
# ======================
def evaluate_trades():
    trades=load_trades()
    updated=False

    for t in trades:
        if t["result"]!="pending":
            continue

        df=yf.Ticker(t["symbol"]).history(period="1d")
        if df.empty:
            continue

        price=df["Close"].iloc[-1]
        entry=t["entry"]

        if price>=entry*1.03:
            t["result"]="win"; updated=True
        elif price<=entry*0.98:
            t["result"]="loss"; updated=True

    if updated:
        save_trades(trades)

# ======================
# AI DECISION（🔥核心）
# ======================
def ai_decision(symbol, d):
    score = 0

    if d["rsi"] < 40: score += 15
    if d["macd"] == "🟢": score += 15
    if d["rr"] > 2: score += 10

    trades = load_trades()
    if trades:
        win = sum(1 for t in trades if t["result"]=="win")
        rate = win/len(trades)*100

        if rate > 65: score += 15
        elif rate < 50: score -= 10

    news_text, news_score = get_news(symbol)
    score += news_score*5

    if score >= 60:
        grade="🟣 S級（強烈入場🔥）"
        action="🔥 重倉（25–30%）"
    elif score >= 50:
        grade="🔵 A級（高勝率）"
        action="👉 正常倉（10–15%）"
    elif score >= 40:
        grade="🟡 B級（觀察）"
        action="👀 等確認"
    elif score >= 30:
        grade="🟠 C級"
        action="⚠️ 小注"
    else:
        grade="🔴 D級"
        action="❌ 放棄"

    return score, grade, action, news_text

# ======================
# FORMAT
# ======================
def format_output(symbol):
    d=get_data(symbol)
    if not d:
        return f"{symbol} 無數據"

    score, grade, action, news = ai_decision(symbol, d)

    return f"""📊【{symbol} AI 分析】

💰 價格：{d['price']}

🧠 AI 評分：{score}
🏆 等級：{grade}

🚦 行動：
{action}

━━━━━━━━━━━

🎯 入場區：
{d['entry_low']} - {d['entry_high']}

🛑 止蝕：{d['stop']}
🎯 目標：{d['target']}

📊 R/R：{d['rr']}

{news}
"""

# ======================
# STATS
# ======================
def stats():
    trades=load_trades()
    if not trades:
        return "📊 未有記錄"

    total=len(trades)
    win=sum(1 for t in trades if t["result"]=="win")
    loss=sum(1 for t in trades if t["result"]=="loss")

    rate=round(win/total*100,1)

    return f"""📊【AI 報告】

📦 交易：{total}
🏆 勝：{win} ｜ ❌ 輸：{loss}

🧠 勝率：{rate}%

📌 提示：
>60% = 可用
長期最重要
"""

# ======================
# LOOP
# ======================
def loop():
    while True:
        try:
            evaluate_trades()

            for s in SYMBOLS:
                d=get_data(s)
                if not d: continue

                score, grade, action, _ = ai_decision(s, d)

                now=time.time()
                last=last_alert.get(s,0)

                if score>=50 and now-last>600:

                    send(CHAT_ID,f"""🚀【{s} AI 入場】

🏆 {grade}
🧠 評分：{score}

🎯 入場：
{d['entry_low']} - {d['entry_high']}

{action}
""")

                    add_trade({
                        "symbol":s,
                        "entry":d["price"],
                        "time":now,
                        "result":"pending"
                    })

                    last_alert[s]=now

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

    elif text=="/stats":
        send(chat_id,stats())

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
