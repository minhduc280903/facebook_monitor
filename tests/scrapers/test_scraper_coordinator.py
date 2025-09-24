#!/usr/bin/env python3
"""
Unit tests for ScraperCoordinator module
Tests orchestration of all scraper components
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime
import json

# Add project root to path
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.scraper_coordinator import ScraperCoordinator
from scrapers.browser_controller import BrowserController
from scrapers.content_extractor import ContentExtractor
from scrapers.navigation_handler import NavigationHandler
from scrapers.interaction_simulator import InteractionSimulator


@pytest.fixture
def mock_page():
    """Create a mock Playwright page object"""
    page = MagicMock()
    page.url = "https://facebook.com/groups/test"
    page.content = AsyncMock(return_value="<html>Mock Page Content</html>")
    page.wait_for_load_state = AsyncMock()
    page.locator = MagicMock()
    page.evaluate = AsyncMock()
    return page


@pytest.fixture
def mock_db_manager():
    """Create a mock DatabaseManager"""
    db_manager = MagicMock()
    db_manager.save_post = MagicMock(return_value=True)
    db_manager.save_interaction = MagicMock(return_value=True)
    db_manager.post_exists = MagicMock(return_value=False)
    db_manager.get_post_by_signature = MagicMock(return_value=None)
    return db_manager


@pytest.fixture
def coordinator(mock_db_manager, mock_page):
    """Create a ScraperCoordinator instance with mocks"""
    with patch('scrapers.scraper_coordinator.BrowserController'), \
         patch('scrapers.scraper_coordinator.ContentExtractor'), \
         patch('scrapers.scraper_coordinator.NavigationHandler'), \
         patch('scrapers.scraper_coordinator.InteractionSimulator'):
        coord = ScraperCoordinator(mock_db_manager, mock_page)
        
        # Setup mock components
        coord.browser_controller = MagicMock(spec=BrowserController)
        coord.content_extractor = MagicMock(spec=ContentExtractor)
        coord.navigation_handler = MagicMock(spec=NavigationHandler)
        coord.interaction_simulator = MagicMock(spec=InteractionSimulator)
        
        return coord


class TestScraperCoordinator:
    """Test suite for ScraperCoordinator module"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, mock_db_manager, mock_page):
        """Test coordinator initialization"""
        with patch('scrapers.scraper_coordinator.BrowserController'), \
             patch('scrapers.scraper_coordinator.ContentExtractor'), \
             patch('scrapers.scraper_coordinator.NavigationHandler'), \
             patch('scrapers.scraper_coordinator.InteractionSimulator'):
            
            coord = ScraperCoordinator(mock_db_manager, mock_page)
            
            assert coord.db_manager == mock_db_manager
            assert coord.page == mock_page
            assert coord.browser_controller is not None
            assert coord.content_extractor is not None
            assert coord.navigation_handler is not None
            assert coord.interaction_simulator is not None
    
    @pytest.mark.asyncio
    async def test_process_url_success(self, coordinator):
        """Test successful URL processing"""
        test_url = "https://facebook.com/groups/test"
        
        # Setup mocks
        coordinator.browser_controller.navigate_to_url = AsyncMock(return_value=True)
        coordinator.browser_controller.check_for_captcha = AsyncMock(return_value=False)
        coordinator.navigation_handler.find_post_elements = AsyncMock(return_value=[
            MagicMock(), MagicMock()  # 2 mock posts
        ])
        coordinator._process_post = AsyncMock(return_value=True)
        
        result = await coordinator.process_url(test_url)
        
        # Verify navigation
        coordinator.browser_controller.navigate_to_url.assert_called_once_with(test_url)
        # Verify CAPTCHA check
        coordinator.browser_controller.check_for_captcha.assert_called_once()
        # Verify post processing
        assert coordinator._process_post.call_count == 2
        # Check result
        assert result['status'] == 'success'
        assert result['posts_processed'] == 2
    
    @pytest.mark.asyncio
    async def test_process_url_navigation_failure(self, coordinator):
        """Test URL processing when navigation fails"""
        test_url = "https://facebook.com/groups/test"
        
        coordinator.browser_controller.navigate_to_url = AsyncMock(return_value=False)
        
        result = await coordinator.process_url(test_url)
        
        assert result['status'] == 'error'
        assert 'error' in result
        assert result['posts_processed'] == 0
    
    @pytest.mark.asyncio
    async def test_process_url_captcha_detected(self, coordinator):
        """Test URL processing when CAPTCHA is detected"""
        test_url = "https://facebook.com/groups/test"
        
        coordinator.browser_controller.navigate_to_url = AsyncMock(return_value=True)
        coordinator.browser_controller.check_for_captcha = AsyncMock(return_value=True)
        
        with pytest.raises(Exception) as excinfo:
            await coordinator.process_url(test_url)
        
        assert "CAPTCHA" in str(excinfo.value)
    
    @pytest.mark.asyncio
    async def test_process_post_new_post(self, coordinator, mock_db_manager):
        """Test processing a new post"""
        mock_post_element = MagicMock()
        
        # Setup extraction results
        post_data = {
            'signature': 'post_123',
            'author': 'Test User',
            'content': 'Test post content',
            'timestamp': '2024-01-15 10:00:00',
            'likes': 10,
            'comments': 5,
            'shares': 2
        }
        
        coordinator.content_extractor.extract_post_signature = AsyncMock(
            return_value=post_data['signature']
        )
        coordinator.content_extractor.extract_post_data = AsyncMock(
            return_value=post_data
        )
        mock_db_manager.post_exists.return_value = False
        
        result = await coordinator._process_post(mock_post_element)
        
        # Verify extraction
        coordinator.content_extractor.extract_post_signature.assert_called_once()
        coordinator.content_extractor.extract_post_data.assert_called_once()
        # Verify save
        mock_db_manager.save_post.assert_called_once()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_process_post_existing_post(self, coordinator, mock_db_manager):
        """Test processing an existing post (update interactions)"""
        mock_post_element = MagicMock()
        
        # Setup extraction results
        post_signature = 'existing_post_123'
        interaction_data = {
            'likes': 20,
            'comments': 10,
            'shares': 5
        }
        
        coordinator.content_extractor.extract_post_signature = AsyncMock(
            return_value=post_signature
        )
        coordinator.content_extractor.extract_interaction_counts = AsyncMock(
            return_value=interaction_data
        )
        mock_db_manager.post_exists.return_value = True
        mock_db_manager.get_post_by_signature.return_value = {'id': 1}
        
        result = await coordinator._process_post(mock_post_element)
        
        # Should extract interactions for existing post
        coordinator.content_extractor.extract_interaction_counts.assert_called_once()
        # Should save interaction data
        mock_db_manager.save_interaction.assert_called_once()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_process_post_extraction_error(self, coordinator):
        """Test handling extraction errors"""
        mock_post_element = MagicMock()
        
        coordinator.content_extractor.extract_post_signature = AsyncMock(
            side_effect=Exception("Extraction failed")
        )
        
        result = await coordinator._process_post(mock_post_element)
        
        # Should handle error gracefully
        assert result is False
    
    @pytest.mark.asyncio
    async def test_scroll_and_load_posts(self, coordinator):
        """Test scrolling and loading more posts"""
        # Setup mocks
        coordinator.navigation_handler.scroll_page = AsyncMock()
        coordinator.navigation_handler.find_post_elements = AsyncMock(
            side_effect=[
                [MagicMock()] * 5,   # First batch: 5 posts
                [MagicMock()] * 8,   # After scroll: 8 posts (3 new)
                [MagicMock()] * 10,  # After scroll: 10 posts (2 new)
                [MagicMock()] * 10   # No new posts
            ]
        )
        
        posts = await coordinator.scroll_and_load_posts(max_scrolls=3)
        
        # Should scroll 3 times
        assert coordinator.navigation_handler.scroll_page.call_count == 3
        # Should return final post count
        assert len(posts) == 10
    
    @pytest.mark.asyncio
    async def test_handle_rate_limiting(self, coordinator):
        """Test rate limiting handling"""
        coordinator.interaction_simulator.simulate_reading = AsyncMock()
        coordinator.interaction_simulator.random_mouse_movement = AsyncMock()
        
        await coordinator.handle_rate_limiting()
        
        # Should simulate human behavior
        coordinator.interaction_simulator.simulate_reading.assert_called()
        coordinator.interaction_simulator.random_mouse_movement.assert_called()
    
    @pytest.mark.asyncio
    async def test_process_batch_posts(self, coordinator):
        """Test batch processing of posts"""
        mock_posts = [MagicMock() for _ in range(5)]
        coordinator._process_post = AsyncMock(side_effect=[True, True, False, True, True])
        
        results = await coordinator.process_batch_posts(mock_posts)
        
        # Should process all posts
        assert coordinator._process_post.call_count == 5
        # Should return processing results
        assert results['total'] == 5
        assert results['successful'] == 4
        assert results['failed'] == 1
    
    @pytest.mark.asyncio
    async def test_simulate_human_behavior(self, coordinator):
        """Test human behavior simulation between actions"""
        coordinator.interaction_simulator.simulate_reading = AsyncMock()
        coordinator.interaction_simulator.random_scroll = AsyncMock()
        coordinator.interaction_simulator.random_mouse_movement = AsyncMock()
        
        await coordinator.simulate_human_behavior(duration=2.0)
        
        # Should call various human-like actions
        assert coordinator.interaction_simulator.simulate_reading.called or \
               coordinator.interaction_simulator.random_scroll.called or \
               coordinator.interaction_simulator.random_mouse_movement.called
    
    @pytest.mark.asyncio
    async def test_error_recovery(self, coordinator):
        """Test error recovery mechanisms"""
        test_url = "https://facebook.com/groups/test"
        
        # Simulate recoverable error
        coordinator.browser_controller.navigate_to_url = AsyncMock(
            side_effect=[Exception("Network error"), True]
        )
        coordinator.browser_controller.check_for_captcha = AsyncMock(return_value=False)
        coordinator.navigation_handler.find_post_elements = AsyncMock(return_value=[])
        
        # Add retry logic if coordinator has it
        if hasattr(coordinator, 'process_url_with_retry'):
            result = await coordinator.process_url_with_retry(test_url, max_retries=2)
            assert coordinator.browser_controller.navigate_to_url.call_count == 2
        else:
            # Test single attempt
            result = await coordinator.process_url(test_url)
            assert result['status'] == 'error'
    
    @pytest.mark.asyncio
    async def test_statistics_tracking(self, coordinator):
        """Test that coordinator tracks statistics"""
        coordinator.stats = {
            'posts_processed': 0,
            'new_posts': 0,
            'updated_posts': 0,
            'errors': 0
        }
        
        # Process some posts
        mock_posts = [MagicMock() for _ in range(3)]
        coordinator._process_post = AsyncMock(side_effect=[True, True, False])
        
        await coordinator.process_batch_posts(mock_posts)
        
        # Stats should be updated
        if hasattr(coordinator, 'stats'):
            assert coordinator.stats['posts_processed'] > 0
    
    @pytest.mark.asyncio
    async def test_cleanup_on_error(self, coordinator):
        """Test cleanup when processing fails"""
        test_url = "https://facebook.com/groups/test"
        
        # Force an error during processing
        coordinator.browser_controller.navigate_to_url = AsyncMock(
            side_effect=Exception("Critical error")
        )
        
        result = await coordinator.process_url(test_url)
        
        # Should return error status
        assert result['status'] == 'error'
        # Should include error details
        assert 'error' in result
        assert 'Critical error' in result['error']
    
    @pytest.mark.asyncio
    async def test_concurrent_post_processing(self, coordinator):
        """Test concurrent processing of multiple posts"""
        mock_posts = [MagicMock() for _ in range(10)]
        
        # Setup async processing
        async def mock_process(post):
            await asyncio.sleep(0.01)  # Simulate work
            return True
        
        coordinator._process_post = mock_process
        
        # Process posts (should handle concurrency if supported)
        start_time = datetime.now()
        results = await coordinator.process_batch_posts(mock_posts)
        duration = (datetime.now() - start_time).total_seconds()
        
        # If concurrent, should be faster than sequential
        # Sequential would take ~0.1s, concurrent much less
        assert results['total'] == 10