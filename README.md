# Hourly Economic News Telegram Bot

A 100% free, zero-server Telegram bot that checks economic news hourly using **GitHub Actions**.

## Setup Instructions

1. Push this repository to GitHub.
2. In your GitHub Repository, go to **Settings** > **Secrets and variables** > **Actions**.
3. Add the following repository secrets:
   - `TELEGRAM_BOT_TOKEN`: Token from [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID`: Your chat ID or channel ID
   - `NEWS_URL`: (Optional) The news URL to scrape
4. Go to the **Actions** tab in GitHub and click **Run workflow** to test it manually!

## How it works

The bot runs on GitHub Actions every hour (`cron: '0 * * * *'`) using Python stdlib with 0 external dependencies.
