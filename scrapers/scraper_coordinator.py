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

from playwright.async_api import Page

from core.database_manager import DatabaseManager
from .browser_controller import BrowserController, CaptchaException
from .content_extractor import ContentExtractor
from .navigation_handler import NavigationHandler
from .interaction_simulator import InteractionSimulator

logger = get_logger(__name__)


class ScraperCoordinator:
    """
    Main coordinator that orchestrates all scraper components
    Implements the Hybrid Logic: fast stream + one-time stream
    """
    
    def __init__(self, db_manager: DatabaseManager, page: Page):
        """
        Initialize ScraperCoordinator with all components
        
        Args:
            db_manager: Database manager instance
            page: Playwright page instance
        """
        self.db_manager = db_manager
        self.page = page
        self.tracking_duration_days = 7
        
        # Load scraping configuration
        try:
            from config import settings
            self.config = settings.scraping
            logger.info(f"📋 Loaded scraping config: unlimited_mode={self.config.unlimited_mode}")
        except Exception as e:
            logger.warning(f"⚠️ Could not load scraping config: {e}, using defaults")
            # Fallback defaults
            class DefaultConfig:
                unlimited_mode = True
                max_posts_safety_limit = 999999
                max_scroll_hours = 24
            self.config = DefaultConfig()
        
        # Load selectors configuration
        self.selectors = self._load_selectors()
        
        # Initialize all components with proper parameters
        self.browser_controller = BrowserController(page, self.selectors)
        self.content_extractor = ContentExtractor(page, self.selectors)
        self.navigation_handler = NavigationHandler(page, self.selectors)
        self.interaction_simulator = InteractionSimulator(page)
        
        # Humanization settings
        self.humanization_enabled = True
        
        logger.info("🎯 ScraperCoordinator initialized with all components")
        if self.config.unlimited_mode:
            logger.info("🚀 Unlimited mode enabled - will scrape all posts from start_date")
    
    def _parse_facebook_timestamp(self, time_string: str) -> Optional[datetime]:
        """
        Phân tích chuỗi thời gian Facebook thành datetime object. (PHIÊN BẢN SỬA LỖI)
        
        Xử lý các định dạng phổ biến:
        - "2 hours ago", "3 minutes ago"
        - "Yesterday", "Today"
        - "September 18", "18 Thg 9"
        - "2025-09-19" (ISO format)
        
        Args:
            time_string: Chuỗi thời gian từ Facebook
            
        Returns:
            datetime object hoặc None nếu không thể phân tích
        """
        if not time_string:
            return None
            
        time_string = time_string.strip().lower()
        now = datetime.now()
        
        try:
            # Pattern 1: "X minutes/hours/days ago"
            ago_pattern = r'(\d+)\s*(minute|hour|day|week)s?\s*ago'
            match = re.search(ago_pattern, time_string)
            if match:
                value = int(match.group(1))
                unit = match.group(2)
                
                if unit == 'minute':
                    return now - timedelta(minutes=value)
                elif unit == 'hour':
                    return now - timedelta(hours=value)
                elif unit == 'day':
                    return now - timedelta(days=value)
                elif unit == 'week':
                    return now - timedelta(weeks=value)
            
            # Pattern 2: "Yesterday"
            if 'yesterday' in time_string:
                return now - timedelta(days=1)
            
            # Pattern 3: "Today" hoặc "just now"
            if 'today' in time_string or 'just now' in time_string or 'now' in time_string:
                return now
            
            # SỬA LỖI LOGIC: Xử lý "Tháng Ngày" (ví dụ: "September 18", "18 Thg 9")
            # Thay thế khối logic cũ bằng khối logic mới này
            month_map = {
                'jan': 1, 'january': 1, 'thg 1': 1,
                'feb': 2, 'february': 2, 'thg 2': 2,
                'mar': 3, 'march': 3, 'thg 3': 3,
                'apr': 4, 'april': 4, 'thg 4': 4,
                'may': 5, 'may': 5, 'thg 5': 5,
                'jun': 6, 'june': 6, 'thg 6': 6,
                'jul': 7, 'july': 7, 'thg 7': 7,
                'aug': 8, 'august': 8, 'thg 8': 8,
                'sep': 9, 'september': 9, 'thg 9': 9,
                'oct': 10, 'october': 10, 'thg 10': 10,
                'nov': 11, 'november': 11, 'thg 11': 11,
                'dec': 12, 'december': 12, 'thg 12': 12,
            }

            # Regex để bắt "tháng ngày" hoặc "ngày tháng"
            pattern = '|'.join(month_map.keys())
            match = re.search(r'(\d{1,2})?\s*(' + pattern + r')\s*(\d{1,2})?', time_string)
            if match:
                parts = [p for p in match.groups() if p and p.strip()]
                if len(parts) >= 2:
                    # Phân tích tháng và ngày từ các phần tìm được
                    month_str = None
                    day_str = None
                    
                    for part in parts:
                        if part in month_map:
                            month_str = part
                        elif part.isdigit():
                            day_str = part
                    
                    if month_str and day_str:
                        try:
                            day = int(day_str)
                            month = month_map[month_str]
                            year = now.year # Mặc định là năm hiện tại

                            # Giả định thông minh: nếu tháng phân tích được lớn hơn tháng hiện tại,
                            # có thể bài viết là của năm ngoái.
                            # FIXED: Xử lý edge case khi ở tháng 1-2 và post là tháng 11-12
                            if month > now.month:
                                year = now.year - 1
                            # FIXED: Xử lý edge case khi post date trong tương lai (do timezone/date difference)
                            elif month == now.month and day > now.day:
                                # Nếu ngày lớn hơn ngày hiện tại trong cùng tháng, có thể là timezone issue
                                # hoặc post là của tháng trước năm ngoái
                                test_date = datetime(year, month, day)
                                if test_date > now:
                                    year = now.year - 1

                            return datetime(year, month, day)
                        except (ValueError, KeyError):
                            pass
                            
            # Thử phân tích định dạng ISO hoặc các định dạng khác
            date_patterns = [
                r'(\d+)[-/](\d+)[-/](\d{4})',  # DD/MM/YYYY hoặc DD-MM-YYYY
                r'(\d{4})[-/](\d+)[-/](\d+)',  # YYYY/MM/DD hoặc YYYY-MM-DD
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, time_string)
                if match:
                    try:
                        if len(match.group(1)) == 4:  # YYYY/MM/DD format
                            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        else:  # DD/MM/YYYY format
                            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        return datetime(year, month, day)
                    except (ValueError, TypeError):
                        continue

        except Exception as e:
            logger.error(f"❌ Lỗi phân tích timestamp '{time_string}': {e}")
            
        # SỬA LỖI LOGIC: Thay đổi hành vi fallback
        # Thay vì return now, hãy trả về None
        logger.warning(f"⚠️ Không thể phân tích timestamp: '{time_string}'")
        return None
    
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
                except:
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
            
            # Scroll to the bottom of the feed to load posts (with limits)
            post_elements = await self._scroll_to_bottom_of_feed(max_posts, max_scroll_time)
            
            if not post_elements:
                logger.warning("⚠️ Không tìm thấy post elements nào")
                return {
                    "new_posts": 0,
                    "interactions_logged": 0, 
                    "errors": 0,
                    "reason": "No posts found"
                }
            
            logger.info(f"📊 Tìm thấy {len(post_elements)} post elements")
            
            # Process posts using Hybrid Logic
            results = {"new_posts": 0, "interactions_logged": 0, "errors": 0}
            
            for i, post_element in enumerate(post_elements):  # REMOVED limit to 20 posts
                try:
                    logger.debug(f"🔄 Xử lý post {i+1}/{len(post_elements)}")
                    
                    # ===== TIME-BASED FILTERING =====
                    # Lấy chuỗi thời gian từ post element
                    try:
                        time_string = await self._extract_post_time(post_element)
                        if time_string:
                            post_datetime = self._parse_facebook_timestamp(time_string)

                            # THÊM KHỐI KIỂM TRA NÀY
                            if post_datetime is None:
                                logger.warning(f"Bỏ qua bài viết vì không phân tích được thời gian: '{time_string}'")
                                continue # Chuyển sang bài viết tiếp theo

                            if post_datetime.date() < scrape_since_date:
                                logger.info(f"📅 Bài viết quá cũ ({post_datetime.date()}), dừng quét trang này")
                                break  # Dừng lại vì các bài sau cũng sẽ cũ hơn
                        else:
                            logger.debug(f"⚠️ Không lấy được thời gian của bài viết {i+1}, tiếp tục xử lý")
                    except Exception as e:
                        logger.warning(f"⚠️ Lỗi kiểm tra thời gian bài viết {i+1}: {e}, tiếp tục xử lý")
                    
                    # ===== FAST STREAM - ALWAYS RUN =====
                    interaction_result = await self._process_fast_stream(post_element, url)
                    
                    if interaction_result["success"]:
                        results["interactions_logged"] += 1
                        
                        # 🔧 PRODUCTION FIX: Atomic dual-stream processing for new posts
                        if interaction_result["is_new_post"]:
                            logger.info("✨ Phát hiện post mới, bắt đầu atomic dual-stream processing...")
                            
                            # Expand and get detailed post information
                            await self.navigation_handler.expand_post_content(post_element, self.content_extractor)
                            post_details = await self._extract_post_details(post_element)
                            
                            if post_details:
                                # Use atomic operation to ensure data consistency
                                atomic_success = self.db_manager.add_new_post_with_interaction(
                                    post_signature=interaction_result['post_signature'],
                                    post_url=post_details.get('post_url', ''),
                                    source_url=url,
                                    like_count=interaction_result['like_count'],
                                    comment_count=interaction_result['comment_count'],
                                    author_name=post_details.get('author_name', ''),
                                    author_id=post_details.get('author_id', ''),
                                    post_content=post_details.get('post_content', '')
                                )
                                
                                if atomic_success:
                                    results["new_posts"] += 1
                                    # Don't count interaction separately since it's included in atomic operation
                                    results["interactions_logged"] -= 1  # Adjust count
                                    logger.info(
                                        f"🎯 Atomic dual-stream success for post: "
                                        f"{interaction_result['post_signature'][:30]}..."
                                    )
                                else:
                                    logger.warning(
                                        f"⚠️ Atomic dual-stream failed for: "
                                        f"{interaction_result['post_signature'][:30]}..."
                                    )
                            else:
                                logger.warning("⚠️ Could not extract post details for atomic operation")
                    else:
                        results["errors"] += 1
                    
                    # Humanized delay and random interactions between posts
                    await self.interaction_simulator.humanized_delay_between_posts(i, len(post_elements))
                    
                except Exception as e:
                    logger.error(f"❌ Lỗi xử lý post {i+1}: {e}")
                    results["errors"] += 1
                    continue
            
            logger.info(f"✅ Hoàn thành xử lý URL: {results}")
            return results
            
        except CaptchaException as e:
            logger.critical(f"🚨 CAPTCHA detected during processing URL {url}: {e}")
            # Re-raise CAPTCHA exception for higher-level handling
            raise
        except Exception as e:
            logger.error(f"💥 Lỗi nghiêm trọng xử lý URL {url}: {e}")
            return {"new_posts": 0, "interactions_logged": 0, "errors": 1, "reason": str(e)}

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

    async def _extract_post_details(self, post_element) -> Optional[Dict[str, Any]]:
        """
        Extract detailed data from post element (Phase 3.0)
        
        Returns:
            Dict containing: post_url, author_name, author_id, post_content
        """
        try:
            details = {}
            
            # ===== EXTRACT POST URL using resilient extraction =====
            post_url = await self.content_extractor.extract_data(post_element, 'post_url')
            details['post_url'] = post_url if post_url else ''
            
            # ===== EXTRACT AUTHOR INFO using resilient extraction =====
            author_name = await self.content_extractor.extract_data(post_element, 'author_name')
            author_profile_url = await self.content_extractor.extract_data(post_element, 'author_profile_url')
            
            details['author_name'] = author_name if author_name else ''
            details['author_id'] = self.content_extractor._extract_user_id_from_url(author_profile_url) if author_profile_url else ''
            
            # ===== EXTRACT POST CONTENT using resilient extraction =====
            content = await self.content_extractor.extract_data(post_element, 'post_content')
            details['post_content'] = content if content else ''
            
            logger.debug(f"📝 Resilient extracted details: author={details['author_name']}, content_length={len(details['post_content'])}")
            
            return details
            
        except Exception as e:
            logger.error(f"❌ Lỗi extract post details: {e}")
            return None
    
    async def _process_fast_stream(self, post_element, source_url: str) -> Dict[str, Any]:
        """
        FAST STREAM - Always run to get signature and interactions
        
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
            logger.error(f"❌ Lỗi fast stream: {e}")
            return {"success": False, "error": str(e)}
    
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
