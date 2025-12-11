# Facebook Monitor System

A production-grade Facebook data collection and monitoring system designed for high-performance scraping, real-time analytics, and anti-detection resilience.

## Overview

This system allows for:
- **Automated Data Collection**: Scraping posts from pages/groups/profiles using Playwright.
- **Real-Time Monitoring**: Tracking engagement (likes, comments, shares) with WebSocket updates.
- **Analytics Dashboard**: Visualizing trends and viral posts via Streamlit.
- **Resilient Architecture**: Built with Circuit Breakers, Retry Logic, and advanced Anti-Detection layers.

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn
- **Scraping**: Playwright, `playwright-stealth`
- **Frontend**: Streamlit, Plotly
- **Database**: PostgreSQL (Data), Redis (Queue & Cache)
- **Task Queue**: Celery

## Key Features

- **7-Layer Anti-Detection**: Includes browser fingerprinting, Pareto-distributed timing, and human-like interaction simulation.
- **Dual-Stream Data**: Separate pipelines for one-time content storage and continuous interaction tracking.
- **Resource Management**: Automated quarantine for failing sessions/proxies.
- **Hot-Reload configs**: Update targets without restarting the system.

## Setup

1. **Environment Variables**:
   Copy `.env.example` (if available) or create `.env` with:
   ```env
   DB_HOST=localhost
   DB_USER=postgres
   DB_PASSWORD=yourpassword
   DB_NAME=facebook_monitor
   REDIS_HOST=localhost
   ```

2. **Dependencies**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Database**:
   Ensure PostgreSQL and Redis are running.

## Running the System

### 1. Start Support Services
Ensure Redis and PostgreSQL are active.

### 2. Start Worker
```bash
celery -A core.multi_queue_worker worker --loglevel=info
```

### 3. Start API Server
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 4. Start Dashboard
```bash
streamlit run webapp_streamlit/dashboard.py
```

**(Note: Adjust paths as necessary based on your project structure)**

## Structure

- `core/`: Core logic (Database, Sessions, Proxies)
- `scrapers/`: Scraper logic (Browser controller, Interaction simulator)
- `api/`: FastAPI server endpoints
- `webapp_streamlit/`: Dashboard frontend
- `utils/`: Utilities (Circuit breaker, Crypto, Logging)
- `tests/`: Unit and integration tests

## License
[License Name]
