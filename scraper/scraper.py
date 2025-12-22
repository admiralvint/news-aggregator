#!/usr/bin/env python3
"""News scraper that fetches articles and sends them to Ollama for summarization."""

import feedparser
import requests
from bs4 import BeautifulSoup
import yaml
import sqlite3
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging
import schedule
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "sources.yaml"
DB_PATH = BASE_DIR / "data" / "articles.db"


def load_config():
    """Load configuration from YAML file."""
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


def is_ollama_available(config: dict) -> bool:
    """Check if Ollama server is reachable and ready."""
    llm_config = config['llm']
    url = f"http://{llm_config['host']}:{llm_config['port']}/api/tags"
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except:
        return False


def init_database():
    """Initialize SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            content TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            summarized_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Database initialized")


def get_article_id(url: str) -> str:
    """Generate unique ID for an article based on URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def article_exists(article_id: str) -> bool:
    """Check if article already exists in database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def save_article(source: str, title: str, url: str, content: str):
    """Save article to database."""
    article_id = get_article_id(url)
    if article_exists(article_id):
        logger.debug(f"Article already exists: {title[:50]}...")
        return None
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO articles (id, source, title, url, content) VALUES (?, ?, ?, ?, ?)",
        (article_id, source, title, url, content)
    )
    conn.commit()
    conn.close()
    logger.info(f"Saved new article: {title[:50]}...")
    return article_id


def fetch_article_content(url: str) -> str | None:
    """
    Fetch article content, trying paywall bypass methods if needed.
    Returns the article text or None if all methods fail.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.google.com/',
    }
    
    def extract_text(html: str) -> str | None:
        """Extract readable text from HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'ads']):
            element.decompose()
        paragraphs = soup.find_all('p')
        if paragraphs:
            text = ' '.join(p.get_text().strip() for p in paragraphs[:30])
            if len(text) > 200:
                return text
        return None
    
    def is_paywalled(text: str | None) -> bool:
        """Detect if content appears to be paywalled."""
        if not text or len(text) < 300:
            return True
        paywall_indicators = [
            'subscribe to continue',
            'subscription required',
            'sign in to read',
            'create an account',
            'register to read',
            'members only',
            'premium content',
            'to continue reading',
            'already a subscriber',
        ]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in paywall_indicators)
    
    # Method 1: Direct fetch with Google referrer
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            content = extract_text(response.text)
            if not is_paywalled(content):
                logger.debug(f"Direct fetch successful for {url[:50]}")
                return content
    except Exception as e:
        logger.debug(f"Direct fetch failed: {e}")
    
    # Method 2: Archive.today
    try:
        archive_url = f"https://archive.today/newest/{url}"
        response = requests.get(archive_url, headers=headers, timeout=20, allow_redirects=True)
        if response.status_code == 200 and 'archive.today' in response.url:
            content = extract_text(response.text)
            if content and len(content) > 300:
                logger.info(f"Archive.today bypass successful for {url[:50]}")
                return content
    except Exception as e:
        logger.debug(f"Archive.today failed: {e}")
    
    # Method 3: 12ft.io
    try:
        bypass_url = f"https://12ft.io/{url}"
        response = requests.get(bypass_url, headers=headers, timeout=20)
        if response.status_code == 200:
            content = extract_text(response.text)
            if content and len(content) > 300:
                logger.info(f"12ft.io bypass successful for {url[:50]}")
                return content
    except Exception as e:
        logger.debug(f"12ft.io failed: {e}")
    
    # Method 4: Wayback Machine (for older articles)
    try:
        wayback_api = f"https://archive.org/wayback/available?url={url}"
        response = requests.get(wayback_api, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('archived_snapshots', {}).get('closest', {}).get('available'):
                archive_url = data['archived_snapshots']['closest']['url']
                archive_response = requests.get(archive_url, headers=headers, timeout=15)
                if archive_response.status_code == 200:
                    content = extract_text(archive_response.text)
                    if content and len(content) > 300:
                        logger.info(f"Wayback Machine bypass successful for {url[:50]}")
                        return content
    except Exception as e:
        logger.debug(f"Wayback Machine failed: {e}")
    
    # Fallback: return whatever we got from direct fetch
    logger.warning(f"All bypass methods failed for {url[:50]}")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return extract_text(response.text)
    except:
        return None


def fetch_rss_feed(source: dict) -> list:
    """Fetch articles from RSS feed."""
    articles = []
    try:
        feed = feedparser.parse(source['url'])
        for entry in feed.entries[:10]:
            title = entry.get('title', 'No title')
            url = entry.get('link', '')
            
            # Get content - try full article fetch with paywall bypass
            content = None
            if url:
                content = fetch_article_content(url)
            
            # Fallback to RSS summary if fetch failed
            if not content:
                content = entry.get('summary', entry.get('description', ''))
            
            if title and (content or url):
                articles.append({
                    'source': source['name'],
                    'title': title,
                    'url': url,
                    'content': content[:5000] if content else ''
                })
    except Exception as e:
        logger.error(f"Error fetching RSS feed {source['name']}: {e}")
    
    return articles


def fetch_hackernews(source: dict) -> list:
    """Fetch top stories from Hacker News."""
    articles = []
    try:
        response = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10
        )
        story_ids = response.json()[:15]
        
        for story_id in story_ids:
            story_response = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=10
            )
            story = story_response.json()
            
            if story and story.get('type') == 'story':
                title = story.get('title', 'No title')
                url = story.get('url', f"https://news.ycombinator.com/item?id={story_id}")
                
                # Try to fetch full article content with paywall bypass
                content = None
                if 'url' in story:
                    content = fetch_article_content(url)
                
                # Fallback to basic HN info
                if not content:
                    content = f"Title: {title}. Points: {story.get('score', 0)}. Comments: {story.get('descendants', 0)}."
                
                articles.append({
                    'source': source['name'],
                    'title': title,
                    'url': url,
                    'content': content[:5000]
                })
    except Exception as e:
        logger.error(f"Error fetching Hacker News: {e}")
    
    return articles


def summarize_with_ollama(article: dict, config: dict) -> str:
    """Send article to Ollama for summarization."""
    llm_config = config['llm']
    url = f"http://{llm_config['host']}:{llm_config['port']}/api/generate"
    
    prompt = f"""Summarize the following news article in 4-5 concise sentences. Focus on the key facts and main points.

Title: {article['title']}

Content: {article['content'][:3000]}

Summary:"""

    try:
        response = requests.post(url, json={
            'model': llm_config['model'],
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': 0.2,
                'num_predict': 400
            }
        }, timeout=120)
        
        if response.status_code == 200:
            result = response.json()
            return result.get('response', '').strip()
        else:
            logger.error(f"Ollama error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error calling Ollama: {e}")
        return None


def update_summary(article_id: str, summary: str):
    """Update article with summary."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE articles SET summary = ?, summarized_at = ? WHERE id = ?",
        (summary, datetime.now().isoformat(), article_id)
    )
    conn.commit()
    conn.close()


def cleanup_old_articles(retention_days: int):
    """Remove articles older than retention period."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
    cursor.execute("DELETE FROM articles WHERE created_at < ?", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} old articles")


def retry_failed_summaries(config: dict, limit: int = 10):
    """Retry summarization for articles that don't have summaries."""
    if not is_ollama_available(config):
        logger.info("Ollama not available - skipping retry of failed summaries")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, content FROM articles WHERE summary IS NULL LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return
    
    logger.info(f"Retrying {len(rows)} articles without summaries...")
    
    for row in rows:
        article = {
            'title': row['title'],
            'content': row['content']
        }
        logger.info(f"Retrying: {row['title'][:50]}...")
        summary = summarize_with_ollama(article, config)
        if summary:
            update_summary(row['id'], summary)
            logger.info(f"Summary: {summary[:100]}...")
        time.sleep(2)


def run_scrape_cycle(config: dict):
    """Run one complete scrape and summarize cycle."""
    logger.info("Starting scrape cycle...")
    
    # Fetch articles from all sources
    all_articles = []
    for source in config['sources']:
        if not source.get('enabled', True):
            continue
        
        logger.info(f"Fetching from {source['name']}...")
        
        if source['type'] == 'rss':
            articles = fetch_rss_feed(source)
        elif source['type'] == 'hackernews':
            articles = fetch_hackernews(source)
        else:
            logger.warning(f"Unknown source type: {source['type']}")
            continue
        
        all_articles.extend(articles)
        time.sleep(1)
    
    logger.info(f"Fetched {len(all_articles)} articles total")
    
    # Check if Ollama is available
    ollama_available = is_ollama_available(config)
    if not ollama_available:
        logger.warning("Ollama not available - saving articles without summaries, will retry next cycle")
    
    # Save new articles and summarize
    new_count = 0
    for article in all_articles:
        article_id = save_article(
            article['source'],
            article['title'],
            article['url'],
            article['content']
        )
        
        if article_id:
            new_count += 1
            if ollama_available:
                logger.info(f"Summarizing: {article['title'][:50]}...")
                summary = summarize_with_ollama(article, config)
                if summary:
                    update_summary(article_id, summary)
                    logger.info(f"Summary: {summary[:100]}...")
                time.sleep(2)
    
    # Retry failed summaries and cleanup
    retry_failed_summaries(config)
    cleanup_old_articles(config.get('retention_days', 7))
    
    logger.info(f"Cycle complete. {new_count} new articles processed.")


def main():
    """Main entry point."""
    logger.info("News Aggregator starting...")
    
    # Initialize
    config = load_config()
    init_database()
    
    # Run immediately on start
    run_scrape_cycle(config)
    
    # Schedule periodic runs
    interval = config.get('scrape_interval_minutes', 60)
    schedule.every(interval).minutes.do(run_scrape_cycle, config)
    
    logger.info(f"Scheduled to run every {interval} minutes")
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()