#!/usr/bin/env python3
"""
Unit tests for NavigationHandler module
Tests page scrolling, element finding, and content expansion
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio

from scrapers.navigation_handler import NavigationHandler


@pytest.mark.unit
class TestNavigationHandler:
    """Test cases for NavigationHandler class"""
    
    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page"""
        page = AsyncMock()
        page.evaluate = AsyncMock()
        page.query_selector_all = AsyncMock()
        page.locator = Mock()
        page.wait_for_timeout = AsyncMock()
        page.keyboard = Mock()
        page.keyboard.press = AsyncMock()
        return page
    
    @pytest.fixture
    def mock_content_extractor(self):
        """Create a mock ContentExtractor"""
        extractor = Mock()
        extractor.selectors = {
            "post_container": {
                "strategies": [{"selector": "div[role='article']", "type": "css"}]
            }
        }
        return extractor
    
    @pytest.fixture  
    def handler(self, mock_page, mock_content_extractor):
        """Create NavigationHandler instance with mocks"""
        return NavigationHandler(mock_page, mock_content_extractor)
    
    @pytest.mark.asyncio
    async def test_init(self, mock_page, mock_content_extractor):
        """Test NavigationHandler initialization"""
        handler = NavigationHandler(mock_page, mock_content_extractor)
        
        assert handler.page == mock_page
        assert handler.content_extractor == mock_content_extractor
    
    @pytest.mark.asyncio
    async def test_humanized_scroll_page(self, handler, mock_page):
        """Test humanized page scrolling"""
        # Mock page height
        mock_page.evaluate.side_effect = [
            1000,  # Initial scroll position
            5000,  # Document height
            1500,  # After first scroll
            5000,  # Document height
            2000,  # After second scroll
            5000   # Document height
        ]
        
        await handler.humanized_scroll_page(scroll_count=2)
        
        # Verify scrolling happened
        assert mock_page.evaluate.call_count >= 4  # At least 2 scrolls with height checks
        
        # Verify delays were added
        assert mock_page.wait_for_timeout.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_find_post_elements_success(self, handler, mock_page):
        """Test finding post elements on page"""
        # Mock post elements
        mock_posts = [Mock(), Mock(), Mock()]
        mock_page.query_selector_all.return_value = mock_posts
        
        posts = await handler.find_post_elements()
        
        assert len(posts) == 3
        assert posts == mock_posts
        mock_page.query_selector_all.assert_called_once_with("div[role='article']")
    
    @pytest.mark.asyncio
    async def test_find_post_elements_empty(self, handler, mock_page):
        """Test finding posts when none exist"""
        mock_page.query_selector_all.return_value = []
        
        posts = await handler.find_post_elements()
        
        assert posts == []
        mock_page.query_selector_all.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_expand_post_content_with_see_more(self, handler):
        """Test expanding post content with 'See more' button"""
        mock_element = Mock()
        mock_see_more = Mock()
        mock_see_more.click = AsyncMock()
        mock_see_more.is_visible = AsyncMock(return_value=True)
        
        # Mock finding "See more" button
        mock_element.query_selector = AsyncMock(return_value=mock_see_more)
        
        await handler.expand_post_content(mock_element)
        
        # Verify it tried to find and click "See more"
        mock_element.query_selector.assert_called()
        mock_see_more.click.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_expand_post_content_no_see_more(self, handler):
        """Test expanding content when no 'See more' button exists"""
        mock_element = Mock()
        mock_element.query_selector = AsyncMock(return_value=None)
        
        # Should complete without error
        await handler.expand_post_content(mock_element)
        
        mock_element.query_selector.assert_called()
    
    @pytest.mark.asyncio
    async def test_scroll_to_element(self, handler, mock_page):
        """Test scrolling to specific element"""
        mock_element = Mock()
        mock_element.scroll_into_view_if_needed = AsyncMock()
        
        await handler.scroll_to_element(mock_element)
        
        mock_element.scroll_into_view_if_needed.assert_called_once()
        # Should add delay after scrolling
        mock_page.wait_for_timeout.assert_called()
    
    @pytest.mark.asyncio
    async def test_wait_for_new_content(self, handler, mock_page):
        """Test waiting for new content to load"""
        # Mock initial and new post counts
        mock_page.query_selector_all.side_effect = [
            [Mock(), Mock()],      # Initial: 2 posts
            [Mock(), Mock()],      # Still 2 posts
            [Mock(), Mock(), Mock()]  # New: 3 posts
        ]
        
        new_content = await handler.wait_for_new_content(
            initial_count=2,
            timeout=1000
        )
        
        assert new_content is True
        assert mock_page.query_selector_all.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_wait_for_new_content_timeout(self, handler, mock_page):
        """Test waiting for new content that never loads"""
        # Mock no new content appearing
        mock_page.query_selector_all.return_value = [Mock(), Mock()]
        
        new_content = await handler.wait_for_new_content(
            initial_count=2,
            timeout=500  # Short timeout for test
        )
        
        assert new_content is False
    
    @pytest.mark.asyncio
    async def test_navigate_with_keyboard(self, handler, mock_page):
        """Test keyboard navigation"""
        await handler.navigate_with_keyboard("End")
        
        mock_page.keyboard.press.assert_called_once_with("End")
        mock_page.wait_for_timeout.assert_called()  # Should wait after key press
    
    @pytest.mark.asyncio
    async def test_get_page_scroll_height(self, handler, mock_page):
        """Test getting page scroll height"""
        mock_page.evaluate.return_value = 10000
        
        height = await handler.get_page_scroll_height()
        
        assert height == 10000
        mock_page.evaluate.assert_called_once_with("document.body.scrollHeight")
    
    @pytest.mark.asyncio
    async def test_is_at_page_bottom(self, handler, mock_page):
        """Test checking if at page bottom"""
        # Mock being at bottom
        mock_page.evaluate.side_effect = [
            9900,   # Current scroll position
            10000   # Document height
        ]
        
        at_bottom = await handler.is_at_page_bottom()
        
        assert at_bottom is True
        assert mock_page.evaluate.call_count == 2
    
    @pytest.mark.asyncio
    async def test_is_at_page_bottom_false(self, handler, mock_page):
        """Test checking when not at page bottom"""
        # Mock not at bottom
        mock_page.evaluate.side_effect = [
            5000,   # Current scroll position
            10000   # Document height
        ]
        
        at_bottom = await handler.is_at_page_bottom()
        
        assert at_bottom is False