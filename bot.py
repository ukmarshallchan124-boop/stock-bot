from flask import Flask, request
import requests, os, time, threading
import yfinance as yf
import math

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

SYMBOLS = ["TSLA","NVDA","AMD","XOM","JPM"]

last_alert = {}
cache = {}
CACHE_TTL = 120


# ======================
# DATA（加強穩定）
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

        # 防舊數據
        last_time = df.index[-1].to_pydatetime().timestamp()
        if time.time() - last_time > 900:
            return None

        cache[key] = (df.copy(), now)

        # 防 memory leak
        if len(cache) > 60:
            oldest = min(cache.items(), key=lambda x: x[1][1])[0]
            del cache[oldest]

        return df
    except Exception as e:
        print("DATA ERROR:", e)
        return None


# ======================
# SEND（防空 + 防錯）
# ======================
def send(chat_id, msg):
    if not chat_id or not msg or not msg.strip():
        return
    try:
        requests.post(
            f"{URL}/sendMessage",
            json={"chat_id": chat_id, "text": msg[:4000]},
            timeout=10
        )
    except Exception as e:
        print("SEND ERROR:", e)


# ======================
# CALC（防 crash）
# ======================
def calc(df):
    try:
        price = float(df["Close"].iloc[-1])

        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        gain_ema = gain.ewm(alpha=1/14).mean()
        loss_ema = loss.ewm(alpha=1/14).mean()

        rs = gain_ema / (loss_ema + 1e-10)
        rsi = round((100 - (100 / (1 + rs))).iloc[-1],1)

        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_up = (ema12 - ema26).iloc[-1] > (ema12 - ema26).ewm(span=9).mean().iloc[-1]

        ma20 = df["Close"].rolling(20).mean().iloc[-1]
        trend_up = price > ma20

        high = float(df["High"].max())
        low = float(df["Low"].min())

        entry_low = low * 1.01
        entry_high = low * 1.03
        stop = low * 0.97
        target = high * 1.02

        rr = (target - entry_low) / (entry_low - stop) if entry_low > stop else 0

        return {
            "price": price,
            "rsi": rsi,
            "macd_up": macd_up,
            "trend_up": trend_up,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop": stop,
            "target": target,
            "rr": rr
        }

    except Exception as e:
        print("CALC ERROR:", e)
        return None


# ======================
# COMMAND（保持你原本 UI）
# ======================
def stock_all():
    msg = "📊【市場掃描】\n\n"

    for s in SYMBOLS:
        df = get_df(s,"5m")
        if not df:
            continue

        d = calc(df)
        if not d:
            continue

        zone = "🟡 Watch"
        if d["entry_low"] <= d["price"] <= d["entry_high"]:
            zone = "🟢 Entry Zone"

        msg += f"""📌 {s}
💰 {round(d['price'],2)} ｜ RSI {d['rsi']}
Trend: {"Up" if d['trend_up'] else "Down"}

🎯 Entry: {round(d['entry_low'],2)} - {round(d['entry_high'],2)}
🛑 Stop: {round(d['stop'],2)}
🎯 Target: {round(d['target'],2)}
📊 RR: {round(d['rr'],2)}

{zone}
━━━━━━━━━━━━━━
"""

    return msg


def market():
    df = get_df("SPY","15m")
    if not df:
        return "⚠️ 市場數據錯誤"

    d = calc(df)
    if not d:
        return "⚠️ 市場計算錯誤"

    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma5 = df["Close"].rolling(5).mean().iloc[-1]
    strength = abs(ma5-ma20)/ma20

    if strength < 0.002:
        state = "⚠️ Sideways（唔建議亂入）"
    elif ma5 < ma20:
        state = "🔻 Downtrend（減倉 / 小心）"
    else:
        state = "🟢 Uptrend（可操作）"

    return f"""🌍【市場結構】

📊 趨勢：
MA5 {'>' if ma5>ma20 else '<'} MA20

📈 動能：
RSI {d['rsi']}

🔥 狀態：
{state}

━━━━━━━━━━━━━━
📌 行動策略：
• Uptrend → 做 breakout / pullback
• Downtrend → 減倉 / 保守
• Sideways → 等機會
"""


def gold():
    df = get_df("GLD","60m")
    if not df:
        return "Gold 無數據"

    d = calc(df)
    if not d:
        return "Gold 計算錯誤"

    return f"""🥇【Gold 分析】

📊 RSI：{d['rsi']}

━━━━━━━━━━━━━━
📌 行動策略：

🟢 市場弱 → 可配置（避險）
🟡 市場強 → 不建議重倉
🔴 恐慌 → breakout 才追
"""


def long_term():
    return """📈【長線策略】

👉 S&P500 / MSFT / ETF
👉 每月 DCA
👉 忽略短期波動
"""


# ======================
# SIGNAL ENGINE（修復版🔥）
# ======================
def loop():
    while True:
        try:
            now = time.time()
            candidates = []

            # ===== 市場判斷 =====
            spy = get_df("SPY","15m")
            if spy:
                ma20 = spy["Close"].rolling(20).mean().iloc[-1]
                ma5 = spy["Close"].rolling(5).mean().iloc[-1]

                if ma5 < ma20:
                    if now - last_alert.get("risk",0) > 1800:
                        send(CHAT_ID,"🚨【Risk Off】市場轉弱 → 減倉")
                        last_alert["risk"] = now

            # ===== 掃描 =====
            for s in SYMBOLS:
                df = get_df(s,"5m")
                if not df:
                    continue

                d = calc(df)
                if not d:
                    continue

                recent_high = df["High"].iloc[-15:-3].max()
                recent_low = df["Low"].iloc[-15:-3].min()

                # 🔥 防假 breakout（range filter）
                if (recent_high - recent_low) / d["price"] < 0.01:
                    continue

                breakout = (
                    df["Close"].iloc[-1] > recent_high and
                    df["Close"].iloc[-2] > recent_high and
                    df["Low"].iloc[-1] > recent_high * 0.998
                )

                vol = df["Volume"]
                vol_ma = vol.rolling(10).mean().iloc[-1]

                if math.isnan(vol_ma) or vol_ma == 0:
                    continue

                volume_spike = vol.iloc[-1] > vol_ma * 1.5

                # ===== Setup =====
                if (
                    d["entry_low"]*0.995 < d["price"] < d["entry_high"]*1.005
                    and now - last_alert.get(s+"_setup",0) > 1800
                ):
                    send(CHAT_ID,f"""👀【Setup】{s}

原因：
• 接近入場區
• 動能開始轉強

策略：
👉 等 breakout 確認""")
                    last_alert[s+"_setup"] = now

                # ===== Breakout =====
                if breakout and now - last_alert.get(s+"_bo",0) > 1800:
                    send(CHAT_ID,f"""📢【Breakout】{s}

原因：
• 突破 {round(recent_high,2)}
• 站穩阻力

策略：
👉 可等回踩或追 momentum""")
                    last_alert[s+"_bo"] = now

                # ===== Entry =====
                if (
                    d["entry_low"] <= d["price"] <= d["entry_high"]
                    and breakout
                    and volume_spike
                ):
                    score = d["rr"]*2 + (70-abs(d["rsi"]-60))

                    grade = "C"
                    if score > 10:
                        grade="A"
                    elif score > 7:
                        grade="B"

                    candidates.append((s,d,score,grade))

            # ===== Top Signals（防空訊息）=====
            if candidates:
                top = sorted(candidates,key=lambda x:x[2],reverse=True)[:3]

                lines = []

                for s,d,score,grade in top:
                    if now - last_alert.get(s,0) > 600:
                        lines.append(f"""📈 {s} ｜ Grade {grade}

🎯 Entry {round(d['entry_low'],2)}-{round(d['entry_high'],2)}
🛑 Stop {round(d['stop'],2)}
🎯 Target {round(d['target'],2)}

📊 RR {round(d['rr'],2)}""")

                        last_alert[s]=now

                if lines:
                    send(CHAT_ID,"🚀【Top Signals】\n\n" + "\n\n".join(lines))

            time.sleep(300)

        except Exception as e:
            print("ERROR:",e)
            time.sleep(10)


# ======================
# THREAD（100%可用）
# ======================
def start_background():
    if not getattr(start_background, "started", False):
        threading.Thread(target=loop, daemon=True).start()
        start_background.started = True

start_background()


# ======================
# WEBHOOK（group兼容）
# ======================
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not data or "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if "/start" in text:
        send(chat_id,"🚀 Bot Ready\n/stock /market /gold /long")

    elif "/stock" in text:
        send(chat_id,stock_all())

    elif "/market" in text:
        send(chat_id,market())

    elif "/gold" in text:
        send(chat_id,gold())

    elif "/long" in text:
        send(chat_id,long_term())

    return "ok"


@app.route("/")
def home():
    return "running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
