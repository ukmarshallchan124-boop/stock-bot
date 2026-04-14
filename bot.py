from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import time, requests, os, threading, json, random
from ta.momentum import RSIIndicator
from ta.trend import MACD
from flask import Flask

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API = os.getenv("NEWS_API")

stocks = ["TSLA", "NVDA", "AMD"]

DATA_FILE = "ai_memory.json"
WEIGHT_FILE = "weights.json"
PROFIT_FILE = "profit.json"

# ======================
# 📂 JSON 工具
# ======================
def load(file):
    try:
        with open(file,"r") as f: return json.load(f)
    except: return {}

def save(file,data):
    with open(file,"w") as f: json.dump(data,f)

# ======================
# 📊 股票數據
# ======================
def get_stock(symbol):
    df = yf.download(symbol, period="5d", interval="15m")
    df = df.dropna()
    close = df["Close"]

    price = close.iloc[-1]
    change = ((price - close.iloc[0])/close.iloc[0])*100

    rsi = RSIIndicator(close).rsi().iloc[-1]
    macd = MACD(close)
    macd_val = macd.macd().iloc[-1]
    signal = macd.macd_signal().iloc[-1]

    return df, price, change, rsi, macd_val, signal

# ======================
# 📈 支撐阻力
# ======================
def get_sr(df):
    return df["Low"].tail(50).min(), df["High"].tail(50).max()

# ======================
# 📰 新聞分數
# ======================
def news_score(symbol):
    try:
        url=f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API}"
        r=requests.get(url).json()
        score=0
        for a in r.get("articles",[])[:2]:
            t=a["title"].lower()
            if "growth" in t or "surge" in t: score+=10
            elif "drop" in t or "risk" in t: score-=10
        return max(0,min(score,20))
    except:
        return 10

# ======================
# ⚙️ 權重
# ======================
def get_w(s):
    w=load(WEIGHT_FILE)
    if s not in w:
        w[s]={"rsi":30,"macd":30,"price":20,"news":20}
        save(WEIGHT_FILE,w)
    return w[s]

def adjust_w(s,result):
    w=load(WEIGHT_FILE)
    x=w[s]
    if result=="win":
        x["macd"]+=2;x["price"]+=1
    else:
        x["rsi"]-=2;x["news"]-=1
    for k in x: x[k]=max(5,min(50,x[k]))
    w[s]=x;save(WEIGHT_FILE,w)

# ======================
# 🧠 AI評分
# ======================
def score(s,rsi,macd,signal,change,news):
    w=get_w(s)
    sc=0

    if rsi<30: sc+=w["rsi"]
    elif rsi<50: sc+=w["rsi"]*0.5

    if macd>signal: sc+=w["macd"]

    if change>3: sc+=w["price"]
    elif change>1: sc+=w["price"]*0.5

    sc+=news*(w["news"]/20)

    return int(sc)

# ======================
# 💰 PROFIT
# ======================
def record_trade(s,p):
    d=load(PROFIT_FILE)
    d.setdefault(s,[]).append({"entry":p,"checked":False})
    save(PROFIT_FILE,d)

def update_profit():
    d=load(PROFIT_FILE)
    for s in d:
        for t in d[s]:
            if t["checked"]: continue
            try:
                df=yf.download(s,period="1d",interval="5m")
                now=df["Close"].iloc[-1]
                p=((now-t["entry"])/t["entry"])*100
                t["profit"]=round(p,2)
                t["checked"]=True
                adjust_w(s,"win" if p>0 else "lose")
            except: pass
    save(PROFIT_FILE,d)

def stats(s):
    d=load(PROFIT_FILE)
    if s not in d: return 0,50,0
    ps=[t["profit"] for t in d[s] if "profit" in t]
    if not ps: return 0,50,0
    avg=round(sum(ps)/len(ps),2)
    win=int(sum(1 for x in ps if x>0)/len(ps)*100)
    ml=min(ps)
    return avg,win,ml

# ======================
# 🚧 動態門檻
# ======================
def threshold(win):
    if win>=70:return 65
    elif win>=50:return 70
    else:return 80

# ======================
# 📤 send
# ======================
def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id":CHAT_ID,"text":msg}
    )

# ======================
# 🚀 主
# ======================
def run():
    while True:
        update_profit()

        for s in stocks:
            try:
                df,p,ch,rsi,macd,signal=get_stock(s)
                sup,res=get_sr(df)
                news=news_score(s)

                sc=score(s,rsi,macd,signal,ch,news)
                avg,win,ml=stats(s)
                th=threshold(win)

                msg=f"""📊【{s}】

💰 ${p:.2f} ({ch:+.2f}%)
📉 支撐:{sup:.2f}
📈 阻力:{res:.2f}

🧠 AI:{sc}/100
📊 勝率:{win}%
🚧 門檻:{th}

💰 平均:{avg}%
📉 最大虧:{ml}%
"""

                if sc>=th:
                    send(msg)
                    record_trade(s,p)

                if p>res:
                    send(f"🚀 {s} 突破 {res:.2f}")
                if p<sup:
                    send(f"⚠️ {s} 跌穿 {sup:.2f}")

                time.sleep(5)

            except Exception as e:
                print(e)

        time.sleep(3600)

# ======================
# 🤖 telegram
# ======================
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Ready\n/check")

async def check(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Running...")

def bot():
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("check",check))
    app.run_polling()

# ======================
# 🌐 防sleep
# ======================
app=Flask(__name__)

@app.route("/")
def home():
    return "OK"

def web():
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0",port=port)

# ======================
# ▶️ start
# ======================
threading.Thread(target=run).start()
threading.Thread(target=web).start()
bot()
