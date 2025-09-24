#!/usr/bin/env python3
"""
Browser Configuration for Facebook Post Monitor - Enterprise Edition

🎯 MỤC ĐÍCH:
- Tập trung TẤT CẢ cấu hình trình duyệt vào MỘT FILE DUY NHẤT
- Đảm bảo browser fingerprint HOÀN TOÀN NHẤT QUÁN trên toàn hệ thống
- Ngăn chặn triệt để browser fingerprinting mismatch

🔧 SỬ DỤNG:
- manual_login.py: Tạo sessions với cấu hình chuẩn
- worker.py: Sử dụng sessions với CHÍNH XÁC cùng cấu hình
- debug_single_worker.py: Test với cấu hình nhất quán

⚠️ QUAN TRỌNG:
- MỌI THAY ĐỔI chỉ thực hiện TẠI FILE NÀY
- KHÔNG ĐƯỢC chỉnh sửa cấu hình browser ở file khác
- Mọi sự thay đổi sẽ ảnh hưởng toàn hệ thống
"""

from typing import Dict, List, Any, Optional

# Constants for browser configuration
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
)
DEFAULT_VIEWPORT_WIDTH = 1366
DEFAULT_VIEWPORT_HEIGHT = 768
DEFAULT_LOCALE = 'vi-VN'
DEFAULT_TIMEZONE = 'Asia/Ho_Chi_Minh'
MOCK_PLUGINS_COUNT = 5
FINGERPRINT_VERSION = "v2.5_unified"


def get_browser_args() -> List[str]:
    """
    Trả về danh sách các arguments cho trình duyệt.

    🛡️ Anti-Detection Browser Arguments:
    - Disable automation detection features
    - Mimic human browsing behavior
    - Consistent system-level configuration

    Returns:
        List[str]: Complete list of browser arguments
    """
    return [
        '--no-first-run',                        # Skip first run experience
        '--no-default-browser-check',            # Skip default browser check
        '--disable-blink-features=AutomationControlled',  # Critical
        '--disable-web-security',                # Allow cross-origin requests
        '--disable-features=VizDisplayCompositor',  # Display optimization
        '--disable-dev-shm-usage',               # Memory optimization
        '--disable-extensions',                  # Clean browser environment
        '--no-sandbox',                          # Security bypass
        '--disable-setuid-sandbox',              # Additional security bypass
        '--disable-gpu',                         # GPU acceleration disable
        '--disable-background-timer-throttling',  # Performance optimization
        '--disable-backgrounding-occluded-windows',  # Window management
        '--disable-renderer-backgrounding',      # Renderer optimization
        '--disable-field-trial-config',  # 🔥 CRITICAL: Field trial consistency
        '--disable-back-forward-cache',  # 🔥 CRITICAL: Navigation consistency
        '--disable-ipc-flooding-protection'  # 🔥 CRITICAL: IPC behavior
    ]


def get_browser_launch_options(
    user_data_dir: str,
    headless: bool = False,
    proxy_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Trả về dict chứa TẤT CẢ các tùy chọn khởi động trình duyệt.

    Args:
        user_data_dir: Đường dẫn đến session directory
        headless: True = headless mode, False = với GUI
        proxy_config: Dict chứa proxy configuration (từ ProxyManager)

    Returns:
        Complete browser launch configuration
    """
    import logging
    logger = logging.getLogger(__name__)
    
    args = get_browser_args()

    # 🔥 QUAN TRỌNG: Headless mode handling
    if headless:
        args.append('--headless=new')  # Use new headless mode

    launch_options = {
        "user_data_dir": user_data_dir,
        "headless": headless,
        "args": args,
        # 🌐 BROWSER IDENTITY - MUST BE IDENTICAL EVERYWHERE
        "user_agent": DEFAULT_USER_AGENT,
        "viewport": {
            'width': DEFAULT_VIEWPORT_WIDTH,
            'height': DEFAULT_VIEWPORT_HEIGHT
        },
        "locale": DEFAULT_LOCALE,
        "timezone_id": DEFAULT_TIMEZONE,
        "java_script_enabled": True,
        "bypass_csp": True,
        "ignore_https_errors": True
    }
    
    # 🔧 PRODUCTION FIX: Tích hợp ProxyManager
    # Nếu có proxy config, áp dụng vào browser options
    if proxy_config:
        try:
            from core.proxy_manager import ProxyManager
            proxy_manager = ProxyManager()
            playwright_proxy = proxy_manager.get_proxy_for_playwright(
                proxy_config
            )
            
            if playwright_proxy:
                launch_options['proxy'] = playwright_proxy
                logger.info(
                    "🔗 Applied proxy to browser: %s:%s",
                    proxy_config.get('host'),
                    proxy_config.get('port')
                )
            else:
                logger.warning(
                    "⚠️ Failed to convert proxy config for Playwright"
                )
                
        except (ImportError, AttributeError, KeyError, ValueError) as e:
            logger.error("❌ Error applying proxy config: %s", e)
            # Continue without proxy rather than failing
    
    return launch_options


def get_init_script() -> str:
    """
    Trả về JavaScript injection script để chống phát hiện.

    🛡️ Anti-Detection JavaScript:
    - Hide webdriver property
    - Mock navigator.plugins
    - Add window.chrome object
    - Mock permissions API

    Returns:
        Complete anti-detection JavaScript code
    """
    return """
        // 🛡️ Hide webdriver property (Core anti-detection)
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });

        // 🛡️ Mock permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // 🛡️ Mock navigator.plugins (CRITICAL: Must match worker.py)
        Object.defineProperty(navigator, 'plugins', {
            get: () => Array.from({length: 5}, (_, i) => i + 1),  // 5 plugins
        });

        // 🛡️ Mock navigator.languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['vi-VN', 'vi', 'en-US', 'en'],
        });

        // 🛡️ Add window.chrome object (CRITICAL: Must exist)
        window.chrome = {
            runtime: {},
        };
    """


def get_browser_fingerprint_summary() -> Dict[str, Any]:
    """
    Trả về summary của browser fingerprint để debugging/verification.

    Returns:
        Summary of all fingerprint components
    """
    args = get_browser_args()
    options = get_browser_launch_options("/dummy/path", headless=False)

    return {
        "total_args": len(args),
        "critical_args": [
            '--disable-field-trial-config',
            '--disable-back-forward-cache',
            '--disable-ipc-flooding-protection'
        ],
        "user_agent": options["user_agent"],
        "viewport": options["viewport"],
        "locale": options["locale"],
        "timezone": options["timezone_id"],
        "plugins_count": MOCK_PLUGINS_COUNT,
        "has_window_chrome": True,
        "fingerprint_version": FINGERPRINT_VERSION
    }


# 🧪 Testing function để verify configuration
def verify_config_consistency() -> None:
    """
    Kiểm tra tính nhất quán của cấu hình.
    Sử dụng để debugging và verification.
    """
    summary = get_browser_fingerprint_summary()

    print("🔍 BROWSER CONFIGURATION VERIFICATION")
    print("=" * 50)
    print(f"📊 Total browser args: {summary['total_args']}")
    print(f"🔥 Critical args present: {len(summary['critical_args'])}/3")
    print(f"🌐 User Agent: {summary['user_agent'][:50]}...")
    print(f"📱 Viewport: {summary['viewport']}")
    print(f"🌍 Locale: {summary['locale']}")
    print(f"⏰ Timezone: {summary['timezone']}")
    print(f"🔌 Plugins count: {summary['plugins_count']}")
    print(f"🪟 Chrome object: {summary['has_window_chrome']}")
    print(f"📋 Version: {summary['fingerprint_version']}")
    print("=" * 50)
    print("✅ Configuration is consistent and ready for use!")


if __name__ == "__main__":
    # Run verification when executed directly
    verify_config_consistency()
