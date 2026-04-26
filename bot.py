from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd

# ======================
# 🌐 BILINGUAL HELPER
# ======================
def bi(zh, en):
    return f"{zh}｜{en}"
    
app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("NEWS_API_KEY")
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

trade_log = {}
last_alert = {}
cache = {}
CACHE_TTL = 120
# =========================================================
# 📰 NEWS SYSTEM（Yahoo + NewsAPI fallback）
# =========================================================
def get_yahoo_news(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol} stock&newsCount=3"
        res = requests.get(url, timeout=5)
        data = res.json()

        news = data.get("news", [])
        if not news:
            return None

        news_text = ""
        for n in news[:3]:
            title = n.get("title", "")[:60]
            source = n.get("publisher", "")
            news_text += f"• {title} ({source})\n"

        return news_text.strip()

    except Exception as e:
        print("YAHOO NEWS ERROR:", e)
        return None


def get_newsapi_news(symbol):
    try:
        if not API_KEY:
            return None

        url = f"https://newsapi.org/v2/everything?q={symbol}&sortBy=publishedAt&pageSize=3&apiKey={API_KEY}"
        res = requests.get(url, timeout=5)
        data = res.json()

        articles = data.get("articles", [])
        if not articles:
            return None

        news_text = ""
        for a in articles[:3]:
            title = a.get("title", "")[:60]
            source = a.get("source", {}).get("name", "")
            news_text += f"• {title} ({source})\n"

        return news_text.strip()

    except Exception as e:
        print("NEWSAPI ERROR:", e)
        return None
# =========================================================
# 🧠 NEWS + SENTIMENT（真正版本）
# =========================================================
def get_news_sentiment(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol} stock&newsCount=5"
        res = requests.get(url, timeout=5)
        data = res.json()

        news = data.get("news", [])
        if not news:
            return "UNKNOWN", bi("⚠️ 無新聞（數據不足）", "No data")
            
        text = " ".join([n.get("title","") for n in news]).lower()

        positive = ["beat","growth","strong","upgrade","record","ai"]
        negative = ["miss","drop","downgrade","weak","loss","cut"]

        score = 0
        for w in positive:
            if w in text:
                score += 1
        for w in negative:
            if w in text:
                score -= 1

        if score >= 2:
            return "POSITIVE", bi("🟢 利好", "Positive")
        elif score <= -2:
            return "NEGATIVE", bi("🔴 利淡", "Negative")
        else:
            return "NEUTRAL", bi("🟡 中性", "Neutral")

    except Exception as e:
           print("SENTIMENT ERROR:", e)
           return "UNKNOWN", bi("⚠️ 無新聞", "No data")
        
# =========================================================
# 🧠 MASTER NEWS FUNCTION（智能 fallback）
# =========================================================
def get_news(symbol):
    news = get_yahoo_news(symbol)

    if news:
        return news

    news = get_newsapi_news(symbol)

    if news:
        return news

    return bi("🟡 無新聞", "No news")
# ======================
# DATA（數據獲取 Data Fetch）
# ======================
def get_df(symbol, interval):
    key = f"{symbol}_{interval}"
    now = time.time()
    
    if interval == "1d":
        period = "1y"   # 🔥 長線要多數據
    else:
        period = "2d"
    
    if key in cache:
        data, ts = cache[key]
        if now - ts < CACHE_TTL:
            return data

    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df is None or df.empty or len(df) < 50:
            return None

        cache[key] = (df.copy(), now)
        return df
    except:
        return None
# ======================
# 🔥 BETTER SUPPORT VALIDATION
# ======================
def check_support_valid(df, support):
    if support is None:
        return False

    touch_count = sum(
        1 for x in df["Low"].iloc[-20:]
        if abs(x - support) < support * 0.003
    )

    return touch_count >= 2
# ======================
# CALC（計算 Indicators）
# ======================
def calc(df):
    price = float(df["Close"].iloc[-1])

    # ======================
    # 📈 Trend
    # ======================
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    trend_up = price > ma20

    # ======================
    # 📊 RSI
    # ======================
    rsi_series = 100 - (100 / (1 + (
        df["Close"].diff().clip(lower=0).rolling(14).mean() /
        (-df["Close"].diff().clip(upper=0).rolling(14).mean() + 1e-10)
    )))
    rsi = round(rsi_series.iloc[-1], 1)

    # ======================
    # 🧱 Support 系統（核心修正）
    # ======================
    support, resistance = get_zones(df)

    better_support = get_better_support(df)
    valid_support = check_support_valid(df, better_support)

    # ======================
    # 👉 用更準嘅 support
    # ======================
    if valid_support:
        base = better_support
    else:
        base = support[0]

    # ======================
    # 🎯 Execution Zone（統一）
    # ======================
    exec_entry_low = base * 0.995
    exec_entry_high = base * 1.005

    exec_stop = base * 0.97

    mid_entry = (exec_entry_low + exec_entry_high) / 2
    risk = (mid_entry - exec_stop)

    # ======================
    # ❌ 避免風險太細（假RR）
    # ======================
    if risk < price * 0.002:   # 0.2%
        return None
    
    exec_target = mid_entry + risk * 2
    exec_rr = (exec_target - mid_entry) / risk if risk > 0 else 0

    # ======================
    # ❌ 限制最大RR（防假靚）
    # ======================
    exec_rr = min(exec_rr, 5)

    # ======================
    # 📦 RETURN
    # ======================
    return {
        "price": price,
        "trend_up": trend_up,
        "rsi": rsi,
        "rr": exec_rr,

        "exec_entry_low": exec_entry_low,
        "exec_entry_high": exec_entry_high,
        "exec_stop": exec_stop,
        "exec_target": exec_target
    }
    
        # ======================
        # 🔥 BETTER SUPPORT（新）
        # ======================
def get_better_support(df):
    lows = df["Low"]

    swing_lows = []
    for i in range(2, len(df)-2):
        if lows.iloc[i] < lows.iloc[i-1] and lows.iloc[i] < lows.iloc[i+1]:
            swing_lows.append(lows.iloc[i])

    if len(swing_lows) < 2:
        return None

    support = sum(swing_lows[-3:]) / min(len(swing_lows),3)
    return support
    
        # ======================
        # 🧱 SUPPORT / RESISTANCE
        # ======================
def get_zones(df):
    high = df["High"].rolling(50).max().iloc[-1]
    low = df["Low"].rolling(50).min().iloc[-1]

    buffer = (high - low) * 0.02  # zone buffer

    resistance = (high - buffer, high)
    support = (low, low + buffer)

    return support, resistance

        # ======================
        # 🕯️ CANDLE ENGINE（新）
        # ======================
def candle_type(df):
    open_ = df["Open"].iloc[-1]
    close = df["Close"].iloc[-1]
    high = df["High"].iloc[-1]
    low = df["Low"].iloc[-1]

    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low

    if close > open_ and body > (upper_wick + lower_wick):
        return "STRONG_BULL"

    if close < open_ and body > (upper_wick + lower_wick):
        return "STRONG_BEAR"

    if lower_wick > body * 2:
        return "BUY_REJECTION"

    if upper_wick > body * 2:
        return "SELL_REJECTION"

    return "NEUTRAL"
    
# =========================================================
# 🌍 MARKET FILTER（市場過濾｜決定可唔可以交易）
# =========================================================
def market_filter():
    df = get_df("SPY","15m")
    if df is None or df.empty:
        return True, bi("⚠️ 無法判斷市場", "Market unclear")
        
    price = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]

    trend = price > ma20
    momentum = ma5 > ma20
    structure = price > ma50

    # 🔥 決策邏輯
    if not trend and not momentum:
        return False, bi("🔴 市場轉弱", "Risk OFF")
    elif trend and momentum and structure:
        return True, bi("🟢 市場健康", "Risk ON")
    else:
        return True, bi("🟡 中性", "Selective trades")
        
# =========================================================
# ⭐ SCORING ENGINE（信號評分系統）
# =========================================================
def score_signal(df, d, sig_code, sentiment):
    score = 0

    # ======================
    # 🎯 信號強度
    # ======================
    if sig_code == "ENTRY":
        score += 2

    # ❌ 唔再追 breakout
    if sig_code == "BREAKOUT":
        score -= 1

    # ✅ 新策略（核心）
    if sig_code == "PULLBACK":
        score += 2.5

    if sig_code == "RETEST":
        score += 2.5

    # ======================
    # 📊 RR
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
    # ⚡ RSI
    # ======================
    if 50 < d["rsi"] < 65:
        score += 1

    # ======================
    # 📰 情緒
    # ======================
    if sentiment == "POSITIVE":
        score += 1
    elif sentiment == "NEGATIVE":
        score -= 1.5
    elif sentiment == "UNKNOWN":
        score -= 0.5   # 輕微減分   
    # ======================
    # 📍 Zone 加分
    # ======================    
    support, resistance = get_zones(df)
    if support[0] <= d["price"] <= support[1]:
        score += 1

    return score
    
    # ======================
    # setup signal
    # ======================
def is_setup(df, d):
    price = d["price"]
    
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    trend_ok = price > ma20

    structure_shift = (
        df["Low"].iloc[-1] > df["Low"].iloc[-3] and
        df["Low"].iloc[-2] > df["Low"].iloc[-4] and
        df["High"].iloc[-1] > df["High"].iloc[-3]
    )

    momentum = df["Close"].iloc[-1] > df["Close"].iloc[-2]

    # 🔥 RSI filter直接放入setup（關鍵）
    rsi_ok = 45 < d["rsi"] < 65

    # ❗唔喺 entry zone（避免太遲）
    zone_low = d["exec_entry_low"]
    zone_high = d["exec_entry_high"]
    not_in_zone = not (zone_low <= price <= zone_high)

    return trend_ok and structure_shift and momentum and rsi_ok and not_in_zone
    
# ======================
# SIGNAL ENGINE（信號引擎）
# ======================
def signal_engine(df, d):
        
    # ======================
    # 安全檢查
    # ======================
    if len(df) < 30:
        return ("WAIT", bi("🟡 數據不足", "WAIT - insufficient data"))
        
    price = d["price"]

    # ======================
    # 基本區間
    # ======================
    support, resistance = get_zones(df)

    recent_high = df["High"].iloc[-20:-3].max() if len(df) > 25 else df["High"].max()
    recent_low = df["Low"].iloc[-20:-3].min() if len(df) > 25 else df["Low"].min()
    
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    trend_ok = price > ma20
   
    # ======================
    # 🔥 Better Support
    # ======================
    better_support = get_better_support(df)

    if better_support is None:
        valid_support = False
    else:
        valid_support = check_support_valid(df, better_support)

    # ======================
    # 🔥 結構轉變（升級版）
    # ======================
    structure_shift = (
        df["Low"].iloc[-1] > df["Low"].iloc[-3] and
        df["Low"].iloc[-2] > df["Low"].iloc[-4] and
        df["High"].iloc[-1] > df["High"].iloc[-3]
)

    
    # ======================
    # 🔥 momentum
    # ======================
    momentum_shift = (
    df["Close"].iloc[-1] > df["Close"].iloc[-2] and
    df["Close"].iloc[-1] > df["Open"].iloc[-1]
)

    # ======================
    # 🕯️ Candle
    # ======================
    candle = candle_type(df)

    # ======================
    # 🔥 Pullback Entry（核心）
    # ======================
    pullback_support = (
    valid_support and
    better_support is not None and
    better_support * 0.993 <= price <= better_support * 1.007 and
    momentum_shift and
    structure_shift and
    trend_ok
)

    # ======================
    # breakout / breakdown
    # ======================
    breakout = price > recent_high
    breakdown = price < recent_low

    # ======================
    # breakout 後回踩
    # ======================
    breakout_retest = (
    df["Close"].iloc[-3] > recent_high and
    df["Close"].iloc[-2] > recent_high and
    recent_high * 0.995 <= price <= recent_high * 1.005 and
    momentum_shift
)

    # ======================
    # 🕯️ K線過濾（新）
    # ======================

    # ❌ 假突破
    if candle == "SELL_REJECTION" and breakout:
       return ("FAKE_BREAKOUT", bi("⚠️ 假突破", "Fake breakout"))

    # 🔥 吸貨確認
    if candle == "BUY_REJECTION" and pullback_support:
       return ("ACCUMULATION", bi("🔥 吸貨確認", "Accumulation"))

    # ======================
    # 🚫 唔追 breakout
    # ======================

    if breakdown:
        return ("RISK", bi("🔴 風險", "Risk"))

    elif breakout_retest:
        return ("RETEST", bi("🔥 突破回踩", "Retest"))
        
    elif pullback_support:
        return ("PULLBACK", bi("🟢 回踩入場", "Pullback"))
        
    elif breakout:
        return ("BREAKOUT", bi("🚫 突破（等回踩）", "Breakout wait"))
        
    else:
        return ("WAIT", bi("🟡 觀望", "Wait"))

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

    trend = bi("📈 上升", "Uptrend") if price > ma20 else bi("📉 下降", "Downtrend")
    structure = bi("健康", "Healthy") if price > ma50 else bi("轉弱", "Weakening")

    # momentum
    ma5 = df["Close"].rolling(5).mean().iloc[-1]
    momentum = bi("🔥 強", "Strong") if ma5 > ma20 else bi("❄️ 弱", "Weak")
    
    # 行動建議
    if price > ma20 and ma5 > ma20:
        action = bi("🟢 可做多（順勢交易）", "Long bias")
    elif price < ma20 and ma5 < ma20:
        action = bi("🔴 保守 / 避險", "Risk-off")
    else:
        action = bi("🟡 震盪（等方向）", "Choppy")
        
    return f"""🌍【市場方向 Market Bias】

📊 指數 Index：SPY
💰 價格 Price：{round(price,2)}

📈 趨勢 Trend：{trend}
🏗 結構 Structure：{structure}
⚡ 動能 Momentum：{momentum}

━━━━━━━━━━━━━━
🧠 市場狀態 Market State：

{action}

━━━━━━━━━━━━━━
⚠️ 交易指引 Trading Guide：

• 🟢 {bi("只做多", "Long bias only")}
• 🔴 {bi("減倉 / 停手", "Reduce risk / Stay out")}
• 🟡 {bi("揀setup先入", "Be selective")}

━━━━━━━━━━━━━━
"""

    # ======================
    # GOLD（黃金分析）
    # ======================
def gold():
    df = get_df("SGLN.L","15m")
    df_global = get_df("GC=F","15m")
    
    if df is None or df_global is None:
    
        return "⚠️ 無法讀取黃金｜Gold data unavailable"
    
    if df_global is not None:
       global_price = df_global["Close"].iloc[-1]
       global_ma20 = df_global["Close"].rolling(20).mean().iloc[-1]

       sgln_price = df["Close"].iloc[-1]
       sgln_ma20 = df["Close"].rolling(20).mean().iloc[-1]

       global_up = global_price > global_ma20
       sgln_lag = sgln_price < sgln_ma20

    if global_up and sgln_lag:
        print("Early opportunity")
    
    if df is None or df.empty:
        return "⚠️ 無法讀取黃金｜Gold data unavailable"

    price = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]

    trend = bi("📈 上升", "Uptrend") if price > ma20 else bi("📉 下降", "Downtrend")
    structure = bi("強勢", "Strong") if price > ma50 else bi("轉弱", "Weak")

    # ======================
    # 黃金邏輯
    # ======================
    if price > ma20:
        logic = bi("⚠️ 市場避險情緒上升", "Risk sentiment rising")
        action = bi("🟡 可作對沖", "Use as hedge")
    else:
        logic = bi("💰 資金流向風險資產", "Risk-on")
        action = bi("🟢 可忽略黃金", "Focus stocks")
        
    return f"""🥇【黃金資金流 Gold Flow】

💰 價格 Price：{round(price,2)}

📈 趨勢 Trend：{trend}
🏗 結構 Structure：{structure}

━━━━━━━━━━━━━━
🧠 市場邏輯 Market Logic：

{logic}

━━━━━━━━━━━━━━
🎯 策略 Strategy：

{action}

• Hedge → {bi("避險用", "Risk hedge")}
• Ignore → {bi("專注股票", "Focus stocks")}

━━━━━━━━━━━━━━
"""

# ======================
# LONG TERM（長線分析）
# ======================
def long_term():
    spy = get_df("SPY","1d")
    msft = get_df("MSFT","1d")
    world = get_df("ACWI","1d")
    
    def analyze(df):
        if df is None or df.empty:
            return "未知 Unknown"

        price = df["Close"].iloc[-1]
        ma50 = df["Close"].rolling(50).mean().iloc[-1]
        ma200 = df["Close"].rolling(200).mean().iloc[-1]

        if price > ma50 and price > ma200:
            return bi("📈 強勢上升", "Strong Uptrend")
        elif price > ma200:
            return bi("🟡 中期上升", "Pullback")
        else:
            return bi("🔴 弱勢", "Downtrend")

    spy_trend = analyze(spy)
    msft_trend = analyze(msft)
    vwra_trend = analyze(world)
    
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
# STOCK SCAN PRO（升級版 UI）
# ======================
def stock_all():
    msg = "📊【波段掃描 Pro｜Swing Scan Pro】\n\n"

    for s in SYMBOLS:
        
        df = get_df(s,"5m")
        if df is None:
            continue

        d = calc(df)
        if d is None:
            continue
    
        sig_code, sig_text = signal_engine(df,d)

        vol = df["Volume"]
        vol_ma = vol.rolling(10).mean().iloc[-1]
        volume_spike = vol.iloc[-1] > vol_ma * 1.5

        vol_tag = "🔥 Volume" if volume_spike else ""
        zone_tag = "📍 Zone" if sig_code in ["PULLBACK","RETEST"] else ""
        tags = " ".join(filter(None, [vol_tag, zone_tag]))

        news = get_news(s)
        sentiment, senti_text = get_news_sentiment(s)
        
        msg += f"""📈【{s}】

💰 價格 Price：{round(d['price'],2)}
📊 RR：{round(d['rr'],2)} ｜ RSI：{d['rsi']}

👉 {sig_text} {tags}

━━━━━━━━━━━━━━
🎯 【入場 Execution】

📍 Entry：
{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

🛑 Stop：
{round(d['exec_stop'],2)}

🎯 Target：
{round(d['exec_target'],2)}

━━━━━━━━━━━━━━
🧠 【背景 Context】

情緒 Sentiment：
{senti_text}

📰 新聞 News：
{news}

━━━━━━━━━━━━━━
"""
    return msg
    
    # ======================
    # premarket_plan
    # ======================
def premarket_plan():
    msg = "📋【今日作戰計劃】\n\n"

    for s in SYMBOLS:
        df = get_df(s,"15m")
        if df is None:
            continue
    
        d = calc(df)
        if d is None:
            continue

        msg += f"""📈 {s}

🎯 入場區：
{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

🛑 止損：
{round(d['exec_stop'],2)}

🎯 目標：
{round(d['exec_target'],2)}

━━━━━━━━━━━━━━
"""

    return msg

# ======================
# market open
# ======================
def is_market_open():
    now_local = time.localtime()
    
    if now_local.tm_hour == 14 and now_local.tm_min < 30:
        return False

    # 轉英國時間（BST / GMT 自動）
    uk_time = time.localtime()

    weekday = uk_time.tm_wday  # 0=Mon, 6=Sun
    hour = uk_time.tm_hour
    minute = uk_time.tm_min

    # ❌ 星期六日
    if weekday >= 5:
        return False

    # 美股時間：14:30 - 21:00（UK time）
    if hour < 14 or (hour == 14 and minute < 30):
        return False
    if hour >= 21:
        return False

    return True
    
# ======================
# 🚀 LOOP（升級完整版）
# ======================
def loop():
    global trade_log
    
    if not is_market_open():
        return
        
    now = time.time()    
    now_local = time.localtime()

    print("LOOP RUNNING...")
    

    trade_log = {
        k:v for k,v in trade_log.items()
        if time.time() - v["time"] < 86400
    }
    
    current_open = sum(
        1 for t in trade_log.values() if t["status"] == "OPEN"
    )
    
    total_risk = sum(
        t["risk"] * t.get("size",1)
        for t in trade_log.values()
        if t["status"] == "OPEN"
    )
            
    # ======================
    # 🧠 CAPITAL CONTROL
    # ======================

    recent_losses = [t for t in trade_log.values() if t["status"] == "LOSS"][-3:]

    # =======================
    # 🌍 市場狀態
    # =======================
    allow_trade, market_msg = market_filter()

    # 👇 backup原始市場狀態
    market_allow = allow_trade

    # 👇 再改（風控）
    if len(recent_losses) == 3:
        allow_trade = False
        print("⛔ Cooldown active")

    # =======================
    # 🔴 RISK-OFF ALERT（市場風險）
    # =======================
    prev_state = last_alert.get("market_state","ON")
    current_state = "OFF" if not allow_trade else "ON"

    if prev_state == "ON" and current_state == "OFF":

        if not market_allow:
            reason_zh = "市場轉弱"
            reason_en = "Market turning weak"
        else:
            reason_zh = "連續虧損（冷卻期）"
            reason_en = "Consecutive losses (cooldown)"
    
        send(CHAT_ID, f"""🔴【風險關閉 Risk OFF】

📉 原因 Reason：
{bi(reason_zh, reason_en)}

━━━━━━━━━━━━━━
🌍 市場狀態 Market：
{market_msg}

━━━━━━━━━━━━━━
⚠️ 建議 Action：

• {bi("停止開新倉","Stop new trades")}
• {bi("減低風險","Reduce risk")}
""")

# ❗一定要放出面（無論有冇send）
    last_alert["market_state"] = current_state
    
        
    # =======================
    # 🧠 RISK MODE（乾淨版）
    # =======================    
    if total_risk > 0.05:
        allow_trade = False
        risk_mode = "LOW"
        market_msg += "\n" + bi("⛔ 已達風險上限（停止開倉）", "Risk cap hit (no new trades)")
        
    elif total_risk > 0.03:
        risk_mode = "LOW"
        market_msg += "\n" + bi("⚠️ 風險降低中","Reducing risk")
    else:
        risk_mode = "NORMAL"

    candidates = []

    for s in SYMBOLS:
        
        df = get_df(s,"5m")
        df15 = get_df(s,"15m")

        if df is None or df15 is None or len(df) < 25:
            continue

        d = calc(df)
        if d is None:
            continue

        if not is_setup(df, d):
            last_alert[s+"_setup_active"] = False

        if is_setup(df, d):

            if not last_alert.get(s+"_setup_active", False):

                last_alert[s+"_setup_active"] = True

        # ======================
        # 🧠 SETUP ALERT Early Setup Forming
        # ======================
        if is_setup(df, d):

            if last_alert.get(s+"_setup_active", False):
                pass
            else:
                last_alert[s+"_setup_active"] = True
                # send alert
            
            zone_low = d["exec_entry_low"]
            zone_high = d["exec_entry_high"]

            if zone_low <= d["price"] <= zone_high:
                distance_entry = 0
            else:
                distance_entry = min(
                    abs(d["price"] - zone_low),
                    abs(d["price"] - zone_high)
                ) / ((zone_high + zone_low)/2)

            dist_text = round(distance_entry * 100, 2)

            # ❗太遠唔通知（避免垃圾signal）
            if distance_entry < 0.03:

                if now - last_alert.get(s+"_setup",0) > 1800:

                    send(CHAT_ID, f"""🧠【Setup形成 Setup Forming】

📈 {s}
💰 價格 Price：{round(d['price'],2)}

━━━━━━━━━━━━━━
📊 結構 Structure：

• {bi("趨勢轉強","Trend improving")}
• {bi("結構上移","Higher lows")}

━━━━━━━━━━━━━━
🎯 準備區域 Watch Zone：

{round(zone_low,2)} - {round(zone_high,2)}

👉 {bi("等回踩入場","Wait for pullback")}
""")

                    last_alert[s+"_setup"] = now

        sig_code, sig_text = signal_engine(df, d)
        print("DEBUG:", s, sig_code, round(d["rsi"],1), "RR:", round(d["rr"],2))
    
        mid_entry = (d["exec_entry_low"] + d["exec_entry_high"]) / 2
        risk = mid_entry - d["exec_stop"]
        
            
        # ======================
        # 🔥 Position sizing（正確版）
        # ======================
        if risk_mode == "LOW":
            size = 0.5
        elif allow_trade:
            size = 1.0 if d["rsi"] < 60 else 1.5
        else:
            size = 0.5

        
        # =======================
        # ❌  太低直接 skip
        # =======================
        if d["rr"] < 1.8:
            continue
            
        # ======================
        # 🔥 多時間框架確認（新）
        # ======================
        ma20_15 = df15["Close"].rolling(20).mean().iloc[-1]
        trend_15 = df15["Close"].iloc[-1] > ma20_15

        if not trend_15:
            continue
            
        structure_ok = (
            df["Low"].iloc[-1] > df["Low"].iloc[-5] and
            df["High"].iloc[-1] > df["High"].iloc[-5]
        )


        # ======================
        # 🔥 Volume Filter（修正）
        # ======================
        vol = df["Volume"]
        vol_ma = vol.rolling(10).mean().iloc[-1]

        if pd.isna(vol_ma):
            continue
        
        volume_spike = vol.iloc[-1] > vol_ma * 1.5
        
        volatility = df["Close"].pct_change().rolling(20).std().iloc[-1]
        

        # ======================
        # 🔥 Fake Breakout Filter（新）
        # ======================
        recent_high = df["High"].iloc[-20:-3].max() if len(df) > 25 else df["High"].max()
        
        fake_bo = (
            df["Close"].iloc[-1] > recent_high and
            df["Close"].iloc[-2] < recent_high and
            (df["High"].iloc[-1] - df["Close"].iloc[-1]) / df["High"].iloc[-1] > 0.003
        )

        engulfing_fail = (
            df["Close"].iloc[-2] > recent_high and
            df["Close"].iloc[-1] < df["Open"].iloc[-1] and
            df["Close"].iloc[-1] < df["Close"].iloc[-2]
        )
        
        if fake_bo or engulfing_fail:
            continue


        # ======================
        # 📰 新聞 + 情緒
        # ======================
        news = get_news(s)
        sentiment, senti_text = get_news_sentiment(s)
        
        # ======================
        # ❌ 避免橫行市場（Sideway Filter）
        # ======================
        range_pct = (df["High"].iloc[-20:].max() - df["Low"].iloc[-20:].min()) / d["price"]
            
        # ======================
        # ⭐ 評分
        # ======================
        score = score_signal(df, d, sig_code, sentiment)

        if range_pct < volatility * 1.2:
            score -= 1

        if not structure_ok and sig_code in ["PULLBACK", "RETEST"]:
            continue
            
        if volume_spike:
            score += 1
        if vol.iloc[-1] < vol_ma * 0.5:
            continue               
            
        # ======================
        # ❌ 止損太遠（輸太多）
        # ======================
        if (d["price"] - d["exec_stop"]) / d["price"] > 0.035:
            continue
                    
        # ======================
        # ⭐ Score filter
        # ======================
        if not allow_trade and score < 4.5:
            continue

        if score < 3.0:
            continue
            
        candidates.append((s, d, score, sig_code, sig_text, news, senti_text, volume_spike))

        # ======================
        # ⚠️ 預警：接近入場區（新）
        # ======================
        zone_low = d["exec_entry_low"]
        zone_high = d["exec_entry_high"]

        # 🔥 先計 distance
        if zone_low <= d["price"] <= zone_high:
            distance_entry = 0
        else:
            distance_entry = min(
                abs(d["price"] - zone_low),
                abs(d["price"] - zone_high)
            ) / ((zone_high + zone_low) / 2)

        dist_text = round(distance_entry * 100, 2)
        
        if distance_entry < 0.01:
            if now - last_alert.get(s+"_near",0) > 900:
                send(CHAT_ID, f"""⚠️【接近入場】

📈 {s}
💰 價格：{round(d['price'],2)}

🎯 入場區：
{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

📊 距離入場：{dist_text}%
""")
                
                last_alert[s+"_near"] = now
            
        # ======================
        # 🔥 接近突破提醒（新）
        # ======================
        if recent_high > 0:
            distance_bo = (recent_high - d["price"]) / recent_high

            if 0 < distance_bo < 0.01:
                if now - last_alert.get(s+"_bo",0) > 900:
                    send(CHAT_ID, f"""🔥【接近突破】

📈 {s}
💰 價格：{round(d['price'],2)}

📊 壓力位：
{round(recent_high,2)}

📊 距離突破：{round(distance_bo*100,2)}%
""")
                
                    last_alert[s+"_bo"] = now

        # ======================
        # 🚀 BREAKOUT ALERT（突破提示）
        # ======================
        if sig_code == "BREAKOUT":

            if now - last_alert.get(s+"_breakout",0) > 1200:

                strength = bi("🔥 強勢","Strong") if volume_spike else bi("⚠️ 普通","Normal")

                send(CHAT_ID, f"""🚀【突破發生 Breakout】

📈 {s}
💰 價格 Price：{round(d['price'],2)}

━━━━━━━━━━━━━━
📊 突破狀態 Status：

• {bi("已突破前高","Break above resistance")}
• {strength}

━━━━━━━━━━━━━━
⚠️ 行動 Action：

• {bi("不建議追高","Avoid chasing")}
• {bi("等待回踩確認","Wait for retest")}
""")

                last_alert[s+"_breakout"] = now


        # ======================
        # 🟢 ENTRY ALERT（升級）
        # ======================

        if current_open >= 2:
            continue
            
        if now - last_alert.get(s+"_entry",0) < 900:
            continue
        
        lock_time = last_alert.get(s+"_entry_lock", 0)

        if time.time() - lock_time < 1800:
            continue   
            
        if s in trade_log and trade_log[s]["status"] == "OPEN":
            continue    
        
        mid = (d["exec_entry_low"] + d["exec_entry_high"]) / 2

        if (
            sig_code in ["PULLBACK", "RETEST"]
            and sentiment in ["POSITIVE","NEUTRAL"]
            and df["Close"].iloc[-1] > df["Close"].iloc[-2]
            and abs(d["price"] - mid) / mid <= 0.01   # ✅ 放入條件
        ):
                    
            trade_log[s] = {
                "entry": d["price"],
                "target": d["exec_target"],
                "stop": d["exec_stop"],
                "time": time.time(),
                "signal": sig_code,
                "status": "OPEN",
                "size": size,
                "risk": d["price"] - d["exec_stop"]
            }
                        
            last_alert[s+"_entry_lock"] = time.time()

            if s in trade_log:
                continue
                
            if len(trade_log) > 200:
                oldest = min(trade_log, key=lambda k: trade_log[k]["time"])
                del trade_log[oldest]
                

            send(CHAT_ID, f"""🟢【入場信號 Entry Signal】

📈 {s}
💰 價格 Price：{round(d['price'],2)}

━━━━━━━━━━━━━━
🧠 【原因 WHY】

• 信號 Signal：{sig_text}
• RSI：{d['rsi']}
• RR：{round(d['rr'],2)}

━━━━━━━━━━━━━━
🎯 【執行 Execution】

📍 入場 Entry：
{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

🛑 止損 Stop：
{round(d['exec_stop'],2)}

🎯 目標 Target：
{round(d['exec_target'],2)}

━━━━━━━━━━━━━━
🧠 【市場 Context】

🌍 Market：
{market_msg}

🧠 Sentiment：
{senti_text}

━━━━━━━━━━━━━━
""")
            last_alert[s+"_entry"] = now
                

        
        # ======================
        # 🔴 RISK ALERT
        # ======================
        if sig_code == "RISK":
            if now - last_alert.get(s+"_risk",0) > 1800:
                send(CHAT_ID, f"{bi('🔴 風險', 'RISK')} {s}")
            
                last_alert[s+"_risk"] = now

            # ======================
            # 🧠 TRACK RESULT（勝率追蹤）
            # ======================
    for symbol, t in list(trade_log.items()):
        
        if time.time() - last_alert.get(symbol+"_entry_lock",0) > 7200:
            last_alert[symbol+"_entry_lock"] = 0
            
        if t["status"] in ["WIN","LOSS","TIMEOUT"]:
            last_alert[symbol+"_entry_lock"] = 0
            continue
            
        if t["status"] != "OPEN":
            continue
            
        # ======================
        # ⛑️ 防卡死
        # ======================
        exit_price = None
        
        df_check = get_df(symbol, "5m")
        if df_check is None:
            continue

        current_price = df_check["Close"].iloc[-1]
        
        timeout = 7200 if t["entry"] < 200 else 10800
        
        if time.time() - t["time"] > timeout:
            t["status"] = "TIMEOUT"
            last_alert[symbol+"_entry_lock"] = 0
            exit_price = t["stop"]
            
            if t.get("R") is None:
                r = (exit_price - t["entry"]) / t["risk"]
                t["R"] = r
                t["R_size"] = r * t.get("size",1)
                t["exit_price"] = exit_price
                
            continue
            
        # ======================
        # 🧠 TRAILING STOP
        # ======================
        risk = t["risk"]
        
        if risk <= 0:
            continue
            
        old_stop = t["stop"]

        current_R = (current_price - t["entry"]) / risk
            
        # ======================
        # 🟡 BE（+1R）
        # ======================
        if not t.get("be_done") and current_R >= 1:
            t["stop"] = t["entry"] + t["risk"] * 0.1
            t["be_done"] = True
            
        if current_R >= 2:
            t["trail_started"] = True

        if t.get("trail_started"):
            new_stop = max(t["stop"], current_price - risk * 0.8)
            if new_stop > t["stop"]:
                t["stop"] = new_stop

        # ======================
        # 🎯 EXIT（只限 OPEN）
        # ======================
        if t["status"] == "OPEN":
            
            if current_price >= t["target"]:
                t["status"] = "WIN"
                last_alert[symbol+"_entry_lock"] = 0
                exit_price = t["target"]

            elif current_price <= t["stop"]:
                t["status"] = "LOSS"
                last_alert[symbol+"_entry_lock"] = 0
                exit_price = t["stop"]
                

        # ======================
        # 📊 記錄 R（只做一次）
        # ======================
        if exit_price is not None and t.get("R") is None:
            entry = t["entry"]
            risk = t["risk"]

            r = (exit_price - entry) / risk

            r_size = r * t.get("size",1)
            t["R"] = r
            t["R_size"] = r_size
            t["exit_price"] = exit_price

        # ======================
        # 📈 更新 RSI
        # ======================
        d_check = calc(df_check)
        if d_check:
            t["rsi"] = d_check["rsi"]


        # ======================
        # 🔄 STOP 更新通知
        # ======================
        if t["stop"] != old_stop:
            send(CHAT_ID, f"""🔄【STOP UPDATED｜止損更新】

📈 {symbol}
🛑 新止損：{round(t["stop"],2)}
""")
            
            
            # ======================
            # 🚀 TOP SIGNAL（升級UI）
            # ======================
    if candidates and current_open < 2:
        s, d, score, sig_code, sig_text, news, senti_text, volume_spike = sorted(
            candidates, key=lambda x: x[2], reverse=True
        )[0]
        if s in trade_log and trade_log[s]["status"] == "OPEN":
            return
            
        if now - last_alert.get(s,0) > 600:

            vol_tag = "🔥 Volume爆發" if volume_spike else ""
            zone_tag = "📍 Zone" if sig_code in ["PULLBACK","RETEST"] else ""
            tags = " ".join(filter(None, [vol_tag, zone_tag]))
        
            
            send(CHAT_ID, f"""🚀【TOP SIGNAL｜最強機會 Best Setup】
            
📈 {s} ｜ ⭐ Score：{round(score,1)}

👉 信號 Signal：
{sig_text} {tags}

━━━━━━━━━━━━━━
🎯 【入場區 Entry Zone】

{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

🛑 止損 Stop：
{round(d['exec_stop'],2)}

🎯 目標 Target：
{round(d['exec_target'],2)}

━━━━━━━━━━━━━━
🌍 【市場 Market】

{market_msg}

🧠 情緒 Sentiment：
{senti_text}

📰 新聞 News：
{news}

━━━━━━━━━━━━━━
""")
            last_alert[s] = now
                

    wins = sum(1 for t in trade_log.values() if t["status"] == "WIN")
    losses = sum(1 for t in trade_log.values() if t["status"] == "LOSS")

    total = wins + losses
    winrate = wins / total if total > 0 else 0

    print(f"WINRATE: {round(winrate*100,1)}% ({wins}/{total})")
    # ======================
    # 📊 EXPECTANCY
    # ======================
    recent_trades = [
        t for t in trade_log.values()
        if "exit_price" in t and time.time() - t["time"] < 86400
    ]

    
    wins_R = [t["R"] for t in recent_trades if t["R"] > 0]
    losses_R = [t["R"] for t in recent_trades if t["R"] < 0]

    if wins_R and losses_R:
        avg_win = sum(wins_R)/len(wins_R)
        avg_loss = abs(sum(losses_R)/len(losses_R))
        winrate_R = len(wins_R) / (len(wins_R) + len(losses_R))

        expectancy = (winrate_R * avg_win) - ((1-winrate_R) * avg_loss)

        print(f"EXP: {round(expectancy,2)}R | AVG WIN: {round(avg_win,2)} | AVG LOSS: {round(avg_loss,2)}")


# ======================
# AUTO LOOP
# ======================
def auto_loop():
    while True:
        try:
            loop()
        except Exception as e:
            print("LOOP ERROR:", e)

        time.sleep(300)
# ======================
# SEND（發送）
# ======================
def send(chat_id, msg):
    try:
        requests.post(f"{URL}/sendMessage",
                      json={"chat_id": chat_id, "text": msg[:4000]},
                      timeout=5)
    except:
        print("SEND ERROR")

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
        send(chat_id, bi("🚀 已啟動", "Bot Ready"))
        
    elif "/stock" in text:
        send(chat_id,stock_all())

    elif "/market" in text:
        send(chat_id,market())

    elif "/gold" in text:
        send(chat_id,gold())

    elif "/long" in text:
        send(chat_id,long_term())
        
    elif "/plan" in text:
        send(chat_id, premarket_plan())
        
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "OK"

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
