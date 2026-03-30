# Facebook Post Monitor - Project Overview

## Purpose
A comprehensive Facebook post monitoring and analytics system that:
- Scrapes Facebook groups/pages for post data 
- Transforms engagement data into forex-style trading charts
- Provides real-time monitoring with WebSocket integration
- Offers professional dashboard with Streamlit frontend

## Architecture
**Hybrid Session-Proxy System:**
- **Workers**: Flexible worker pool that takes tasks from Redis queue
- **Session-Proxy Binding**: Each Facebook session is permanently bound to one proxy
- **Resource Management**: Intelligent quarantine system for sessions and proxies
- **Performance Tracking**: Success rates, failure counts, response times

## Key Components

### Core Backend (`core/`)
- `session_manager.py`: Manages Facebook session pool with role-based assignment
- `proxy_manager.py`: Intelligent proxy management with health checking  
- `session_proxy_binder.py`: Persistent session-proxy binding system
- `database_manager.py`: PostgreSQL database operations
- `target_manager.py`: Manages Facebook targets (groups/pages)

### Workers & Schedulers
- `multi_queue_worker.py`: Main worker that processes scraping tasks
- `discovery_scheduler.py`: Schedules discovery of new posts
- `tracking_scheduler.py`: Tracks engagement changes on existing posts
- `scan_scheduler.py`: Manages scanning operations

### Scrapers (`scrapers/`)
- `browser_controller.py`: Playwright browser automation
- `content_extractor.py`: Extract post content and metadata
- `interaction_simulator.py`: Simulate human interactions
- `navigation_handler.py`: Handle page navigation

### Frontend (`webapp_streamlit/`)
- Multi-page Streamlit dashboard
- Forex-style charts with Plotly
- Real-time monitoring with WebSocket
- Mobile-responsive design

## Tech Stack
- **Backend**: Python 3.13, FastAPI, PostgreSQL, Redis
- **Browser Automation**: Playwright (Chromium)
- **Frontend**: Streamlit, Plotly, Pandas
- **Infrastructure**: Docker support, cross-process file locking
- **Monitoring**: Real-time WebSocket, comprehensive logging