#!/usr/bin/env python3
"""
Script đăng nhập thủ công để tránh verification
Sử dụng khi bị Facebook yêu cầu verification

Phase 3.0: Có thể lưu session vào thư mục cụ thể cho session pool
** NÂNG CẤP: Sử dụng cấu hình trình duyệt nâng cao
để tránh bị kẹt ở màn hình 2FA **
"""

import asyncio
import os
import sys
from playwright.async_api import async_playwright
from utils.browser_config import get_browser_launch_options, get_init_script
from typing import Optional


async def manual_login(session_name: Optional[str] = None):
    """
    Đăng nhập thủ công để lưu session
    
    Args:
        session_name: Tên session để lưu vào sessions/ folder
    """
    print("🔐 MANUAL LOGIN MODE - PHASE 3.0 (NÂNG CẤP)")
    print("Tạo session cho session pool với trình duyệt chống phát hiện")
    print("=" * 60)

    # Xác định session name
    if not session_name:
        print("📝 Session name chưa được chỉ định")
        session_name = input("Nhập session name (vd: account_1): ").strip()

        if not session_name:
            print("❌ Tên session không được để trống. Thoát.")
            return False

    print(f"🏷️ Session name: {session_name}")

    playwright = await async_playwright().start()

    # Xác định thư mục lưu session
    sessions_base_dir = os.path.join(os.getcwd(), "sessions")
    user_data_dir = os.path.join(sessions_base_dir, session_name)

    # Tạo thư mục nếu chưa có
    os.makedirs(user_data_dir, exist_ok=True)
    print(f"📁 Sử dụng session folder: {user_data_dir}")

    # 🔧 SỬ DỤNG BROWSER CONFIG CENTRALIZED - Đảm bảo consistency 100%
    launch_options = get_browser_launch_options(
        user_data_dir, headless=False
    )
    browser = await playwright.chromium.launch_persistent_context(**launch_options)

    # 🔧 SỬ DỤNG INIT SCRIPT CENTRALIZED - Đảm bảo anti-detection 100% nhất quán
    await browser.add_init_script(get_init_script())

    # Mở trang Facebook
    page = browser.pages[0] if browser.pages else await browser.new_page()
    await page.goto('https://www.facebook.com/')

    print("\n📋 Hướng dẫn:")
    print("1. Trình duyệt đã mở. Vui lòng đăng nhập Facebook trên đó.")
    print("2. Xử lý mọi yêu cầu xác thực (mã 2FA, reCAPTCHA, v.v.).")
    print(
        "3. Đảm bảo bạn đã vào được trang chủ "
        "(news feed) của Facebook."
    )
    print("4. Sau khi đăng nhập thành công, quay lại đây và nhấn Enter để lưu session.")

    input("\n>>> Nhấn Enter sau khi đăng nhập xong...")

    # --- THAY ĐỔI BẮT ĐẦU ---
    # Kiểm tra đăng nhập một cách tin cậy hơn
    print("\n🔍 Đang xác thực trạng thái đăng nhập...")
    login_successful = False

    # Danh sách các "dấu hiệu" đã đăng nhập thành công
    logged_in_indicators = [
        '[aria-label="Trang chủ"]',      # Nút Home (Tiếng Việt)
        '[aria-label="Home"]',           # Nút Home (Tiếng Anh)
        'div[role="navigation"]',        # Thanh điều hướng chính
        'div[aria-label="Tài khoản"]',   # Icon tài khoản (Tiếng Việt)
        'div[aria-label="Account"]',     # Icon tài khoản (Tiếng Anh)
        'a[href="/marketplace/"]',       # Link đến Marketplace
        '[data-testid="search"]'         # Ô tìm kiếm (fallback)
    ]

    # Cho page thêm thời gian để tải
    await asyncio.sleep(2)

    for indicator in logged_in_indicators:
        try:
            # Tăng timeout lên 10 giây cho chắc chắn
            await page.wait_for_selector(
                indicator, timeout=5000, state='visible'
            )
            print(f"✅ Xác nhận thành công với dấu hiệu: {indicator}")
            login_successful = True
            break  # Tìm thấy một dấu hiệu là đủ -> thoát vòng lặp
        except Exception:
            print(f"   ... không tìm thấy dấu hiệu: {indicator}")
            continue  # Thử dấu hiệu tiếp theo

    if not login_successful:
        current_url = page.url
        print(
            f"⚠️ Dường như chưa đăng nhập thành công. "
            f"URL hiện tại: {current_url}"
        )
        print(
            "Vui lòng thử lại. Đảm bảo bạn đã vào được "
            "trang chủ Facebook."
        )
    # --- THAY ĐỔI KẾT THÚC ---

    if login_successful:
        print("\n✅ Đăng nhập thành công!")
        print(f"📁 Session đã được lưu vào: {user_data_dir}")
        print("🔄 Cập nhật session status và session-proxy binding...")

        # 🔗 CONSISTENT: Cập nhật session status với binding system
        try:
            from core.session_manager import SessionManager
            from core.proxy_manager import ProxyManager
            
            session_manager = SessionManager()
            proxy_manager = ProxyManager()
            
            # Kiểm tra xem có proxy available không để tạo binding
            proxy_stats = proxy_manager.get_stats()
            if proxy_stats.get('ready', 0) > 0:
                print("🔗 Đang tạo session-proxy binding...")
                # Sử dụng checkout mechanism để tạo binding
                result = session_manager.checkout_session_with_proxy(proxy_manager, timeout=10)
                if result:
                    obtained_session_name, proxy_config = result
                    if obtained_session_name == session_name:
                        # Checkin ngay để set READY và tạo binding
                        session_manager.checkin_session_with_proxy(
                            session_name, proxy_config, proxy_manager, "READY", "READY"
                        )
                        print(f"✅ Session '{session_name}' đã được bind với proxy {proxy_config.get('proxy_id')}")
                    else:
                        print(f"⚠️ Binding conflict: expected {session_name}, got {obtained_session_name}")
                        # Fallback to separate checkin
                        session_manager.checkin_session(session_name, "READY")
                        if obtained_session_name and proxy_config:
                            session_manager.checkin_session_with_proxy(
                                obtained_session_name, proxy_config, proxy_manager
                            )
                else:
                    print("⚠️ Không thể tạo session-proxy binding, sử dụng separate checkin")
                    session_manager.checkin_session(session_name, "READY")
            else:
                print("⚠️ Không có proxy available, sử dụng separate checkin")
                session_manager.checkin_session(session_name, "READY")
            
            print(f"✅ Session '{session_name}' đã được cập nhật thành 'READY' trong pool.")

        except Exception as e:
            print(f"⚠️ Không thể cập nhật session status: {e}")
            print("💡 Bạn có thể cập nhật thủ công file session_status.json.")

    await browser.close()
    await playwright.stop()

    return login_successful


def main():
    """Main function với command line interface"""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║           PHASE 3.0 - MANUAL SESSION SETUP (NÂNG CẤP)         ║")
    print("║                                                              ║")
    print("║  🔐 Tạo session cho session pool với trình duyệt an toàn      ║")
    print("║  🔄 Tự động cập nhật session_status.json                    ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    session_name = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        success = asyncio.run(manual_login(session_name))

        if success:
            print("\n🎉 Setup session hoàn thành!")
            print("Bây giờ bạn có thể chạy các worker để sử dụng session này.")
        else:
            print("\n❌ Setup session thất bại.")
    except KeyboardInterrupt:
        print("\n⏹️ Setup bị hủy bởi người dùng.")
    except Exception as e:
        print(f"\n💥 Lỗi: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
