#!/usr/bin/env python3
"""
Script tự động đăng nhập Facebook với 2FA
Sử dụng dữ liệu từ account.txt với format: id|password|2fa_code|email|password_alt|email_alt

Phase 3.0: Tự động hóa hoàn toàn quy trình đăng nhập với xử lý 2FA
"""

import asyncio
import os
import sys
import time
import pyotp
import re
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
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

    def parse_account_file(self, account_file_path: str) -> List[Dict[str, str]]:
        """
        Parse account.txt file with format:
        id|password|2fa_secret|... (chỉ quan tâm 3 field đầu)
        
        Returns:
            List of account dictionaries
        """
        accounts = []
        try:
            with open(account_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):  # Skip empty lines and comments
                    continue
                    
                parts = line.split('|')
                if len(parts) >= 3:  # Chỉ cần 3 field đầu: id|password|2fa_secret
                    account = {
                        'id': parts[0].strip(),
                        'password': parts[1].strip(),
                        '2fa_secret': parts[2].strip(),
                        'line_number': line_num
                    }
                    accounts.append(account)
                else:
                    print(f"[WARNING] Dòng {line_num} không đúng format (cần ít nhất id|password|2fa): {line}")
                    
        except FileNotFoundError:
            print(f"[ERROR] Không tìm thấy file: {account_file_path}")
        except Exception as e:
            print(f"[ERROR] Lỗi đọc file account: {e}")
            
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
        """Setup browser with session - Enhanced with storage state loading"""
        sessions_base_dir = os.path.join(os.getcwd(), "sessions")
        user_data_dir = os.path.join(sessions_base_dir, session_name)
        storage_state_path = os.path.join(user_data_dir, "storage_state.json")
        
        # Create session directory
        os.makedirs(user_data_dir, exist_ok=True)
        print(f"[FOLDER] Su dung session folder: {user_data_dir}")
        
        # Launch browser with consistent configuration
        launch_options = get_browser_launch_options(
            user_data_dir, headless=headless
        )
        
        # ENHANCED: Load storage state nếu tồn tại
        if os.path.exists(storage_state_path):
            print(f"[SESSION] Loading saved storage state from: {storage_state_path}")
            try:
                launch_options['storage_state'] = storage_state_path
            except Exception as e:
                print(f"[WARNING] Không thể load storage state: {e}")
        
        self.browser = await self.playwright.chromium.launch_persistent_context(**launch_options)
        
        # SỬ DỤNG INIT SCRIPT CENTRALIZED - Đảm bảo anti-detection 100% nhất quán  
        await self.browser.add_init_script(get_init_script())
        
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
                print("[SUCCESS] ✅ Đăng nhập thành công!")
                
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
                print("[ERROR] ❌ Đăng nhập thất bại")
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
                except:
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
                except:
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
                except:
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
                        except:
                            continue
                    
                    break
                except:
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
                except:
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
                except:
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

    async def update_session_status(self, session_name: str):
        """Update session status in system - GIỐNG Y HỆT manual_login.py"""
        try:
            print("[UPDATE] Cap nhat session status va session-proxy binding...")
            
            from core.session_manager import SessionManager
            from core.proxy_manager import ProxyManager
            
            session_manager = SessionManager()
            proxy_manager = ProxyManager()
            
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

        except Exception as e:
            print(f"[ERROR] Khong the cap nhat session status: {e}")
            print("[INFO] Ban co the cap nhat thu cong file session_status.json.")


async def auto_login_from_file(account_file: str, account_index: Optional[int] = None, 
                              headless: bool = False):
    """
    Tự động đăng nhập từ file account.txt - GIỐNG Y HỆT manual_login.py
    
    Args:
        account_file: Path to account file
        account_index: Index of account to login (0-based), None for all accounts
        headless: Run in headless mode
    """
    print("[MANUAL_LOGIN] AUTO LOGIN MODE - PHASE 3.0 (NANG CAP)")
    print("Tu dong dang nhap Facebook voi 2FA")
    print("=" * 60)
    
    async with FacebookAutoLogin() as fb_login:
        accounts = fb_login.parse_account_file(account_file)
        
        if not accounts:
            print("[ERROR] Không tìm thấy account nào trong file")
            return False
        
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
        for i, account in enumerate(accounts_to_process):
            print(f"[PROCESS] Processing account {i+1}/{len(accounts_to_process)}: ID {account['id']}")
            
            # Generate session name using ID - GIỐNG Y HỆT manual_login.py
            session_name = account['id']  # Session name = ID
            print(f"[SESSION] Session name: {session_name}")
            
            try:
                # Setup browser for this account
                await fb_login.setup_browser(session_name, headless=headless)
                
                # Attempt login
                if await fb_login.login_facebook(account):
                    success_count += 1
                    print(f"[SUCCESS] ✅ Account ID {account['id']} login successful")
                    print(f"[SAVED] Session da duoc luu vao: sessions/{session_name}")
                    
                    # Update session status
                    await fb_login.update_session_status(session_name)
                else:
                    print(f"[ERROR] ❌ Account ID {account['id']} login failed")
                
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
        
        print(f"[RESULT] Hoàn thành! {success_count}/{len(accounts_to_process)} account(s) thành công")
        return success_count > 0


def main():
    """Main function với command line interface - GIỐNG Y HỆT manual_login.py"""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║           PHASE 3.0 - AUTO LOGIN WITH 2FA (NÂNG CẤP)         ║")
    print("║                                                              ║")
    print("║  🤖 Tự động đăng nhập Facebook với 2FA authenticator        ║")
    print("║  🔐 Tích hợp với session pool và proxy management           ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    # Parse command line arguments
    account_file = "account.txt"
    account_index = None
    headless = False
    
    if len(sys.argv) > 1:
        account_file = sys.argv[1]
    
    if len(sys.argv) > 2:
        try:
            account_index = int(sys.argv[2])
        except ValueError:
            print("[ERROR] Account index phải là số")
            return
    
    if len(sys.argv) > 3:
        headless = sys.argv[3].lower() in ['true', '1', 'yes']
    
    try:
        success = asyncio.run(
            auto_login_from_file(
                account_file=account_file,
                account_index=account_index,
                headless=headless
            )
        )
        
        if success:
            print("\n🎉 Auto login hoàn thành!")
            print("Bây giờ bạn có thể chạy các worker để sử dụng session này.")
        else:
            print("\n❌ Auto login thất bại.")
    except KeyboardInterrupt:
        print("\n⏹️ Auto login bị hủy bởi người dùng.")
    except Exception as e:
        print(f"\n💥 Lỗi: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
