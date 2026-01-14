#!/usr/bin/env python3
"""News scraper that fetches articles and sends them to Ollama for summarization."""

import asyncio
import hashlib
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import aiohttp
import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

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

# Category definitions with keywords and source hints
CATEGORIES = {
    "Motorsport": {
        "keywords": ["f1", "formula 1", "racing", "driver", "lap", "podium", "qualifying", 
                     "grand prix", "verstappen", "hamilton", "ferrari", "mclaren", "red bull racing",
                     "pit stop", "championship", "fia", "motorsport"],
        "sources": ["The Race", "Motorsport F1", "Racefans"]
    },
    "Tech": {
        "keywords": ["ai", "artificial intelligence", "software", "startup", "chip", "processor",
                     "google", "microsoft", "amazon", "cloud", "developer", "programming", "tech",
                     "nvidia", "amd", "intel", "semiconductor"],
        "sources": ["The Verge", "Ars Technica", "WCCF Tech", "Slashdot"]
    },
    "Gaming": {
        "keywords": ["game", "ps5", "xbox", "steam", "nintendo", "playstation", "gaming",
                     "esports", "gamer", "rpg", "fps", "mmo", "release date", "trailer"],
        "sources": ["PC Gamer", "IGN"]
    },
    "Security": {
        "keywords": ["hack", "breach", "malware", "ransomware", "cve", "vulnerability",
                     "cybersecurity", "phishing", "exploit", "zero-day", "patch", "security"],
        "sources": ["Bleeping Computer"]
    },
    "Apple": {
        "keywords": ["iphone", "mac", "ios", "macos", "apple", "ipad", "airpods", "watchos",
                     "macbook", "imac", "apple watch", "app store", "tim cook"],
        "sources": ["Macrumors", "9to5 Mac"]
    },
    "Hardware": {
        "keywords": ["gpu", "graphics card", "rtx", "radeon", "geforce", "benchmark",
                     "overclock", "motherboard", "ram", "ssd", "cpu cooler"],
        "sources": ["Videocardz"]
    }
}

# Summarization prompts for different styles
SUMMARY_PROMPTS = {
    "brief": """Summarize this news article in 1-2 sentences. Be extremely concise - capture only the single most important point.

Title: {title}

Content: {content}

One-line summary:""",
    
    "standard": """Summarize the following news article in 4-5 concise sentences. Focus on the key facts and main points.

Title: {title}

Content: {content}

Summary:""",
    
    "detailed": """Provide a comprehensive summary of this news article in 6-8 sentences. Include:
- The main news/announcement
- Key supporting details and context
- Why this matters or potential implications

Title: {title}

Content: {content}

Detailed summary:""",
    
    "bullets": """Summarize this news article as 3-5 bullet points. Each bullet should be a complete, standalone fact. Use "•" as the bullet character.

Title: {title}

Content: {content}

Key points:"""
}


def load_config() -> dict[str, Any]:
    """Load configuration from YAML file."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, FileNotFoundError) as e:
        logger.error(f"Failed to load config: {e}")
        raise


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def is_ollama_available(config: dict) -> bool:
    """Check if Ollama server is reachable and ready."""
    llm_config = config.get('llm', {})
    if not llm_config:
        return False
    url = f"http://{llm_config['host']}:{llm_config['port']}/api/tags"
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def init_database() -> None:
    """Initialize SQLite database with schema."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                content TEXT,
                summary TEXT,
                category TEXT,
                duplicate_of TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                summarized_at TIMESTAMP,
                FOREIGN KEY (duplicate_of) REFERENCES articles(id)
            )
        ''')
        
        # Add new columns if they don't exist (for existing databases)
        try:
            cursor.execute("ALTER TABLE articles ADD COLUMN category TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute("ALTER TABLE articles ADD COLUMN duplicate_of TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        conn.commit()
    logger.info("Database initialized")


def get_article_id(url: str) -> str:
    """Generate unique ID for an article based on URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def article_exists(article_id: str) -> bool:
    """Check if article already exists in database."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,))
        return cursor.fetchone() is not None


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity ratio between two texts."""
    if not text1 or not text2:
        return 0.0
    # Use first 500 chars for faster comparison
    return SequenceMatcher(None, text1[:500].lower(), text2[:500].lower()).ratio()


def find_similar_article(title: str, content: str, threshold: float = 0.85) -> str | None:
    """
    Find an existing article that is similar to the given title/content.
    Returns the ID of the similar article if found, None otherwise.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        # Only check recent articles (last 3 days) for performance
        cursor.execute("""
            SELECT id, title, content FROM articles 
            WHERE created_at > datetime('now', '-3 days')
            AND duplicate_of IS NULL
        """)
        
        for row in cursor.fetchall():
            # Check title similarity first (faster)
            title_sim = calculate_similarity(title, row['title'])
            if title_sim > threshold:
                logger.info(f"Duplicate detected (title similarity: {title_sim:.2f}): {title[:50]}")
                return row['id']
            
            # If titles are somewhat similar, check content
            if title_sim > 0.5 and content and row['content']:
                content_sim = calculate_similarity(content, row['content'])
                if content_sim > threshold:
                    logger.info(f"Duplicate detected (content similarity: {content_sim:.2f}): {title[:50]}")
                    return row['id']
    
    return None


def categorize_article(title: str, content: str, source: str) -> str:
    """
    Categorize an article based on keywords and source.
    Returns the category name or "General" if no match.
    """
    text = f"{title} {content}".lower()
    
    # First, check if source has a default category
    for category, config in CATEGORIES.items():
        if source in config["sources"]:
            return category
    
    # Then check keywords
    best_match = "General"
    best_score = 0
    
    for category, config in CATEGORIES.items():
        score = sum(1 for keyword in config["keywords"] if keyword in text)
        if score > best_score:
            best_score = score
            best_match = category
    
    return best_match if best_score >= 2 else "General"


def save_article(source: str, title: str, url: str, content: str) -> str | None:
    """Save article to database with deduplication and categorization."""
    article_id = get_article_id(url)
    
    if article_exists(article_id):
        logger.debug(f"Article already exists: {title[:50]}...")
        return None
    
    # Check for duplicates
    duplicate_of = find_similar_article(title, content)
    if duplicate_of:
        logger.info(f"Skipping duplicate article: {title[:50]}...")
        return None
    
    # Categorize the article
    category = categorize_article(title, content, source)
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO articles (id, source, title, url, content, category, duplicate_of) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (article_id, source, title, url, content, category, duplicate_of)
        )
        conn.commit()
    
    logger.info(f"Saved new article [{category}]: {title[:50]}...")
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
    except requests.RequestException as e:
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
    except requests.RequestException as e:
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
    except requests.RequestException as e:
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
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"Wayback Machine failed: {e}")
    
    # Fallback: return whatever we got from direct fetch
    logger.warning(f"All bypass methods failed for {url[:50]}")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return extract_text(response.text)
    except requests.RequestException:
        return None


async def fetch_url_async(session: aiohttp.ClientSession, url: str, headers: dict) -> str | None:
    """Async fetch a single URL."""
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status == 200:
                return await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.debug(f"Async fetch failed for {url[:50]}: {e}")
    return None


async def fetch_rss_feed_async(session: aiohttp.ClientSession, source: dict, semaphore: asyncio.Semaphore) -> list[dict]:
    """Fetch articles from RSS feed asynchronously."""
    articles = []
    async with semaphore:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            html = await fetch_url_async(session, source['url'], headers)
            if not html:
                return articles
            
            feed = feedparser.parse(html)
            for entry in feed.entries[:10]:
                title = entry.get('title', 'No title')
                url = entry.get('link', '')
                
                # Get content from RSS (we'll do full fetch synchronously for paywall bypass)
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


async def fetch_hackernews_async(session: aiohttp.ClientSession, source: dict, semaphore: asyncio.Semaphore) -> list[dict]:
    """Fetch top stories from Hacker News asynchronously."""
    articles = []
    async with semaphore:
        try:
            async with session.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    return articles
                story_ids = (await response.json())[:15]
            
            # Fetch story details in parallel
            story_tasks = []
            for story_id in story_ids:
                story_tasks.append(
                    session.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
                )
            
            responses = await asyncio.gather(*story_tasks, return_exceptions=True)
            
            for resp in responses:
                if isinstance(resp, Exception):
                    continue
                try:
                    story = await resp.json()
                    if story and story.get('type') == 'story':
                        title = story.get('title', 'No title')
                        url = story.get('url', f"https://news.ycombinator.com/item?id={story.get('id')}")
                        content = f"Title: {title}. Points: {story.get('score', 0)}. Comments: {story.get('descendants', 0)}."
                        
                        articles.append({
                            'source': source['name'],
                            'title': title,
                            'url': url,
                            'content': content[:5000]
                        })
                except (aiohttp.ClientError, ValueError):
                    continue
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Error fetching Hacker News: {e}")
    
    return articles


async def fetch_all_sources_async(sources: list[dict]) -> list[dict]:
    """Fetch all sources in parallel using async."""
    all_articles = []
    semaphore = asyncio.Semaphore(5)  # Limit concurrent requests
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for source in sources:
            if not source.get('enabled', True):
                continue
            
            # Handle string "true"/"false" from YAML
            enabled = source.get('enabled', True)
            if isinstance(enabled, str):
                enabled = enabled.lower() == 'true'
            if not enabled:
                continue
            
            logger.info(f"Queuing fetch for {source['name']}...")
            
            if source['type'] == 'rss':
                tasks.append(fetch_rss_feed_async(session, source, semaphore))
            elif source['type'] == 'hackernews':
                tasks.append(fetch_hackernews_async(session, source, semaphore))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Fetch task failed: {result}")
            elif isinstance(result, list):
                all_articles.extend(result)
    
    return all_articles


def summarize_with_ollama(article: dict, config: dict) -> str | None:
    """Send article to Ollama for summarization."""
    llm_config = config.get('llm', {})
    if not llm_config:
        return None
    
    url = f"http://{llm_config['host']}:{llm_config['port']}/api/generate"
    
    # Get summary style from config, default to standard
    style = llm_config.get('summary_style', 'standard')
    if style not in SUMMARY_PROMPTS:
        style = 'standard'
    
    prompt = SUMMARY_PROMPTS[style].format(
        title=article['title'],
        content=article['content'][:3000]
    )
    
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
    except requests.RequestException as e:
        logger.error(f"Error calling Ollama: {e}")
        return None


def update_summary(article_id: str, summary: str) -> None:
    """Update article with summary."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE articles SET summary = ?, summarized_at = ? WHERE id = ?",
            (summary, datetime.now().isoformat(), article_id)
        )
        conn.commit()


def cleanup_old_articles(retention_days: int) -> None:
    """Remove articles older than retention period."""
    with get_db() as conn:
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        cursor.execute("DELETE FROM articles WHERE created_at < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} old articles")


def retry_failed_summaries(config: dict, limit: int = 10) -> None:
    """Retry summarization for articles that don't have summaries."""
    if not is_ollama_available(config):
        logger.info("Ollama not available - skipping retry of failed summaries")
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, content FROM articles WHERE summary IS NULL AND duplicate_of IS NULL LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
    
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


def run_scrape_cycle(config: dict) -> None:
    """Run one complete scrape and summarize cycle."""
    start_time = time.time()
    logger.info("Starting scrape cycle...")
    
    # Fetch articles from all sources asynchronously
    all_articles = asyncio.run(fetch_all_sources_async(config['sources']))
    
    fetch_time = time.time() - start_time
    logger.info(f"Fetched {len(all_articles)} articles in {fetch_time:.1f}s (async)")
    
    # Try to fetch full article content for articles with short content
    for article in all_articles:
        if article['content'] and len(article['content']) < 500 and article['url']:
            full_content = fetch_article_content(article['url'])
            if full_content and len(full_content) > len(article['content']):
                article['content'] = full_content
    
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
    
    total_time = time.time() - start_time
    logger.info(f"Cycle complete. {new_count} new articles processed in {total_time:.1f}s.")


def main() -> None:
    """Main entry point."""
    import schedule
    
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