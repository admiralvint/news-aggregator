#!/usr/bin/env python3
"""Simple web interface for reading news summaries."""

from flask import Flask, render_template_string, request
import sqlite3
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
DB_PATH = Path(__file__).parent.parent / "data" / "articles.db"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Digest</title>
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }
        h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }
        .filters {
            background: white;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .filters form {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
        }
        .filters select, .filters button {
            padding: 8px 12px;
            border-radius: 4px;
            border: 1px solid #ddd;
            font-size: 14px;
        }
        .filters button {
            background: #3498db;
            color: white;
            border: none;
            cursor: pointer;
        }
        .filters button:hover {
            background: #2980b9;
        }
        .stats {
            color: #666;
            font-size: 14px;
            margin-bottom: 15px;
        }
        .article {
            background: white;
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .article:hover {
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }
        .article h2 {
            margin: 0 0 10px 0;
            font-size: 18px;
        }
        .article h2 a {
            color: #2c3e50;
            text-decoration: none;
        }
        .article h2 a:hover {
            color: #3498db;
        }
        .meta {
            font-size: 12px;
            color: #888;
            margin-bottom: 10px;
        }
        .source {
            background: #e8f4f8;
            color: #2980b9;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 500;
        }
        .summary {
            line-height: 1.6;
            color: #444;
        }
        .no-articles {
            text-align: center;
            padding: 40px;
            color: #888;
        }
        .refresh-info {
            text-align: center;
            color: #888;
            font-size: 12px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <h1>📰 News Digest</h1>
    
    <div class="filters">
        <form method="get">
            <label for="source">Source:</label>
            <select name="source" id="source">
                <option value="">All sources</option>
                {% for src in sources %}
                <option value="{{ src }}" {{ 'selected' if src == selected_source else '' }}>{{ src }}</option>
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
</body>
</html>
"""


def time_ago(dt_str):
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
    except:
        return "recently"


def get_articles(source_filter=None, days=7):
    """Fetch articles from database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
        SELECT source, title, url, summary, created_at 
        FROM articles 
        WHERE created_at > datetime('now', ?)
    """
    params = [f'-{days} days']
    
    if source_filter:
        query += " AND source = ?"
        params.append(source_filter)
    
    query += " ORDER BY created_at DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'source': row['source'],
        'title': row['title'],
        'url': row['url'],
        'summary': row['summary'],
        'time_ago': time_ago(row['created_at'])
    } for row in rows]


def get_sources():
    """Get list of unique sources."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT source FROM articles ORDER BY source")
    sources = [row[0] for row in cursor.fetchall()]
    conn.close()
    return sources


@app.route('/')
def index():
    source_filter = request.args.get('source', '')
    days = int(request.args.get('days', 7))
    
    articles = get_articles(source_filter or None, days)
    sources = get_sources()
    
    return render_template_string(
        HTML_TEMPLATE,
        articles=articles,
        sources=sources,
        selected_source=source_filter,
        days=days,
        now=datetime.now().strftime('%Y-%m-%d %H:%M')
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)