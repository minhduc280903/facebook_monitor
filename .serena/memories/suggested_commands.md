# Suggested Commands for Facebook Monitor Project

## Development Commands (Windows)

### Project Setup
```bash
# Install dependencies
pip install -r requirements.txt
pip install -r backend_requirements.txt

# Install Playwright browsers
python -m playwright install chromium
```

### Running the System
```bash
# Start complete system
python run_multi_queue_system.py --full

# Start individual components
python multi_queue_worker.py
python discovery_scheduler.py
python tracking_scheduler.py

# Start API server
python api/main.py
```

### Batch Scripts
```bash
# Start system (Windows)
start_system.bat

# Start API only
start_api.bat
```

### Testing
```bash
# Run all tests
python -m pytest tests/

# Run specific test modules
python -m pytest tests/test_session_manager.py
python -m pytest tests/test_proxy_manager.py

# Run browser test
python test_browser.py

# Manual scraping test
python manual_scrape_test.py
```

### Frontend Dashboard
```bash
# Run Streamlit dashboard
streamlit run webapp_streamlit/app.py
```

### Maintenance Commands
```bash
# Reset sessions
python reset_sessions.py

# Manage targets
python manage_targets.py

# Debug utilities
python debug_total_reactions.py
python simple_test.py
```

### Database Operations
```bash
# Database connection test
python -m pytest tests/test_db_connection.py
```

### System Commands (Windows)
```bash
# File operations
dir                 # List directory contents
type filename       # Display file contents  
find "pattern" *.py # Search in files
cd path             # Change directory

# Process management
tasklist | findstr python  # Find Python processes
taskkill /F /IM python.exe # Kill Python processes
```

### Docker (if using)
```bash
docker-compose up -d
docker-compose logs -f
docker-compose down
```