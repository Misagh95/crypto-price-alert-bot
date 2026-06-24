#!/bin/bash
# Usage:
# 1. Create repo on GitHub (e.g. crypto-price-alert-bot)
# 2. Make this script executable: chmod +x push-to-github.sh
# 3. Run: ./push-to-github.sh https://github.com/YOUR_USERNAME/REPO_NAME.git

set -e

REPO_URL="$1"

if [ -z "$REPO_URL" ]; then
  echo "❌ Error: Please provide your GitHub repository URL."
  echo "Example: ./push-to-github.sh https://github.com/john/crypto-price-alert-bot.git"
  exit 1
fi

echo "🚀 Preparing to push files to: $REPO_URL"

# Initialize git if not already
git init

# Add all files in the current directory
git add .

# Commit
git commit -m "Initial commit: 6 crypto telegram bot examples" || true

# Add remote
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"

# Push
git branch -M main
git push -u origin main

echo "✅ Done! Files pushed to GitHub successfully."
