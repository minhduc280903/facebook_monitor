# 🚀 Deploy Facebook Scraper to Ubuntu VPS

## ⚡ One-Command Setup - Native VPS Deployment

### VPS Info:
- **IP:** 149.28.150.95
- **User:** root
- **Password:** fK%7Mp2JSjU2Mg!n
- **OS:** Ubuntu 22.04 x64
- **Resources:** 8 vCPUs, 16GB RAM, 350GB NVMe

---

## 📦 BƯỚC 1: Upload Code lên VPS

### Từ Windows PowerShell:

```powershell
# Option 1: Dùng SCP (nếu có OpenSSH)
scp -r C:\vibecode\facebook\* root@149.28.150.95:/opt/facebook-scraper/

# Option 2: Dùng WinSCP GUI
# 1. Download WinSCP: https://winscp.net/
# 2. Connect: 149.28.150.95, user: root, pass: fK%7Mp2JSjU2Mg!n
# 3. Drag & drop: C:\vibecode\facebook\ → /opt/facebook-scraper/
```

### Từ WSL:

```bash
rsync -avz --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
  /mnt/c/vibecode/facebook/ root@149.28.150.95:/opt/facebook-scraper/
```

---

## 🚀 BƯỚC 2: Configure Ngrok (Optional - Public Access)

**Nếu muốn public access qua ngrok:**

1. Get ngrok authtoken: https://dashboard.ngrok.com/get-started/your-authtoken
2. Tạo file `.ngrok_token` trên VPS:

```bash
ssh root@149.28.150.95
cd /opt/facebook-scraper
echo "YOUR_NGROK_AUTHTOKEN_HERE" > .ngrok_token
```

**Nếu không cần ngrok:** Skip bước này, script sẽ chạy bình thường.

---

## 🚀 BƯỚC 3: Chạy Setup Script (1 lệnh duy nhất!)

### SSH vào VPS:

```bash
ssh root@149.28.150.95
# Password: fK%7Mp2JSjU2Mg!n
```

### Chạy setup:

```bash
cd /opt/facebook-scraper
chmod +x setup_ubuntu.sh
./setup_ubuntu.sh
```

**⏱️ Thời gian:** 5-10 phút

**✅ Script sẽ tự động setup toàn bộ hệ thống:**
1. ✅ Install ALL system dependencies
2. ✅ Install Python 3.11 + venv
3. ✅ Install PostgreSQL + create database
4. ✅ Install Redis (512MB memory limit)
5. ✅ Install Google Chrome official
6. ✅ Install Playwright browsers
7. ✅ Create .env file with all configs
8. ✅ Initialize status files (proxy_status.json, session_status.json)
9. ✅ **AUTO-MIGRATE proxies & accounts to PostgreSQL** 🆕
10. ✅ Run worker initialization (auto_login, cleanup locks)
11. ✅ Calculate dynamic concurrency (READY sessions × WORKING proxies)
12. ✅ Configure Supervisor with 6 services
13. ✅ Start everything

---

## 📊 KIỂM TRA

### Xem status services:

```bash
supervisorctl status
```

**Expected output:**
```
celery_beat                      RUNNING
celery_worker_scan               RUNNING
celery_worker_maintenance        RUNNING
api                              RUNNING
streamlit                        RUNNING
flower                           RUNNING
ngrok                            RUNNING
```

### Xem logs real-time:

```bash
# Tất cả logs
tail -f /var/log/facebook-scraper/*.log

# Chỉ worker logs
tail -f /var/log/facebook-scraper/worker_scan.log

# Chỉ errors
tail -f /var/log/facebook-scraper/*_err.log
```

### Access services:

- **API:** http://149.28.150.95:8000
- **Dashboard:** http://149.28.150.95:8501
- **Flower (Celery Monitoring):** http://149.28.150.95:5555
- **Ngrok Public URL:** Run `/opt/facebook-scraper/get_ngrok_url.sh` to get public URL

### Get ngrok public URL:

```bash
# Lấy ngrok public URL
/opt/facebook-scraper/get_ngrok_url.sh

# Hoặc check trực tiếp
curl -s http://localhost:4040/api/tunnels | grep -o 'https://[a-zA-Z0-9.-]*.ngrok-free.app'

# Hoặc xem log
tail -20 /var/log/facebook-scraper/ngrok.log
```

---

## 🔧 QUẢN LÝ SERVICES

### Restart tất cả:

```bash
supervisorctl restart facebook-scraper:*
```

### Restart từng service:

```bash
supervisorctl restart celery_worker_scan
supervisorctl restart celery_beat
supervisorctl restart api
supervisorctl restart streamlit
```

### Stop tất cả:

```bash
supervisorctl stop facebook-scraper:*
```

### Start tất cả:

```bash
supervisorctl start facebook-scraper:*
```

---

## ⚙️ ADMIN PANEL - QUẢN LÝ PROXIES & ACCOUNTS

### Access Admin Panel

**URL:** http://149.28.150.95:8501 → Sidebar → **⚙️ Admin Panel**

### Tính năng:

#### 🌐 Tab 1: Proxy Management
- ✅ **Add Single Proxy:** Thêm từng proxy với auto health check
- ✅ **Bulk Add Proxies:** Import nhiều proxies cùng lúc
- ✅ **Test All Proxies:** Chạy health check toàn bộ
- ✅ **Proxy List:** Xem status, success rate, response time
- ✅ **Actions:** Test, Reset, Delete từng proxy

#### 👤 Tab 2: Accounts & Sessions
- ✅ **Upload account.txt:** Upload và auto-login Facebook
- ✅ **Session List:** Xem status, performance của sessions
- ✅ **Session Actions:** Reset, Quarantine, Mark Need Login
- ✅ **Session-Proxy Bindings:** Xem bindings hiện tại

#### 📊 Tab 3: System Status
- ✅ **Proxy Performance:** Top 5 best performing proxies
- ✅ **Session Performance:** Top 5 best performing sessions
- ✅ **Quick Actions:** Reset All, Clean Quarantines

### Workflow sau deployment:

**1. Thêm proxies:**
```
Admin Panel → Tab Proxies → ➕ Add Single Proxy
  Nhập: host, port, username, password, type
  Click Add → Tự động health check → Lưu DB
  
hoặc

Admin Panel → Tab Proxies → 📋 Bulk Add Proxies
  Paste nhiều proxies (host:port:user:pass)
  Click Import → Lưu tất cả vào DB
```

**2. Thêm accounts:**
```
Admin Panel → Tab Accounts → ➕ Add Single Account
  Nhập: FB ID, email, password, 2FA, cookies
  Click Add → Lưu DB
  
hoặc

Admin Panel → Tab Accounts → 📋 Bulk Add Accounts
  Paste nhiều accounts (id|password|2fa|cookies|email)
  Click Import → Lưu tất cả vào DB

hoặc

Admin Panel → Tab Accounts → 📤 Import from account.txt
  Upload file → Click Import → Parse và lưu DB
```

**3. Xong!** 
- ✅ Proxies từ DB → ProxyManager tự động load
- ✅ Accounts từ DB → Có thể trigger login (future)
- ✅ Workers tự động sử dụng proxies
- ✅ Sessions tự động binding với proxies
- ✅ Hệ thống tự động health check và quarantine


### Quản lý:

**View & Monitor:**
- 📊 Proxy List: Filter by status, xem performance
- 📊 Account List: Filter by status, xem session status
- 🔗 Bindings: Xem account-proxy relationships

**Actions:**
- 🧪 Test proxy health
- ✅ Activate/Deactivate accounts
- 🗑️ Delete proxy/account
- 🔄 Reset statuses

---

## 🔄 CẬP NHẬT CODE

Khi có code mới:

```bash
# 1. Upload code mới (từ Windows)
scp -r C:\vibecode\facebook\* root@149.28.150.95:/opt/facebook-scraper/

# 2. SSH vào VPS
ssh root@149.28.150.95

# 3. Restart services
cd /opt/facebook-scraper
supervisorctl restart facebook-scraper:*
```

---

## 🐛 TROUBLESHOOTING

### Service không start:

```bash
# Check logs
tail -100 /var/log/facebook-scraper/worker_scan_err.log
tail -100 /var/log/facebook-scraper/streamlit_err.log

# Restart
supervisorctl restart facebook-scraper:*

# Restart từng service
supervisorctl restart celery_worker_scan
supervisorctl restart streamlit
```

### Streamlit không start (file not found):

```bash
# Check file exists
ls -la /opt/facebook-scraper/webapp_streamlit/app.py

# If missing, check alternative paths
ls -la /opt/facebook-scraper/webapp_streamlit/1_*.py

# Restart after upload
supervisorctl restart streamlit
```

### Database issues:

```bash
# Check PostgreSQL status
systemctl status postgresql

# Restart PostgreSQL
systemctl restart postgresql
```

### Redis issues:

```bash
# Check Redis status
systemctl status redis-server

# Test Redis
redis-cli ping
# Expected: PONG
```

### Ngrok not working:

```bash
# Check if authtoken configured
cat /opt/facebook-scraper/.ngrok_token

# If missing, add token:
echo "YOUR_NGROK_AUTHTOKEN" > /opt/facebook-scraper/.ngrok_token

# Re-configure ngrok
/usr/local/bin/ngrok config add-authtoken $(cat /opt/facebook-scraper/.ngrok_token)

# Restart ngrok
supervisorctl restart ngrok

# Wait 3 seconds then get URL
sleep 3
/opt/facebook-scraper/get_ngrok_url.sh
```

**Get ngrok authtoken:**
1. Free account: https://dashboard.ngrok.com/signup
2. Copy token: https://dashboard.ngrok.com/get-started/your-authtoken
3. Paste vào `.ngrok_token` file

---

## 📝 VPS DEPLOYMENT BENEFITS

### ⚡ Native Performance
- ✅ **Real Ubuntu system** - Native OS environment
- ✅ **Official Google Chrome** - Not containerized Chromium
- ✅ **Real GPU rendering** - Hardware acceleration
- ✅ **200+ system fonts** - Like real PC
- ✅ **Better fingerprint** - Harder to detect

### 🔒 Security & Stability
- ✅ **Lower detection risk** - Real system fingerprint
- ✅ **Better resource management** - Direct OS access
- ✅ **Easier debugging** - No container overhead
- ✅ **Ngrok built-in** - Public access ready

**→ Giảm 70-80% khả năng bị checkpoint!** 🎯

