#!/usr/bin/env python3
"""
Unit tests for ContentExtractor module
Tests data extraction strategies and resilience
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from scrapers.content_extractor import ContentExtractor


@pytest.mark.unit 
class TestContentExtractor:
    """Test cases for ContentExtractor class"""
    
    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page"""
        page = AsyncMock()
        page.locator = Mock()
        page.query_selector = AsyncMock()
        page.query_selector_all = AsyncMock()
        page.evaluate = AsyncMock()
        return page
    
    @pytest.fixture
    def mock_selectors(self):
        """Create mock selectors configuration"""
        return {
            "post_container": {
                "strategies": [
                    {"selector": "div[role='article']", "type": "css"}
                ]
            },
            "author_name": {
                "strategies": [
                    {"selector": "h3 a[role='link']", "type": "css"},
                    {"selector": "strong", "type": "css"}
                ]
            },
            "post_content": {
                "strategies": [
                    {"selector": "div[data-ad-preview='message']", "type": "css"},
                    {"selector": "div[dir='auto']", "type": "css"}
                ]
            },
            "likes_count": {
                "strategies": [
                    {"selector": "[aria-label*='Like']", "type": "css", "attribute": "aria-label"},
                    {"selector": "span:has-text('Like')", "type": "text"}
                ]
            }
        }
    
    @pytest.fixture
    def extractor(self, mock_page, mock_selectors):
        """Create ContentExtractor instance with mocks"""
        with patch('scrapers.content_extractor.ContentExtractor.load_selectors', return_value=mock_selectors):
            return ContentExtractor(mock_page)
    
    @pytest.mark.asyncio
    async def test_init(self, mock_page):
        """Test ContentExtractor initialization"""
        with patch('scrapers.content_extractor.ContentExtractor.load_selectors') as mock_load:
            mock_load.return_value = {}
            extractor = ContentExtractor(mock_page)
            
            assert extractor.page == mock_page
            assert extractor.selectors == {}
            assert extractor.strategy_stats == {}
            mock_load.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_extract_text_from_element_success(self, extractor, mock_page):
        """Test successful text extraction from element"""
        mock_element = Mock()
        mock_element.inner_text = AsyncMock(return_value="Test content")
        
        text = await extractor.extract_text_from_element(mock_element)
        
        assert text == "Test content"
        mock_element.inner_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_extract_text_from_element_none(self, extractor):
        """Test text extraction with None element"""
        text = await extractor.extract_text_from_element(None)
        assert text == ""
    
    @pytest.mark.asyncio
    async def test_extract_count_from_text_with_k(self, extractor):
        """Test extracting count from text with K suffix"""
        count = extractor.extract_count_from_text("1.5K likes")
        assert count == 1500
    
    @pytest.mark.asyncio
    async def test_extract_count_from_text_with_m(self, extractor):
        """Test extracting count from text with M suffix"""
        count = extractor.extract_count_from_text("2.3M views")
        assert count == 2300000
    
    @pytest.mark.asyncio
    async def test_extract_count_from_text_plain_number(self, extractor):
        """Test extracting plain number from text"""
        count = extractor.extract_count_from_text("42 comments")
        assert count == 42
    
    @pytest.mark.asyncio
    async def test_extract_count_from_text_no_number(self, extractor):
        """Test extracting count when no number present"""
        count = extractor.extract_count_from_text("No likes yet")
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_create_post_signature(self, extractor):
        """Test creating post signature"""
        post_data = {
            "author": "John Doe",
            "content": "This is a test post with some content",
            "timestamp": "2024-01-15 10:30:00"
        }
        
        signature = extractor.create_post_signature(post_data)
        
        assert signature is not None
        assert len(signature) == 64  # SHA256 hash length in hex
        
        # Same data should produce same signature
        signature2 = extractor.create_post_signature(post_data)
        assert signature == signature2
    
    @pytest.mark.asyncio
    async def test_create_post_signature_missing_data(self, extractor):
        """Test creating signature with missing data"""
        post_data = {
            "author": "John Doe"
            # Missing content and timestamp
        }
        
        signature = extractor.create_post_signature(post_data)
        
        # Should still create a signature
        assert signature is not None
        assert len(signature) == 64
    
    @pytest.mark.asyncio
    async def test_extract_url_from_element(self, extractor):
        """Test URL extraction from element"""
        mock_element = Mock()
        mock_element.get_attribute = AsyncMock(return_value="https://facebook.com/post/123")
        
        url = await extractor.extract_url_from_element(mock_element)
        
        assert url == "https://facebook.com/post/123"
        mock_element.get_attribute.assert_called_once_with("href")
    
    @pytest.mark.asyncio
    async def test_extract_data_with_strategies(self, extractor, mock_page):
        """Test data extraction using multiple strategies"""
        # Mock first strategy fails, second succeeds
        mock_element = Mock()
        mock_element.query_selector = AsyncMock()
        
        # First strategy returns None
        mock_element.query_selector.side_effect = [None, Mock()]
        
        # Mock successful text extraction on second element
        with patch.object(extractor, 'extract_text_from_element', return_value="Extracted text"):
            result = await extractor.extract_data(
                mock_element,
                "author_name",
                data_type="text"
            )
        
        assert result == "Extracted text"
        # Verify it tried multiple strategies
        assert mock_element.query_selector.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_extract_data_all_strategies_fail(self, extractor, mock_page):
        """Test data extraction when all strategies fail"""
        mock_element = Mock()
        mock_element.query_selector = AsyncMock(return_value=None)
        
        result = await extractor.extract_data(
            mock_element,
            "author_name",
            data_type="text"
        )
        
        # Should return default value
        assert result == ""
    
    @pytest.mark.asyncio
    async def test_extract_data_count_type(self, extractor, mock_page):
        """Test extracting count type data"""
        mock_element = Mock()
        mock_sub_element = Mock()
        mock_sub_element.inner_text = AsyncMock(return_value="1.2K likes")
        mock_element.query_selector = AsyncMock(return_value=mock_sub_element)
        
        result = await extractor.extract_data(
            mock_element,
            "likes_count",
            data_type="count"
        )
        
        assert result == 1200
    
    def test_get_strategy_stats(self, extractor):
        """Test getting strategy statistics"""
        # Simulate some strategy usage
        extractor.strategy_stats = {
            "author_name": {"strategy_0": 5, "strategy_1": 3},
            "post_content": {"strategy_0": 8}
        }
        
        stats = extractor.get_strategy_stats()
        
        assert stats == extractor.strategy_stats
        assert stats["author_name"]["strategy_0"] == 5
        assert stats["post_content"]["strategy_0"] == 8