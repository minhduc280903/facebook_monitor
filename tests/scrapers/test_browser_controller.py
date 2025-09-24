#!/usr/bin/env python3
"""
Unit tests for BrowserController module
Tests browser management, navigation, and anti-detection features
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from scrapers.browser_controller import BrowserController, CaptchaException


@pytest.mark.unit
class TestBrowserController:
    """Test cases for BrowserController class"""
    
    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page"""
        page = AsyncMock(spec=Page)
        page.url = "https://facebook.com"
        page.title = AsyncMock(return_value="Facebook")
        page.content = AsyncMock(return_value="<html>Mock content</html>")
        page.wait_for_load_state = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.goto = AsyncMock()
        page.evaluate = AsyncMock(return_value=None)
        page.locator = Mock()
        return page
    
    @pytest.fixture
    def controller(self, mock_page):
        """Create a BrowserController instance with mock page"""
        return BrowserController(mock_page)
    
    @pytest.mark.asyncio
    async def test_init(self, mock_page):
        """Test BrowserController initialization"""
        controller = BrowserController(mock_page)
        assert controller.page == mock_page
        assert controller.selectors is not None
    
    @pytest.mark.asyncio
    async def test_navigate_to_url_success(self, controller, mock_page):
        """Test successful navigation to URL"""
        test_url = "https://facebook.com/groups/test"
        
        # Mock successful navigation
        mock_page.goto.return_value = None
        mock_page.wait_for_load_state.return_value = None
        
        result = await controller.navigate_to_url(test_url)
        
        assert result is True
        mock_page.goto.assert_called_once_with(
            test_url,
            wait_until='networkidle',
            timeout=30000
        )
        mock_page.wait_for_load_state.assert_called_once_with('domcontentloaded')
    
    @pytest.mark.asyncio
    async def test_navigate_to_url_timeout(self, controller, mock_page):
        """Test navigation timeout handling"""
        test_url = "https://facebook.com/groups/slow"
        
        # Mock timeout error
        mock_page.goto.side_effect = PlaywrightTimeoutError("Navigation timeout")
        
        result = await controller.navigate_to_url(test_url)
        
        assert result is False
        mock_page.goto.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_is_captcha_present_detected(self, controller, mock_page):
        """Test CAPTCHA detection when present"""
        # Mock CAPTCHA selectors being found
        mock_locator = Mock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_page.locator.return_value = mock_locator
        
        # Mock page title containing "Security Check"
        mock_page.title.return_value = "Security Check Required"
        
        is_captcha = await controller.is_captcha_present()
        
        assert is_captcha is True
    
    @pytest.mark.asyncio
    async def test_is_captcha_present_not_detected(self, controller, mock_page):
        """Test CAPTCHA detection when not present"""
        # Mock no CAPTCHA elements found
        mock_locator = Mock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_page.locator.return_value = mock_locator
        
        # Mock normal page title
        mock_page.title.return_value = "Facebook"
        
        is_captcha = await controller.is_captcha_present()
        
        assert is_captcha is False
    
    @pytest.mark.asyncio
    async def test_apply_stealth_mode_with_stealth(self, controller, mock_page):
        """Test stealth mode application when playwright-stealth is available"""
        with patch('scrapers.browser_controller.STEALTH_AVAILABLE', True):
            with patch('scrapers.browser_controller.stealth_async') as mock_stealth:
                await controller.apply_stealth_mode()
                mock_stealth.assert_called_once_with(mock_page)
    
    @pytest.mark.asyncio
    async def test_apply_stealth_mode_without_stealth(self, controller, mock_page):
        """Test stealth mode fallback when playwright-stealth is not available"""
        with patch('scrapers.browser_controller.STEALTH_AVAILABLE', False):
            # Should run without error and use basic evasion
            await controller.apply_stealth_mode()
            
            # Verify basic anti-detection JavaScript was injected
            mock_page.evaluate.assert_called()
    
    @pytest.mark.asyncio
    async def test_wait_for_element_success(self, controller, mock_page):
        """Test successful element waiting"""
        selector = "div[role='article']"
        mock_page.wait_for_selector.return_value = Mock()
        
        result = await controller.wait_for_element(selector, timeout=5000)
        
        assert result is True
        mock_page.wait_for_selector.assert_called_once_with(
            selector, 
            timeout=5000
        )
    
    @pytest.mark.asyncio
    async def test_wait_for_element_timeout(self, controller, mock_page):
        """Test element waiting timeout"""
        selector = "div.nonexistent"
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Element not found")
        
        result = await controller.wait_for_element(selector, timeout=1000)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_check_and_handle_captcha_raises_exception(self, controller, mock_page):
        """Test CAPTCHA handling raises exception when detected"""
        # Mock CAPTCHA being present
        with patch.object(controller, 'is_captcha_present', return_value=True):
            with pytest.raises(CaptchaException) as exc_info:
                await controller.check_and_handle_captcha()
            
            assert "CAPTCHA detected" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_check_and_handle_captcha_no_exception(self, controller, mock_page):
        """Test CAPTCHA handling when no CAPTCHA present"""
        # Mock no CAPTCHA
        with patch.object(controller, 'is_captcha_present', return_value=False):
            # Should complete without raising exception
            await controller.check_and_handle_captcha()