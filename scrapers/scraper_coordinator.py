#!/usr/bin/env python3
"""
Scraper Coordinator for Facebook Post Monitor
Main orchestration module that coordinates all scraper components
"""

import json
from logging_config import get_logger
import os
from datetime import datetime, timezone, date, timedelta
from typing import Optional, Dict, Any, List
import asyncio
import random
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

from core.database_manager import DatabaseManager
from .browser_controller import BrowserController, CaptchaException
from .content_extractor import ContentExtractor
from .navigation_handler import NavigationHandler
from .interaction_simulator import InteractionSimulator
from utils.timestamp_parser import parse_facebook_timestamp

logger = get_logger(__name__)


class ScraperCoordinator:
    """
    Main coordinator that orchestrates all scraper components
    Implements the Hybrid Logic: fast stream + one-time stream
    """
    
    def __init__(self, db_manager: DatabaseManager, page: Page, session_name: str = None):
        """
        Initialize ScraperCoordinator with all components
        
        Args:
            db_manager: Database manager instance
            page: Playwright page instance
            session_name: Optional session name for per-session behavior variation
        """
        self.db_manager = db_manager
        self.page = page
        self.session_name = session_name
        self.tracking_duration_days = 7
        
        # Load scraping configuration
        try:
            from config import settings
            self.config = settings.scraping
            logger.info(f"📋 Loaded scraping config: max_scroll_hours={self.config.max_scroll_hours}h")
        except Exception as e:
            logger.warning(f"⚠️ Could not load scraping config: {e}, using defaults")
            # Fallback defaults
            class DefaultConfig:
                max_posts_safety_limit = 999999
                max_scroll_hours = 24
            self.config = DefaultConfig()
        
        # Load selectors configuration
        self.selectors = self._load_selectors()
        
        # Initialize all components with proper parameters
        self.browser_controller = BrowserController(page, self.selectors)
        self.content_extractor = ContentExtractor(page, self.selectors)
        self.navigation_handler = NavigationHandler(page, self.selectors)
        # ✅ Pass session_name for per-session behavior variation
        self.interaction_simulator = InteractionSimulator(page, session_id=session_name)
        
        # Humanization settings
        self.humanization_enabled = True
        
        logger.info(f"🎯 ScraperCoordinator initialized with all components (session={session_name})")
        logger.info("🚀 Date-based scraping enabled - will scrape until reaching start_date (deploy date)")
    
    def _parse_facebook_timestamp(self, time_string: str) -> Optional[datetime]:
        """
        Phân tích chuỗi thời gian Facebook thành datetime object.
        
        ⚠️ REFACTORED: Logic đã được tách ra utils.timestamp_parser để dễ maintain
        
        Args:
            time_string: Chuỗi thời gian từ Facebook
            
        Returns:
            datetime object hoặc None nếu không thể phân tích
        """
        return parse_facebook_timestamp(time_string)
    
    async def _extract_post_time(self, post_element) -> Optional[str]:
        """
        Extract thời gian bài viết từ post element.
        
        Args:
            post_element: Post element từ Playwright
            
        Returns:
            Chuỗi thời gian hoặc None nếu không tìm thấy
        """
        try:
            # Strategy 1: Tìm time element với datetime attribute
            time_element = await post_element.query_selector('time')
            if time_element:
                datetime_attr = await time_element.get_attribute('datetime')
                if datetime_attr:
                    return datetime_attr
                
                # Fallback: lấy text content của time element
                time_text = await time_element.inner_text()
                if time_text:
                    return time_text.strip()
            
            # Strategy 2: Tìm các selector phổ biến cho timestamp
            timestamp_selectors = [
                '[data-utime]',
                '[title*="ago"]',
                '[aria-label*="ago"]',
                'span:has-text("ago")',
                'span:has-text("hour")',
                'span:has-text("minute")',
                'span:has-text("day")',
                'a[href*="story_fbid"]'  # Link có thời gian
            ]
            
            for selector in timestamp_selectors:
                try:
                    element = await post_element.query_selector(selector)
                    if element:
                        # Thử lấy title hoặc aria-label trước
                        for attr in ['title', 'aria-label', 'data-utime']:
                            attr_value = await element.get_attribute(attr)
                            if attr_value:
                                return attr_value
                        
                        # Fallback: lấy text content
                        text = await element.inner_text()
                        if text and any(word in text.lower() for word in ['ago', 'hour', 'minute', 'day', 'yesterday']):
                            return text.strip()
                except (PlaywrightError, AttributeError) as e:
                    logger.debug(f"Failed to extract post time from element: {e}")
                    continue
            
            logger.debug("⚠️ Không tìm thấy thời gian bài viết")
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Lỗi extract post time: {e}")
            return None
    
    def _load_selectors(self) -> Dict[str, Any]:
        """
        Load selectors from selectors.json or use fallback
        
        Returns:
            Dict containing selectors configuration
        """
        try:
            selectors_file = 'selectors.json'
            if os.path.exists(selectors_file):
                with open(selectors_file, 'r', encoding='utf-8') as f:
                    selectors = json.load(f)
                logger.info("✅ Loaded selectors from selectors.json")
                return selectors
            else:
                logger.warning(f"⚠️ {selectors_file} not found, using fallback selectors")
                return self._get_fallback_selectors()
                
        except Exception as e:
            logger.error(f"❌ Error loading selectors: {e}, using fallback")
            return self._get_fallback_selectors()
    
    def _get_fallback_selectors(self) -> Dict[str, Any]:
        """
        Fallback selectors if selectors.json is not available
        
        Returns:
            Dict containing fallback selectors
        """
        return {
            "post": {
                "containers": [
                    'div[data-pagelet="FeedUnit"]',
                    'div[role="article"]',
                    'div[data-testid="story-subtitle"]'
                ],
                "fields": {
                    "like_count": {
                        "strategies": [
                            {"type": "css", "path": 'span[data-testid="like_count"]'},
                            {"type": "css", "path": 'span:has-text("Like")'}, 
                            {"type": "css", "path": 'a[aria-label*="reaction"]'}
                        ],
                        "validation": {"type": "integer", "min": 0}
                    },
                    "comment_count": {
                        "strategies": [
                            {"type": "css", "path": 'span:has-text("comment")'},
                            {"type": "css", "path": 'a[aria-label*="comment"]'}
                        ],
                        "validation": {"type": "integer", "min": 0}
                    },
                    "author": {
                        "strategies": [
                            {"type": "css", "path": 'h3 a'},
                            {"type": "css", "path": 'strong a'}
                        ],
                        "validation": {"type": "string", "min_length": 1}
                    }
                }
            }
        }
    
    async def process_url(self, url: str, max_posts: Optional[int] = None, max_scroll_time: Optional[int] = None) -> Dict[str, Any]:
        """
        Main processing function implementing Hybrid Logic with atomic dual-stream
        với time-based filtering
        
        Args:
            url: Facebook group/page URL to process
            max_posts: Maximum number of posts to collect (None = use config defaults)
            max_scroll_time: Maximum time to spend scrolling in seconds (None = use config defaults)
            
        Returns:
            Dict containing processing results
        """
        logger.info(f"🎯 Bắt đầu xử lý URL: {url}")
        
        # Apply config-based defaults
        if max_posts is None:
            max_posts = self.config.max_posts_safety_limit
        if max_scroll_time is None:
            max_scroll_time = self.config.max_scroll_hours * 3600  # Convert hours to seconds
            
        logger.info(f"📊 Scraping limits: max_posts={max_posts:,}, max_time={max_scroll_time/3600:.1f}h")
        
        # ===== KIỂM TRA VÀ THIẾT LẬP START_DATE =====
        start_date_str = self.db_manager.get_setting('initial_scrape_start_date')
        
        if start_date_str is None:
            # Nếu không có, đây là lần chạy đầu tiên trên CSDL trống
            scrape_since_date = date.today()
            # Lưu lại ngày này cho các lần chạy sau
            self.db_manager.set_setting('initial_scrape_start_date', scrape_since_date.isoformat())
            logger.info(f"🎯 Lần chạy đầu tiên, thiết lập start_date là: {scrape_since_date}")
        else:
            # Nếu có, sử dụng ngày đã lưu
            scrape_since_date = date.fromisoformat(start_date_str)
            logger.info(f"🎯 Quét các bài viết từ ngày: {scrape_since_date}")
        
        try:
            # Apply anti-detection measures
            await self.browser_controller.apply_stealth_mode()
            
            # Navigate to URL
            navigation_success = await self.browser_controller.navigate_to_url(url, retries=3)
            if not navigation_success:
                logger.error(f"❌ Không thể điều hướng đến URL {url} sau nhiều lần thử.")
                return {
                    "new_posts": 0, 
                    "interactions_logged": 0, 
                    "errors": 1, 
                    "reason": "Navigation failed"
                }
            
            # Check for CAPTCHA after navigation
            if await self.browser_controller.is_captcha_present():
                logger.critical(f"🚨 CAPTCHA detected on URL: {url}")
                raise CaptchaException(f"CAPTCHA detected on {url}", "navigation")
            
            # 🚀 BATCH PROCESSING: Scroll + Extract incrementally
            results = await self._scroll_and_process_batches(url, scrape_since_date, max_posts, max_scroll_time)
            
            logger.info(f"✅ Hoàn thành xử lý URL: {results}")
            return results
            
        except CaptchaException as e:
            logger.critical(f"🚨 CAPTCHA detected during processing URL {url}: {e}")
            # Re-raise CAPTCHA exception for higher-level handling
            raise
        except Exception as e:
            logger.error(f"💥 Critical error processing URL {url}: {type(e).__name__}: {e}", exc_info=True)
            return {"new_posts": 0, "interactions_logged": 0, "errors": 1, "reason": f"{type(e).__name__}: {str(e)}"}

    async def _scroll_and_process_batches(self, url: str, scrape_since_date: date, max_posts: int, max_scroll_time: int) -> Dict[str, Any]:
        """
        🚀 BATCH PROCESSING: Scroll + Extract incrementally instead of waiting for all scrolling to finish
        
        This method combines scrolling and extraction:
        1. Scroll to find new posts
        2. Extract and save those posts IMMEDIATELY
        3. Continue scrolling
        4. Repeat until done
        
        Benefits:
        - ✅ Get data immediately, no waiting
        - ✅ Avoid stale elements (elements don't get old)
        - ✅ Lower memory usage (don't hold 400+ elements)
        - ✅ Better performance
        """
        import time
        
        start_time = time.time()
        results = {"new_posts": 0, "interactions_logged": 0, "errors": 0}
        
        # Track processed posts to avoid duplicates
        processed_post_signatures = set()
        processed_count = 0
        total_posts_found = 0
        
        stale_scrolls = 0
        total_scrolls = 0
        should_stop = False  # Flag for date-based stopping
        
        logger.info(f"🚀 BATCH PROCESSING MODE: Extract while scrolling!")
        logger.info(f"📊 Limits: max_posts={max_posts:,}, max_time={max_scroll_time/3600:.1f}h")
        logger.info(f"📅 Will stop when finding posts older than {scrape_since_date}")
        
        # Initial load
        post_elements = await self.navigation_handler.find_post_elements(self.content_extractor)
        total_posts_found = len(post_elements)
        logger.info(f"📍 Initial load: {total_posts_found} posts found")
        
        while not should_stop and stale_scrolls < 3:
            # Check safety limits
            elapsed_time = time.time() - start_time
            if elapsed_time > max_scroll_time:
                logger.warning(f"⏰ SAFETY: Time limit reached. Stopping.")
                break
            
            if processed_count >= max_posts:
                logger.warning(f"📊 SAFETY: Processed {processed_count} posts. Stopping.")
                break
            
            # 🎯 PROCESS CURRENT BATCH
            new_posts_in_batch = []
            for post_element in post_elements:
                try:
                    # Quick signature check to avoid reprocessing
                    post_html_snippet = (await post_element.inner_html())[:200]
                    quick_sig = str(hash(post_html_snippet))
                    
                    if quick_sig in processed_post_signatures:
                        continue  # Already processed
                    
                    processed_post_signatures.add(quick_sig)
                    new_posts_in_batch.append(post_element)
                    
                except Exception as e:
                    logger.debug(f"Skip post due to error getting signature: {e}")
                    continue
            
            logger.info(f"📦 Processing batch: {len(new_posts_in_batch)} new posts")
            
            # 🚀 OPTIMIZATION: Batch collect signatures first to avoid N+1 queries
            batch_data = []
            for post_element in new_posts_in_batch:
                try:
                    # Generate signature for this post
                    post_signature = await self.content_extractor.generate_post_signature(post_element)
                    if post_signature:
                        batch_data.append({
                            'element': post_element,
                            'signature': post_signature
                        })
                except Exception as e:
                    logger.debug(f"Skip post - cannot generate signature: {e}")
                    continue
            
            # 🚀 BATCH CHECK: Single query instead of N queries
            all_signatures = [item['signature'] for item in batch_data]
            existing_signatures = self.db_manager.get_existing_post_signatures_batch(all_signatures)
            logger.debug(f"⚡ Batch check: {len(existing_signatures)}/{len(all_signatures)} posts exist")
            
            # Process each post with pre-fetched existence info
            for i, item in enumerate(batch_data):
                try:
                    processed_count += 1
                    post_element = item['element']
                    post_signature = item['signature']
                    is_new_post = post_signature not in existing_signatures
                    
                    # TIME-BASED FILTERING
                    try:
                        time_string = await self._extract_post_time(post_element)
                        if time_string:
                            post_datetime = self._parse_facebook_timestamp(time_string)
                            
                            if post_datetime is None:
                                logger.debug(f"Cannot parse time: '{time_string}', continuing")
                            elif post_datetime.date() < scrape_since_date:
                                logger.info(f"📅 Found old post ({post_datetime.date()}), stopping extraction")
                                should_stop = True
                                break
                    except Exception as e:
                        logger.debug(f"Error checking post time: {e}")
                    
                    # ✅ ANTI-DETECTION: Random mouse movement while viewing post (40% chance)
                    if random.random() < 0.4:
                        await self.interaction_simulator.random_mouse_movement()
                    
                    # FAST STREAM - Extract interactions (without DB check, we already know)
                    interaction_result = await self._process_fast_stream_optimized(
                        post_element, url, post_signature, is_new_post
                    )
                    
                    if interaction_result["success"]:
                        results["interactions_logged"] += 1
                        
                        # Atomic dual-stream for new posts
                        if is_new_post:
                            logger.info(f"✨ New post detected ({processed_count}/{total_posts_found})")
                            
                            await self.navigation_handler.expand_post_content(post_element, self.content_extractor)
                            
                            # ✅ ANTI-DETECTION: Simulate reading new post (20% chance)
                            if random.random() < 0.2:
                                await self.interaction_simulator.random_interaction_during_delay()
                            
                            post_details = await self._extract_post_details(post_element)
                            
                            if post_details:
                                atomic_success = self.db_manager.add_new_post_with_interaction(
                                    post_signature=post_signature,
                                    post_url=post_details.get('post_url', ''),
                                    source_url=url,
                                    like_count=interaction_result['like_count'],
                                    comment_count=interaction_result['comment_count'],
                                    author_name=post_details.get('author_name', ''),
                                    author_id=post_details.get('author_id', ''),
                                    post_content=post_details.get('post_content', ''),
                                    post_type=post_details.get('post_type', 'TEXT'),
                                    post_status=post_details.get('post_status', 'ACTIVE')
                                )
                                
                                if atomic_success:
                                    results["new_posts"] += 1
                                    results["interactions_logged"] -= 1
                                    logger.info(f"🎯 Saved post {processed_count}: {post_signature[:30]}...")
                    else:
                        results["errors"] += 1
                    
                    # ✅ ANTI-DETECTION: Human-like delay with interactions (Pareto distribution + mouse movements)
                    if i < len(batch_data) - 1:  # Not last post
                        await self.interaction_simulator.humanized_delay_between_posts(
                            current_index=i,
                            total_posts=len(batch_data)
                        )
                        
                except Exception as e:
                    logger.error(f"❌ Error processing post {processed_count}: {e}")
                    results["errors"] += 1
                    continue
            
            if should_stop:
                logger.info("🛑 Stopping due to date limit reached")
                break
            
            # 💤 IDLE PERIOD: Random chance to simulate user distraction/multitasking
            # Real users don't continuously scroll - they get distracted, check other tabs, etc.
            # 10-15% chance per batch (adjusted by session variation)
            idle_chance = 0.10 + (random.random() * 0.05)  # 10-15% base chance
            if random.random() < idle_chance:
                # Pareto distribution for idle duration
                # Most idles: 30-60s (quick distraction)
                # Some idles: 60-120s (longer break)
                idle_duration = min(random.paretovariate(1.5) * 30, 120.0)
                logger.info(f"💤 IDLE: Simulating user distraction for {idle_duration:.1f}s...")
                
                # During idle, minimal or no activity
                # 30% chance to have minimal mouse movement during idle
                if random.random() < 0.3:
                    await asyncio.sleep(idle_duration * 0.7)
                    await self.interaction_simulator.random_mouse_movement()
                    await asyncio.sleep(idle_duration * 0.3)
                    logger.debug("💤 IDLE: Minor activity during idle")
                else:
                    # Complete idle - no activity
                    await asyncio.sleep(idle_duration)
                    logger.debug("💤 IDLE: Complete idle period")
                
                logger.info(f"✅ IDLE: Resumed after {idle_duration:.1f}s break")
            
            # 📜 SCROLL FOR MORE POSTS
            last_count = total_posts_found
            await self.navigation_handler.humanized_scroll_page()
            total_scrolls += 1
            await asyncio.sleep(random.uniform(2.0, 4.0))
            
            post_elements = await self.navigation_handler.find_post_elements(self.content_extractor)
            total_posts_found = len(post_elements)
            
            if total_posts_found > last_count:
                stale_scrolls = 0
                new_count = total_posts_found - last_count
                logger.info(f"📜 Scroll #{total_scrolls}: Found {new_count} more posts (total: {total_posts_found})")
            else:
                stale_scrolls += 1
                logger.info(f"📜 Scroll #{total_scrolls}: No new posts (attempt {stale_scrolls}/3)")
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Batch processing done: {processed_count} posts processed in {elapsed:.1f}s ({total_scrolls} scrolls)")
        
        return results

    async def _scroll_to_bottom_of_feed(self, max_posts: Optional[int] = None, max_scroll_time: Optional[int] = None) -> List[Any]:
        """
        Scrolls to load posts with intelligent stopping conditions.

        UNLIMITED MODE: Will scroll until date-based filtering stops or safety limits reached.
        
        Args:
            max_posts: Maximum posts to load before stopping (None = use config)
            max_scroll_time: Maximum time to spend scrolling in seconds (None = use config)

        Returns:
            A list of all post elements found on the page.
        """
        import time
        
        # Apply config defaults if not specified
        if max_posts is None:
            max_posts = self.config.max_posts_safety_limit
        if max_scroll_time is None:
            max_scroll_time = self.config.max_scroll_hours * 3600
        
        start_time = time.time()
        post_elements = await self.navigation_handler.find_post_elements(self.content_extractor)
        last_post_count = 0
        stale_scrolls = 0
        total_scrolls = 0
        
        logger.info(f"🎯 Starting UNLIMITED scroll mode: max_posts={max_posts:,}, max_time={max_scroll_time/3600:.1f}h")
        logger.info("📅 Will scroll until finding posts older than start_date (date-based filtering in process_url)")
        logger.info("⚡ No scroll limit - will continue until date filtering stops or no more posts")

        while stale_scrolls < 3:
            # Check time limit (safety mechanism only - should rarely trigger)
            elapsed_time = time.time() - start_time
            if elapsed_time > max_scroll_time:
                logger.warning(f"⏰ SAFETY: Time limit reached ({max_scroll_time/3600:.1f} hours). Stopping scroll.")
                logger.info("💡 This is a safety mechanism. Normal stop should be from date filtering.")
                break
                
            # Check post count limit (safety mechanism only - should rarely trigger)
            if len(post_elements) >= max_posts:
                logger.warning(f"📊 SAFETY: Post limit reached ({max_posts:,} posts). Stopping scroll.")
                logger.info("💡 This is a safety mechanism. Normal stop should be from date filtering.")
                break
            
            last_post_count = len(post_elements)
            await self.navigation_handler.humanized_scroll_page()
            total_scrolls += 1
            
            # Wait for content to potentially load
            await asyncio.sleep(random.uniform(2.0, 4.0))

            post_elements = await self.navigation_handler.find_post_elements(self.content_extractor)

            if len(post_elements) > last_post_count:
                stale_scrolls = 0
                logger.info(f"📜 Scrolled and found more posts. Total so far: {len(post_elements)} (scroll #{total_scrolls})")
            else:
                stale_scrolls += 1
                logger.info(f"📜 Scroll attempt {stale_scrolls}/3 with no new posts (scroll #{total_scrolls})")
            
            # Progress update every 50 posts
            if len(post_elements) % 50 == 0 and len(post_elements) != last_post_count:
                elapsed = time.time() - start_time
                logger.info(f"📈 Progress: {len(post_elements)} posts in {elapsed:.1f}s")

        elapsed_total = time.time() - start_time
        logger.info(f"✅ Finished scrolling. Found {len(post_elements)} posts in {elapsed_total:.1f}s ({total_scrolls} scrolls)")
        return post_elements

    def _clean_facebook_url(self, url: str) -> str:
        """
ư        Clean Facebook URL by removing ALL query parameters
        
        Examples:
        IN:  https://www.facebook.com/groups/OFFB.VN/posts/25156158847358662/?__cft__[0]=...&__tn__=...
        OUT: https://www.facebook.com/groups/OFFB.VN/posts/25156158847358662/
        
        IN:  https://www.facebook.com/groups/OFFB.VN/posts/25152263871081493/?comment_id=25152481784393035
        OUT: https://www.facebook.com/groups/OFFB.VN/posts/25152263871081493/
        
        ✅ Removes: comment_id, __cft__, __tn__, and ALL other parameters
        """
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(url)
            # Remove ALL query parameters (?, &, comment_id, __cft__, __tn__, etc.)
            clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
            logger.debug(f"🧹 Cleaned URL: {url[:80]} -> {clean_url[:80]}")
            return clean_url
        except Exception as e:
            logger.warning(f"⚠️ Could not clean URL: {e}, using original")
            return url
    
    async def _extract_post_details(self, post_element) -> Optional[Dict[str, Any]]:
        """
        Extract detailed data from post element (Phase 3.0)
        
        Returns:
            Dict containing: post_url, author_name, author_id, post_content
            None if post_url cannot be extracted (prevents saving invalid posts)
        
        ✅ FIX: Validate post_url exists before proceeding to prevent empty URLs in database
        """
        try:
            details = {}
            
            # ===== EXTRACT POST URL using resilient extraction =====
            post_url = await self.content_extractor.extract_data(post_element, 'post_url')
            
            # ✅ CRITICAL VALIDATION: Post MUST have valid URL
            if not post_url or not post_url.strip():
                logger.warning("⚠️ Skipping post - No post_url extracted (cannot rescan without URL)")
                return None  # Skip this post - don't save to database
            
            # ✅ Validate URL format
            post_url = post_url.strip()
            if not (post_url.startswith('http://') or post_url.startswith('https://')):
                logger.warning(f"⚠️ Skipping post - Invalid URL format: {post_url[:50]}")
                return None  # Skip this post
            
            # ✅ Clean URL: Remove tracking parameters (__cft__, __tn__, etc.)
            post_url = self._clean_facebook_url(post_url)
            
            details['post_url'] = post_url
            
            # ===== EXTRACT AUTHOR INFO using resilient extraction =====
            author_name = await self.content_extractor.extract_data(post_element, 'author_name')
            author_profile_url = await self.content_extractor.extract_data(post_element, 'author_profile_url')
            
            details['author_name'] = author_name if author_name else ''
            details['author_id'] = self.content_extractor._extract_user_id_from_url(author_profile_url) if author_profile_url else ''
            
            # ===== EXTRACT POST CONTENT using resilient extraction =====
            content = await self.content_extractor.extract_data(post_element, 'post_content')
            details['post_content'] = content if content else ''
            
            # ===== ✅ NEW: DETECT POST TYPE (VIDEO/PHOTO/TEXT/LINK) =====
            try:
                post_type = await self.content_extractor.detect_post_type(post_element)
                details['post_type'] = post_type
                logger.debug(f"🎯 Detected post_type: {post_type}")
            except Exception as e:
                logger.warning(f"⚠️ Error detecting post_type: {e}")
                details['post_type'] = 'TEXT'  # Safe fallback
            
            # ===== ✅ NEW: DETECT POST STATUS (ACTIVE/DEAD/STALE) =====
            try:
                # Calculate post age from timestamp if available
                post_age_hours = None
                timestamp_element = await self.content_extractor.extract_data(post_element, 'post_timestamp')
                if timestamp_element:
                    parsed_time = parse_facebook_timestamp(timestamp_element)
                    if parsed_time:
                        age_delta = datetime.now() - parsed_time
                        post_age_hours = age_delta.total_seconds() / 3600
                
                post_status = await self.content_extractor.detect_post_status(post_element, post_age_hours)
                details['post_status'] = post_status
                logger.debug(f"🎯 Detected post_status: {post_status} (age: {post_age_hours:.1f}h)" if post_age_hours else f"🎯 Detected post_status: {post_status}")
            except Exception as e:
                logger.warning(f"⚠️ Error detecting post_status: {e}")
                details['post_status'] = 'ACTIVE'  # Safe fallback
            
            logger.debug(f"📝 Resilient extracted details: author={details['author_name']}, content_length={len(details['post_content'])}, type={details.get('post_type')}, status={details.get('post_status')}")
            
            return details
            
        except Exception as e:
            logger.error(f"❌ Error extracting post details: {type(e).__name__}: {e}", exc_info=False)
            return None
    
    async def _process_fast_stream(self, post_element, source_url: str) -> Dict[str, Any]:
        """
        FAST STREAM - Always run to get signature and interactions
        
        ⚠️ DEPRECATED: Use _process_fast_stream_optimized for batch processing
        This method is kept for backward compatibility
        
        Returns:
            Dict with keys: success, post_signature, is_new_post, like_count, comment_count
        """
        try:
            # 1. Generate signature
            post_signature = await self.content_extractor.generate_post_signature(post_element)
            if not post_signature:
                return {"success": False, "error": "Không tạo được signature"}
            
            # 2. Get interaction counts using resilient extraction
            like_count = await self.content_extractor.extract_data(post_element, 'like_count')
            comment_count = await self.content_extractor.extract_data(post_element, 'comment_count')
            
            # Fallback to 0 if extraction failed but ensure integers
            like_count = like_count if isinstance(like_count, int) else 0
            comment_count = comment_count if isinstance(comment_count, int) else 0
            
            # 3. Check if post is new
            is_new_post = self.db_manager.is_post_new(post_signature)
            
            # 4. Log interaction to database
            current_utc = datetime.now(timezone.utc).isoformat()
            success = self.db_manager.log_interaction(
                post_signature=post_signature,
                log_timestamp_utc=current_utc,
                like_count=like_count,
                comment_count=comment_count
            )
            
            logger.debug(f"⚡ Fast stream: {like_count} likes, {comment_count} comments, new={is_new_post}")
            
            return {
                "success": success,
                "post_signature": post_signature,
                "is_new_post": is_new_post,
                "like_count": like_count,
                "comment_count": comment_count
            }
            
        except Exception as e:
            logger.error(f"❌ Error in fast stream processing: {type(e).__name__}: {e}", exc_info=False)
            return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}
    
    async def _process_fast_stream_optimized(self, post_element, source_url: str, 
                                            post_signature: str, is_new_post: bool) -> Dict[str, Any]:
        """
        🚀 OPTIMIZED FAST STREAM - No DB check needed, signature & existence pre-fetched
        
        This method is used in batch processing where we already know:
        - post_signature (from batch signature generation)
        - is_new_post (from batch existence check)
        
        Args:
            post_element: Playwright element handle
            source_url: Source URL being scraped
            post_signature: Pre-generated post signature
            is_new_post: Whether post is new (from batch check)
        
        Returns:
            Dict with keys: success, like_count, comment_count
        """
        try:
            # 1. Get interaction counts using resilient extraction
            like_count = await self.content_extractor.extract_data(post_element, 'like_count')
            comment_count = await self.content_extractor.extract_data(post_element, 'comment_count')
            
            # Fallback to 0 if extraction failed but ensure integers
            like_count = like_count if isinstance(like_count, int) else 0
            comment_count = comment_count if isinstance(comment_count, int) else 0
            
            # 2. Log interaction to database
            current_utc = datetime.now(timezone.utc).isoformat()
            success = self.db_manager.log_interaction(
                post_signature=post_signature,
                log_timestamp_utc=current_utc,
                like_count=like_count,
                comment_count=comment_count
            )
            
            logger.debug(f"⚡ Fast stream (optimized): {like_count} likes, {comment_count} comments, new={is_new_post}")
            
            return {
                "success": success,
                "like_count": like_count,
                "comment_count": comment_count
            }
            
        except Exception as e:
            logger.error(f"❌ Error in fast stream processing: {type(e).__name__}: {e}", exc_info=False)
            return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}
    
    async def _process_one_time_stream(self, post_element, post_signature: str, source_url: str) -> Dict[str, Any]:
        """
        One-time Stream: Only runs for new posts to get detailed data
        
        Args:
            post_element: Post element to process
            post_signature: Post signature from fast stream
            source_url: Source URL
            
        Returns:
            Dict with one-time stream results
        """
        try:
            # Extract detailed post information
            post_details = await self.content_extractor.extract_post_details(post_element)
            if not post_details:
                logger.warning("⚠️ Could not extract post details")
                return {"success": False, "reason": "No post details"}
            
            # Prepare post data for database
            post_data = {
                "signature": post_signature,
                "url": post_details.get("post_url", ""),
                "author_name": post_details.get("author", ""),
                "author_id": post_details.get("author_id", ""),
                "content": post_details.get("content", ""),
                "source_url": source_url,
                "discovered_at": datetime.now(timezone.utc),
                "tracking_enabled": True,
                "tracking_expires_at": datetime.now(timezone.utc),
                "scraper_version": "3.0_hybrid"
            }
            
            # Save post to database
            post_saved = self.db_manager.add_post(
                signature=post_signature,
                url=post_details.get("post_url", ""),
                author_name=post_details.get("author", ""),
                author_id=post_details.get("author_id", ""),
                content=post_details.get("content", ""),
                source_url=source_url,
                tracking_duration_days=self.tracking_duration_days
            )
            
            if post_saved:
                logger.info(f"✅ One-time stream: Saved new post {post_signature}")
                return {
                    "success": True,
                    "post_signature": post_signature,
                    "post_data": post_data
                }
            else:
                logger.warning("⚠️ Failed to save post data")
                return {"success": False, "reason": "Database save failed"}
                
        except Exception as e:
            logger.error(f"❌ One-time stream error: {e}")
            return {"success": False, "reason": str(e)}
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive processing statistics
        
        Returns:
            Dict containing all component stats
        """
        return {
            "coordinator": {
                "tracking_duration_days": self.tracking_duration_days,
                "humanization_enabled": self.humanization_enabled
            },
            "content_extractor": self.content_extractor.get_strategy_stats(),
            "interaction_simulator": self.interaction_simulator.get_interaction_stats(),
            "browser_controller": {"stealth_mode": "active"},
            "selectors_loaded": len(self.selectors.get("post", {}).get("fields", {}))
        }
    
    async def cleanup(self) -> None:
        """
        Cleanup coordinator and all components
        """
        try:
            logger.info("🧹 Cleaning up ScraperCoordinator")
            
            # Components cleanup (if needed)
            # Most cleanup is handled by Playwright page lifecycle
            
            logger.info("✅ ScraperCoordinator cleanup completed")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
    
    def __str__(self) -> str:
        return f"ScraperCoordinator(components=5, humanization={self.humanization_enabled})"
