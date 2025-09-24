#!/usr/bin/env python3
"""
Browser Controller for Facebook Post Monitor
Handles browser management, navigation, and anti-detection
"""

import asyncio
from typing import Optional, Dict, Any
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

# Import playwright-stealth for anti-detection
try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    stealth_async = None

from utils.async_patterns import AsyncDelay
from logging_config import get_logger

logger = get_logger(__name__)


class CaptchaException(Exception):
    """Exception raised when CAPTCHA is detected during scraping."""
    
    def __init__(self, message: str = "CAPTCHA detected", captcha_type: str = "unknown"):
        super().__init__(message)
        self.captcha_type = captcha_type


class BrowserController:
    """Handles browser management, navigation, and anti-detection features."""
    
    def __init__(self, page: Page, selectors: Optional[Dict[str, Any]] = None):
        """
        Initialize BrowserController
        
        Args:
            page: Playwright page instance
            selectors: Optional selectors configuration dictionary
        """
        self.page = page
        self.selectors = selectors or {}
        logger.info("🌐 BrowserController initialized")    
    async def navigate_to_url(self, url: str, retries: int = 3) -> bool:
        """
        Navigate to URL with retry logic and error handling
        
        Args:
            url: Target URL to navigate to
            retries: Number of retry attempts
            
        Returns:
            bool: True if navigation successful
            
        Raises:
            CaptchaException: If CAPTCHA is detected after navigation
        """
        import random
        import asyncio
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        
        for attempt in range(retries):
            try:
                logger.debug(f"🧭 Điều hướng đến: {url} (Lần thử {attempt + 1}/{retries})")
                await self.page.goto(url, wait_until='domcontentloaded', timeout=45000)
                
                # Check for CAPTCHA after navigation
                if await self.is_captcha_present():
                    logger.error("🛑 CAPTCHA detected after navigation")
                    raise CaptchaException("CAPTCHA present after navigation")
                
                # FIX: Handle security checkpoints
                if "checkpoint" in self.page.url:
                    logger.warning("🔐 Facebook security checkpoint detected. Attempting to resolve...")
                    checkpoint_resolved = await self.handle_checkpoint()
                    if not checkpoint_resolved:
                        logger.error("❌ Failed to resolve security checkpoint.")
                        return False
                    logger.info("✅ Checkpoint resolved successfully. Continuing navigation...")

                # Wait for first post to appear (if we have selectors)
                if hasattr(self, 'selectors') and self.selectors:
                    first_post_selector = self.selectors.get('post', {}).get('containers', [])[0] if self.selectors.get('post', {}).get('containers') else None
                    if first_post_selector:
                        try:
                            await self.page.wait_for_selector(first_post_selector, timeout=20000)
                        except PlaywrightTimeoutError:
                            logger.warning(f"⚠️ First post selector not found: {first_post_selector}")
                
                logger.debug("✅ Trang đã tải và posts đã xuất hiện")
                return True
                
            except CaptchaException:
                # Re-raise CAPTCHA exceptions immediately
                raise
                
            except PlaywrightTimeoutError as e:
                logger.warning(f"⏳ Timeout khi điều hướng (lần {attempt + 1}): {e}")
                if attempt < retries - 1:
                    # Humanized backoff delay
                    backoff_delay = random.uniform(3.0, 8.0)
                    await asyncio.sleep(backoff_delay)
                else:
                    logger.error("❌ Hết số lần thử điều hướng.")
                    return False
                    
            except Exception as e:
                logger.error(f"❌ Lỗi không xác định khi điều hướng: {e}")
                if attempt < retries - 1:
                    backoff_delay = random.uniform(3.0, 8.0)
                    await asyncio.sleep(backoff_delay)
                else:
                    return False
        
        return False
    
    async def apply_stealth_mode(self) -> None:
        """
        Apply stealth techniques to avoid bot detection
        
        Uses playwright-stealth if available, otherwise applies manual stealth techniques
        """
        try:
            if STEALTH_AVAILABLE:
                try:
                    from playwright_stealth import stealth_async
                    await stealth_async(self.page)
                    logger.debug("✨ Applied playwright-stealth to page")
                except ImportError:
                    logger.debug("⚠️ Playwright-stealth not available, using manual stealth techniques")
                    await self._apply_manual_stealth()
            else:
                logger.debug("⚠️ Playwright-stealth not available, using manual stealth techniques")
                await self._apply_manual_stealth()
        except Exception as e:
            logger.warning(f"⚠️ Failed to apply stealth mode: {e}")
    
    async def _apply_manual_stealth(self) -> None:
        """Apply manual stealth techniques when playwright-stealth is not available"""
        await self.page.add_init_script("""
            // Override webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // Mock chrome runtime
            window.chrome = {
                runtime: {},
            };
            
            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
        """)
    
    async def is_captcha_present(self) -> bool:
        """
        Check if CAPTCHA is present on the current page
        
        Returns:
            bool: True if CAPTCHA detected, False otherwise
        """
        try:
            # Common CAPTCHA indicators
            captcha_selectors = [
                # reCAPTCHA
                "div[class*='recaptcha']",
                "iframe[src*='recaptcha']",
                "#recaptcha",
                
                # hCaptcha
                "div[class*='hcaptcha']",
                "iframe[src*='hcaptcha']",
                "#hcaptcha",
                
                # Facebook specific CAPTCHA
                "div[class*='captcha']",
                "img[alt*='captcha']",
                "img[alt*='CAPTCHA']",
                "div:has-text('Security Check')",
                "div:has-text('Kiểm tra bảo mật')",
                "div:has-text('Please verify')",
                "div:has-text('Vui lòng xác minh')",
                
                # Generic CAPTCHA text patterns
                "text='Enter the text you see'",
                "text='Nhập văn bản bạn thấy'",
                "text='I'm not a robot'",
                "text='Tôi không phải robot'"
            ]
            
            for selector in captcha_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        # Check if element is visible
                        is_visible = await element.is_visible()
                        if is_visible:
                            logger.critical(f"🚨 CAPTCHA detected with selector: {selector}")
                            return True
                except Exception:
                    continue
            
            # Check page title for CAPTCHA keywords
            title = await self.page.title()
            captcha_keywords = ['captcha', 'security check', 'verification', 'kiểm tra bảo mật']
            if any(keyword in title.lower() for keyword in captcha_keywords):
                logger.critical(f"🚨 CAPTCHA detected in page title: {title}")
                return True
            
            # Check URL for CAPTCHA indicators
            url = self.page.url
            if 'captcha' in url.lower() or 'checkpoint' in url.lower():
                logger.critical(f"🚨 CAPTCHA detected in URL: {url}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error checking for CAPTCHA: {e}")
            return False
    
    async def handle_checkpoint(self) -> bool:
        """
        Handles the 'Help us confirm it's you' security checkpoint.
        
        Returns:
            bool: True if the checkpoint was resolved successfully, False otherwise.
        """
        try:
            # Look for a 'Continue' button, accommodating different languages.
            continue_button_selector = "button:has-text('Continue'), button:has-text('Tiếp tục')"
            continue_button = self.page.locator(continue_button_selector).first
            
            if await continue_button.is_visible(timeout=10000):
                logger.info("🖱️ Found 'Continue' button on checkpoint page. Clicking it now.")
                await continue_button.click()
                
                # Wait for the navigation away from the checkpoint URL.
                await self.page.wait_for_url(lambda url: "checkpoint" not in url, timeout=30000)
                logger.info("✅ Successfully navigated away from the checkpoint page.")
                return True
            else:
                logger.warning("⚠️ Could not find a 'Continue' button on the checkpoint page.")
                return False
        except PlaywrightTimeoutError:
            logger.error("⏳ Timed out waiting for navigation after clicking 'Continue'. Checkpoint may not be resolved.")
            return False
        except Exception as e:
            logger.error(f"❌ An unexpected error occurred while handling the checkpoint: {e}")
            return False

    async def get_page_info(self) -> dict:
        """
        Get current page information
        
        Returns:
            dict: Page information including URL and title
        """
        try:
            return {
                "url": self.page.url,
                "title": await self.page.title(),
                "ready_state": await self.page.evaluate("document.readyState")
            }
        except Exception as e:
            logger.error(f"❌ Error getting page info: {e}")
            return {"error": str(e)}
