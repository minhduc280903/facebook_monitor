#!/bin/bash
# 🚀 Facebook Scraper - Ubuntu VPS One-Click Setup
# ✅ HOÀN CHỈNH - Production-ready deployment on Ubuntu VPS

set -e  # Exit on error

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_step() { echo -e "${GREEN}[STEP]${NC} $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }

if [ "$EUID" -ne 0 ]; then 
    print_error "Run as root: sudo bash setup_ubuntu.sh"
    exit 1
fi

APP_DIR="/opt/facebook-scraper"

echo "=========================================="
echo "🚀 FACEBOOK SCRAPER - UBUNTU VPS"
echo "=========================================="
echo "⚡ Real Chrome + GPU + Native Performance"
echo ""

# ============================================
# STEP 1: System Update & Dependencies
# ============================================
print_step "Installing ALL system dependencies..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    build-essential software-properties-common \
    wget curl git vim htop supervisor \
    postgresql postgresql-contrib redis-server nginx \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    gcc libpq-dev locales \
    fonts-unifont fonts-liberation fonts-noto-color-emoji \
    libglib2.0-0 libnss3 libnss3-dev libnspr4 \
    libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libexpat1 libxcb1 libxkbcommon0 \
    libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 \
    xvfb x11vnc

# UTF-8 locale
echo "en_US.UTF-8 UTF-8" > /etc/locale.gen
locale-gen en_US.UTF-8

# ============================================
# STEP 2: Google Chrome Official
# ============================================
print_step "Installing Google Chrome (official)..."
if ! command -v google-chrome &> /dev/null; then
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - 2>/dev/null
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
    apt-get update -qq
    apt-get install -y -qq google-chrome-stable
fi
print_success "Chrome: $(google-chrome --version)"

# ============================================
# STEP 2.5: Install Ngrok
# ============================================
print_step "Installing ngrok..."
if ! command -v ngrok &> /dev/null; then
    wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz -O /tmp/ngrok.tgz
    tar xzf /tmp/ngrok.tgz -C /usr/local/bin
    rm /tmp/ngrok.tgz
    chmod +x /usr/local/bin/ngrok
fi
print_success "Ngrok: $(ngrok version)"

# Check for ngrok authtoken
if [ -f "$APP_DIR/.ngrok_token" ]; then
    NGROK_TOKEN=$(cat $APP_DIR/.ngrok_token | tr -d '\n\r ')
    /usr/local/bin/ngrok config add-authtoken "$NGROK_TOKEN"
    print_success "Ngrok authtoken configured"
else
    print_warning "Ngrok authtoken not found. Create $APP_DIR/.ngrok_token with your token"
    print_warning "Get token from: https://dashboard.ngrok.com/get-started/your-authtoken"
fi

# ============================================
# STEP 3: Check Code & Required Files Exist
# ============================================
cd $APP_DIR 2>/dev/null || {
    print_error "Directory $APP_DIR not found!"
    print_warning "Upload code first: scp -r C:\\vibecode\\facebook\\* root@149.28.150.95:$APP_DIR/"
    exit 1
}

# Check main code exists
if [ ! -f "multi_queue_worker.py" ]; then
    print_error "Code not found! Upload first."
    exit 1
fi

# Check critical code files (NOT data files)
MISSING_FILES=""
[ ! -f "requirements.txt" ] && MISSING_FILES="$MISSING_FILES requirements.txt"
[ ! -f "config.py" ] && MISSING_FILES="$MISSING_FILES config.py"

if [ ! -z "$MISSING_FILES" ]; then
    print_error "Missing critical files:$MISSING_FILES"
    print_warning "These files are required for the system to run!"
    exit 1
fi

print_success "All required code files found"

# Check optional data files (create empty if missing)
print_step "Checking data files..."

if [ ! -f "account.txt" ]; then
    print_warning "account.txt not found - creating empty file"
    echo "# Facebook accounts (format: id|password|2fa_secret)" > account.txt
    echo "# Add accounts via Admin Panel UI instead" >> account.txt
fi

if [ ! -f "proxies.txt" ]; then
    print_warning "proxies.txt not found - creating empty file"
    echo "# Proxies (format: host:port:username:password)" > proxies.txt
    echo "# Add proxies via Admin Panel UI instead" >> proxies.txt
fi

if [ ! -f "targets.json" ]; then
    print_warning "targets.json not found - creating default"
    echo '{"targets": []}' > targets.json
    print_warning "⚠️ No targets configured - add targets to targets.json later"
fi

print_success "Data files initialized"

# ============================================
# STEP 4: Python Environment
# ============================================
print_step "Setting up Python 3.11 venv..."
python3.11 -m venv venv
source venv/bin/activate

print_step "Installing Python packages..."
venv/bin/pip install --upgrade pip -q
venv/bin/pip install --timeout=300 -r requirements.txt -q

print_step "Installing Playwright..."
# ✅ ANTI-DETECTION: Dùng Google Chrome system, KHÔNG install Chromium!
# venv/bin/playwright install chromium  # ❌ SKIP - dùng system Chrome
venv/bin/playwright install-deps chromium  # Chỉ install dependencies

# ============================================
# STEP 5: PostgreSQL Setup
# ============================================
print_step "Setting up PostgreSQL..."
systemctl start postgresql
systemctl enable postgresql

DB_PASS="fbscraper_$(openssl rand -hex 8)"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS facebook_scraper;" 2>/dev/null || true
sudo -u postgres psql -c "DROP USER IF EXISTS fb_user;" 2>/dev/null || true
sudo -u postgres psql << EOF
CREATE DATABASE facebook_scraper;
CREATE USER fb_user WITH PASSWORD '$DB_PASS';
GRANT ALL PRIVILEGES ON DATABASE facebook_scraper TO fb_user;
\c facebook_scraper
GRANT ALL ON SCHEMA public TO fb_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO fb_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO fb_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO fb_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO fb_user;
EOF

print_success "PostgreSQL: facebook_scraper database created with user fb_user"

# ============================================
# STEP 6: Redis Setup
# ============================================
print_step "Setting up Redis..."
systemctl start redis-server
systemctl enable redis-server

# Redis memory limit: 512MB for optimal performance
sed -i 's/^# maxmemory <bytes>/maxmemory 512mb/' /etc/redis/redis.conf
sed -i 's/^# maxmemory-policy noeviction/maxmemory-policy allkeys-lru/' /etc/redis/redis.conf
systemctl restart redis-server

print_success "Redis: 512MB memory limit configured"

# ============================================
# STEP 7: Create .env File (CRITICAL!)
# ============================================
print_step "Creating .env file..."
cat > $APP_DIR/.env << EOF
# Database (VPS Mode - localhost) - Match config.py env_prefix "DB_"
DATABASE_URL=postgresql://fb_user:$DB_PASS@localhost:5432/facebook_scraper
DB_HOST=localhost
DB_PORT=5432
DB_USER=fb_user
DB_PASSWORD=$DB_PASS
DB_NAME=facebook_scraper

# Redis (VPS Mode - localhost) - Match config.py env_prefix "REDIS_"
REDIS_URL=redis://localhost:6379/0
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Worker
WORKER_CONCURRENCY=6
WORKER_HEADLESS=false

# Environment (VPS native deployment)
PYTHONUNBUFFERED=1
PYTHONIOENCODING=utf-8
LANG=C.UTF-8
LC_ALL=C.UTF-8

# API
API_CORS_ORIGINS=http://localhost:8501

# Streamlit
API_BASE_URL=http://localhost:8000
STREAMLIT_SERVER_ENABLE_WEBSOCKET=true
STREAMLIT_SERVER_MAX_MESSAGE_SIZE=200
EOF

print_success ".env file created"

# ============================================
# STEP 8: Initialize Status Files
# ============================================
print_step "Initializing status files..."
test -f proxy_status.json || echo "{}" > proxy_status.json
test -f session_status.json || echo "{}" > session_status.json
test -f session_proxy_bindings.json || echo '{"bindings":{}}' > session_proxy_bindings.json

# ============================================
# STEP 9: Create Directories
# ============================================
mkdir -p sessions logs screenshots /var/log/facebook-scraper
chmod 755 sessions logs screenshots /var/log/facebook-scraper

# ============================================
# STEP 10: Database Migrations
# ============================================
print_step "Running database migrations..."
source venv/bin/activate

# Initialize database schema (creates tables)
if [ -f "init_database.py" ]; then
    python init_database.py
    print_success "Database schema initialized"
fi

# Migrate proxies from file to DB (ONE TIME - idempotent)
if [ -f "migrations/migrate_proxies_to_db.py" ]; then
    print_step "Migrating proxies to database..."
    python migrations/migrate_proxies_to_db.py || {
        print_warning "Proxy migration skipped (may already be migrated)"
    }
fi

# Migrate accounts from file to DB (ONE TIME - idempotent)
if [ -f "migrations/migrate_accounts_to_db.py" ]; then
    print_step "Migrating accounts to database..."
    python migrations/migrate_accounts_to_db.py || {
        print_warning "Account migration skipped (may already be migrated)"
    }
fi

print_success "All migrations complete"

# ============================================
# STEP 11: Worker Initialization Script
# ============================================
print_step "Creating worker initialization script..."
cat > $APP_DIR/init_worker.sh << 'INIT_SCRIPT'
#!/bin/bash
# Worker initialization script

echo "🚀 Worker initialization..."

# CD to app directory
cd /opt/facebook-scraper

# Set environment
export PYTHONPATH=/opt/facebook-scraper:$PYTHONPATH
export DISPLAY=:99

# Use venv Python explicitly
PYTHON=/opt/facebook-scraper/venv/bin/python

# Kill existing browsers
pkill -9 chromium 2>/dev/null || true
pkill -9 chrome 2>/dev/null || true
sleep 2

# Clean singleton locks
find ./sessions -name "SingletonLock" -type f -delete 2>/dev/null || true
find ./sessions -name "SingletonCookie" -type f -delete 2>/dev/null || true
find ./sessions -name "SingletonSocket" -type f -delete 2>/dev/null || true

# Initialize status files
test -f proxy_status.json || echo "{}" > proxy_status.json
test -f session_status.json || echo "{}" > session_status.json

# Run auto_login if exists (will skip if account.txt is empty)
if [ -f "auto_login.py" ]; then
    echo "🔐 Running auto_login..."
    # ✅ Script will skip gracefully if account.txt is empty
    # ✅ ANTI-DETECTION: headless=false (use real Chrome with GUI via Xvfb)
    $PYTHON auto_login.py account.txt all false true || true
    
    # Kill browsers after login
    pkill -9 chromium 2>/dev/null || true
    pkill -9 chrome 2>/dev/null || true
    sleep 2
    
    # Clean locks again
    find ./sessions -name "SingletonLock" -type f -delete 2>/dev/null || true
fi

# Reset sessions
if [ -f "reset_sessions.py" ]; then
    $PYTHON reset_sessions.py --all || true
fi

# Calculate dynamic concurrency based on available sessions and proxies
READY_SESSIONS=$($PYTHON -c "import json,os; data=json.load(open('session_status.json')) if os.path.exists('session_status.json') else {}; print(sum(1 for s in data.values() if s.get('status')=='READY'))" 2>/dev/null || echo 2)
WORKING_PROXIES=$($PYTHON -c "import json,os; data=json.load(open('proxy_status.json')) if os.path.exists('proxy_status.json') else {}; print(sum(1 for p in data.values() if p.get('status')=='READY' and p.get('consecutive_failures', 0) < 3))" 2>/dev/null || echo 2)

if [ $READY_SESSIONS -lt $WORKING_PROXIES ]; then
    VALID_PAIRS=$READY_SESSIONS
else
    VALID_PAIRS=$WORKING_PROXIES
fi

if [ $VALID_PAIRS -lt 2 ]; then
    VALID_PAIRS=2
fi

echo "✅ Worker Calculation:"
echo "   - Ready sessions: $READY_SESSIONS"
echo "   - Working proxies: $WORKING_PROXIES"
echo "   - Valid pairs: $VALID_PAIRS"
echo "   - Worker concurrency: ${WORKER_CONCURRENCY:-$VALID_PAIRS}"

echo "$VALID_PAIRS" > /tmp/worker_concurrency.txt

echo "✅ Worker initialization complete!"
INIT_SCRIPT

chmod +x $APP_DIR/init_worker.sh

# ============================================
# STEP 12: Start Xvfb (before worker init)
# ============================================
print_step "Starting Xvfb (virtual display)..."
# Kill existing Xvfb if running
pkill -9 Xvfb 2>/dev/null || true
sleep 1

# Start Xvfb in background
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset > /dev/null 2>&1 &
XVFB_PID=$!
sleep 2

# Verify Xvfb started
if ps -p $XVFB_PID > /dev/null; then
    print_success "Xvfb started (PID: $XVFB_PID)"
else
    print_warning "Xvfb may not have started properly"
fi

export DISPLAY=:99

# ============================================
# STEP 13: Run Worker Initialization
# ============================================
print_step "Running worker initialization..."
cd $APP_DIR
source venv/bin/activate
bash init_worker.sh

# Read calculated concurrency
if [ -f /tmp/worker_concurrency.txt ]; then
    CALC_CONCURRENCY=$(cat /tmp/worker_concurrency.txt)
else
    CALC_CONCURRENCY=6
fi

print_success "Worker concurrency: $CALC_CONCURRENCY"

# ============================================
# STEP 14: Supervisor Configuration
# ============================================
print_step "Configuring Supervisor for process management..."

# Build environment string with DB credentials + API URL for Streamlit
ENV_COMMON="PYTHONPATH=\"/opt/facebook-scraper\",DB_HOST=\"localhost\",DB_PORT=\"5432\",DB_USER=\"fb_user\",DB_PASSWORD=\"$DB_PASS\",DB_NAME=\"facebook_scraper\",REDIS_HOST=\"localhost\",REDIS_PORT=\"6379\",REDIS_DB=\"0\",API_BASE_URL=\"http://localhost:8000\""

cat > /etc/supervisor/conf.d/facebook-scraper.conf << SUPERVISOR_EOF
[program:celery_beat]
command=/opt/facebook-scraper/venv/bin/celery -A multi_queue_worker beat --loglevel=info
directory=/opt/facebook-scraper
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/celery_beat.log
stderr_logfile=/var/log/facebook-scraper/celery_beat_err.log
environment=$ENV_COMMON

[program:celery_worker_scan]
command=/opt/facebook-scraper/venv/bin/celery -A multi_queue_worker worker --loglevel=info --queues=scan_high,scan_normal,discovery --pool=prefork --concurrency=$CALC_CONCURRENCY --max-tasks-per-child=10 --hostname=worker_scan@%%h
directory=/opt/facebook-scraper
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/worker_scan.log
stderr_logfile=/var/log/facebook-scraper/worker_scan_err.log
environment=$ENV_COMMON,DISPLAY=":99"

[program:celery_worker_maintenance]
command=/opt/facebook-scraper/venv/bin/celery -A multi_queue_worker worker --loglevel=info --queues=maintenance --pool=prefork --concurrency=2 --max-tasks-per-child=100 --hostname=worker_maintenance@%%h
directory=/opt/facebook-scraper
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/worker_maintenance.log
stderr_logfile=/var/log/facebook-scraper/worker_maintenance_err.log
environment=$ENV_COMMON,DISPLAY=":99"

[program:xvfb]
command=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/xvfb.log
stderr_logfile=/var/log/facebook-scraper/xvfb_err.log
priority=10

[program:api]
command=/opt/facebook-scraper/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 30 --ws-ping-timeout 10 --ws-max-size 16777216 --limit-concurrency 100 --timeout-keep-alive 65
directory=/opt/facebook-scraper
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/api.log
stderr_logfile=/var/log/facebook-scraper/api_err.log
environment=$ENV_COMMON

[program:streamlit]
command=/opt/facebook-scraper/venv/bin/streamlit run webapp_streamlit/app.py --server.port=8501 --server.address=0.0.0.0 --server.enableWebsocketCompression=true
directory=/opt/facebook-scraper
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/streamlit.log
stderr_logfile=/var/log/facebook-scraper/streamlit_err.log
environment=$ENV_COMMON

[program:flower]
command=/opt/facebook-scraper/venv/bin/celery -A multi_queue_worker flower --port=5555
directory=/opt/facebook-scraper
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/flower.log
stderr_logfile=/var/log/facebook-scraper/flower_err.log
environment=$ENV_COMMON

[program:ngrok]
command=/usr/local/bin/ngrok http 8501 --log=stdout
directory=/opt/facebook-scraper
user=root
autostart=true
autorestart=true
stdout_logfile=/var/log/facebook-scraper/ngrok.log
stderr_logfile=/var/log/facebook-scraper/ngrok_err.log
environment=HOME="/root"

[group:facebook-scraper]
programs=xvfb,celery_beat,celery_worker_scan,celery_worker_maintenance,api,streamlit,flower,ngrok
SUPERVISOR_EOF

# Kill temporary Xvfb (Supervisor will start permanent one)
print_step "Stopping temporary Xvfb..."
if [ ! -z "$XVFB_PID" ]; then
    kill $XVFB_PID 2>/dev/null || true
    sleep 1
fi
pkill -9 Xvfb 2>/dev/null || true

# ============================================
# STEP 15: Start Services
# ============================================
print_step "Starting all services..."

# Create log directory
mkdir -p /var/log/facebook-scraper
chown -R root:root /var/log/facebook-scraper

# Start Supervisor daemon
systemctl start supervisor
systemctl enable supervisor
sleep 2

# Load and start services
supervisorctl reread
supervisorctl update
supervisorctl start facebook-scraper:*

sleep 5

# ============================================
# STEP 16: Configure Firewall
# ============================================
if command -v ufw &> /dev/null; then
    print_step "Configuring firewall..."
    ufw allow 22/tcp    # SSH
    ufw allow 8000/tcp  # API
    ufw allow 8501/tcp  # Streamlit
    ufw allow 5555/tcp  # Flower
    echo "y" | ufw enable 2>/dev/null || true
    print_success "Firewall configured"
fi

# ============================================
# STEP 17: Create Helper Script to Get Ngrok URL
# ============================================
cat > $APP_DIR/get_ngrok_url.sh << 'NGROK_HELPER'
#!/bin/bash
# Get ngrok public URL
curl -s http://localhost:4040/api/tunnels | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['tunnels'][0]['public_url'] if data.get('tunnels') else 'Ngrok not running')" 2>/dev/null || echo "Ngrok not available"
NGROK_HELPER
chmod +x $APP_DIR/get_ngrok_url.sh

# ============================================
# DONE!
# ============================================
echo ""
echo "=========================================="
echo "✅ SETUP COMPLETE!"
echo "=========================================="
echo ""

print_success "Services Status:"
supervisorctl status facebook-scraper:*

echo ""
sleep 3  # Wait for ngrok to start

# Get ngrok URL
NGROK_URL=$($APP_DIR/get_ngrok_url.sh)

echo "📊 Service URLs:"
echo "   API:       http://149.28.150.95:8000"
echo "   Dashboard: http://149.28.150.95:8501"
echo "   Flower:    http://149.28.150.95:5555"
if [[ "$NGROK_URL" != "Ngrok not"* ]]; then
    echo "   Ngrok:     $NGROK_URL (Public Access)"
else
    print_warning "Ngrok: Not configured (add authtoken to .ngrok_token)"
fi
echo ""

echo "📝 Commands:"
echo "   Status:     supervisorctl status"
echo "   Restart:    supervisorctl restart facebook-scraper:*"
echo "   Logs:       tail -f /var/log/facebook-scraper/*.log"
echo "   Ngrok URL:  $APP_DIR/get_ngrok_url.sh"
echo ""

echo "🔧 Configuration:"
echo "   Chrome:     $(google-chrome --version)"
echo "   Ngrok:      $(ngrok version)"
echo "   PostgreSQL: localhost:5432 (facebook_scraper)"
echo "   Redis:      localhost:6379 (512MB)"
echo "   Workers:    $CALC_CONCURRENCY (auto-calculated)"
echo ""

echo "🎉 Facebook Scraper is running!"
echo "⚡ Native VPS deployment with Real Chrome + GPU!"
echo "🌐 Ngrok - Public access enabled!"
echo ""
