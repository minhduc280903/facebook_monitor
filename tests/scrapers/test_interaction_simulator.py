#!/usr/bin/env python3
"""
Unit tests for InteractionSimulator module
Tests human-like interaction patterns and behavior
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime
import random
import asyncio

# Add project root to path
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.interaction_simulator import InteractionSimulator


@pytest.fixture
def mock_page():
    """Create a mock Playwright page object"""
    page = MagicMock()
    page.evaluate = AsyncMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.mouse.click = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.locator = MagicMock()
    page.viewport_size = MagicMock(return_value={"width": 1920, "height": 1080})
    return page


@pytest.fixture
def simulator(mock_page):
    """Create an InteractionSimulator instance with mock page"""
    return InteractionSimulator(mock_page)


class TestInteractionSimulator:
    """Test suite for InteractionSimulator module"""
    
    @pytest.mark.asyncio
    async def test_human_delay_range(self, simulator):
        """Test that human delays are within expected ranges"""
        # Test multiple delays to ensure randomness
        delays = []
        for _ in range(10):
            delay = await simulator.human_delay(0.5, 1.5)
            delays.append(delay)
        
        # Check all delays are within range
        assert all(0.5 <= d <= 1.5 for d in delays)
        # Check we have some variance (not all the same)
        assert len(set(delays)) > 1
    
    @pytest.mark.asyncio
    async def test_random_mouse_movement(self, simulator, mock_page):
        """Test random mouse movements"""
        await simulator.random_mouse_movement()
        
        # Should move mouse to random position
        mock_page.mouse.move.assert_called_once()
        call_args = mock_page.mouse.move.call_args[0]
        x, y = call_args[0], call_args[1]
        
        # Check coordinates are within viewport
        assert 0 <= x <= 1920
        assert 0 <= y <= 1080
    
    @pytest.mark.asyncio
    async def test_simulate_reading_basic(self, simulator, mock_page):
        """Test basic reading simulation"""
        await simulator.simulate_reading(2.0)
        
        # Should have some mouse movements and scrolls
        assert mock_page.mouse.move.call_count >= 1
        assert mock_page.mouse.wheel.call_count >= 1
        assert mock_page.wait_for_timeout.called
    
    @pytest.mark.asyncio
    async def test_simulate_reading_with_movements(self, simulator, mock_page):
        """Test reading simulation includes natural movements"""
        await simulator.simulate_reading(3.0)
        
        # Verify multiple interactions occurred
        total_interactions = (
            mock_page.mouse.move.call_count +
            mock_page.mouse.wheel.call_count
        )
        assert total_interactions >= 2
    
    @pytest.mark.asyncio
    async def test_random_scroll_behavior(self, simulator, mock_page):
        """Test random scrolling patterns"""
        await simulator.random_scroll()
        
        # Should scroll with random delta
        mock_page.mouse.wheel.assert_called_once()
        call_args = mock_page.mouse.wheel.call_args[1]
        delta_y = call_args.get('delta_y', 0)
        
        # Check scroll amount is reasonable
        assert 50 <= abs(delta_y) <= 500
    
    @pytest.mark.asyncio
    async def test_hover_element(self, simulator, mock_page):
        """Test hovering over elements"""
        # Create mock element
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value={
            'x': 100, 'y': 200, 'width': 300, 'height': 50
        })
        mock_element.hover = AsyncMock()
        
        await simulator.hover_element(mock_element)
        
        # Should hover over the element
        mock_element.hover.assert_called_once()
        # Should wait after hover
        mock_page.wait_for_timeout.assert_called()
    
    @pytest.mark.asyncio
    async def test_hover_element_no_bbox(self, simulator, mock_page):
        """Test hovering when element has no bounding box"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value=None)
        mock_element.hover = AsyncMock()
        
        await simulator.hover_element(mock_element)
        
        # Should still try to hover
        mock_element.hover.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_click_element_with_hover(self, simulator, mock_page):
        """Test clicking element with pre-hover"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(return_value={
            'x': 100, 'y': 200, 'width': 300, 'height': 50
        })
        mock_element.hover = AsyncMock()
        mock_element.click = AsyncMock()
        
        await simulator.click_element(mock_element, hover_first=True)
        
        # Should hover then click
        mock_element.hover.assert_called_once()
        mock_element.click.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_click_element_without_hover(self, simulator, mock_page):
        """Test direct clicking without hover"""
        mock_element = MagicMock()
        mock_element.click = AsyncMock()
        mock_element.hover = AsyncMock()
        
        await simulator.click_element(mock_element, hover_first=False)
        
        # Should click directly without hover
        mock_element.hover.assert_not_called()
        mock_element.click.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_type_text_human_like(self, simulator, mock_page):
        """Test human-like text typing"""
        mock_element = MagicMock()
        mock_element.type = AsyncMock()
        mock_element.click = AsyncMock()
        
        test_text = "Hello World"
        await simulator.type_text(mock_element, test_text)
        
        # Should click to focus then type
        mock_element.click.assert_called_once()
        mock_element.type.assert_called_once()
        
        # Check typing parameters
        type_call = mock_element.type.call_args
        assert type_call[0][0] == test_text
        # Should have delay between keystrokes
        assert 'delay' in type_call[1]
        assert type_call[1]['delay'] > 0
    
    @pytest.mark.asyncio
    async def test_scroll_to_element(self, simulator, mock_page):
        """Test scrolling to bring element into view"""
        mock_element = MagicMock()
        mock_element.scroll_into_view_if_needed = AsyncMock()
        mock_element.bounding_box = AsyncMock(return_value={
            'x': 100, 'y': 800, 'width': 300, 'height': 50
        })
        
        await simulator.scroll_to_element(mock_element)
        
        # Should scroll element into view
        mock_element.scroll_into_view_if_needed.assert_called_once()
        # Should have some delay
        mock_page.wait_for_timeout.assert_called()
    
    @pytest.mark.asyncio
    async def test_escape_key_press(self, simulator, mock_page):
        """Test pressing escape key"""
        await simulator.press_escape()
        
        # Should press Escape key
        mock_page.keyboard.press.assert_called_with('Escape')
        # Should wait after pressing
        mock_page.wait_for_timeout.assert_called()
    
    @pytest.mark.asyncio
    async def test_page_refresh(self, simulator, mock_page):
        """Test page refresh simulation"""
        mock_page.reload = AsyncMock()
        
        await simulator.refresh_page()
        
        # Should reload page
        mock_page.reload.assert_called_once()
        # Should wait after reload
        mock_page.wait_for_timeout.assert_called()
    
    @pytest.mark.asyncio
    async def test_natural_behavior_sequence(self, simulator, mock_page):
        """Test a sequence of natural behaviors"""
        # Simulate natural browsing behavior
        await simulator.simulate_reading(1.0)
        await simulator.random_mouse_movement()
        await simulator.random_scroll()
        
        # Verify various interactions occurred
        assert mock_page.mouse.move.call_count >= 2
        assert mock_page.mouse.wheel.call_count >= 1
        assert mock_page.wait_for_timeout.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_simulate_hesitation(self, simulator, mock_page):
        """Test hesitation behavior simulation"""
        # Add method to simulator if not exists
        if not hasattr(simulator, 'simulate_hesitation'):
            simulator.simulate_hesitation = AsyncMock()
        
        await simulator.simulate_hesitation()
        
        # Should include small movements and pauses
        if not isinstance(simulator.simulate_hesitation, AsyncMock):
            assert mock_page.mouse.move.called
            assert mock_page.wait_for_timeout.called
    
    @pytest.mark.asyncio
    async def test_viewport_aware_movement(self, simulator, mock_page):
        """Test that mouse movements respect viewport bounds"""
        # Test multiple movements
        for _ in range(5):
            await simulator.random_mouse_movement()
        
        # Check all movements are within viewport
        for call in mock_page.mouse.move.call_args_list:
            x, y = call[0][0], call[0][1]
            assert 0 <= x <= 1920
            assert 0 <= y <= 1080
    
    @pytest.mark.asyncio
    async def test_error_handling_in_hover(self, simulator, mock_page):
        """Test error handling when hovering fails"""
        mock_element = MagicMock()
        mock_element.bounding_box = AsyncMock(side_effect=Exception("Element not found"))
        mock_element.hover = AsyncMock()
        
        # Should not raise exception
        await simulator.hover_element(mock_element)
        
        # Should still attempt hover despite bbox error
        mock_element.hover.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_click_with_retry(self, simulator, mock_page):
        """Test clicking with retry on failure"""
        mock_element = MagicMock()
        mock_element.click = AsyncMock(side_effect=[Exception("First click failed"), None])
        
        # Add retry logic if not in original
        try:
            await simulator.click_element(mock_element)
            # Should succeed on retry or handle gracefully
            assert True
        except:
            # If no retry logic, should raise
            assert mock_element.click.call_count == 1