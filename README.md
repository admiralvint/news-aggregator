# 📰 News Aggregator

A self-hosted news aggregator that fetches articles from RSS feeds, automatically categorizes them, and generates AI-powered summaries using [Ollama](https://ollama.ai/).

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ Features

- **Multi-source RSS Aggregation** — Fetch from any RSS/Atom feed (tech news, gaming, motorsport, etc.)
- **Async Parallel Fetching** — Fast concurrent scraping with rate limiting
- **AI Summaries** — Generate article summaries via Ollama LLM (optional)
- **Auto-categorization** — Automatically categorize articles by topic keywords
- **Duplicate Detection** — Content-hash based deduplication
- **Web Interface** — Clean Flask-based UI with filtering by source, category, and date
- **Health Monitoring** — Built-in `/health` endpoint for container monitoring
- **Docker-ready** — Easy deployment with Docker Compose

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.12, Flask |
| Scraping | aiohttp, feedparser, BeautifulSoup4 |
| Database | SQLite |
| Summarization | Ollama (any compatible model) |
| Containerization | Docker, Docker Compose |

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- (Optional) Ollama server for AI summaries

### 1. Clone the repository

```bash
git clone https://github.com/admiralvint/news-aggregator.git
cd news-aggregator
```

### 2. Configure your sources

Edit `config/sources.yaml` to add your preferred news sources:

```yaml
scrape_interval_minutes: 240
retention_days: 7

sources:
  - name: "Ars Technica"
    url: "https://feeds.arstechnica.com/arstechnica/index"
    type: "rss"
    enabled: true

  - name: "The Verge"
    url: "https://www.theverge.com/rss/index.xml"
    type: "rss"
    enabled: true

# Optional: LLM for summaries
llm:
  host: "192.168.1.100"  # Your Ollama server IP
  port: 11434
  model: "llama3"
  summary_style: "standard"  # Options: brief, standard, detailed, bullets
```

### 3. Build and run

```bash
docker compose build
docker compose up -d
```

### 4. Access the web interface

Open **http://localhost:5000** in your browser.

## 📁 Project Structure

```
news-aggregator/
├── config/
│   └── sources.yaml      # News sources & LLM configuration
├── data/
│   └── articles.db       # SQLite database (auto-created)
├── scraper/
│   ├── scraper.py        # Main scraping & summarization logic
│   ├── web.py            # Flask web interface
│   └── requirements.txt  # Python dependencies
├── docker-compose.yml    # Container orchestration
└── Dockerfile            # Container image definition
```

## ⚙️ Configuration

### Source Types

| Type | Description |
|------|-------------|
| `rss` | Standard RSS/Atom feeds |
| `hackernews` | Hacker News API integration |

### Summary Styles

Configure in `sources.yaml` under `llm.summary_style`:

| Style | Description |
|-------|-------------|
| `brief` | 1-2 sentence summary |
| `standard` | 4-5 sentence summary (default) |
| `detailed` | Comprehensive paragraph |
| `bullets` | 3-5 bullet points |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Container timezone |

## 🔧 Running Without Docker

```bash
# Install dependencies
pip install -r scraper/requirements.txt

# Run the scraper (background process)
python scraper/scraper.py &

# Run the web interface
python scraper/web.py
```

## 📡 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web interface with article list |
| `GET /health` | Health check with article stats |

### Query Parameters (Web Interface)

| Parameter | Description |
|-----------|-------------|
| `source` | Filter by source name |
| `category` | Filter by auto-detected category |
| `days` | Show articles from last N days (1, 3, 7, 14, 30) |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

MIT License — feel free to use and modify as needed.
