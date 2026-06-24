"""
Crypto Price Alert Bot
Monitors cryptocurrency prices via CoinGecko and sends Telegram alerts.
Features: price alerts, price command, top coins, 24h change tracking, admin controls.
"""
import os
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

ADMIN_IDS = [x.strip() for x in os.getenv("ADMIN_CHAT_ID", "").split(",") if x.strip()]
ALERTS_FILE = os.path.join(DATA_DIR, "price_alerts.json")
COIN_CACHE_FILE = os.path.join(DATA_DIR, "coin_cache.json")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))  # seconds
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "15"))
COINGECKO_API = os.getenv("COINGECKO_API", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# In-memory state
coin_cache: Dict[str, Any] = {}
alerts_db: Dict[str, List[Dict[str, Any]]] = {}
last_alerted: Dict[str, Dict[str, float]] = {}


def load_json(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")
            return default
    return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_admin(chat_id: Any) -> bool:
    if not ADMIN_IDS:
        return True
    return str(chat_id) in ADMIN_IDS


def to_chat_id(value: Any) -> Any:
    try:
        return int(value)
    except Exception:
        return value


def load_state() -> None:
    global alerts_db, last_alerted
    alerts_db = load_json(ALERTS_FILE, {})
    last_alerted = load_json(os.path.join(DATA_DIR, "last_alerted.json"), {})
    coin_cache.update(load_json(COIN_CACHE_FILE, {}))


def save_alerts() -> None:
    save_json(ALERTS_FILE, alerts_db)


def save_last_alerted() -> None:
    save_json(os.path.join(DATA_DIR, "last_alerted.json"), last_alerted)


coingecko_headers = {}
if COINGECKO_API_KEY:
    coingecko_headers["x-cg-demo-api-key"] = COINGECKO_API_KEY


async def fetch_coingecko(endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
    url = f"{COINGECKO_API}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url, params=params, headers=coingecko_headers)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"CoinGecko error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"CoinGecko request failed: {e}")
    return None


async def refresh_coin_cache() -> None:
    """Cache top 250 coins list for symbol/id lookup."""
    data = await fetch_coingecko("/coins/list")
    if data:
        for coin in data:
            coin_cache[coin["symbol"].lower()] = coin["id"]
        save_json(COIN_CACHE_FILE, coin_cache)
        logger.info(f"Coin cache refreshed: {len(coin_cache)} symbols")


def resolve_coin_id(query: str) -> Optional[str]:
    q = query.lower().strip()
    # direct id
    if q in coin_cache.values():
        return q
    # by symbol
    if q in coin_cache:
        return coin_cache[q]
    # search exact name match
    for symbol, cid in coin_cache.items():
        if symbol == q or cid == q:
            return cid
    return None


async def get_price(coin_id: str) -> Optional[Dict[str, Any]]:
    data = await fetch_coingecko(
        f"/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
        },
    )
    if not data or "market_data" not in data:
        return None
    md = data["market_data"]
    return {
        "id": data["id"],
        "symbol": data["symbol"].upper(),
        "name": data["name"],
        "price_usd": md["current_price"].get("usd"),
        "price_btc": md["current_price"].get("btc"),
        "change_24h": md["price_change_percentage_24h"],
        "change_7d": md["price_change_percentage_7d"],
        "market_cap": md["market_cap"].get("usd"),
        "volume_24h": md["total_volume"].get("usd"),
        "ath": md["ath"].get("usd"),
        "ath_change": md["ath_change_percentage"].get("usd"),
        "last_updated": data.get("last_updated", ""),
    }


async def get_simple_prices(ids: List[str]) -> Dict[str, Any]:
    if not ids:
        return {}
    data = await fetch_coingecko(
        "/simple/price",
        params={
            "ids": ",".join(ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        },
    )
    return data or {}


# =============================
# Telegram Commands
# =============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    alerts = alerts_db.get(str(chat_id), [])
    text = (
        f"👋 Welcome to Crypto Price Alert Bot!\n\n"
        f"📊 Active alerts: {len(alerts)}\n\n"
        f"🛠 Commands:\n"
        f"/price <coin> - Get current price (e.g. /price btc)\n"
        f"/alert <coin> <condition> <price> - Set price alert (e.g. /alert btc above 70000)\n"
        f"/alerts - List your active alerts\n"
        f"/remove <number> - Remove alert by number\n"
        f"/top - Show top 10 coins\n"
        f"/trending - Show trending coins"
    )
    await update.message.reply_text(text)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /price <coin>\nExample: /price bitcoin")
        return
    query = " ".join(context.args)
    coin_id = resolve_coin_id(query)
    if not coin_id:
        await update.message.reply_text(f"❌ Could not find coin: {query}")
        return
    info = await get_price(coin_id)
    if not info:
        await update.message.reply_text("❌ Failed to fetch price. Try again later.")
        return

    price = info["price_usd"]
    ch24 = info["change_24h"] or 0
    ch7d = info["change_7d"] or 0
    emoji_24 = "🟢" if ch24 >= 0 else "🔴"
    emoji_7d = "🟢" if ch7d >= 0 else "🔴"

    text = (
        f"💰 <b>{info['name']} ({info['symbol']})</b>\n"
        f"Price: <b>${price:,.4f}</b>\n"
        f"24h: {emoji_24} {ch24:+.2f}%\n"
        f"7d: {emoji_7d} {ch7d:+.2f}%\n"
        f"Market Cap: ${info['market_cap']:,.0f}\n"
        f"24h Volume: ${info['volume_24h']:,.0f}\n"
        f"ATH: ${info['ath']:,.4f} ({info['ath_change']:+.2f}%)"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ Usage: /alert <coin> <above|below> <price>\nExample: /alert btc above 70000"
        )
        return
    coin_query = context.args[0]
    condition = context.args[1].lower()
    try:
        target = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Price must be a number.")
        return
    if condition not in ("above", "below"):
        await update.message.reply_text("❌ Condition must be 'above' or 'below'.")
        return
    coin_id = resolve_coin_id(coin_query)
    if not coin_id:
        await update.message.reply_text(f"❌ Could not find coin: {coin_query}")
        return
    info = await get_price(coin_id)
    if not info:
        await update.message.reply_text("❌ Failed to validate coin price.")
        return

    key = str(chat_id)
    alerts_db.setdefault(key, [])
    alert = {
        "coin_id": coin_id,
        "symbol": info["symbol"],
        "name": info["name"],
        "condition": condition,
        "target": target,
        "created_at": datetime.utcnow().isoformat(),
    }
    alerts_db[key].append(alert)
    save_alerts()
    await update.message.reply_text(
        f"✅ Alert set for <b>{info['name']}</b> {condition} <b>${target:,.4f}</b>.",
        parse_mode="HTML",
    )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    key = str(chat_id)
    alerts = alerts_db.get(key, [])
    if not alerts:
        await update.message.reply_text("📭 No active alerts.")
        return
    lines = []
    for i, a in enumerate(alerts, 1):
        lines.append(
            f"{i}. <b>{a['name']}</b> ({a['symbol']}) - {a['condition']} ${a['target']:,.4f}"
        )
    text = "📋 <b>Active Alerts:</b>\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /remove <alert_number>")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number.")
        return
    key = str(chat_id)
    alerts = alerts_db.get(key, [])
    if idx < 0 or idx >= len(alerts):
        await update.message.reply_text("❌ Alert number not found.")
        return
    removed = alerts.pop(idx)
    save_alerts()
    await update.message.reply_text(
        f"✅ Removed alert for {removed['name']} {removed['condition']} ${removed['target']}."
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    data = await fetch_coingecko(
        "/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": "10",
            "page": "1",
            "sparkline": "false",
            "price_change_percentage": "24h",
        },
    )
    if not data:
        await update.message.reply_text("❌ Failed to fetch top coins.")
        return
    lines = ["🏆 <b>Top 10 Coins:</b>\n"]
    for i, c in enumerate(data, 1):
        ch = c.get("price_change_percentage_24h") or 0
        emoji = "🟢" if ch >= 0 else "🔴"
        lines.append(
            f"{i}. <b>{c['name']}</b> ({c['symbol'].upper()})\n"
            f"   ${c['current_price']:,.4f} | {emoji} {ch:+.2f}% | Cap: ${c.get('market_cap', 0):,.0f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    data = await fetch_coingecko("/search/trending")
    if not data or "coins" not in data:
        await update.message.reply_text("❌ Failed to fetch trending coins.")
        return
    lines = ["🔥 <b>Trending Coins:</b>\n"]
    for i, item in enumerate(data["coins"][:10], 1):
        c = item["item"]
        lines.append(f"{i}. <b>{c['name']}</b> ({c['symbol']}) - Rank #{c['market_cap_rank']}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# =============================
# Background Monitoring
# =============================

async def check_alerts(app: Application) -> None:
    while True:
        try:
            all_coin_ids = set()
            for alerts in alerts_db.values():
                for a in alerts:
                    all_coin_ids.add(a["coin_id"])
            if not all_coin_ids:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            prices = await get_simple_prices(list(all_coin_ids))
            if not prices:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for chat_key, alerts in list(alerts_db.items()):
                chat_id = to_chat_id(chat_key)
                triggered: List[int] = []
                for idx, alert in enumerate(alerts):
                    coin_id = alert["coin_id"]
                    if coin_id not in prices:
                        continue
                    current = prices[coin_id].get("usd")
                    if current is None:
                        continue
                    condition = alert["condition"]
                    target = alert["target"]
                    state_key = f"{chat_key}:{coin_id}:{condition}:{target}"
                    last = last_alerted.get(state_key, {}).get("price")

                    fired = False
                    if condition == "above" and current >= target:
                        if last is None or last < target:
                            fired = True
                    elif condition == "below" and current <= target:
                        if last is None or last > target:
                            fired = True

                    if fired:
                        ch = prices[coin_id].get("usd_24h_change", 0) or 0
                        emoji = "🟢" if ch >= 0 else "🔴"
                        text = (
                            f"🚨 <b>Price Alert!</b>\n\n"
                            f"<b>{alert['name']} ({alert['symbol']})</b> is now {condition} "
                            f"<b>${target:,.4f}</b>\n"
                            f"Current price: <b>${current:,.4f}</b>\n"
                            f"24h change: {emoji} {ch:+.2f}%"
                        )
                        try:
                            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                        except Exception as e:
                            logger.warning(f"Alert send failed for {chat_id}: {e}")
                        last_alerted[state_key] = {"price": current, "time": datetime.utcnow().isoformat()}
                        triggered.append(idx)
                if triggered:
                    save_last_alerted()
        except Exception as e:
            logger.error(f"Alert checker error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


async def post_init(application: Application) -> None:
    asyncio.create_task(check_alerts(application))
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("price", "Get current price: /price btc"),
        BotCommand("alert", "Set alert: /alert btc above 70000"),
        BotCommand("alerts", "List your alerts"),
        BotCommand("remove", "Remove alert: /remove 1"),
        BotCommand("top", "Top 10 coins by market cap"),
        BotCommand("trending", "Trending coins"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Price alert bot initialized.")


def main() -> None:
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing!")
        return
    load_state()
    asyncio.run(refresh_coin_cache())

    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", cmd_price))
    application.add_handler(CommandHandler("alert", cmd_alert))
    application.add_handler(CommandHandler("alerts", cmd_alerts))
    application.add_handler(CommandHandler("remove", cmd_remove))
    application.add_handler(CommandHandler("top", cmd_top))
    application.add_handler(CommandHandler("trending", cmd_trending))

    application.run_polling()


if __name__ == "__main__":
    main()
