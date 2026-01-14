#!/usr/bin/env python3
"""Simple web interface for reading news summaries."""

from flask import Flask, render_template_string, request, jsonify
import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

app = Flask(__name__)
DB_PATH = Path(__file__).parent.parent / "data" / "articles.db"


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Digest</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=Source+Sans+3:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            font-family: 'Source Sans 3', -apple-system, BlinkMacSystemFont, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a1a;
            color: #e0d6cc;
        }
        h1 {
            font-family: 'Lora', Georgia, serif;
            color: #d4a574;
            border-bottom: 2px solid #4a3728;
            padding-bottom: 12px;
            font-weight: 500;
            letter-spacing: 0.5px;
        }
        .filters {
            background: #252525;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            border: 1px solid #333;
        }
        .filters form {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
        }
        .filters label {
            color: #a89888;
            font-size: 14px;
        }
        .filters select, .filters button {
            padding: 8px 12px;
            border-radius: 6px;
            border: 1px solid #444;
            font-size: 14px;
            font-family: 'Source Sans 3', sans-serif;
            background: #333;
            color: #e0d6cc;
        }
        .filters select:focus, .filters button:focus {
            outline: none;
            border-color: #d4a574;
        }
        .filters button {
            background: #4a3728;
            color: #e0d6cc;
            border: none;
            cursor: pointer;
            font-weight: 500;
            transition: background 0.2s;
        }
        .filters button:hover {
            background: #5c4633;
        }
        .stats {
            color: #8b7355;
            font-size: 14px;
            margin-bottom: 15px;
        }
        .article {
            background: #252525;
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            border: 1px solid #333;
            transition: border-color 0.2s, transform 0.2s;
        }
        .article:hover {
            border-color: #4a3728;
            transform: translateY(-2px);
        }
        .article h2 {
            font-family: 'Lora', Georgia, serif;
            margin: 0 0 10px 0;
            font-size: 18px;
            font-weight: 500;
            line-height: 1.4;
        }
        .article h2 a {
            color: #e8ddd0;
            text-decoration: none;
            transition: color 0.2s;
        }
        .article h2 a:hover {
            color: #d4a574;
        }
        .meta {
            font-size: 12px;
            color: #7a6a5a;
            margin-bottom: 12px;
        }
        .source {
            background: #3d2e22;
            color: #d4a574;
            padding: 3px 10px;
            border-radius: 4px;
            font-weight: 500;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .category {
            background: #2a3d22;
            color: #a4d474;
            padding: 3px 10px;
            border-radius: 4px;
            font-weight: 500;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-left: 5px;
        }
        .summary {
            font-family: 'Lora', Georgia, serif;
            line-height: 1.7;
            color: #c4b8a8;
            font-size: 15px;
        }
        .no-articles {
            text-align: center;
            padding: 40px;
            color: #6a5a4a;
            font-family: 'Lora', Georgia, serif;
            font-style: italic;
        }
        .refresh-info {
            text-align: center;
            color: #5a4a3a;
            font-size: 12px;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #333;
        }
        .error {
            background: #3d2222;
            border: 1px solid #5c3333;
            color: #d47474;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            margin: 20px 0;
        }
        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #1a1a1a;
        }
        ::-webkit-scrollbar-thumb {
            background: #4a3728;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #5c4633;
        }
    </style>
</head>
<body>
    <h1>📰 News Digest</h1>
    
    {% if error %}
    <div class="error">
        <p>{{ error }}</p>
    </div>
    {% else %}
    <div class="filters">
        <form method="get">
            <label for="source">Source:</label>
            <select name="source" id="source">
                <option value="">All sources</option>
                {% for src in sources %}
                <option value="{{ src }}" {{ 'selected' if src == selected_source else '' }}>{{ src }}</option>
                {% endfor %}
            </select>
            
            <label for="category">Category:</label>
            <select name="category" id="category">
                <option value="">All categories</option>
                {% for cat in categories %}
                <option value="{{ cat }}" {{ 'selected' if cat == selected_category else '' }}>{{ cat }}</option>
                {% endfor %}
            </select>
            
            <label for="days">From:</label>
            <select name="days" id="days">
                <option value="1" {{ 'selected' if days == 1 else '' }}>Last 24 hours</option>
                <option value="3" {{ 'selected' if days == 3 else '' }}>Last 3 days</option>
                <option value="7" {{ 'selected' if days == 7 else '' }}>Last 7 days</option>
            </select>
            
            <button type="submit">Filter</button>
        </form>
    </div>
    
    <div class="stats">
        Showing {{ articles|length }} article(s)
    </div>
    
    {% if articles %}
        {% for article in articles %}
        <article class="article">
            <h2><a href="{{ article.url }}" target="_blank">{{ article.title }}</a></h2>
            <div class="meta">
                <span class="source">{{ article.source }}</span>
                {% if article.category %}<span class="category">{{ article.category }}</span>{% endif %}
                &middot; {{ article.time_ago }}
            </div>
            <div class="summary">{{ article.summary or 'Summary pending...' }}</div>
        </article>
        {% endfor %}
    {% else %}
        <div class="no-articles">
            <p>No articles found. The scraper might still be fetching content.</p>
        </div>
    {% endif %}
    
    <div class="refresh-info">
        Last updated: {{ now }} | Refreshes automatically every scrape cycle
    </div>
    {% endif %}
</body>
</html>
"""


def time_ago(dt_str: str) -> str:
    """Convert datetime string to human-readable 'time ago' format."""
    try:
        dt = datetime.fromisoformat(dt_str)
        diff = datetime.now() - dt
        
        if diff.days > 0:
            return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    except (ValueError, TypeError):
        return "recently"


def get_articles(source_filter: str | None = None, category_filter: str | None = None, days: int = 7) -> list[dict]:
    """Fetch articles from database."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT source, title, url, summary, category, created_at 
                FROM articles 
                WHERE created_at > datetime('now', ?)
                AND duplicate_of IS NULL
            """
            params = [f'-{days} days']
            
            if source_filter:
                query += " AND source = ?"
                params.append(source_filter)
            
            if category_filter:
                query += " AND category = ?"
                params.append(category_filter)
            
            query += " ORDER BY created_at DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
        
        return [{
            'source': row['source'],
            'title': row['title'],
            'url': row['url'],
            'summary': row['summary'],
            'category': row['category'],
            'time_ago': time_ago(row['created_at'])
        } for row in rows]
    except sqlite3.Error as e:
        raise RuntimeError(f"Database error: {e}")


def get_sources() -> list[str]:
    """Get list of unique sources."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT source FROM articles ORDER BY source")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error:
        return []


def get_categories() -> list[str]:
    """Get list of unique categories."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT category FROM articles WHERE category IS NOT NULL ORDER BY category")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error:
        return []


def get_article_stats() -> dict:
    """Get article statistics for health endpoint."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE duplicate_of IS NULL")
            count = cursor.fetchone()[0]
            
            cursor.execute("SELECT MAX(created_at), MIN(created_at) FROM articles WHERE duplicate_of IS NULL")
            row = cursor.fetchone()
            latest = row[0] if row else None
            oldest = row[1] if row else None
            
            return {
                "article_count": count,
                "latest_article": latest,
                "oldest_article": oldest
            }
    except sqlite3.Error as e:
        raise RuntimeError(f"Database error: {e}")


@app.route('/')
def index():
    source_filter = request.args.get('source', '')
    category_filter = request.args.get('category', '')
    days = int(request.args.get('days', 7))
    
    try:
        articles = get_articles(source_filter or None, category_filter or None, days)
        sources = get_sources()
        categories = get_categories()
        error = None
    except RuntimeError as e:
        articles = []
        sources = []
        categories = []
        error = str(e)
    
    return render_template_string(
        HTML_TEMPLATE,
        articles=articles,
        sources=sources,
        categories=categories,
        selected_source=source_filter,
        selected_category=category_filter,
        days=days,
        now=datetime.now().strftime('%Y-%m-%d %H:%M'),
        error=error
    )


@app.route('/health')
def health():
    """Health check endpoint for monitoring."""
    try:
        stats = get_article_stats()
        return jsonify({
            "status": "ok",
            "database": "connected",
            "article_count": stats["article_count"],
            "latest_article": stats["latest_article"],
            "oldest_article": stats["oldest_article"]
        })
    except RuntimeError as e:
        return jsonify({
            "status": "error",
            "database": "disconnected",
            "error": str(e)
        }), 500
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.errorhandler(sqlite3.Error)
def handle_db_error(error):
    """Handle database errors."""
    return render_template_string(
        HTML_TEMPLATE,
        articles=[],
        sources=[],
        categories=[],
        selected_source='',
        selected_category='',
        days=7,
        now=datetime.now().strftime('%Y-%m-%d %H:%M'),
        error=f"Database error: {error}"
    ), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)