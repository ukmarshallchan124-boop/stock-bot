from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import pandas as pd

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
            return "UNKNOWN", "⚠️ 無新聞（數據不足）"

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
            return "POSITIVE", "🟢 利好 Positive"
        elif score <= -2:
            return "NEGATIVE", "🔴 利淡 Negative"
        else:
            return "NEUTRAL", "🟡 中性 Neutral"

    except Exception as e:
           print("SENTIMENT ERROR:", e)
           return "UNKNOWN", "⚠️ 數據缺失"
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

    return "🟡 無新聞 No news"
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
        
    # ============
    # Fake Signal
    # ============
def is_bad_setup(d):
    # 基本 filter
    if d["rsi"] > 70 or d["rsi"] < 40:
        return True

    # 🧠 根據過去輸嘅 pattern 避開
    recent_losses = [t for t in trade_log.values() if t["status"] == "LOSS"][-5:]

    if len(recent_losses) >= 3:
        avg_loss_rsi = sum(t.get("rsi",50) for t in recent_losses[-3:]) / 3

        # 如果而家 RSI 接近過去輸嘅區域 → 避
        if abs(d["rsi"] - avg_loss_rsi) < 5:
            return True

    return False
    
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
# ⭐ SCORING ENGINE（信號評分系統）
# =========================================================
def score_signal(df, d, sig, sentiment):
    score = 0

    # ======================
    # 🎯 信號強度
    # ======================
    if "ENTRY" in sig:
        score += 2

    # ❌ 唔再追 breakout
    if "BREAKOUT（等回踩）" in sig:
        score -= 1

    # ✅ 新策略（核心）
    if "PULLBACK" in sig:
        score += 2.5

    if "RETEST" in sig:
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
# SIGNAL ENGINE（信號引擎）
# ======================
def signal_engine(df, d):
        
    # ======================
    # 安全檢查
    # ======================
    if len(df) < 30:
        return "🟡 WAIT｜數據不足"

    price = d["price"]

    # ======================
    # 基本區間
    # ======================
    support, resistance = get_zones(df)

    recent_high = df["High"].iloc[-30:-5].max()
    recent_low = df["Low"].iloc[-30:-5].min()
    
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
       return "⚠️ FAKE BREAKOUT｜假突破"

    # 🔥 吸貨確認
    if candle == "BUY_REJECTION" and pullback_support:
       return "🔥 吸貨確認｜更強PULLBACK"

    # ======================
    # 🚫 唔追 breakout
    # ======================

    if breakdown:
        return "🔴 RISK｜風險"

    elif breakout_retest:
        return "🔥 RETEST｜突破回踩"

    elif pullback_support:
        return "🟢 PULLBACK｜回踩入場"

    elif breakout:
        return "🚫 BREAKOUT（等回踩）"

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

    trend = "📈 上升 Uptrend" if price > ma20 else "📉 下降 Downtrend"
    structure = "強勢 Strong" if price > ma50 else "轉弱 Weak"

    # ======================
    # 黃金邏輯
    # ======================
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
    world = get_df("ACWI","1d")
    
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
    
        sig = signal_engine(df,d)

        vol = df["Volume"]
        vol_ma = vol.rolling(10).mean().iloc[-1]
        volume_spike = vol.iloc[-1] > vol_ma * 1.5

        vol_tag = "🔥 Volume" if volume_spike else ""
        zone_tag = "📍 Zone" if "PULLBACK" in sig or "RETEST" in sig else ""
        tags = " ".join(filter(None, [vol_tag, zone_tag]))

        news = get_news(s)
        sentiment, senti_text = get_news_sentiment(s)
        
        msg += f"""📈【{s}】

💰 價格：{round(d['price'],2)}
📊 RR：{round(d['rr'],2)} ｜ RSI：{d['rsi']}

👉 信號：
{sig} {tags}

━━━━━━━━━━━━━━
🎯 入場區：
{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

🛑 止損：
{round(d['exec_stop'],2)}

🎯 目標：
{round(d['exec_target'],2)}
━━━━━━━━━━━━━━

🧠 情緒：
{senti_text}

📰 新聞：
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
# 🚀 LOOP（升級完整版）
# ======================
def loop():
    now = time.time()
    
    sig = signal_engine(df, d)
       
    print("DEBUG:", s, sig, round(d["rsi"],1), "RR:", round(d["rr"],2))

    print("LOOP RUNNING...")
    
    open_trades = sum(1 for t in trade_log.values() if t["status"] == "OPEN")
    
    total_risk = sum(
    ((t["risk"]) / t["entry"]) * t.get("size",1)
    for t in trade_log.values()
    if t["status"] == "OPEN"
)
    
    # =======================
    # 🌍 市場狀態
    # =======================
    allow_trade, market_msg = market_filter()
    
    if total_risk > 0.05:
        allow_trade = False
        market_msg += "\n⚠️ Risk cap reached"

    candidates = []

    for s in SYMBOLS:
        df = get_df(s,"5m")
        df15 = get_df(s,"15m")

        if df is None or df15 is None or len(df) < 25:
            continue

        d = calc(df)
        if d is None:
            continue
            
        mid_entry = (d["exec_entry_low"] + d["exec_entry_high"]) / 2
        risk = mid_entry - d["exec_stop"]
        
            
        # =======================    
        # 🔥 Position sizing
        # ======================= 
        if allow_trade:
            size = 1.0 if d["rsi"] < 60 else 1.5
        else:
            size = 0.5
        
        # =======================
        # ❌ RR 太低直接 skip
        # =======================
        if d["rr"] < 1.5:
            continue
        
        if is_bad_setup(d):
            continue
            
        # ======================
        # 🔥 多時間框架確認（新）
        # ======================
        ma20_15 = df15["Close"].rolling(20).mean().iloc[-1]
        trend_15 = df15["Close"].iloc[-1] > ma20_15
        structure_ok = (
        df["Low"].iloc[-1] > df["Low"].iloc[-5] and
        df["High"].iloc[-1] > df["High"].iloc[-5]
        )
     
        if not trent_15 and not structure_ok:
            continue
    
        # ======================
        # 🔥 Fake Breakout Filter（新）
        # ======================
        recent_high = df["High"].iloc[-20:-3].max()
        fake_bo = (
            df["Close"].iloc[-1] > recent_high and
            df["Close"].iloc[-2] < recent_high
        )
        if fake_bo:
            continue

        # ======================
        # 🔥 Volume Filter（修正）
        # ======================
        vol = df["Volume"]
        vol_ma = vol.rolling(10).mean().iloc[-1]
        
        volume_spike = vol.iloc[-1] > vol_ma * 1.5
        
        volatility = df["Close"].pct_change().rolling(20).std().iloc[-1]

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
        score = score_signal(df, d, sig, sentiment)

        if vol.iloc[-1] < vol_ma * 0.5:
            score -= 0.3
        
        if volume_spike:
            score += 1
        
        if range_pct < volatility * 1.2:
            score -= 1
            
        # ======================
        # 🛑 RISK CONTROL（新）
        # ======================

        # ======================
        # ❌ RR 太低唔玩
        # ======================
        if d["rr"] < 1.5:
            continue
            
        # ======================
        # ❌ 止損太遠（輸太多）
        # ======================
        if (d["price"] - d["exec_stop"]) / d["price"] > 0.05:
            continue
        
        # ==========================
        # ❌ 開市頭30分鐘唔玩（精準版）
         # =========================
        now_utc = time.gmtime()
        hour = now_utc.tm_hour
        minute = now_utc.tm_min

        # =======================
        # 13:30 - 14:00 UTC（美股開市亂流）
        # =======================
        if hour == 13 and minute >= 30:
            continue
            
        # ======================
        # 🔴 市場過濾
        # ======================
        if not allow_trade and ("ENTRY" in sig or "PULLBACK" in sig or "RETEST" in sig):
             continue

        # ======================
        # ⭐ 分數過濾
        # ======================
        if not allow_trade:
            score -= 2
        
        if score < 2.8:
            continue
            
        candidates.append((s, d, score, sig, news, senti_text, volume_spike))

        # ======================
        # ⚠️ 預警：接近入場區（新）
        # ======================
        zone_low = d["exec_entry_low"]
        zone_high = d["exec_entry_high"]
        
        if zone_low <= d["price"] <= zone_high:
            distance_entry = 0
        else:
            distance_entry = min(
                abs(d["price"] - zone_low),
                abs(d["price"] - zone_high)
            ) / ((zone_high + zone_low) / 2)
        

        if distance_entry < 0.01:
            if now - last_alert.get(s+"_near",0) > 900:
                send(CHAT_ID, f"""⚠️【接近入場】

📈 {s}
💰 價格：{round(d['price'],2)}

🎯 入場區：
{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

📊 距離入場：{round(distance_entry*100,2)}%
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
        # 🟢 ENTRY ALERT（升級）
        # ======================
        
        current_open = sum(1 for t in trade_log.values() if t["status"] == "OPEN")

        if current_open >= 3:
            continue

        if now - last_alert.get(s+"_entry",0) < 900:
            continue
        
        lock_time = last_alert.get(s+"_entry_lock", 0)

        if time.time() - lock_time < 1800:
            continue   
            
        if s in trade_log and trade_log[s]["status"] == "OPEN":
            continue    
        
        mid = (d["exec_entry_low"] + d["exec_entry_high"]) / 2

        if abs(d["price"] - mid) / mid > 0.01:
            continue
            
        if (
            any(x in sig for x in ["PULLBACK", "RETEST"])
            and sentiment != "NEGATIVE"
            and d["rsi"] < 65
        ):
                    
            trade_log[s] = {
                "entry": d["price"],
                "target": d["exec_target"],
                "stop": d["exec_stop"],
                "time": time.time(),
                "signal": sig,
                "status": "OPEN",
                "size": size,
                "risk": d["price"] - d["exec_stop"]
            }
             
            last_alert[s+"_entry_lock"] = time.time()
                    
            if len(trade_log) > 200:
                oldest = min(trade_log, key=lambda k: trade_log[k]["time"])
                del trade_log[oldest]
            
            send(CHAT_ID, f"""🟢【ENTRY｜入場】

📈 {s}
💰 價格：{round(d['price'],2)}

📊 距離入場：{round(distance_entry*100,2)}%
━━━━━━━━━━━━━━
🎯 入場區：
{round(d['exec_entry_low'],2)} - {round(d['exec_entry_high'],2)}

🛑 止損：
{round(d['exec_stop'],2)}

🎯 目標：
{round(d['exec_target'],2)}
━━━━━━━━━━━━━━

📊 RR：{round(d['rr'],2)}

🧠 情緒：
{senti_text}

📰 新聞：
{news}

━━━━━━━━━━
""")
            last_alert[s+"_entry"] = now
                

        
        # ======================
        # 🔴 RISK ALERT
        # ======================
        if "RISK" in sig:
            if now - last_alert.get(s+"_risk",0) > 1800:
                send(CHAT_ID, f"🔴 RISK｜風險 {s}")
            
                last_alert[s+"_risk"] = now

            # ======================
            # 🧠 TRACK RESULT（勝率追蹤）
            # ======================
    for symbol, t in trade_log.items():
            
        if t["status"] in ["WIN","LOSS","TIMEOUT"]:
            last_alert[symbol+"_entry_lock"] = 0
            continue
            
        if t["status"] != "OPEN":
            continue

            # ⛑️ 防卡死
        timeout = 7200 if t["entry"] < 200 else 10800
            
        if time.time() - t["time"] > timeout:
            t["status"] = "TIMEOUT"
            last_alert[symbol+"_entry_lock"] = 0
            continue
            
        df_check = get_df(symbol, "5m")
        if df_check is None:
            continue

        price = df_check["Close"].iloc[-1]

        # ======================
        # 🧠 TRAILING STOP
        # ======================
        risk = t["risk"]

        old_stop = t["stop"]
        
        if not t.get("trail_started") and price > t["entry"] + 2*risk:
            t["trail_started"] = True

        if t.get("trail_started"):
            new_stop = price - risk
            if new_stop > t["stop"]:
                t["stop"] = new_stop
        
        # break-even
        if not t.get("be_done") and price > t["entry"] + risk:
            t["stop"] = t["entry"]
            t["be_done"] = True

        # trail profit（只可以向上）
        new_stop = price - risk

        if price >= t["target"]:
            t["status"] = "WIN"
            last_alert[symbol+"_entry_lock"] = 0
            
        elif price <= t["stop"]:
            t["status"] = "LOSS" 
            last_alert[symbol+"_entry_lock"] = 0
            
        d_check = calc(df_check)
        if d_check:
            t["rsi"] = d_check["rsi"]
            
        if t["stop"] != old_stop:
            send(CHAT_ID, f"""🔄【STOP UPDATED】

📈 {symbol}
🛑 新止損：{round(t["stop"],2)}
""")
            
            
            # ======================
            # 🚀 TOP SIGNAL（升級UI）
            # ======================
    if candidates:
        s, d, score, sig, news, senti_text, volume_spike = sorted(
        candidates, key=lambda x: x[2], reverse=True
        )[0]

        vol_tag = "🔥 Volume爆發" if volume_spike else ""
        zone_tag = "📍 Zone" if "PULLBACK" in sig or "RETEST" in sig else ""
        tags = " ".join(filter(None, [vol_tag, zone_tag]))
        
        if now - last_alert.get(s,0) > 600:
            send(CHAT_ID, f"""🚀【TOP SIGNAL｜最強機會】

📈 {s}
💰 價格：{round(d['price'],2)}
📊 RR：{round(d['rr'],2)}

👉 信號：
{sig} {tags}
━━━━━━━━━━━━━━

🎯 入場區：
{round(d['exec_entry_low'],2)} - 
{round(d['exec_entry_high'],2)}

🛑 止損：
{round(d['exec_stop'],2)}

🎯 目標：
{round(d['exec_target'],2)}
━━━━━━━━━━━━━━

⭐ Score：{round(score,1)}

🌍 市場：
{market_msg}

🧠 情緒：
{senti_text}

📰 新聞：
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
        send(chat_id,"🚀 Bot Ready｜已啟動")

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
