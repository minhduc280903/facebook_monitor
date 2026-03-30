# Task Completion Guidelines

## After Completing Any Task

### 1. Code Quality Checks
- **Type Checking**: Ensure all new code has proper type hints
- **Error Handling**: Add comprehensive try-catch blocks with logging
- **Thread Safety**: Use proper locking for shared resources
- **Performance**: Consider impact on session/proxy pools

### 2. Testing
```bash
# Run relevant tests
python -m pytest tests/test_[relevant_module].py

# Test browser functionality if changed
python test_browser.py

# Test manual scraping if scrapers changed
python manual_scrape_test.py
```

### 3. Integration Testing
```bash
# Test system startup
python run_multi_queue_system.py --test

# Test API endpoints if API changed
python -m pytest tests/test_api_integration.py

# Test WebSocket if real-time features changed
python -m pytest tests/test_api_websocket.py
```

### 4. Documentation Updates
- Update docstrings for new/modified functions
- Add Vietnamese comments for complex logic
- Update configuration examples if needed
- Update memory files if architecture changes

### 5. Configuration Validation
- Check JSON files are valid: `targets.json`, `selectors.json`
- Validate session/proxy status files
- Ensure binding files are consistent

### 6. System Health Check
```bash
# Check session pool status
python -c "from core.session_manager import SessionManager; sm = SessionManager(); print(sm.get_stats())"

# Check proxy pool status  
python -c "from core.proxy_manager import ProxyManager; pm = ProxyManager(); print(pm.get_stats())"

# Check session-proxy bindings
python -c "from core.session_proxy_binder import SessionProxyBinder; spb = SessionProxyBinder(); print(spb.get_binding_stats())"
```

### 7. Deployment Preparation
- Test Streamlit dashboard: `streamlit run webapp_streamlit/app.py`
- Verify all dependencies in requirements files
- Check Windows batch scripts work correctly
- Ensure database migrations if schema changed

### 8. Performance Monitoring
- Monitor resource usage during operation
- Check for memory leaks in long-running workers
- Validate quarantine logic working properly
- Review success rates and failure patterns

## Critical Areas to Test After Changes

### Session/Proxy Management Changes
- Test checkout/checkin operations
- Verify binding persistence
- Check quarantine recovery
- Validate performance tracking

### Scraper Changes
- Test browser automation
- Verify content extraction
- Check error handling for Facebook changes
- Test interaction simulation

### Database Changes
- Verify data integrity
- Check transaction handling
- Test connection pooling
- Validate migration scripts

### API Changes
- Test all endpoints
- Verify WebSocket functionality
- Check CORS settings
- Test error responses