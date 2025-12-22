FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY scraper/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY scraper/ ./scraper/
COPY config/ ./config/

# Create data directory
RUN mkdir -p /app/data

# Run the scraper
CMD ["python", "-u", "scraper/scraper.py"]