from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
NEWS_API_KEY = 60e376f3c4c54b7198c941c3fb96600f
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

last_alert = {}
cache = {}
CACHE_TTL = 120
# ======================
# REAL NEWS（Yahoo Finance）
# ======================
def get_news(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}&newsCount=3"
        res = requests.get(url, timeout=5)
        data = res.json()

        news = data.get("news", [])
        if not news:
            return "🟡 無新聞 No news"

        news_text = ""
        for n in news[:3]:
            title = n.get("title", "")[:60]
            source = n.get("publisher", "")
            news_text += f"• {title} ({source})\n"

        return news_text.strip()

    except Exception as e:
        print("YAHOO NEWS ERROR:", e)
        return "⚠️ Yahoo news error"

def get_news(symbol):
        news = get_yahoo_news(symbol)
        if "error" in news or "無新聞" in news:
        news = get_newsapi_news(symbol)
            return news
# ======================
# REAL NEWS（NewsAPI）
# ======================
def get_news(symbol):
    try:
        API_KEY = os.getenv("NEWS_API_KEY")
        if not API_KEY:
            return "⚠️ No News API key"

        url = f"https://newsapi.org/v2/everything?q={symbol}&sortBy=publishedAt&pageSize=3&apiKey={API_KEY}"
        res = requests.get(url, timeout=5)
        data = res.json()

        articles = data.get("articles", [])
        if not articles:
            return "🟡 無新聞 No news"

        news_text = ""
        for a in articles[:3]:
            title = a.get("title", "")[:60]
            source = a.get("source", {}).get("name", "")
            news_text += f"• {title} ({source})\n"

        return news_text.strip()

    except Exception as e:
        print("NEWS ERROR:", e)
        return "⚠️ News error"

def get_news(symbol):
        news = get_yahoo_news(symbol)
        if "error" in news or "無新聞" in news:
        news = get_newsapi_news(symbol)
            return news
# ======================
# DATA（數據獲取 Data Fetch）
# ======================
def get_df(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in cache:
        data, ts = cache[key]
        if now - ts < CACHE_TTL:
            return data

    try:
        df = yf.Ticker(symbol).history(period="2d", interval=interval)
        if df is None or df.empty or len(df) < 50:
            return None

        cache[key] = (df.copy(), now)
        return df
    except:
        return None

# ======================
# CALC（計算 Indicators）
# ======================
def calc(df):
    price = float(df["Close"].iloc[-1])

    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    trend_up = price > ma20  # 趨勢 Trend

    high = float(df["High"].max())
    low = float(df["Low"].min())

    entry_low = low * 1.01
    entry_high = low * 1.03
    stop = low * 0.97
    target = high * 1.02

    risk = entry_low - stop
    rr = (target - entry_low) / risk if risk > 0 else 0  # Risk Reward

    # RSI
    rsi = round(100 - (100 / (1 + (
        df["Close"].diff().clip(lower=0).rolling(14).mean() /
        (-df["Close"].diff().clip(upper=0).rolling(14).mean() + 1e-10)
    ))),1)

    return {
        "price": price,
        "trend_up": trend_up,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "target": target,
        "rr": rr,
        "rsi": rsi
    }
# =========================================================
# 🌍 MARKET FILTER（市場過濾｜決定可唔可以交易）
# =========================================================
def market_filter():
    df = get_df("SPY","15m")
    if df is None or df.empty:
        return True, "⚠️ 無法判斷市場"

    price = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]

    trend = price > ma20
    momentum = ma5 > ma20
    structure = price > ma50

    # 🔥 決策邏輯
    if not trend and not momentum:
        return False, "🔴 Risk OFF（市場轉弱）"
    elif trend and momentum and structure:
        return True, "🟢 Risk ON（市場健康）"
    else:
        return True, "🟡 中性（Selective trades）"
# =========================================================
# 📰 NEWS + SENTIMENT（新聞情緒分析）
# =========================================================
def get_news_sentiment(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}&newsCount=5"
        res = requests.get(url, timeout=5)
        data = res.json()

        news = data.get("news", [])
        if not news:
            return "NEUTRAL", "🟡 無新聞"

        # 🔥 合併所有標題做簡單 NLP
        text = " ".join([n.get("title","") for n in news]).lower()

        positive_words = ["beat","growth","strong","upgrade","profit","record"]
        negative_words = ["miss","drop","downgrade","weak","loss","cut"]

        score = 0
        for w in positive_words:
            if w in text:
                score += 1
        for w in negative_words:
            if w in text:
                score -= 1

        if score >= 2:
            return "POSITIVE", "🟢 利好 Positive"
        elif score <= -2:
            return "NEGATIVE", "🔴 利淡 Negative"
        else:
            return "NEUTRAL", "🟡 中性 Neutral"

    except Exception as e:
        print("NEWS ERROR:", e)
        return "NEUTRAL", "⚠️ News error"
# =========================================================
# ⭐ SCORING ENGINE（信號評分系統）
# =========================================================
def score_signal(df, d, sig, sentiment):
    score = 0

    # ======================
    # 🎯 信號強度
    # ======================
    if "ENTRY" in sig:
        score += 2
    if "BREAKOUT" in sig:
        score += 2.5

    # ======================
    # 📊 RR（風險回報）
    # ======================
    if d["rr"] > 2:
        score += 1
    elif d["rr"] > 1.5:
        score += 0.5

    # ======================
    # 📈 趨勢
    # ======================
    if d["trend_up"]:
        score += 1

    # ======================
    # ⚡ RSI（健康區）
    # ======================
    if 50 < d["rsi"] < 65:
        score += 1

    # ======================
    # 📰 新聞情緒
    # ======================
    if sentiment == "POSITIVE":
        score += 1
    elif sentiment == "NEGATIVE":
        score -= 1.5

    return score
# ======================
# SIGNAL ENGINE（信號引擎）
# ======================
def signal_engine(df, d):
    price = d["price"]

    recent_high = df["High"].iloc[-20:-3].max()
    recent_low = df["Low"].iloc[-20:-3].min()

    breakout = df["Close"].iloc[-1] > recent_high
    in_entry = d["entry_low"] <= price <= d["entry_high"]
    near_entry = d["entry_low"]*0.995 < price < d["entry_high"]*1.005
    risk_off = df["Close"].iloc[-1] < recent_low

    if risk_off:
        return "🔴 RISK｜風險"
    elif breakout:
        return "🚀 BREAKOUT｜突破"
    elif in_entry:
        return "🟢 ENTRY｜入場"
    elif near_entry:
        return "👀 SETUP｜準備"
    else:
        return "🟡 WAIT｜觀望"

# ======================
# MARKET（市場分析）
# ======================
def market():
    df = get_df("SPY","15m")
    if df is None or df.empty:
        return "⚠️ 無法讀取市場｜Market data unavailable"

    price = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]

    trend = "📈 上升 Uptrend" if price > ma20 else "📉 下降 Downtrend"
    structure = "健康 Healthy" if price > ma50 else "轉弱 Weakening"

    # momentum
    ma5 = df["Close"].rolling(5).mean().iloc[-1]
    momentum = "🔥 強 Strong" if ma5 > ma20 else "❄️ 弱 Weak"

    # 行動建議
    if price > ma20 and ma5 > ma20:
        action = "🟢 可做多（順勢交易）｜Long bias"
    elif price < ma20 and ma5 < ma20:
        action = "🔴 保守 / 避險｜Risk-off"
    else:
        action = "🟡 震盪（等方向）｜Choppy"

    return f"""🌍【市場分析 Market】

📊 指數 Index：SPY
💰 價格 Price：{round(price,2)}

📈 趨勢 Trend：{trend}
🏗 結構 Structure：{structure}
⚡ 動能 Momentum：{momentum}

🧠 判斷 Bias：
{action}

━━━━━━━━━━━━━━
"""

# ======================
# GOLD（黃金分析）
# ======================
def gold():
    df = get_df("GC=F","15m")
    if df is None or df.empty:
        return "⚠️ 無法讀取黃金｜Gold data unavailable"

    price = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]

    trend = "📈 上升 Uptrend" if price > ma20 else "📉 下降 Downtrend"
    structure = "強勢 Strong" if price > ma50 else "轉弱 Weak"

    # 黃金邏輯
    if price > ma20:
        logic = "⚠️ 市場避險情緒上升（Risk ↑）"
        action = "🟡 可作對沖｜Hedge"
    else:
        logic = "💰 資金流向風險資產（Risk-on）"
        action = "🟢 可忽略黃金｜Focus stocks"

    return f"""🥇【黃金分析 Gold】

💰 價格 Price：{round(price,2)}

📈 趨勢 Trend：{trend}
🏗 結構 Structure：{structure}

🧠 市場邏輯 Market Logic：
{logic}

👉 策略 Strategy：
{action}

━━━━━━━━━━━━━━
"""
# ======================
# LONG TERM（長線分析）
# ======================
def long_term():
    spy = get_df("SPY","1d")
    msft = get_df("MSFT","1d")
    vwra = get_df("VWRA.L","1d")

    def analyze(df):
        if df is None or df.empty:
            return "未知 Unknown"

        price = df["Close"].iloc[-1]
        ma50 = df["Close"].rolling(50).mean().iloc[-1]
        ma200 = df["Close"].rolling(200).mean().iloc[-1]

        if price > ma50 and price > ma200:
            return "📈 強勢上升 Strong Uptrend"
        elif price > ma200:
            return "🟡 中期上升 Pullback"
        else:
            return "🔴 弱勢 Downtrend"

    spy_trend = analyze(spy)
    msft_trend = analyze(msft)
    vwra_trend = analyze(vwra)

    return f"""📈【長線投資 Long Term】

📊 S&P500（SPY）
👉 {spy_trend}

📊 全球ETF（VWRA）
👉 {vwra_trend}

📊 Microsoft（MSFT）
👉 {msft_trend}

🧠 策略 Strategy：

🟢 強勢 → 持續定投 DCA
🟡 回調 → 分段加倉 Buy dips
🔴 弱勢 → 控制風險 Risk control

━━━━━━━━━━━━━━
"""
# ======================
# NEWS（簡單新聞分析 Placeholder）
# ======================
def get_news(symbol):
    # 🔥 之後可以接 News API / Yahoo news
    # 現在先用簡單 sentiment 模擬
    fake_news = {
        "TSLA": "🟢 正面 Positive（AI + 自動駕駛利好）",
        "NVDA": "🟢 正面 Positive（AI需求強勁）",
        "AMD": "🟡 中性 Neutral（等待數據）",
        "XOM": "🟢 正面 Positive（油價支撐）",
        "JPM": "🔴 負面 Negative（金融壓力）"
    }
    return fake_news.get(symbol, "🟡 中性 Neutral")


# ======================
# STOCK SCAN PRO（升級版 UI）
# ======================
def stock_all():
    msg = "📊【波段掃描 Pro｜Swing Scan Pro】\n\n"

    for s in SYMBOLS:
        df = get_df(s,"5m")
        if df is None:
            continue

        d = calc(df)
        sig = signal_engine(df,d)

        # 🔥 趨勢文字
        trend_text = "📈 上升 Uptrend" if d["trend_up"] else "📉 下降 Downtrend"

        # 🔥 信號解釋
        explain = {
            "🟢 ENTRY｜入場": "👉 可考慮入場（風險已定）",
            "👀 SETUP｜準備": "👉 接近入場區（等待確認）",
            "🚀 BREAKOUT｜突破": "👉 強勢突破（追勢）",
            "🔴 RISK｜風險": "👉 跌穿支撐（避開）",
            "🟡 WAIT｜觀望": "👉 無明確方向"
        }.get(sig, "")

        # 🔥 新聞
        news = get_news(s)

        msg += f"""📈【{s}】

💰 價格 Price：{round(d['price'],2)}
📊 RR：{round(d['rr'],2)} ｜ RSI {d['rsi']}

{trend_text}

🎯 入場 Entry：
{round(d['entry_low'],2)} - {round(d['entry_high'],2)}

🛑 止損 Stop：
{round(d['stop'],2)}

🎯 目標 Target：
{round(d['target'],2)}

🧠 信號 Signal：
{sig}
{explain}

📰 新聞 News：
{news}

━━━━━━━━━━━━━━
"""

    return msg

# =========================================================
# 🚀 AUTO SIGNAL LOOP（核心引擎）
# =========================================================
def loop():
    now = time.time()

    # 🌍 市場狀態
    allow_trade, market_msg = market_filter()

    candidates = []

    for s in SYMBOLS:
        df = get_df(s,"5m")
        if df is None or len(df) < 25:
            continue

        d = calc(df)
        sig = signal_engine(df, d)

        # 📰 新聞
        sentiment, news_text = get_news_sentiment(s)

        # ⭐ 評分
        score = score_signal(df, d, sig, sentiment)

        # =================================================
        # 🔴 市場過濾（最重要）
        # =================================================
        if not allow_trade:
            if "ENTRY" in sig or "BREAKOUT" in sig:
                continue

        # =================================================
        # ⭐ 分數過濾
        # =================================================
        if score < 3:
            continue

        candidates.append((s, d, score, sig, news_text))

        # =================================================
        # 🟢 ENTRY ALERT
        # =================================================
        if "ENTRY" in sig:
            if now - last_alert.get(s+"_entry",0) > 1800:
                send(CHAT_ID, f"""🟢【ENTRY｜入場】

📈 {s}
💰 價格：{round(d['price'],2)}
📊 RR：{round(d['rr'],2)}

📰 {news_text}

━━━━━━━━━━
""")
                last_alert[s+"_entry"] = now

        # =================================================
        # 🔴 RISK ALERT
        # =================================================
        if "RISK" in sig:
            send(CHAT_ID, f"🔴 RISK｜風險 {s}")

    # =====================================================
    # 🚀 TOP SIGNAL（排行榜第一）
    # =====================================================
    if candidates:
        s, d, score, sig, news_text = sorted(
            candidates, key=lambda x: x[2], reverse=True
        )[0]

        if now - last_alert.get(s,0) > 600:
            send(CHAT_ID, f"""🚀【TOP SIGNAL｜最強機會】

📈 {s}
💰 價格：{round(d['price'],2)}
📊 RR：{round(d['rr'],2)}

👉 信號：{sig}
⭐ Score：{round(score,1)}

📰 {news_text}

━━━━━━━━━━
""")
            last_alert[s] = now

# ======================
# AUTO LOOP
# ======================
def auto_loop():
    while True:
        loop()
        time.sleep(300)

# ======================
# SEND（發送）
# ======================
def send(chat_id,msg):
    requests.post(f"{URL}/sendMessage",json={"chat_id":chat_id,"text":msg[:4000]})

# ======================
# WEBHOOK
# ======================
@app.route("/",methods=["POST"])
def webhook():
    data = request.get_json()
    if not data: return "ok"

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text","").lower()

    if "/start" in text:
        send(chat_id,"🚀 Bot Ready｜機械人已啟動")

    elif "/stock" in text:
        send(chat_id,stock_all())

    elif "/market" in text:
        send(chat_id,market())

    elif "/gold" in text:
        send(chat_id,gold())

    elif "/long" in text:
        send(chat_id,long_term())

    return "ok"

@app.route("/scan")
def scan():
    loop()
    return "scan done"

# ======================
# RUN
# ======================
if __name__ == "__main__":
    threading.Thread(target=auto_loop,daemon=True).start()
    app.run(host="0.0.0.0",port=10000)
