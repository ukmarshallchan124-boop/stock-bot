from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import yfinance as yf
import time, requests, os, threading, json
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
# 📂 JSON
# ======================
def load(f):
    try:
        with open(f,"r") as x: return json.load(x)
    except: return {}

def save(f,d):
    with open(f,"w") as x: json.dump(d,x)

# ======================
# 📊 股票
# ======================
def get_stock(s):
    df=yf.download(s,period="5d",interval="15m")
    df=df.dropna()
    close=df["Close"]

    p=close.iloc[-1]
    ch=((p-close.iloc[0])/close.iloc[0])*100

    rsi=RSIIndicator(close).rsi().iloc[-1]
    macd=MACD(close)
    m=macd.macd().iloc[-1]
    sig=macd.macd_signal().iloc[-1]

    return df,p,ch,rsi,m,sig

def get_sr(df):
    return df["Low"].tail(50).min(), df["High"].tail(50).max()

# ======================
# 📰 新聞
# ======================
def news_score(s):
    try:
        url=f"https://newsapi.org/v2/everything?q={s}&apiKey={NEWS_API}"
        r=requests.get(url).json()
        sc=0
        for a in r.get("articles",[])[:2]:
            t=a["title"].lower()
            if "growth" in t or "surge" in t: sc+=10
            elif "drop" in t or "risk" in t: sc-=10
        return max(0,min(sc,20))
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

def adjust_w(s,res):
    w=load(WEIGHT_FILE)
    x=w[s]
    if res=="win":
        x["macd"]+=2;x["price"]+=1
    else:
        x["rsi"]-=2;x["news"]-=1
    for k in x: x[k]=max(5,min(50,x[k]))
    w[s]=x;save(WEIGHT_FILE,w)

# ======================
# 🧠 AI
# ======================
def score(s,rsi,macd,signal,ch,news):
    w=get_w(s)
    sc=0
    if rsi<30: sc+=w["rsi"]
    elif rsi<50: sc+=w["rsi"]*0.5
    if macd>signal: sc+=w["macd"]
    if ch>3: sc+=w["price"]
    elif ch>1: sc+=w["price"]*0.5
    sc+=news*(w["news"]/20)
    return int(sc)

# ======================
# 💰 profit
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
                pr=((now-t["entry"])/t["entry"])*100
                t["profit"]=round(pr,2)
                t["checked"]=True
                adjust_w(s,"win" if pr>0 else "lose")
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
# 🚧 門檻
# ======================
def threshold(win):
    if win>=70:return 65
    elif win>=50:return 70
    else:return 80

# ======================
# 📦 message
# ======================
def build_msg(s):
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
    return msg,sc,th,p,sup,res

# ======================
# 📤 send
# ======================
def send(msg):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id":CHAT_ID,"text":msg})

# ======================
# 🚀 自動
# ======================
def run():
    while True:
        update_profit()

        for s in stocks:
            try:
                msg,sc,th,p,sup,res=build_msg(s)

                if sc>=th:
                    send(msg)
                    record_trade(s,p)

                if p>res: send(f"🚀 {s} 突破 {res:.2f}")
                if p<sup: send(f"⚠️ {s} 跌穿 {sup:.2f}")

                time.sleep(5)

            except Exception as e:
                print(e)

        time.sleep(3600)

# ======================
# 🤖 commands
# ======================
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
"""🤖 AI Trading Bot

/check → 全部分析
/check TSLA → 單一
/best → 最強
/stats → 排名
/risk → 市場"""
)

async def check(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if context.args:
        s=context.args[0].upper()
        msg,*_=build_msg(s)
        await update.message.reply_text(msg)
    else:
        for s in stocks:
            msg,*_=build_msg(s)
            await update.message.reply_text(msg)

async def best(update:Update,context:ContextTypes.DEFAULT_TYPE):
    best_stock=None
    best_score=0

    for s in stocks:
        _,sc,_,_,_,_=build_msg(s)
        if sc>best_score:
            best_score=sc
            best_stock=s

    await update.message.reply_text(f"🏆 最強：{best_stock} ({best_score})")

async def stats_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg="📊 排名\n"
    ranking=[]
    for s in stocks:
        avg,_,_=stats(s)
        ranking.append((s,avg))
    ranking.sort(key=lambda x:x[1],reverse=True)
    for s,a in ranking:
        msg+=f"{s}: {a}%\n"
    await update.message.reply_text(msg)

async def risk(update:Update,context:ContextTypes.DEFAULT_TYPE):
    total=0
    for s in stocks:
        _,sc,_,_,_,_=build_msg(s)
        total+=sc

    avg=total/len(stocks)

    if avg>70:
        r="🟢 市場偏強"
    elif avg>50:
        r="⚪ 中性"
    else:
        r="🔴 高風險"

    await update.message.reply_text(f"🌍 市場：{r}")

def bot():
    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("check",check))
    app.add_handler(CommandHandler("best",best))
    app.add_handler(CommandHandler("stats",stats_cmd))
    app.add_handler(CommandHandler("risk",risk))

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
