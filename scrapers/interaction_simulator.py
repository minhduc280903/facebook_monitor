#!/usr/bin/env python3
"""
Interaction Simulator for Facebook Post Monitor
Handles human-like interactions to avoid detection
"""

import asyncio
import random
from logging_config import get_logger
from playwright.async_api import Page

from utils.async_patterns import AsyncDelay

logger = get_logger(__name__)


class InteractionSimulator:
    """Simulates human-like interactions to avoid bot detection."""
    
    def __init__(self, page: Page, session_id: str = None):
        """
        Initialize InteractionSimulator
        
        Args:
            page: Playwright page instance
            session_id: Optional session ID for per-session behavior variation
        """
        self.page = page
        
        # ⚡ PER-SESSION PARETO ALPHA (anti-detection)
        # Different sessions have slightly different behavior patterns
        if session_id:
            import hashlib
            import random as random_module
            seed = int(hashlib.md5(session_id.encode()).hexdigest()[:8], 16)
            rng = random_module.Random(seed)
            self.pareto_alpha = rng.uniform(1.2, 1.8)  # ✅ Unique per session
        else:
            self.pareto_alpha = 1.5  # Default fallback
        
        logger.info(f"🤖 InteractionSimulator initialized (Pareto α={self.pareto_alpha:.2f})")
    
    async def random_mouse_movement(self) -> None:
        """
        Perform random mouse movement to simulate human behavior
        
        Moves mouse to random positions with human-like patterns
        """
        import random
        
        try:
            # Get viewport size
            viewport = self.page.viewport_size or {'width': 1920, 'height': 1080}
            
            # Random position within viewport (avoid edges)
            margin = 50
            x = random.randint(margin, viewport['width'] - margin)
            y = random.randint(margin, viewport['height'] - margin)
            
            # Move mouse with human-like steps
            await self.page.mouse.move(x, y, steps=random.randint(5, 15))
            
            # Occasional click on empty space (rare)
            if random.random() < 0.05:  # 5% chance
                await self.page.mouse.click(x, y)
                logger.debug(f"🐭 Random click at ({x}, {y})")
            else:
                logger.debug(f"🐭 Mouse moved to ({x}, {y})")
            
        except Exception as e:
            logger.debug(f"Random mouse movement failed: {e}")
    
    async def humanized_delay_between_posts(self, current_index: int, total_posts: int) -> None:
        """
        Create humanized delay between processing posts with occasional extra interactions
        
        Args:
            current_index: Current post index being processed
            total_posts: Total number of posts to process
        """
        import random
        import asyncio
        
        try:
            # ⚡ PARETO DELAY (anti-detection) - per-session alpha
            # 80% delays: 0.3-1.5s (fast actions)
            # 20% delays: 1.5-8s (long pauses)
            base_delay = min(random.paretovariate(self.pareto_alpha) * 0.3, 8.0)
            
            # Occasionally VERY long pause (like real user distracted)
            if random.random() < 0.05:  # 5% chance (reduced from 20%)
                base_delay *= random.uniform(3.0, 6.0)
                logger.debug(f"😴 Extended pause (distracted): {base_delay:.1f}s")
            
            # Random interactions during delay
            if random.random() < 0.3:  # 30% chance
                await self.random_interaction_during_delay()
            
            await asyncio.sleep(base_delay)
            
            # Progress-based pauses (longer pauses as we process more)
            progress = (current_index + 1) / total_posts
            if progress > 0.5 and random.random() < 0.15:  # 15% chance after halfway
                thinking_pause = random.uniform(1.0, 3.0)
                await asyncio.sleep(thinking_pause)
                logger.debug(f"🤔 Thinking pause: {thinking_pause:.1f}s")
                
        except Exception as e:
            logger.debug(f"Humanized delay failed: {e}")
    
    async def random_interaction_during_delay(self) -> None:
        """
        Perform random interactions during delays to simulate human behavior
        
        Includes scrolling, mouse movements, and reading pauses
        """
        import random
        import asyncio
        
        try:
            interaction_type = random.choice([
                'scroll_small',
                'mouse_move',
                'pause_and_look',
                'mini_scroll_back'
            ])
            
            if interaction_type == 'scroll_small':
                # Small scroll up or down
                scroll_amount = random.randint(100, 400) * random.choice([-1, 1])
                await self.page.mouse.wheel(0, scroll_amount)
                logger.debug(f"📜 Small scroll: {scroll_amount}px")
                
            elif interaction_type == 'mouse_move':
                await self.random_mouse_movement()
                
            elif interaction_type == 'pause_and_look':
                # Simulate reading/looking
                pause_time = random.uniform(0.5, 2.0)
                await asyncio.sleep(pause_time)
                logger.debug(f"👀 Looking pause: {pause_time:.1f}s")
                
            elif interaction_type == 'mini_scroll_back':
                # Scroll down then back up (like re-reading)
                down_scroll = random.randint(200, 500)
                await self.page.mouse.wheel(0, down_scroll)
                await asyncio.sleep(random.uniform(0.5, 1.0))
                await self.page.mouse.wheel(0, -down_scroll // 2)
                logger.debug(f"🔄 Scroll back pattern: {down_scroll}px")
                
        except Exception as e:
            logger.debug(f"Random interaction failed: {e}")
    
    async def humanized_click(self, element) -> None:
        """
        Perform a humanized click on an element
        
        Args:
            element: The element to click on
        """
        import random
        import asyncio
        
        try:
            # Move mouse to element first
            box = await element.bounding_box()
            if box:
                # Click at random position within element (not exact center)
                click_x = box['x'] + random.uniform(0.3, 0.7) * box['width']
                click_y = box['y'] + random.uniform(0.3, 0.7) * box['height']
                
                # Move to position first
                await self.page.mouse.move(click_x, click_y, steps=random.randint(3, 8))
                
                # Small pause before click
                await asyncio.sleep(random.uniform(0.1, 0.3))
                
                # Click with slight randomness in timing
                await self.page.mouse.down()
                await asyncio.sleep(random.uniform(0.05, 0.15))  # Hold time
                await self.page.mouse.up()
                
                logger.debug(f"👆 Humanized click at ({click_x:.1f}, {click_y:.1f})")
            else:
                # Fallback to regular click
                await element.click()
                
        except Exception as e:
            logger.debug(f"Humanized click failed, using fallback: {e}")
            await element.click()
    
    async def simulate_typing(self, element, text: str) -> None:
        """
        Simulate human-like typing
        
        Args:
            element: Input element to type into
            text: Text to type
        """
        try:
            await element.click()  # Focus the element
            await AsyncDelay.smart_delay(0.2, jitter=0.1)
            
            for char in text:
                await self.page.keyboard.press(char)
                
                # Random delay between keystrokes
                typing_delay = random.uniform(0.05, 0.15)
                
                # Occasional longer pauses (thinking)
                if random.random() < 0.1:  # 10% chance
                    typing_delay += random.uniform(0.3, 0.8)
                
                await AsyncDelay.smart_delay(typing_delay, jitter=0.02)
            
            logger.debug(f"⌨️ Simulated typing: '{text}' ({len(text)} characters)")
            
        except Exception as e:
            logger.debug(f"❌ Error in simulated typing: {e}")
    
    async def simulate_scrolling_behavior(self, duration: float = 10.0) -> None:
        """
        Simulate natural scrolling behavior over a period
        
        Args:
            duration: How long to scroll for (seconds)
        """
        try:
            end_time = asyncio.get_event_loop().time() + duration
            
            while asyncio.get_event_loop().time() < end_time:
                # Random scroll direction and amount
                scroll_direction = random.choice([-1, 1, 1, 1])  # Bias towards down
                scroll_amount = random.randint(100, 500) * scroll_direction
                
                await self.page.mouse.wheel(0, scroll_amount)
                
                # Random pause between scrolls
                pause = random.uniform(0.8, 2.5)
                await AsyncDelay.smart_delay(pause, jitter=0.3)
                
                # Occasional mouse movement during scrolling
                if random.random() < 0.4:  # 40% chance
                    await self.random_mouse_movement()
            
            logger.debug(f"📜 Completed natural scrolling behavior ({duration}s)")
            
        except Exception as e:
            logger.debug(f"❌ Error in scrolling behavior: {e}")
    
    async def simulate_distraction(self) -> None:
        """
        Simulate user getting distracted (tab switching, etc.)
        """
        try:
            distraction_types = ['pause', 'mouse_leave', 'minimal_activity']
            distraction = random.choice(distraction_types)
            
            if distraction == 'pause':
                # Simple long pause
                pause_time = random.uniform(5.0, 15.0)
                await AsyncDelay.smart_delay(pause_time, jitter=1.0)
                logger.debug(f"😴 Simulated distraction pause: {pause_time:.1f}s")
                
            elif distraction == 'mouse_leave':
                # Move mouse to edge of screen
                await self.page.mouse.move(0, 0)
                pause_time = random.uniform(3.0, 8.0)
                await AsyncDelay.smart_delay(pause_time, jitter=0.5)
                logger.debug(f"👋 Simulated mouse leaving page: {pause_time:.1f}s")
                
            elif distraction == 'minimal_activity':
                # Some small movements but mostly inactive
                for _ in range(random.randint(2, 4)):
                    await self.random_mouse_movement()
                    await AsyncDelay.smart_delay(random.uniform(2.0, 4.0), jitter=0.5)
                logger.debug("🎯 Simulated minimal distraction activity")
                
        except Exception as e:
            logger.debug(f"❌ Error in distraction simulation: {e}")
    
    async def _prepare_for_click(self, element) -> None:
        """
        Prepare for clicking an element (scroll into view, hover)
        
        Args:
            element: Element to prepare for clicking
        """
        try:
            # Scroll element into view if needed
            await element.scroll_into_view_if_needed()
            
            # Move mouse near the element
            box = await element.bounding_box()
            if box:
                # Add slight randomization to click position
                target_x = box['x'] + box['width'] / 2 + random.randint(-10, 10)
                target_y = box['y'] + box['height'] / 2 + random.randint(-5, 5)
                
                await self.page.mouse.move(target_x, target_y)
                
                # Brief hover delay
                await AsyncDelay.smart_delay(
                    random.uniform(0.1, 0.3),
                    jitter=0.05
                )
            
        except Exception as e:
            logger.debug(f"❌ Error preparing for click: {e}")
    
    async def _random_hover(self) -> None:
        """
        Hover over a random element on the page
        """
        try:
            # Find clickable elements to hover over
            hoverable_selectors = [
                'a', 'button', '[role="button"]', '[role="link"]',
                'span[role="button"]', 'div[role="button"]'
            ]
            
            for selector in hoverable_selectors:
                try:
                    elements = await self.page.query_selector_all(selector)
                    if elements:
                        # Pick random element
                        random_element = random.choice(elements)
                        
                        # Check if it's visible
                        if await random_element.is_visible():
                            await random_element.hover()
                            
                            # Brief hover time
                            await AsyncDelay.smart_delay(
                                random.uniform(0.3, 1.0),
                                jitter=0.1
                            )
                            
                            logger.debug(f"👆 Random hover on: {selector}")
                            return
                            
                except Exception:
                    continue
            
            logger.debug("ℹ️ No suitable elements found for random hover")
            
        except Exception as e:
            logger.debug(f"❌ Error in random hover: {e}")
    
    async def warmup_session(self, duration_range: tuple = (15, 25)) -> None:
        """
        🔥 WARMUP SESSION: Simulate normal browsing before scraping
        
        Purpose:
        - Build behavioral fingerprint as "normal user"
        - Avoid cold-start detection (new session immediately scraping = bot)
        - Establish natural interaction patterns
        
        Activities:
        - Random scrolling (2-5 times)
        - Mouse movements (3-7 times)
        - Occasional clicks on feed items (20% chance)
        - Reading pauses (2-8s between actions)
        
        Args:
            duration_range: Min/max warmup duration in seconds (default: 15-25s)
        """
        import random
        import asyncio
        
        try:
            warmup_duration = random.uniform(*duration_range)
            logger.info(f"🔥 WARMUP: Starting {warmup_duration:.1f}s warmup session...")
            
            start_time = asyncio.get_event_loop().time()
            end_time = start_time + warmup_duration
            
            # Random number of activities during warmup
            num_scrolls = random.randint(2, 5)
            num_mouse_moves = random.randint(3, 7)
            
            activities = []
            
            # Add scroll activities
            for i in range(num_scrolls):
                activities.append(('scroll', i))
            
            # Add mouse movement activities
            for i in range(num_mouse_moves):
                activities.append(('mouse', i))
            
            # Shuffle activities for natural randomness
            random.shuffle(activities)
            
            # Execute activities with time constraint
            for activity_type, activity_idx in activities:
                # Check if we still have time
                current_time = asyncio.get_event_loop().time()
                if current_time >= end_time:
                    break
                
                try:
                    if activity_type == 'scroll':
                        # Natural scroll amount
                        scroll_amount = random.randint(300, 800)
                        await self.page.mouse.wheel(0, scroll_amount)
                        logger.debug(f"🔥 WARMUP: Scrolled {scroll_amount}px")
                        
                        # Pareto delay after scroll
                        delay = min(random.paretovariate(self.pareto_alpha) * 0.5, 5.0)
                        await asyncio.sleep(delay)
                        
                    elif activity_type == 'mouse':
                        await self.random_mouse_movement()
                        
                        # Shorter delay after mouse movement
                        delay = random.uniform(0.5, 2.0)
                        await asyncio.sleep(delay)
                        
                        # 20% chance to click on something harmless
                        if random.random() < 0.2:
                            # Try to find and hover over a feed item (without clicking)
                            try:
                                feed_items = await self.page.query_selector_all('div[role="article"], div[role="feed"] > div')
                                if feed_items and len(feed_items) > 0:
                                    random_item = random.choice(feed_items[:5])  # Only top 5 to avoid scrolling
                                    await random_item.hover()
                                    logger.debug(f"🔥 WARMUP: Hovered over feed item")
                                    await asyncio.sleep(random.uniform(1.0, 3.0))
                            except Exception:
                                pass  # Ignore hover errors during warmup
                    
                except Exception as e:
                    logger.debug(f"🔥 WARMUP: Minor error in activity: {e}")
                    continue
            
            # Final reading pause before actual scraping
            final_pause = random.uniform(2.0, 5.0)
            await asyncio.sleep(final_pause)
            
            actual_duration = asyncio.get_event_loop().time() - start_time
            logger.info(f"✅ WARMUP: Completed {actual_duration:.1f}s warmup session")
            
        except Exception as e:
            logger.warning(f"⚠️ WARMUP: Error during warmup (non-critical): {e}")
            # Non-critical error, continue with scraping
    
    async def get_interaction_stats(self) -> dict:
        """
        Get interaction statistics
        
        Returns:
            dict: Interaction statistics
        """
        return {
            "simulator_active": True,
            "delay_distribution": "Pareto(alpha=1.5)",
            "typical_delay_range": "0.3-1.5s (80%), 1.5-8s (20%)"
        }
