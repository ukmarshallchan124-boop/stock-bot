from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
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
# MARKET
# ======================
def market_trend():
    try:
        spy = yf.Ticker("SPY").history(period="5d", interval="1d")
        if spy.empty:
            return "⚪ 市場未知", 0

        change = (spy["Close"].iloc[-1] - spy["Close"].iloc[-3]) / spy["Close"].iloc[-3] * 100

        if change > 1:
            return "📈 市場偏強", 10
        elif change < -1:
            return "📉 市場偏弱", -10
        else:
            return "⚪ 市場震盪", 0
    except:
        return "⚪ 市場未知", 0

# ======================
# FETCH
# ======================
def fetch(symbol, interval):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval=interval)
        if df.empty or len(df) < 30:
            df = yf.Ticker(symbol).history(period="1mo", interval="1d")
        if df.empty or len(df) < 30:
            return None
        return df
    except:
        return None

# ======================
# INDICATORS
# ======================
def indicators(df):
    close = df["Close"]

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean()/loss.rolling(14).mean()
    rsi = round((100-(100/(1+rs))).iloc[-1],1)

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()

    macd_val = macd_line.iloc[-1] - signal.iloc[-1]

    return rsi, macd_val

# ======================
# MTF
# ======================
def mtf(symbol):
    df = fetch(symbol,"1h")
    if df is None:
        return None

    close = df["Close"]
    df4 = close.iloc[::4]

    if len(df4) < 20:
        return None

    trend_4h = df4.iloc[-1] > df4.ewm(span=50).mean().iloc[-1]
    trend_1h = close.iloc[-1] > close.ewm(span=20).mean().iloc[-1]
    pullback = close.iloc[-1] < close.rolling(10).max().iloc[-1]

    return trend_4h, trend_1h, pullback

# ======================
# AI SCORE
# ======================
def ai_score(df, symbol):
    score = 50

    mtf_data = mtf(symbol)
    if mtf_data:
        t4, t1, pb = mtf_data
        if t4: score += 10
        if t1: score += 10
        if pb: score += 5

    rsi, macd = indicators(df)

    if 50 < rsi < 70:
        score += 10
    elif rsi > 75:
        score -= 10

    score += 10 if macd > 0 else -5

    _, m = market_trend()
    score += m

    return max(0, min(100, score))

# ======================
# DATA
# ======================
def get_data(symbol):
    df = fetch(symbol,"15m")
    if df is None:
        return None

    price = df["Close"].iloc[-1]
    high = df["High"].max()
    low = df["Low"].min()

    entry_low = low*1.01
    entry_high = low*1.03
    stop = low*0.97
    target = high*1.02

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
# TIMING
# ======================
def timing(df):
    ema9 = df["Close"].ewm(span=9).mean()
    ema21 = df["Close"].ewm(span=21).mean()
    return "🟢 可留意" if ema9.iloc[-1] > ema21.iloc[-1] else "❌ 唔好追"

# ======================
# NEWS（升級版🔥）
# ======================
def get_news(symbol):
    try:
        news = yf.Ticker(symbol).news or []
        news = news[:3]

        txt = ""
        score = 0

        for n in news:
            title = n.get("title","").lower()

            if any(k in title for k in ["beat","record","surge","strong earnings"]):
                tag = "🟢 強利好"
                score += 2
            elif any(k in title for k in ["growth","ai","expand"]):
                tag = "🟢 利好"
                score += 1
            elif any(k in title for k in ["cut","downgrade","drop","risk","lawsuit"]):
                tag = "🔴 利淡"
                score -= 1
            else:
                tag = "⚪ 中性"

            txt += f"• {n.get('title','')}\n{tag}\n\n"

        summary = "🟢 偏利好" if score>0 else "🔴 偏利淡" if score<0 else "⚪ 中性"

        return txt or "⚪ 無新聞\n", summary
    except:
        return "⚪ 無新聞\n", "⚪ 中性"

# ======================
# FORMAT
# ======================
def format_output(symbol,d,df):
    score = ai_score(df,symbol)
    grade = "A" if score>=75 else "B" if score>=55 else "C"

    rsi,macd_raw = indicators(df)
    macd = "🟢 偏強" if macd_raw>0 else "🔴 偏弱"

    timing_text = timing(df)
    news_txt,news_summary = get_news(symbol)
    market,_ = market_trend()

    return f"""
📊【{symbol} 波段分析｜PRO】

💰 價格：{d['price']}
🎯 AI信心：{score}/100
⏱️ Timing：{timing_text}

📈 Setup 等級：{grade}

━━━━━━━━━━━━━━━

RSI：{rsi}
MACD：{macd}

━━━━━━━━━━━━━━━

📉 支撐：{d['entry_low']}
📈 阻力：{d['target']}

━━━━━━━━━━━━━━━

💰 策略🔥
👉 入場：{d['entry_low']} - {d['entry_high']}
👉 止蝕：{d['stop']}
👉 目標：{d['target']}

📊 R/R：{d['rr']}

━━━━━━━━━━━━━━━

🌍 {market}

━━━━━━━━━━━━━━━

🧠 AI判斷：
👉 {"🚫 唔建議" if score<50 else "⏳ 等位" if score<75 else "✅ 可留意"}

━━━━━━━━━━━━━━━

📰【新聞】

{news_txt}
🧠 {news_summary}
"""

# ======================
# LOOP（強化版🔥）
# ======================
def loop():
    while True:
        try:
            now=time.time()

            for s in SWING_STOCKS:
                data = get_data(s)
                if not data: continue

                df,d = data
                score = ai_score(df,s)
                mtf_data = mtf(s)
                if not mtf_data: continue

                t4,t1,pb = mtf_data

                state = signal_state.get(s,{"setup":0,"entry":0,"zone":None})
                zone = f"{d['entry_low']}-{d['entry_high']}"

                # SETUP（強過濾）
                if score >= 70 and t4 and (t1 or pb) and d["rr"] >= 2:
                    if now - state["setup"] > SETUP_COOLDOWN and zone != state["zone"]:
                        send(CHAT_ID,f"👀【{s} Setup PRO】AI:{score}\n{zone}")
                        state["setup"]=now
                        state["zone"]=zone

                # ENTRY（真交易）
                momentum = df["Close"].diff().iloc[-3:].mean()
                in_range = d["entry_low"] <= d["price"] <= d["entry_high"]

                if in_range and score >= 75 and momentum > 0 and timing(df)=="🟢 可留意":
                    if now - state["entry"] > ENTRY_COOLDOWN:
                        send(CHAT_ID,f"🚀【{s} Entry PRO】AI:{score}")
                        state["entry"]=now

                signal_state[s]=state

            time.sleep(300)

        except Exception as e:
            print("LOOP ERROR:",e)

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
        price=df["Close"].iloc[-1]
        pnl=(price-entry)/entry*100
        return f"{symbol} 盈虧：{round(pnl,2)}%"
    except:
        return "無數據"

def long_term():
    return """
💰【長線投資】

📊 MSFT：
👉 回調加倉

📈 S&P500：
👉 每月DCA

🧠 長線持有
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
    text=data["message"].get("text","").strip()

    if text in ["/start","start"]:
        send(chat_id,"🚀 V34.2 PRO FIX",menu())

    elif "波段分析" in text:
        send(chat_id,"⏳ 分析中...",menu())
        for s in SWING_STOCKS:
            data = get_data(s)
            if data:
                df,d=data
                send(chat_id,format_output(s,d,df),menu())

    elif "長線投資" in text:
        send(chat_id,long_term(),menu())

    elif text.replace('.','',1).isdigit():
        send(chat_id,calc(text),menu())

    elif len(text.split())==2:
        s,p=text.split()
        send(chat_id,position(s.upper(),float(p)),menu())

    return "ok"

@app.route("/")
def home():
    return "running"

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
