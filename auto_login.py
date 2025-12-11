#!/usr/bin/env python3
"""
Script tự động đăng nhập Facebook với 2FA
Sử dụng dữ liệu từ account.txt với format:
  - Format: id|password|2fa_secret
  
Phase 3.0: Tự động hóa hoàn toàn quy trình đăng nhập với xử lý 2FA
KHÔNG SỬ DỤNG cookie injection - chỉ real login qua 2FA để tránh checkpoint
"""

import asyncio
import os
import sys
import time
import pyotp
import re
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from utils.browser_config import get_browser_launch_options, get_init_script
from typing import Optional, Dict, Any, List


class FacebookAutoLogin:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None
        
    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    def _cleanup_singleton_locks(self, user_data_dir: str):
        """
        Clean up Chrome singleton lock files to prevent "profile in use" errors
        
        This is needed because:
        - Sessions might be in use by workers
        - Chrome creates lock files that persist even after crash
        - VPS might have stale locks from previous runs
        """
        import glob
        
        lock_files = [
            'SingletonLock',
            'SingletonSocket',
            'SingletonCookie'
        ]
        
        for lock_file in lock_files:
            lock_path = os.path.join(user_data_dir, lock_file)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                    print(f"[CLEANUP] Removed lock file: {lock_file}")
                except Exception as e:
                    print(f"[WARNING] Could not remove {lock_file}: {e}")
        
        # Also clean lock files in subdirectories
        for lock_file in lock_files:
            lock_pattern = os.path.join(user_data_dir, '**', lock_file)
            for lock_path in glob.glob(lock_pattern, recursive=True):
                try:
                    os.remove(lock_path)
                    print(f"[CLEANUP] Removed nested lock: {lock_path}")
                except Exception as e:
                    print(f"[WARNING] Could not remove {lock_path}: {e}")

    def parse_account_file(self, account_file_path: str) -> List[Dict[str, str]]:
        """
        ✅ UPDATED: Đọc accounts từ DATABASE thay vì file
        
        Lấy tất cả accounts có:
        - status = ACTIVE
        - session_status = NOT_CREATED hoặc NEEDS_LOGIN
        
        Returns:
            List of account dictionaries (id, password, 2fa_secret)
        """
        accounts = []
        
        try:
            # Import DatabaseManager
            from core.database_manager import DatabaseManager
            
            db = DatabaseManager()
            
            # Lấy tất cả accounts từ database
            db_accounts = db.get_all_accounts(is_active=True)
            
            if not db_accounts:
                print(f"[SKIP] Không có accounts trong database")
                print(f"[INFO] 💡 Add accounts via Admin Panel UI instead")
                return []
            
            # Convert database accounts to format needed for auto_login
            for idx, acc in enumerate(db_accounts, 1):
                # Chỉ login những account chưa có session hoặc cần login lại
                session_status = acc.get('session_status', 'NOT_CREATED')
                if session_status in ['NOT_CREATED', 'NEEDS_LOGIN']:
                    account = {
                        'id': acc['facebook_id'],
                        'password': acc.get('password', ''),
                        '2fa_secret': acc.get('totp_secret', ''),
                        'cookies': None,  # ❌ KHÔNG dùng cookies - luôn force real login
                        'line_number': idx,
                        'db_id': acc['id']  # Store DB ID for updating later
                    }
                    
                    # Validate account has required fields
                    if not account['id']:
                        print(f"[WARNING] Account ID {acc['id']} thiếu facebook_id, skip")
                        continue
                    
                    if not account['password']:
                        print(f"[WARNING] Account {account['id']} thiếu password, skip")
                        continue
                        
                    if not account['2fa_secret']:
                        print(f"[WARNING] Account {account['id']} thiếu 2FA secret, skip")
                        continue
                    
                    accounts.append(account)
                    print(f"[DB] Loaded account {account['id']} (DB ID: {account['db_id']}, Status: {session_status})")
                else:
                    print(f"[SKIP] Account {acc['facebook_id']} already logged in (Status: {session_status})")
            
            print(f"[DB] Total accounts to login: {len(accounts)}/{len(db_accounts)}")
            
        except Exception as e:
            print(f"[ERROR] Lỗi đọc accounts từ database: {e}")
            import traceback
            traceback.print_exc()
            
        return accounts

    def generate_2fa_code(self, secret: str) -> str:
        """
        Generate 6-digit 2FA code from secret
        
        Args:
            secret: 2FA secret key
            
        Returns:
            6-digit code string
        """
        try:
            # Remove spaces and convert to uppercase
            secret = re.sub(r'\s+', '', secret.upper())
            
            # Generate TOTP code
            totp = pyotp.TOTP(secret)
            code = totp.now()
            
            print(f"[2FA] Generated 2FA code: {code}")
            return code
            
        except Exception as e:
            print(f"[ERROR] Lỗi generate 2FA code: {e}")
            # Return the original secret as fallback (in case it's already a code)
            return secret


    async def setup_browser(self, session_name: str, headless: bool = False):
        """
        Setup browser with session - Production-ready for VPS deployment
        
        FEATURES:
        1. ✅ Anti-detection mode (default=False for GUI with Xvfb)
        2. [OK] Remove storage_state param (not supported in persistent context)
        3. [OK] Clean singleton locks before launch
        4. [FINGERPRINT] Load per-session fingerprint (GenLogin/GPM style)
        """
        sessions_base_dir = os.path.join(os.getcwd(), "sessions")
        user_data_dir = os.path.join(sessions_base_dir, session_name)
        
        # Create session directory
        os.makedirs(user_data_dir, exist_ok=True)
        print(f"[FOLDER] Su dung session folder: {user_data_dir}")
        
        # [OK] FIX: Clean singleton locks before launch (prevent "profile in use" error)
        self._cleanup_singleton_locks(user_data_dir)
        
        # [FINGERPRINT] RE-GENERATE fingerprint with current age (for evolution)
        session_fingerprint = None
        proxy_config = None
        
        try:
            from core.session_manager import SessionManager
            from core.proxy_manager import ProxyManager
            from core.session_proxy_binder import SessionProxyBinder
            from utils.browser_config import generate_session_fingerprint
            from datetime import datetime
            
            session_manager = SessionManager()
            session_resource = session_manager.resource_pool.get(session_name)
            
            if session_resource:
                # ✅ RE-GENERATE fingerprint with CURRENT age (not cached)
                days_since_creation = 0
                if session_resource.created_at:
                    days_since_creation = (datetime.now() - session_resource.created_at).days
                
                session_fingerprint = generate_session_fingerprint(
                    session_name,
                    days_since_creation=days_since_creation
                )
                
                print(f"[FINGERPRINT] Regenerated for {session_name} (age: {days_since_creation} days): "
                      f"WebGL={session_fingerprint.get('webgl', {}).get('vendor', 'N/A')}, "
                      f"Screen={session_fingerprint.get('hardware', {}).get('screen_width', 'N/A')}x{session_fingerprint.get('hardware', {}).get('screen_height', 'N/A')}")
            else:
                print(f"[FINGERPRINT] [WARN] No session resource for {session_name}")
            
            # [PROXY] PHASE 3: Load proxy binding (CRITICAL for IP consistency!)
            from core.database_manager import DatabaseManager
            db = DatabaseManager()
            proxy_manager = ProxyManager(db_manager=db)
            binder = SessionProxyBinder(db_manager=db)
            
            # Get available proxies
            available_proxies = proxy_manager.get_healthy_proxy_ids()
            
            if available_proxies:
                # Get bound proxy for session
                bound_proxy_id = binder.get_proxy_for_session(session_name, available_proxies)
                
                if bound_proxy_id:
                    # ✅ FIX: Get proxy from database instead of using get_proxy_config (method doesn't exist)
                    try:
                        from core.database_manager import DatabaseManager
                        db = DatabaseManager()
                        # Extract proxy ID number from proxy_id string (e.g., "proxy_2" -> 2)
                        proxy_id_num = int(bound_proxy_id.split('_')[1]) if '_' in bound_proxy_id else int(bound_proxy_id)
                        proxy_data = db.get_proxy_by_id(proxy_id_num)
                        
                        if proxy_data:
                            proxy_config = {
                                'host': proxy_data['host'],
                                'port': proxy_data['port'],
                                'username': proxy_data.get('username'),
                                'password': proxy_data.get('password'),
                                'type': proxy_data.get('proxy_type', 'http'),
                                'proxy_id': bound_proxy_id
                            }
                            print(f"[PROXY] Using bound proxy: {bound_proxy_id} ({proxy_config['host']}:{proxy_config['port']})")
                        else:
                            proxy_config = None
                            print(f"[PROXY/WARN] Proxy {bound_proxy_id} not found in database")
                    except Exception as e:
                        print(f"[PROXY/ERROR] Error loading proxy config: {e}")
                        proxy_config = None
                    
                    if proxy_config:
                        # [PROXY] PHASE 3: Inject proxy geolocation into fingerprint
                        if session_fingerprint and bound_proxy_id in proxy_manager.resource_pool:
                            proxy_resource = proxy_manager.resource_pool[bound_proxy_id]
                            proxy_geo = proxy_resource.metadata.get('geolocation')
                            
                            if proxy_geo:
                                # ✅ STRICT VALIDATION: REJECT if geolocation invalid
                                required_fields = ['latitude', 'longitude', 'timezone', 'country']
                                missing_fields = [f for f in required_fields if not proxy_geo.get(f)]
                                
                                if missing_fields:
                                    error_msg = f"Proxy {bound_proxy_id} geolocation incomplete (missing: {missing_fields}) - ABORTING"
                                    print(f"[PROXY] [ERROR] {error_msg}")
                                    raise Exception(error_msg)
                                
                                # Validate coordinate ranges
                                lat = proxy_geo.get('latitude')
                                lng = proxy_geo.get('longitude')
                                
                                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                                    error_msg = f"Invalid proxy coordinates: lat={lat}, lng={lng} - ABORTING"
                                    print(f"[PROXY] [ERROR] {error_msg}")
                                    raise Exception(error_msg)
                                
                                # ✅ Valid - apply to fingerprint
                                session_fingerprint['timezone'] = proxy_geo['timezone']
                                session_fingerprint['geolocation'] = {
                                    'latitude': lat,
                                    'longitude': lng,
                                    'accuracy': 100
                                }
                                print(f"[PROXY] ✅ Validated geo: {proxy_geo.get('city')}, {proxy_geo.get('country')} (TZ: {proxy_geo['timezone']})")
                            else:
                                # ❌ NO geolocation - ABORT
                                error_msg = f"Proxy {bound_proxy_id} has NO geolocation data - ABORTING"
                                print(f"[PROXY] [ERROR] {error_msg}")
                                raise Exception(error_msg)
                    else:
                        print(f"[PROXY] [WARN] Could not get config for proxy {bound_proxy_id}")
                else:
                    print(f"[PROXY] [WARN] No bound proxy for {session_name}, using direct connection")
            else:
                print(f"[PROXY] [WARN] No available proxies, using direct connection")
                
        except Exception as e:
            print(f"[FINGERPRINT/PROXY] [ERROR] Error: {e}")
        
        # 🔒 ANTI-DETECTION: Inject unique machine ID per session BEFORE browser launch
        try:
            from utils.browser_config import generate_unique_machine_id, inject_machine_id_to_local_state
            from datetime import datetime
            
            # Generate deterministic machine ID (use current time for new sessions)
            creation_date = datetime.now() if not os.path.exists(os.path.join(user_data_dir, "Local State")) else None
            machine_id = generate_unique_machine_id(session_name, creation_date)
            
            # Inject into Chromium Local State BEFORE browser reads it
            inject_machine_id_to_local_state(user_data_dir, machine_id)
            print(f"[MACHINE-ID] Injected unique ID for {session_name}: {machine_id[:13]}...")
        except Exception as e:
            print(f"[MACHINE-ID] [WARN] Failed to inject (non-critical): {e}")
        
        # Launch browser with consistent configuration
        # [PROXY] CRITICAL FIX: Use SAME proxy as multi_queue_worker for IP consistency!
        launch_options = get_browser_launch_options(
            user_data_dir, 
            headless=headless,
            proxy_config=proxy_config,  # [PROXY] PHASE 3: Use bound proxy!
            session_fingerprint=session_fingerprint  # [FINGERPRINT] Apply fingerprint
        )
        
        # [OK] FIX: DON'T add storage_state to launch_options
        # Persistent context auto-saves state to user_data_dir
        # storage_state parameter is NOT supported in launch_persistent_context()
        
        self.browser = await self.playwright.chromium.launch_persistent_context(**launch_options)
        
        # [FINGERPRINT] Use centralized init script with fingerprint - GenLogin/GPM style
        await self.browser.add_init_script(get_init_script(session_fingerprint))
        print(f"[FINGERPRINT] Applied advanced anti-detect fingerprint")
        
        # Get or create page
        self.page = self.browser.pages[0] if self.browser.pages else await self.browser.new_page()

    async def login_facebook(self, account: Dict[str, str]) -> bool:
        """
        Tự động đăng nhập Facebook với account data - GIỐNG Y HỆT manual_login.py
        
        Args:
            account: Dictionary chứa thông tin account
            
        Returns:
            True if login successful, False otherwise
        """
        try:
            print(f"[LOGIN] Bắt đầu đăng nhập account ID: {account['id']}")
            
            # Navigate to Facebook - giống manual_login.py
            await self.page.goto('https://www.facebook.com/')
            await asyncio.sleep(2)
            
            # ENHANCED: Try refresh session first
            if await self.refresh_session_if_needed():
                print("[SUCCESS] Session còn valid, không cần đăng nhập lại")
                return True
            
            # Check if already logged in (backup check)
            if await self.is_logged_in():
                print("[SUCCESS] Đã đăng nhập từ session trước đó")
                return True
            
            # Step 1: Fill ID and password (KHÔNG PHẢI EMAIL)
            await self.fill_login_form(account['id'], account['password'])
            
            # Step 2: Handle 2FA if needed
            if await self.handle_2fa_flow(account['2fa_secret']):
                print("[2FA] Xử lý 2FA thành công")
            else:
                print("[2FA] Không cần 2FA hoặc có lỗi xử lý 2FA")
            
            # Step 3: Handle post-login dialogs
            await self.handle_post_login_dialogs()
            
            # Step 4: Verify login success - Enhanced with storage state saving
            if await self.is_logged_in():
                print("[SUCCESS] Login successful!")
                
                # ENHANCED: Explicitly save cookies and storage state
                try:
                    sessions_base_dir = os.path.join(os.getcwd(), "sessions")
                    user_data_dir = os.path.join(sessions_base_dir, account['id'])
                    storage_state_path = os.path.join(user_data_dir, "storage_state.json")
                    
                    await self.page.context.storage_state(path=storage_state_path)
                    print(f"[STORAGE] Storage state saved to: {storage_state_path}")
                    
                    # Wait để browser lưu toàn bộ data
                    await asyncio.sleep(3)
                    
                except Exception as e:
                    print(f"[WARNING] Không thể lưu storage state: {e}")
                
                return True
            else:
                print("[ERROR] Login failed")
                return False
                
        except Exception as e:
            print(f"[ERROR] Lỗi trong quá trình đăng nhập: {e}")
            return False

    async def fill_login_form(self, user_id: str, password: str):
        """Fill login form and submit - Dùng ID thay vì email"""
        try:
            # Wait for login form
            await self.page.wait_for_selector('input[name="email"]', timeout=10000)
            
            # Fill ID (vào field email)
            await self.page.fill('input[name="email"]', user_id)
            await asyncio.sleep(0.5)
            
            # Fill password  
            await self.page.fill('input[name="pass"]', password)
            await asyncio.sleep(0.5)
            
            # Click login button
            login_button = await self.page.wait_for_selector(
                'button[name="login"], input[name="login"]', timeout=5000
            )
            await login_button.click()
            
            print("[LOGIN] Đã submit form đăng nhập")
            await asyncio.sleep(3)  # Wait for response
            
        except Exception as e:
            print(f"[ERROR] Lỗi fill login form: {e}")
            raise

    async def handle_2fa_flow(self, secret_2fa: str) -> bool:
        """Handle 2FA authentication flow"""
        try:
            # Wait a bit to see if 2FA is required
            await asyncio.sleep(2)
            
            # Check if "Try Another Way" button exists
            try_another_way_selectors = [
                'text="Try Another Way"',
                'text="Thử cách khác"',
                '[role="button"]:has-text("Try Another Way")',
                '[role="button"]:has-text("Thử cách khác")'
            ]
            
            try_another_way_found = False
            for selector in try_another_way_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.click(selector)
                    print("[2FA] Clicked 'Try Another Way'")
                    try_another_way_found = True
                    await asyncio.sleep(2)
                    break
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
            
            # Look for Authentication App option
            auth_app_selectors = [
                'text="Authentication app"',
                'text="Ứng dụng xác thực"',
                '[role="radio"]:has-text("Authentication app")',
                '[role="radio"]:has-text("Ứng dụng xác thực")'
            ]
            
            auth_app_found = False
            for selector in auth_app_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.click(selector)
                    print("[2FA] Selected 'Authentication app'")
                    auth_app_found = True
                    await asyncio.sleep(1)
                    break
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
            
            # Click Continue button
            continue_selectors = [
                'text="Continue"',
                'text="Tiếp tục"',
                '[role="button"]:has-text("Continue")',
                '[role="button"]:has-text("Tiếp tục")'
            ]
            
            for selector in continue_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.click(selector)
                    print("[2FA] Clicked 'Continue'")
                    await asyncio.sleep(2)
                    break
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
            
            # Look for 2FA code input field
            code_input_selectors = [
                'input[placeholder*="Code"]',
                'input[placeholder*="Mã"]',
                'input[type="text"][autocomplete="off"]',
                'input[id*="code"]',
                'input[name*="code"]'
            ]
            
            code_input_found = False
            for selector in code_input_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    
                    # Generate 2FA code
                    totp_code = self.generate_2fa_code(secret_2fa)
                    
                    # Fill 2FA code
                    await self.page.fill(selector, totp_code)
                    print(f"[2FA] Nhập mã 2FA: {totp_code}")
                    code_input_found = True
                    await asyncio.sleep(1)
                    
                    # Click Continue/Submit after entering code
                    for continue_selector in continue_selectors:
                        try:
                            await self.page.wait_for_selector(continue_selector, timeout=2000)
                            await self.page.click(continue_selector)
                            print("[2FA] Clicked Continue after 2FA code")
                            await asyncio.sleep(3)
                            break
                        except (PlaywrightTimeoutError, PlaywrightError):
                            continue
                    
                    break
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
            
            return code_input_found
            
        except Exception as e:
            print(f"[ERROR] Lỗi xử lý 2FA: {e}")
            return False

    async def handle_post_login_dialogs(self):
        """Handle dialogs that appear after login"""
        try:
            # Handle "Save your password" dialog
            save_selectors = [
                'text="Save"',
                'text="Lưu"',
                '[role="button"]:has-text("Save")',
                '[role="button"]:has-text("Lưu")'
            ]
            
            for selector in save_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.click(selector)
                    print("[DIALOG] Clicked 'Save' for password dialog")
                    await asyncio.sleep(2)
                    break
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
            
            # Handle "Trust this device" dialog
            trust_selectors = [
                'text="Trust this device"',
                'text="Tin cậy thiết bị này"',
                '[role="button"]:has-text("Trust this device")',
                '[role="button"]:has-text("Tin cậy thiết bị này")'
            ]
            
            for selector in trust_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.click(selector)
                    print("[DIALOG] Clicked 'Trust this device'")
                    await asyncio.sleep(2)
                    break
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
            
        except Exception as e:
            print(f"[ERROR] Lỗi xử lý post-login dialogs: {e}")

    async def is_logged_in(self) -> bool:
        """Check if user is logged in to Facebook - Enhanced with refresh logic"""
        try:
            print("[VERIFY] Dang xac thuc trang thai dang nhap...")
            login_successful = False
            
            # ENHANCED: Refresh page trước khi check
            current_url = self.page.url
            if "facebook.com/login" not in current_url and "facebook.com" in current_url:
                # Đã ở Facebook nhưng không phải trang login
                await self.page.reload()
                await asyncio.sleep(3)
            
            # Danh sach cac "dau hieu" da dang nhap thanh cong
            logged_in_indicators = [
                '[aria-label="Trang chu"]',      # Nut Home (Tieng Viet)
                '[aria-label="Home"]',           # Nut Home (Tieng Anh)
                'div[role="navigation"]',        # Thanh dieu huong chinh
                'div[aria-label="Tai khoan"]',   # Icon tai khoan (Tieng Viet)
                'div[aria-label="Account"]',     # Icon tai khoan (Tieng Anh)
                'a[href="/marketplace/"]',       # Link den Marketplace
                '[data-testid="search"]'         # O tim kiem (fallback)
            ]
            
            # ENHANCED: Increase wait time
            await asyncio.sleep(3)  # Tăng từ 2 lên 3
            
            for indicator in logged_in_indicators:
                try:
                    # ENHANCED: Tăng timeout lên 7 giây cho chắc chắn
                    await self.page.wait_for_selector(
                        indicator, timeout=7000, state='visible'  # Tăng từ 5000 lên 7000
                    )
                    print(f"[SUCCESS] Xac nhan thanh cong voi dau hieu: {indicator}")
                    login_successful = True
                    break  # Tim thay mot dau hieu la du -> thoat vong lap
                except Exception:
                    print(f"   ... khong tim thay dau hieu: {indicator}")
                    continue  # Thu dau hieu tiep theo
            
            if not login_successful:
                current_url = self.page.url
                print(
                    f"[WARNING] Duong nhu chua dang nhap thanh cong. "
                    f"URL hien tai: {current_url}"
                )
            
            return login_successful
            
        except Exception as e:
            print(f"[ERROR] Lỗi kiểm tra trạng thái đăng nhập: {e}")
            return False

    async def refresh_session_if_needed(self) -> bool:
        """Refresh session nếu cần thiết"""
        try:
            # Navigate to Facebook home
            await self.page.goto('https://www.facebook.com/', wait_until='networkidle')
            await asyncio.sleep(3)

            # Check if still logged in
            if await self.is_logged_in():
                return True

            # Try to refresh by navigating to profile
            await self.page.goto('https://www.facebook.com/me', wait_until='networkidle')
            await asyncio.sleep(2)

            # Check again
            return await self.is_logged_in()

        except Exception as e:
            print(f"[ERROR] Lỗi refresh session: {e}")
            return False
    
    def _is_session_valid(self, session_name: str) -> bool:
        """
        Check if session folder exists and has required files
        
        [OK] FIX CRITICAL: Also check session_status.json to detect NEEDS_LOGIN!
        
        Args:
            session_name: Session folder name
            
        Returns:
            True if session appears valid AND not marked as NEEDS_LOGIN
        """
        try:
            sessions_base_dir = os.path.join(os.getcwd(), "sessions")
            session_path = os.path.join(sessions_base_dir, session_name)
            
            # Check if session folder exists
            if not os.path.exists(session_path):
                return False
            
            # Check for required Chromium session files
            required_files = ['Local State', 'Default']
            for required_file in required_files:
                file_path = os.path.join(session_path, required_file)
                if not os.path.exists(file_path):
                    return False
            
            # Optional: Check if session has cookies
            cookies_path = os.path.join(session_path, 'Default', 'Cookies')
            network_cookies = os.path.join(session_path, 'Default', 'Network', 'Cookies')
            
            has_cookies = os.path.exists(cookies_path) or os.path.exists(network_cookies)
            
            if not has_cookies:
                return False
            
            # [OK] CRITICAL FIX: Check session_status.json to detect NEEDS_LOGIN/QUARANTINED
            try:
                import json
                status_file = 'session_status.json'
                if os.path.exists(status_file):
                    with open(status_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    
                    # Check if session exists in status file
                    if session_name in session_data:
                        session_status = session_data[session_name].get('status', 'UNKNOWN')
                        
                        # Session is INVALID if status is NEEDS_LOGIN, QUARANTINED, or DISABLED
                        if session_status in ['NEEDS_LOGIN', 'QUARANTINED', 'DISABLED']:
                            print(f"[CHECK] Session {session_name} status: {session_status} - NEEDS RE-LOGIN")
                            return False
                        
                        print(f"[CHECK] Session {session_name} status: {session_status} - OK")
                    else:
                        print(f"[CHECK] Session {session_name} not found in session_status.json - assuming VALID")
            except Exception as status_err:
                print(f"[WARNING] Could not check session_status.json: {status_err}")
                # If can't read status file, fallback to folder check only
            
            return True
            
        except Exception as e:
            print(f"[WARNING] Error checking session validity for {session_name}: {e}")
            return False

    async def update_session_status(self, session_name: str, db_account_id: int = None):
        """Update session status in system - UPDATED: Also update database"""
        try:
            print("[UPDATE] Cap nhat session status va session-proxy binding...")
            
            from core.session_manager import SessionManager
            from core.proxy_manager import ProxyManager
            from core.database_manager import DatabaseManager
            from datetime import datetime
            
            session_manager = SessionManager()
            proxy_manager = ProxyManager()
            db = DatabaseManager()
            
            # CONSISTENT: Cap nhat session status voi binding system - GIỐNG Y HỆT manual_login.py
            proxy_stats = proxy_manager.get_stats()
            if proxy_stats.get('ready', 0) > 0:
                print("[BINDING] Dang tao session-proxy binding...")

                # Get available proxy IDs
                available_proxy_ids = []
                for proxy_id, proxy_resource in proxy_manager.resource_pool.items():
                    if proxy_resource.status == "READY" and not proxy_resource.is_quarantined():
                        available_proxy_ids.append(proxy_id)

                if available_proxy_ids:
                    # FIXED: Tạo binding trực tiếp cho session này
                    bound_proxy_id = session_manager.proxy_binder.get_proxy_for_session(
                        session_name, available_proxy_ids
                    )

                    if bound_proxy_id:
                        # Update session status to READY
                        session_manager.checkin_session(session_name, "READY")
                        print(f"[BOUND] Session '{session_name}' da duoc bind voi proxy {bound_proxy_id}")
                    else:
                        print("[WARNING] Khong the tao binding, su dung separate checkin")
                        session_manager.checkin_session(session_name, "READY")
                else:
                    print("[WARNING] Khong co proxy san sang, su dung separate checkin")
                    session_manager.checkin_session(session_name, "READY")
            else:
                print("[WARNING] Khong co proxy available, su dung separate checkin")
                session_manager.checkin_session(session_name, "READY")
            
            print(f"[READY] Session '{session_name}' da duoc cap nhat thanh 'READY' trong pool.")
            
            # ✅ UPDATE DATABASE: Update accounts table with session info
            if db_account_id:
                session_folder = f"sessions/{session_name}"
                success = db.update_account_session(
                    account_id=db_account_id,
                    session_folder=session_folder,
                    session_status='LOGGED_IN',
                    last_login_at=datetime.now()
                )
                if success:
                    print(f"[DB] ✅ Updated database for account {db_account_id}: session_status='LOGGED_IN'")
                else:
                    print(f"[DB] ⚠️  Failed to update database for account {db_account_id}")

        except Exception as e:
            print(f"[ERROR] Khong the cap nhat session status: {e}")
            print("[INFO] Ban co the cap nhat thu cong file session_status.json.")


async def auto_login_from_file(account_file: str, account_index: Optional[int] = None, 
                              headless: bool = False, skip_existing: bool = True):
    """
    Tự động đăng nhập từ file account.txt - ENHANCED for Docker
    
    Args:
        account_file: Path to account file
        account_index: Index of account to login (0-based), None for all accounts
        headless: Run in headless mode (False = GUI mode for anti-detection)
        skip_existing: Skip accounts that already have valid sessions
    """
    print("[AUTO_LOGIN] AUTO LOGIN MODE - PHASE 3.0 (PRODUCTION)")
    print(f"Headless: {headless} | Skip existing: {skip_existing}")
    print("=" * 60)
    
    async with FacebookAutoLogin() as fb_login:
        # ✅ UPDATED: Không cần check file nữa vì parse_account_file() đọc từ database
        # Vẫn truyền account_file param để giữ backward compatibility
        print(f"[DB] Loading accounts from database...")
        accounts = fb_login.parse_account_file(account_file)
        
        if not accounts:
            print("[INFO] Không có account nào cần login (database trống hoặc tất cả đã login)")
            return True  # Not an error - just nothing to do
        
        print(f"[INFO] Tim thay {len(accounts)} account(s)")
        
        # Determine which accounts to process
        if account_index is not None:
            if 0 <= account_index < len(accounts):
                accounts_to_process = [accounts[account_index]]
            else:
                print(f"[ERROR] Account index {account_index} không hợp lệ")
                return False
        else:
            accounts_to_process = accounts
        
        success_count = 0
        skipped_count = 0
        
        for i, account in enumerate(accounts_to_process):
            print(f"[PROCESS] Processing account {i+1}/{len(accounts_to_process)}: ID {account['id']}")
            
            # Generate session name using ID
            session_name = account['id']  # Session name = ID
            print(f"[SESSION] Session name: {session_name}")
            
            # Check if session already exists and is valid
            if skip_existing and fb_login._is_session_valid(session_name):
                print(f"[SKIP] Session {session_name} already exists and valid, skipping login")
                skipped_count += 1
                success_count += 1  # Count as success
                continue
            
            try:
                # [FIX] CREATE BINDING BEFORE SETUP BROWSER (for IP consistency)
                try:
                    from core.session_proxy_binder import SessionProxyBinder
                    from core.proxy_manager import ProxyManager
                    
                    # Initialize managers
                    from core.database_manager import DatabaseManager
                    db = DatabaseManager()
                    binder = SessionProxyBinder(db_manager=db)
                    proxy_mgr = ProxyManager(db_manager=db)
                    
                    # Get available healthy proxies
                    healthy_proxy_ids = proxy_mgr.get_healthy_proxy_ids(force_check=False)
                    
                    if healthy_proxy_ids:
                        # Check if session already has binding
                        existing_binding = binder.bindings_cache.get(session_name)
                        
                        if not existing_binding:
                            # ✅ FIX: Chọn proxy chưa được bind (tránh duplicate)
                            all_bindings = binder.get_all_bindings()
                            already_bound_proxies = set(all_bindings.values())
                            
                            # Tìm proxy chưa được bind
                            available_proxy = None
                            for proxy_candidate in healthy_proxy_ids:
                                if proxy_candidate not in already_bound_proxies:
                                    available_proxy = proxy_candidate
                                    break
                            
                            # Fallback: nếu tất cả đã bind, reuse proxy (round-robin)
                            if not available_proxy:
                                available_proxy = healthy_proxy_ids[0]
                                print(f"[PRE-BINDING] ⚠️  All proxies bound, reusing {available_proxy}")
                            
                            # ✅ FIX RACE: Use atomic method instead of direct cache access
                            if binder.bind_session_atomic(session_name, available_proxy):
                                print(f"[PRE-BINDING] ✅ Created binding: {session_name} → {available_proxy}")
                            else:
                                print(f"[PRE-BINDING] ❌ Failed to create binding for {session_name}")
                        else:
                            print(f"[PRE-BINDING] Using existing: {session_name} → {existing_binding}")
                    else:
                        # ❌ KHÔNG CHO PHÉP LOGIN KHÔNG PROXY!
                        # Lý do: IP inconsistency → Account ban 100%
                        print(f"[PRE-BINDING] ❌ ABORT: No healthy proxies available!")
                        print(f"[PRE-BINDING] ❌ Cannot login without proxy - IP inconsistency = account ban!")
                        print(f"[PRE-BINDING] ❌ Skipping account {account['id']}")
                        continue  # Skip this account
                except Exception as bind_error:
                    print(f"[PRE-BINDING] ⚠️  Could not create pre-binding: {bind_error}")
                
                # Setup browser for this account (will use the binding we just created)
                await fb_login.setup_browser(session_name, headless=headless)
                
                # ❌ KHÔNG BAO GIỜ INJECT COOKIES CŨ!
                # ✅ CHỈ DÙNG 2FA LOGIN - AN TOÀN 100%
                # Lý do:
                # 1. Cookies cũ đã expire → Failed login → Suspicions++
                # 2. Cookie injection sau launch_persistent_context → Conflict
                # 3. IP inconsistency (cookies từ IP A, request từ IP B) → Account ban
                
                print(f"[LOGIN] Starting REAL login for {account['id']} (2FA method - safest)")
                login_success = False
                
                # Attempt REAL login via 2FA (no cookie shortcuts!)
                if await fb_login.login_facebook(account):
                    login_success = True
                    print(f"[SUCCESS] Account ID {account['id']} login successful via 2FA")
                else:
                    print(f"[ERROR] Account ID {account['id']} login failed")
                
                if login_success:
                    success_count += 1
                    print(f"[SAVED] Session saved to: sessions/{session_name}")
                    
                    # Update session status (session_status.json + database)
                    await fb_login.update_session_status(session_name, db_account_id=account.get('db_id'))
                    
                    # [FIX] AUTO-CREATE BINDING with proxy
                    try:
                        from core.session_proxy_binder import SessionProxyBinder
                        from core.proxy_manager import ProxyManager
                        
                        # Initialize managers
                        from core.database_manager import DatabaseManager
                        db = DatabaseManager()
                        binder = SessionProxyBinder(db_manager=db)
                        proxy_mgr = ProxyManager(db_manager=db)
                        
                        # Get available healthy proxy IDs
                        healthy_proxy_ids = proxy_mgr.get_healthy_proxy_ids(force_check=False)
                        
                        if healthy_proxy_ids:
                            # ✅ FIX: Chọn proxy chưa được bind (tránh duplicate)
                            all_bindings = binder.get_all_bindings()
                            already_bound_proxies = set(all_bindings.values())
                            
                            # Tìm proxy chưa được bind
                            available_proxy = None
                            for proxy_candidate in healthy_proxy_ids:
                                if proxy_candidate not in already_bound_proxies:
                                    available_proxy = proxy_candidate
                                    break
                            
                            # Fallback: nếu tất cả đã bind, reuse proxy (round-robin)
                            if not available_proxy:
                                available_proxy = healthy_proxy_ids[0]
                                print(f"[BINDING] ⚠️  All proxies bound, reusing {available_proxy}")
                            
                            # ✅ FIX RACE: Use atomic method instead of direct cache access
                            if binder.bind_session_atomic(session_name, available_proxy):
                                print(f"[BINDING] ✅ Session {session_name} → {available_proxy}")
                            else:
                                print(f"[BINDING] ❌ Failed to bind {session_name}")
                        else:
                            print(f"[WARN] No healthy proxies available for binding")
                    except Exception as bind_error:
                        print(f"[WARN] Could not create binding: {bind_error}")
                
                # Close browser for this account
                if fb_login.browser:
                    await fb_login.browser.close()
                    fb_login.browser = None
                
            except Exception as e:
                print(f"[ERROR] Error processing account ID {account['id']}: {e}")
                
            # ENHANCED: Add delay between accounts
            if len(accounts_to_process) > 1:
                print("[WAIT] Waiting 10 seconds before next account...")  # Tăng từ 5 lên 10
                await asyncio.sleep(10)  # Tăng từ 5 lên 10
        
        # Print summary
        print("")
        print("=" * 60)
        print("[RESULT] AUTO LOGIN SUMMARY")
        print("=" * 60)
        print(f"Total accounts processed: {len(accounts_to_process)}")
        print(f"[OK] Successful logins: {success_count - skipped_count}")
        print(f"[SKIP] Skipped (already valid): {skipped_count}")
        print(f"[FAIL] Failed: {len(accounts_to_process) - success_count}")
        print("=" * 60)
        
        return success_count > 0


def main():
    """Main function với command line interface - Production ready"""
    print("=" * 70)
    print("        FACEBOOK POST MONITOR - ENTERPRISE EDITION")
    print("         PHASE 3.0 - AUTO LOGIN WITH 2FA (PRODUCTION)")
    print("")
    print("  Auto login Facebook with 2FA authenticator")
    print("  Integrated with session pool and proxy management")
    print("  VPS-optimized with skip existing sessions")
    print("=" * 70)
    print()
    
    # Parse command line arguments
    # Usage: python auto_login.py [account.txt] [index|all] [headless] [skip_existing]
    account_file = "account.txt"
    account_index = None
    headless = False  # ✅ FIX: Default False for anti-detection (use Xvfb on VPS)
    skip_existing = True  # [OK] Default skip existing for efficiency
    
    if len(sys.argv) > 1:
        account_file = sys.argv[1]
    
    if len(sys.argv) > 2:
        arg = sys.argv[2].lower()
        if arg == 'all':
            account_index = None  # Login all accounts
        else:
            try:
                account_index = int(arg)
            except ValueError:
                print(f"[ERROR] Account index must be a number or 'all', got: {arg}")
                sys.exit(1)
    
    if len(sys.argv) > 3:
        headless = sys.argv[3].lower() in ['true', '1', 'yes']
    
    if len(sys.argv) > 4:
        skip_existing = sys.argv[4].lower() in ['true', '1', 'yes']
    
    print(f"[CONFIG] Account file: {account_file}")
    print(f"[CONFIG] Account index: {'all' if account_index is None else account_index}")
    print(f"[CONFIG] Headless: {headless}")
    print(f"[CONFIG] Skip existing: {skip_existing}")
    print()
    
    try:
        success = asyncio.run(
            auto_login_from_file(
                account_file=account_file,
                account_index=account_index,
                headless=headless,
                skip_existing=skip_existing
            )
        )
        
        if success:
            print("\n[SUCCESS] Auto login completed!")
            print("Now you can run workers to use this session.")
            sys.exit(0)  # Success exit code
        else:
            print("\n[FAIL] Auto login failed - no successful sessions!")
            sys.exit(1)  # Failure exit code
            
    except KeyboardInterrupt:
        print("\n[CANCEL] Auto login cancelled by user.")
        sys.exit(130)  # Standard exit code for Ctrl+C
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)  # Error exit code


if __name__ == "__main__":
    main()
