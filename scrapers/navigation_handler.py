#!/usr/bin/env python3
"""
Navigation Handler for Facebook Post Monitor
Handles page navigation, scrolling, and element finding
"""

import asyncio
import random
from logging_config import get_logger
from typing import List
from playwright.async_api import Page

from utils.async_patterns import AsyncDelay

logger = get_logger(__name__)


class NavigationHandler:
    """Handles page navigation, scrolling patterns, and element discovery."""
    
    def __init__(self, page: Page, selectors: dict):
        """
        Initialize NavigationHandler
        
        Args:
            page: Playwright page instance
            selectors: Selectors configuration
        """
        self.page = page
        self.selectors = selectors
        
        # Humanization settings for natural behavior
        self.min_scroll_delay = 1.0
        self.max_scroll_delay = 3.0
        
        logger.info("🧭 NavigationHandler initialized")
    
    async def humanized_scroll_page(self) -> None:
        """
        Scroll page in a humanized manner to load more posts
        
        Implements natural scrolling patterns with random variations
        to mimic human behavior
        """
        import random
        import asyncio
        
        logger.debug("📜 Cuộn trang humanized để load posts...")
        
        # Random number of scrolls - Pareto distribution (long tail)
        # Most sessions: 2-4 scrolls, some: 5-10 scrolls (natural variance)
        scroll_count = min(int(random.paretovariate(1.8)) + 2, 10)
        
        for i in range(scroll_count):
            # Random scroll distance - Pareto distribution (natural human scrolling)
            # 70% small-medium (300-800px), 30% large (800-1500px)
            if random.random() < 0.7:
                scroll_distance = random.randint(300, 800)
            else:
                scroll_distance = random.randint(800, 1500)
            
            # Move mouse to random position before scrolling
            await self._random_mouse_movement()
            
            # Scroll with humanized pattern
            await self.page.mouse.wheel(0, scroll_distance)
            
            # ⚡ PARETO DELAY (anti-detection): Long-tail distribution
            # 80% delays: 0.5-2s (fast scrolling)
            # 20% delays: 2-10s (reading/pausing)
            delay = min(random.paretovariate(1.5), 10.0)
            await asyncio.sleep(delay)
            
            logger.debug(f"📜 Cuộn humanized lần {i+1}/{scroll_count} - {scroll_distance}px, delay {delay:.1f}s")
            
            # ✅ ANTI-DETECTION: Reading pauses - PARETO DISTRIBUTION (more natural)
            # Increased to 50% chance and longer duration for more human-like behavior
            if random.random() < 0.5:
                # Pareto: Most 3-8s, some 8-30s (deep reading)
                reading_pause = min(random.paretovariate(1.8) + 3.0, 30.0)  # Increased from 1.5-15s
                await asyncio.sleep(reading_pause)
                logger.debug(f"📖 Mô phỏng đọc trong {reading_pause:.1f}s")    
    async def find_post_elements(self, content_extractor=None) -> List:
        """
        Find all post elements on the page using resilient extraction
        
        Args:
            content_extractor: ContentExtractor instance for data extraction
            
        Returns:
            List of post elements found on the page
        """
        try:
            # Get post_containers configuration from selectors
            post_containers_config = self.selectors.get('post_containers')
            if not post_containers_config:
                logger.warning("⚠️ No post_containers configuration in selectors")
                return []
            
            strategies = post_containers_config.get('strategies', [])
            if not strategies:
                logger.warning("⚠️ No strategies for post_containers")
                return []
            
            # Sort strategies by priority
            sorted_strategies = sorted(strategies, key=lambda x: x.get('priority', 999))
            
            logger.debug(f"🔍 Tìm post containers với {len(sorted_strategies)} strategies")
            
            # Try each strategy to find post containers on the page
            for index, strategy in enumerate(sorted_strategies):
                try:
                    strategy_type = strategy.get('type', 'css')
                    strategy_path = strategy.get('path', '')
                    strategy_desc = strategy.get('description', 'No description')
                    
                    logger.debug(f"🔍 Trying strategy #{index+1}: {strategy_desc}")
                    
                    if strategy_type == 'css':
                        post_elements = await self.page.query_selector_all(strategy_path)
                    elif strategy_type == 'xpath':
                        post_elements = await self.page.query_selector_all(f"xpath={strategy_path}")
                    else:
                        logger.warning(f"⚠️ Unsupported strategy type for post_containers: {strategy_type}")
                        continue
                    
                    if post_elements:
                        logger.info(f"✅ Strategy #{index+1} found {len(post_elements)} posts: {strategy_desc}")
                        return post_elements
                    else:
                        logger.warning(f"⚠️ Strategy #{index+1} found no posts: {strategy_desc}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Strategy #{index+1} failed: {e}")
                    continue
            
            logger.warning("⚠️ All post container strategies failed")
            return []
                
        except Exception as e:
            logger.error(f"❌ Error finding post containers: {e}")
            return []
    
    async def expand_post_content(self, post_element, content_extractor=None) -> None:
        """
        Expand 'See more' to view full content using resilient extraction
        
        Args:
            post_element: The post element to expand
            content_extractor: ContentExtractor instance for finding expand buttons
        """
        import random
        import asyncio
        
        try:
            if not content_extractor:
                logger.warning("⚠️ ContentExtractor not provided, cannot expand content")
                return
            
            # Use resilient extraction to find expand buttons
            expand_elements = await content_extractor.extract_data(post_element, 'expand_buttons')
            
            if expand_elements and isinstance(expand_elements, list):
                for expand_element in expand_elements:
                    try:
                        text = await expand_element.inner_text()
                        if text and ('see more' in text.lower() or 'xem thêm' in text.lower()):
                            # Humanized interaction with expand button
                            await self._humanized_click(expand_element)
                            
                            # Wait with random delay for content to expand
                            expand_delay = random.uniform(0.3, 0.8)
                            await asyncio.sleep(expand_delay)
                            
                            logger.debug("✅ Expanded post content using resilient extraction")
                            return
                    except Exception:
                        continue
            
            logger.debug("⚠️ No expand buttons found with resilient extraction")
                        
        except Exception as e:
            logger.debug(f"Không expand được content: {e}")
    
    async def wait_for_posts_to_load(self, timeout: int = 20000) -> bool:
        """
        Wait for posts to load on the page
        
        Args:
            timeout: Maximum wait time in milliseconds
            
        Returns:
            bool: True if posts loaded successfully
        """
        try:
            # Get first post container selector
            container_selectors = self.selectors.get('post', {}).get('containers', [])
            
            if not container_selectors:
                logger.warning("⚠️ No post container selectors to wait for")
                return False
            
            first_selector = container_selectors[0]
            
            logger.debug(f"⏳ Waiting for posts to load with selector: {first_selector}")
            
            # Wait for first post to appear
            await self.page.wait_for_selector(first_selector, timeout=timeout)
            
            logger.debug("✅ Posts loaded successfully")
            return True
            
        except Exception as e:
            logger.warning(f"⏰ Posts loading timeout or error: {e}")
            return False
    
    async def scroll_to_element(self, element, behavior: str = "smooth") -> None:
        """
        Scroll to bring element into view
        
        Args:
            element: Element to scroll to
            behavior: Scroll behavior ('smooth' or 'instant')
        """
        try:
            await element.scroll_into_view_if_needed()
            
            # Add small humanized delay
            await AsyncDelay.smart_delay(0.5, jitter=0.2)
            
            logger.debug("📍 Scrolled to element")
            
        except Exception as e:
            logger.debug(f"❌ Error scrolling to element: {e}")
    
    async def check_page_end(self) -> bool:
        """
        Check if we've reached the end of the page
        
        Returns:
            bool: True if at page end
        """
        try:
            # Check if we can scroll further
            before_height = await self.page.evaluate("document.body.scrollHeight")
            
            # Try to scroll down
            await self.page.mouse.wheel(0, 1000)
            await AsyncDelay.smart_delay(2.0, jitter=0.3)
            
            after_height = await self.page.evaluate("document.body.scrollHeight")
            
            # If height didn't change, we're likely at the end
            at_end = before_height == after_height
            
            if at_end:
                logger.debug("📍 Reached end of page")
            
            return at_end
            
        except Exception as e:
            logger.debug(f"❌ Error checking page end: {e}")
            return False
    
    async def _random_mouse_movement(self) -> None:
        """Move mouse to random position for natural behavior"""
        try:
            # Get viewport size
            viewport = await self.page.evaluate("""
                () => ({
                    width: window.innerWidth,
                    height: window.innerHeight
                })
            """)
            
            # Random position within viewport
            x = random.randint(100, viewport['width'] - 100)
            y = random.randint(100, viewport['height'] - 100)
            
            # Move mouse smoothly
            await self.page.mouse.move(x, y)
            
            logger.debug(f"🖱️ Mouse moved to ({x}, {y})")
            
        except Exception as e:
            logger.debug(f"❌ Error moving mouse: {e}")
    
    async def _humanized_click(self, element) -> None:
        """
        Perform humanized click on element
        
        Args:
            element: Element to click
        """
        try:
            # Scroll element into view first
            await self.scroll_to_element(element)
            
            # Random pre-click delay
            await AsyncDelay.smart_delay(
                random.uniform(0.1, 0.5),
                jitter=0.1
            )
            
            # Click the element
            await element.click()
            
            # Random post-click delay
            await AsyncDelay.smart_delay(
                random.uniform(0.2, 0.8),
                jitter=0.1
            )
            
            logger.debug("🖱️ Humanized click performed")
            
        except Exception as e:
            logger.debug(f"❌ Error performing humanized click: {e}")
    
    async def get_page_stats(self) -> dict:
        """
        Get current page statistics
        
        Returns:
            dict: Page stats including scroll position, height, etc.
        """
        try:
            stats = await self.page.evaluate("""
                () => ({
                    scrollTop: window.pageYOffset,
                    scrollHeight: document.body.scrollHeight,
                    viewportHeight: window.innerHeight,
                    url: window.location.href,
                    title: document.title
                })
            """)
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Error getting page stats: {e}")
            return {"error": str(e)}
