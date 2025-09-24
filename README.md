# 📈 Facebook Post Monitor - Advanced Forex Chart Engine

## 🎉 Phase 1 Complete - Production Ready Dashboard

A professional Streamlit application that transforms Facebook post engagement data into forex-style trading charts with real-time monitoring capabilities.

## ✨ Features

### 📊 Frontend Dashboard
- **Multiple Chart Types**: Candlestick, Line, OHLC, Area charts
- **Advanced Timeframes**: 5T, 15T, 30T, 1H, 2H, 4H, 8H, 1D
- **Professional Controls**: Custom date ranges, zoom, drawing tools
- **Export Functions**: JSON, CSV, PNG export capabilities
- **Mobile Responsive**: Touch-optimized interface
- **Real-time Updates**: WebSocket integration for live data

### 🔧 Backend Architecture  
- **Hybrid Session-Proxy Binding**: Each Facebook session permanently bound to one proxy
- **Intelligent Resource Management**: Performance tracking with automatic quarantine
- **Worker Pool Flexibility**: Workers can handle any scraping task from Redis queue
- **Enterprise Reliability**: Cross-process file locking and comprehensive error handling
- **Role-Based Assignment**: Specialized accounts for discovery vs tracking tasks

## 🚀 Quick Start

### Deploy on Streamlit Community Cloud

1. Visit [share.streamlit.io](https://share.streamlit.io)
2. Sign in with GitHub
3. Click "New app"
4. Select this repository
5. Set main file: `webapp_streamlit/app.py`
6. Deploy!

### Local Development

```bash
# Install dependencies
pip install streamlit pandas plotly

# Run the app
streamlit run webapp_streamlit/app.py
```

## 📊 Application Structure

### Frontend Dashboard
```
webapp_streamlit/
├── app.py                          # Main dashboard
├── pages/
│   ├── 1_🎯_Target_Analysis.py     # Target analysis
│   ├── 2_📊_Post_Deep_Dive.py      # Post details
│   ├── 3_💹_Forex_Analysis.py      # Advanced forex charts
│   └── 4_⚡_Real_Time_Monitor.py   # Real-time monitoring
└── core/
    └── db_reader.py                # Database interface
```

### Backend System
```
core/
├── session_manager.py              # Facebook session pool management
├── proxy_manager.py                # Proxy pool with health checking
├── session_proxy_binder.py         # Session-proxy binding system
├── database_manager.py             # PostgreSQL operations
└── target_manager.py               # Facebook targets management

workers/
├── multi_queue_worker.py           # Main scraping worker
├── discovery_scheduler.py          # New post discovery
├── tracking_scheduler.py           # Engagement tracking
└── scan_scheduler.py               # Scan coordination

scrapers/
├── browser_controller.py           # Playwright automation
├── content_extractor.py            # Post content extraction
├── interaction_simulator.py        # Human-like interactions
└── navigation_handler.py           # Page navigation
```

## 🎯 Key Components

### Session-Proxy Binding System

- **Consistent Identity**: Each Facebook session permanently bound to one proxy
- **Automatic Assignment**: Deterministic proxy selection based on session hash
- **Persistent Storage**: Bindings survive system restarts
- **Intelligent Fallback**: Graceful handling of resource unavailability

### Resource Management

- **Performance Tracking**: Success rates, response times, failure counts
- **Automatic Quarantine**: Poor-performing resources temporarily isolated
- **Health Monitoring**: Continuous proxy connectivity verification
- **Load Balancing**: Optimal resource distribution across workers

### Forex Chart Engine

- Professional candlestick charts
- Multiple timeframe analysis
- Volume correlation
- Export capabilities

### Real-time Monitoring

- WebSocket connections
- Live data updates
- System health monitoring
- Interactive controls

### Mobile Optimization

- Responsive design
- Touch-friendly interface
- Performance optimized

## 🌐 Live Demo

Visit the deployed application: [Your Streamlit URL]

## 📝 Requirements

- Python 3.9+
- Streamlit 1.28+
- Pandas 2.1+
- Plotly 5.17+

## 🤝 Contributing

This is a production-ready application. For issues or feature requests, please create an issue.

## 📄 License

Private project - All rights reserved.

