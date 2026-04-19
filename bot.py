from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("TWELVE_API_KEY")

URL = f"https://api.telegram.org/bot{TOKEN}"

SWING_STOCKS = ["TSLA","NVDA","AMD"]

cache = {}
CACHE_TTL = 300

state = {}
user_state = {}

SETUP_COOLDOWN = 1800
ENTRY_COOLDOWN = 3600
BREAKOUT_COOLDOWN = 3600

# ======================
# SEND
# ======================
def send(chat_id, text, keyboard=None):
    try:
        data = {"chat_id": chat_id, "text": text[:4000]}
        if keyboard:
            data["reply_markup"] = keyboard
        requests.post(f"{URL}/sendMessage", json=data, timeout=10)
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
# FETCH（Twelve + Cache）
# ======================
def fetch(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in cache and now - cache[key]["time"] < CACHE_TTL:
        return cache[key]["data"], cache[key]["src"]

    try:
        if API_KEY:
            url = "https://api.twelvedata.com/time_series"
            params = {
                "symbol": symbol,
                "interval": interval,
                "outputsize": 100,
                "apikey": API_KEY
            }

            r = requests.get(url, params=params, timeout=5).json()

            if "values" in r:
                df = pd.DataFrame(list(reversed(r["values"])))

                df["close"] = df["close"].astype(float)
                df["high"] = df["high"].astype(float)
                df["low"] = df["low"].astype(float)
                df["volume"] = df["volume"].astype(float)

                df.rename(columns={
                    "close":"Close",
                    "high":"High",
                    "low":"Low",
                    "volume":"Volume"
                }, inplace=True)

                cache[key] = {"data": df, "time": now, "src":"twelve"}
                return df, "twelve"
    except:
        pass

    try:
        df = yf.Ticker(symbol).history(period="5d", interval=interval)
        if not df.empty:
            cache[key] = {"data": df, "time": now, "src":"yahoo"}
            return df, "yahoo"
    except:
        pass

    return None, None

# ======================
# INDICATORS
# ======================
def indicators(df):
    close = df["Close"]

    ema9 = close.ewm(span=9).mean()
    ema21 = close.ewm(span=21).mean()
    trend = ema9.iloc[-1] > ema21.iloc[-1]

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = round((100-(100/(1+rs))).iloc[-1],1)

    return rsi, trend

def volume_ok(df):
    return df["Volume"].iloc[-1] > df["Volume"].rolling(20).mean().iloc[-1]

def momentum(df):
    m = df["Close"].diff().iloc[-3:].mean()
    if m > 0: return "🟢 加速"
    if m < 0: return "🔴 轉弱"
    return "⚪ 中性"

def mtf(df):
    close = df["Close"]

    t15 = close.ewm(span=9).mean().iloc[-1] > close.ewm(span=21).mean().iloc[-1]
    t1 = close.iloc[::4].iloc[-1] > close.iloc[::4].ewm(span=20).mean().iloc[-1]
    t4 = close.iloc[::16].iloc[-1] > close.iloc[::16].ewm(span=50).mean().iloc[-1]

    pullback = close.iloc[-1] < close.rolling(10).max().iloc[-1]

    return t4,t1,t15,pullback

def ai_score(df):
    score = 50
    rsi,_ = indicators(df)
    t4,t1,t15,pb = mtf(df)

    if t4: score+=10
    if t1: score+=10
    if t15: score+=5
    if pb: score+=5
    if volume_ok(df): score+=10

    if 50<rsi<65: score+=10
    if rsi>70: score-=10

    return max(0,min(100,score))

# ======================
# ENTRY SIGNAL（核心升級）
# ======================
def entry_signal(df):
    try:
        close = df["Close"]

        ema9 = close.ewm(span=9).mean()
        ema21 = close.ewm(span=21).mean()

        ema_cross = ema9.iloc[-1] > ema21.iloc[-1]
        mom = close.diff().iloc[-3:].mean() > 0

        rsi,_ = indicators(df)
        rsi_ok = 50 < rsi < 70

        vol = volume_ok(df)

        score = sum([ema_cross, mom, rsi_ok, vol])

        if score >= 3:
            return "🟢 入場信號成立（Trend + Momentum）"
        elif score == 2:
            return "🟡 部分確認（等多一支K）"
        else:
            return "❌ 未確認"
    except:
        return "⚪ 無數據"

# ======================
# DATA
# ======================
def sr(df):
    return df["Low"].rolling(20).min().iloc[-1], df["High"].rolling(20).max().iloc[-1]

def get_data(symbol):
    df,src = fetch(symbol,"15min")
    if df is None or len(df)<50:
        return None

    price = df["Close"].iloc[-1]
    low,high = sr(df)

    entry_low = low
    entry_high = low*1.02
    stop = low*0.97
    target = high

    rr = round((target-entry_low)/(entry_low-stop),2)

    return df,{
        "price":round(price,2),
        "entry_low":round(entry_low,2),
        "entry_high":round(entry_high,2),
        "stop":round(stop,2),
        "target":round(target,2),
        "rr":rr
    }

# ======================
# NEWS
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news[:3]
        txt=""
        score=0

        for n in news:
            title=n.get("title","")
            lower=title.lower()

            if any(w in lower for w in ["ai","growth","beat","strong"]):
                txt+=f"• {title}\n🟢 利好 → 支持上升\n\n"; score+=1
            elif any(w in lower for w in ["drop","risk","cut"]):
                txt+=f"• {title}\n🔴 利淡 → 增加回調風險\n\n"; score-=1
            else:
                txt+=f"• {title}\n⚪ 中性\n\n"

        summary="🟢 偏強" if score>0 else "🔴 偏弱" if score<0 else "⚪ 中性"
        return txt,summary

    except:
        return "⚪ 無新聞","⚪ 中性"

# ======================
# FORMAT
# ======================
def format_output(symbol,d,df):
    rsi,_ = indicators(df)
    score = ai_score(df)
    t4,t1,t15,pb = mtf(df)

    signal = entry_signal(df)
    news_txt,news_summary = get_news(symbol)

    return f"""
📊【{symbol} 波段分析】

💰 價格：{d['price']}
🧠 AI信心：{score}
⏱️ 入場信號：{signal}

━━━━━━━━━━━━━━━

📊 結構：
4H：{"🟢 上升" if t4 else "🔴 弱"}
1H：{"🟡 回調" if pb else "🟢 延續"}
15m：{"🟢 轉強" if t15 else "⚪ 未確認"}

RSI：{rsi}
Momentum：{momentum(df)}

━━━━━━━━━━━━━━━

💰 策略🔥
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}
📊 R/R：{d['rr']}

━━━━━━━━━━━━━━━

📰 新聞

{news_txt}
🧠 {news_summary}
"""

# ======================
# LOOP（推送）
# ======================
def loop():
    while True:
        try:
            now=time.time()

            for s in SWING_STOCKS:
                data=get_data(s)
                if not data: continue

                df,d=data
                score=ai_score(df)

                st=state.get(s,{"setup":0,"entry":0,"breakout":0,"zone":None})
                zone=f"{d['entry_low']}-{d['entry_high']}"

                if score>60 and d["rr"]>2:
                    if now-st["setup"]>SETUP_COOLDOWN and zone!=st["zone"]:
                        send(CHAT_ID,f"👀【{s} Setup】\n回調區：{zone}")
                        st["setup"]=now
                        st["zone"]=zone

                if d["entry_low"]<=d["price"]<=d["entry_high"] and score>70:
                    sig = entry_signal(df)

                    if "🟢" in sig:
                        if now-st["entry"]>ENTRY_COOLDOWN:
                            send(CHAT_ID,f"🚀【{s} Entry】\n{sig}\n區間：{zone}")
                            st["entry"]=now

                if d["price"]>d["target"] and score>75:
                    if now-st["breakout"]>BREAKOUT_COOLDOWN:
                        send(CHAT_ID,f"🚀【{s} Breakout】突破 {d['target']}")
                        st["breakout"]=now

                state[s]=st

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:",e)

threading.Thread(target=loop,daemon=True).start()

# ======================
# TOOLS
# ======================
def calc_flow(chat_id, text):
    try:
        x=float(text)
        send(chat_id,f"+10%→{round(x*1.1,2)}\n-10%→{round(x*0.9,2)}")
        user_state.pop(chat_id,None)
    except:
        send(chat_id,"請輸入數字，例如：100")

def position_flow(chat_id, text):
    try:
        s,p=text.split()
        df,_=fetch(s.upper(),"15min")
        price=df["Close"].iloc[-1]
        pnl=(price-float(p))/float(p)*100
        send(chat_id,f"{s.upper()} 盈虧：{round(pnl,2)}%")
        user_state.pop(chat_id,None)
    except:
        send(chat_id,"格式錯誤，例如：NVDA 190")

# ======================
# LONG TERM
# ======================
def long_term():
    spy = yf.Ticker("SPY").history(period="1d")
    msft = yf.Ticker("MSFT").history(period="1d")

    spy_p = round(spy["Close"].iloc[-1],2)
    msft_p = round(msft["Close"].iloc[-1],2)

    return f"""
💰【長線投資】

📊 S&P500 現價：{spy_p}
👉 每月DCA

📊 MSFT 現價：{msft_p}
👉 等回調先買

🧠 S&P = 地基
MSFT = 增長
"""

# ======================
# WEBHOOK
# ======================
@app.route("/",methods=["POST"])
def webhook():
    data=request.get_json()
    if not data: return "ok"

    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","")

    if text in ["/start","start"]:
        send(chat_id,"🚀 V39.6 PRO",menu())

    elif text=="📊 波段分析":
        for s in SWING_STOCKS:
            data=get_data(s)
            if data:
                df,d=data
                send(chat_id,format_output(s,d,df))

    elif text=="🧮 計算工具":
        user_state[chat_id]="calc"
        send(chat_id,"請輸入金額，例如：100")

    elif text=="📍 持倉分析":
        user_state[chat_id]="pos"
        send(chat_id,"輸入：股票 成本\n例如 NVDA 190")

    elif text=="💰 長線投資":
        send(chat_id,long_term())

    elif chat_id in user_state:
        if user_state[chat_id]=="calc":
            calc_flow(chat_id,text)
        elif user_state[chat_id]=="pos":
            position_flow(chat_id,text)

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
