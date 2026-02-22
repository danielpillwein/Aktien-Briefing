# 📈 Aktien-Briefing

> Your personal AI-powered stock market briefing agent that delivers daily portfolio insights straight to your Telegram 🚀

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)](https://python.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1--mini-412991?logo=openai&logoColor=white)](https://openai.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 🎯 What is this?

**Aktien-Briefing** is an intelligent stock market assistant that wakes up every morning, fetches the latest news about your portfolio, analyzes sentiment using AI, and sends you a beautiful briefing via Telegram. No more endless scrolling through financial news – get the insights that actually matter! 💡

This project showcases:
- 🧠 **AI-powered news analysis** with OpenAI GPT-4.1-mini
- ⚡ **Async processing** for blazing-fast parallel execution
- 🐳 **Docker-ready** deployment for production use
- 📱 **Telegram integration** for instant mobile notifications
- 🗃️ **Smart caching** to save API costs and speed things up

---

## ✨ Features

### 📊 Portfolio & Watchlist Tracking
Track your own stocks plus a separate watchlist. Get daily price changes with visual indicators (🟢 up / 🔴 down / 🟡 sideways).

### 📰 Multi-Source News Aggregation
Pulls news from multiple RSS feeds in parallel:
- Google News
- Yahoo Finance
- Bing News

### 🤖 Two-Step AI Analysis
Each article goes through a smart pipeline:
1. **Summarization** – GPT creates a concise summary
2. **Sentiment Analysis** – Classifies as positive/neutral/negative

### 🌍 AI Market Overview
Get a macro market analysis plus a personalized portfolio assessment with an actionable conclusion.

### 📲 Telegram Notifications
Receives beautifully formatted briefings with:
- Portfolio & Watchlist prices
- News summaries with sentiment indicators
- Direct links to source articles
- Daily auto-cleanup of old messages

### ⏰ Scheduled Execution
Runs automatically every day at your configured time. Set it and forget it!

### 🗄️ Archiving & Logging
- Daily briefings are archived as JSONL files
- Rotating log files with 7-day retention
- Optional compression of old archives

---

## 🏗️ Project Structure

```
Aktien-Briefing/
├── main.py              # Entry point (scheduler or test mode)
├── config/
│   ├── settings.yaml    # Portfolio, watchlist, schedules
│   └── prompts/         # AI prompt templates
├── core/
│   ├── briefing_agent.py    # Main orchestration logic
│   ├── async_ai.py          # OpenAI integration
│   ├── fetch_news.py        # RSS news fetching
│   ├── fetch_prices.py      # Stock price retrieval
│   └── market_overview.py   # AI market analysis
├── utils/
│   ├── notifications.py     # Telegram messaging
│   ├── cache.py             # Response caching
│   └── archive_manager.py   # Briefing archival
├── templates/
│   └── briefing.md.j2       # Report template
├── Dockerfile
└── docker-compose.yml
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+ 
- OpenAI API key
- Telegram Bot Token & Chat ID

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/Aktien-Briefing.git
cd Aktien-Briefing
```

### 2. Create your `.env` file

Create a `.env` file in the project root with the following structure:

```env
# OpenAI API Configuration
OPENAI_API_KEY=sk-your-openai-api-key-here

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=your_chat_id_here
```

> 💡 **Pro tip:** You can get your `TELEGRAM_CHAT_ID` by messaging your bot and checking `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`

### 3. Configure your portfolio

Edit `config/settings.yaml` to add your stocks:

```yaml
portfolio:
  - ticker: "AAPL"
    name: "Apple Inc."
  - ticker: "GOOG"
    name: "Alphabet Inc."

watchlist:
  - ticker: "NVDA"
    name: "NVIDIA Corporation"

scheduler:
  time: "07:00"
  timezone: "Europe/Vienna"
  day_of_week: "tue-sat"
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Run it!

**Test mode** (runs immediately):
```bash
python main.py --test
```

**Scheduler mode** (waits for configured time):
```bash
python main.py
```

---

## 🐳 Docker Deployment

The easiest way to run this in production:

```bash
docker-compose up -d --build
```

The container will:
- Automatically restart unless stopped
- Persist cache, data, outputs, archives, and logs via volumes
- Load your `.env` file automatically

---

## 🔧 Configuration

### `config/settings.yaml`

| Section | Description |
|---------|-------------|
| `portfolio` | Your main stock holdings (ticker + company name) |
| `watchlist` | Stocks you're watching but don't own |
| `scheduler` | When to run (`time`, `timezone`, `day_of_week`) |
| `performance` | Caching, retries, concurrency settings |
| `archive` | Archiving behavior and retention |

### Customizing AI Prompts

All AI prompts are stored in `config/prompts/` as `.txt` files:
- `summary.txt` – Article summarization prompt
- `sentiment.txt` – Sentiment classification prompt
- `market_overview.txt` – Market analysis prompt
- `system_analyst.txt` – System analyst persona

Feel free to tweak them for different languages or analysis styles! 🎨

---

## 📝 Example Output

Here's what a Telegram briefing looks like:

```
📈 Portfolio (2024-01-15)
GOOG: +1.23% 🟢
MSFT: -0.45% 🔴
AAPL: +0.12% 🟡

📰 Portfolio-News
Alphabet Inc.:
- Google announces new AI features for Cloud platform
  (Positiv 🟢) Read more

🌍 Marktanalyse
Macro: Markets remain bullish on tech sector...
Portfolio: Your holdings are well-positioned...
Fazit: 🟢 Overall positive outlook
```

---

## 🤝 Contributing

PRs are welcome! Feel free to:
- 🐛 Report bugs
- 💡 Suggest features
- 🔧 Submit pull requests
