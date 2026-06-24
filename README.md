# Crypto Price Alert Bot

A Telegram bot that monitors cryptocurrency prices via CoinGecko and sends price alerts.

## Features

- `/price <coin>` — Get current price and 24h/7d change
- `/alert <coin> <above|below> <price>` — Set price alerts
- `/alerts` — List active alerts
- `/remove <number>` — Remove an alert
- `/top` — Top 10 coins by market cap
- `/trending` — Trending coins

## Environment Variables

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_CHAT_ID=123456789
DATA_DIR=.
CHECK_INTERVAL=60
HTTP_TIMEOUT=15
COINGECKO_API_KEY=your_key  # Optional, increases rate limits
COINGECKO_API=https://api.coingecko.com/api/v3
```

## Install & Run

```bash
pip install -r requirements.txt
python bot.py
```

## Deploy

This project includes a `Dockerfile` and `render.yaml` for quick deployment on Render.com or any Docker-compatible host.

See the root `DEPLOY.md` for detailed instructions.
