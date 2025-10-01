#!/usr/bin/env python3
"""
Content Extractor for Facebook Post Monitor
Handles data extraction from post elements using multiple strategies
"""

import re
from logging_config import get_logger
from typing import Optional, List, Dict, Any
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

from utils.validation_helpers import DataValidator, FieldExtractor

logger = get_logger(__name__)


class ContentExtractor:
    """Handles content extraction from Facebook post elements."""
    
    def __init__(self, page: Page, selectors: Dict[str, Any]):
        """
        Initialize ContentExtractor
        
        Args:
            page: Playwright page instance
            selectors: Selectors configuration loaded from file
        """
        self.page = page
        self.selectors = selectors
        self.strategy_stats = {}
        self.failed_selectors = set()
        
        logger.info("🔍 ContentExtractor initialized")
    
    async def extract_data(self, post_element, field_name: str) -> Optional[Any]:
        """
        CORE RESILIENT EXTRACTION FUNCTION
        
        Loops through strategies by priority order, trying each one,
        and performs validation. Returns validated value or None.
        
        Args:
            post_element: Playwright element of the post
            field_name: Field name in selectors.json (e.g. 'like_count')
            
        Returns:
            Validated data or None if all strategies fail
        """
        # --- FIX START: Handle nested field names ---
        field_config = self.selectors
        try:
            for part in field_name.split('.'):
                field_config = field_config[part]
        except KeyError:
            logger.warning(f"🔍 Field '{field_name}' không tồn tại trong selectors.json")
            return None
        # --- FIX END ---
        
        strategies = field_config.get('strategies', [])
        validation_config = field_config.get('validation', {})
        
        if not strategies:
            logger.warning(f"🔍 Field '{field_name}' không có strategies")
            return None
        
        # Sort strategies by priority
        sorted_strategies = sorted(strategies, key=lambda x: x.get('priority', 999))
        
        logger.debug(f"🔍 Extracting '{field_name}' với {len(sorted_strategies)} strategies")
        
        for index, strategy in enumerate(sorted_strategies):
            strategy_type = strategy.get('type', 'css')
            strategy_path = strategy.get('path', '')
            strategy_desc = strategy.get('description', 'No description')
            
            try:
                logger.debug(f"🔍 Trying strategy #{index+1} for '{field_name}': {strategy_desc}")
                
                # Extract data by strategy type
                raw_data = await self._extract_by_strategy(post_element, strategy_type, strategy_path, field_name)
                
                if raw_data is not None:
                    # Validate data
                    validation_result = DataValidator.validate_data(raw_data, validation_config, field_name)

                    if validation_result['is_valid']:
                        # Success!
                        logger.info(f"✅ Field '{field_name}': Strategy #{index+1} ({strategy_type}) succeeded - Value: {validation_result['cleaned_data']}")

                        # Track success
                        self._track_strategy_success(field_name, index, strategy_desc)

                        return validation_result['cleaned_data']
                    else:
                        logger.warning(f"⚠️ Field '{field_name}': Strategy #{index+1} extracted data but validation failed: {validation_result['error_message']} - Raw data: {raw_data}")
                else:
                    # ENHANCED LOGGING: Always log extraction failures for like_count
                    if field_name == 'like_count':
                        logger.warning(f"❌ REACTION EXTRACTION FAILED: Strategy #{index+1} ({strategy_type}) - {strategy_desc}")
                        logger.warning(f"   Selector: {strategy_path}")
                    elif field_name != 'author_name':
                        logger.warning(f"⚠️ Field '{field_name}': Strategy #{index+1} failed to extract data")
                    
            except Exception as e:
                # Skip logging author_name failures - user doesn't care
                if field_name != 'author_name':
                    logger.warning(f"⚠️ Field '{field_name}': Strategy #{index+1} threw exception: {e}")
                continue
        
        # All strategies failed - skip logging for author_name
        if field_name != 'author_name':
            logger.error(f"❌ Field '{field_name}': ALL {len(sorted_strategies)} strategies failed!")
        
        # Track failure
        self._track_strategy_failure(field_name, validation_config)
        
        return None
    
    async def _extract_by_strategy(self, element, strategy_type: str, strategy_path: str, field_name: str) -> Optional[Any]:
        """
        Extract data using specific strategy type
        
        Args:
            element: Element to extract from
            strategy_type: Type of strategy (css, text, attribute, etc.)
            strategy_path: Path/selector for extraction
            field_name: Field being extracted
            
        Returns:
            Extracted raw data or None
        """
        try:
            if strategy_type == 'css':
                # 🐳 DOCKER FIX: Add wait for dynamic elements
                if 'count' in field_name.lower():
                    try:
                        await element.wait_for_selector(strategy_path, timeout=3000)
                    except (PlaywrightTimeoutError, PlaywrightError) as e:
                        logger.debug(f"Wait timeout for {field_name} selector '{strategy_path}': {e}")
                        pass  # Continue even if wait fails
                
                elements = await element.query_selector_all(strategy_path)
                
                # Xử lý khác nhau tùy theo field type
                if 'count' in field_name.lower():
                    return await self._extract_count_from_elements(elements)
                elif 'url' in field_name.lower() or 'link' in field_name.lower():
                    return await self._extract_url_from_elements(elements)
                elif field_name == 'post_containers':
                    # Special case for post containers - return list of elements
                    return elements if elements else None
                elif field_name == 'expand_buttons':
                    # Special case for expand buttons - return list of elements
                    return elements if elements else None
                elif field_name == 'reaction_details.modal_trigger':
                    return elements if elements else None
                else:
                    return await self._extract_text_from_elements(elements)
                    
            elif strategy_type == 'text':
                text = await element.inner_text()
                return text.strip() if text else None
                
            elif strategy_type == 'xpath':
                # 🐳 DOCKER FIX: Add wait for XPath elements (reactions are often dynamic)
                if 'count' in field_name.lower():
                    try:
                        await element.wait_for_selector(f"xpath={strategy_path}", timeout=3000)
                    except (PlaywrightTimeoutError, PlaywrightError) as e:
                        logger.debug(f"Wait timeout for {field_name} xpath '{strategy_path}': {e}")
                        pass  # Continue even if wait fails
                
                # XPath strategy support
                elements = await element.query_selector_all(f"xpath={strategy_path}")
                
                # Handle different field types for XPath like CSS
                if 'count' in field_name.lower():
                    return await self._extract_count_from_elements(elements)
                elif 'url' in field_name.lower() or 'link' in field_name.lower():
                    return await self._extract_url_from_elements(elements)
                elif field_name == 'post_containers':
                    # Special case for post containers - return list of elements
                    return elements if elements else None
                elif field_name == 'expand_buttons':
                    # Special case for expand buttons - return list of elements  
                    return elements if elements else None
                elif field_name == 'reaction_details.modal_trigger':
                    return elements if elements else None
                else:
                    return await self._extract_text_from_elements(elements)
                    
            elif strategy_type == 'attribute':
                # strategy_path format: "selector|attribute_name"
                parts = strategy_path.split('|')
                if len(parts) == 2:
                    selector, attr_name = parts
                    elem = await element.query_selector(selector)
                    if elem:
                        return await elem.get_attribute(attr_name)
                return None
                
            else:
                logger.warning(f"Unknown strategy type: {strategy_type}")
                return None
                
        except Exception as e:
            logger.debug(f"Strategy extraction failed: {e}")
            return None
    
    async def _extract_count_from_elements(self, elements: List) -> Optional[int]:
        """
        Extract count (số lượng) từ danh sách elements
        
        Args:
            elements: Danh sách elements
            
        Returns:
            Số count hoặc None
        """
        for idx, element in enumerate(elements):
            try:
                # First try text content
                text = await element.text_content()
                if text and text.strip():
                    # 🐛 DEBUG: Log extracted text
                    logger.info(f"🔍 LIKE COUNT Element [{idx}] text_content: '{text.strip()[:200]}'")
                    count = self._extract_count_from_text(text.strip())
                    if count >= 0:  # 0 là valid count
                        logger.warning(f"🎯 EXTRACTED LIKE COUNT={count} from text: '{text.strip()[:100]}'")
                        return count
                
                # If text is empty or no count found, try aria-label
                aria_label = await element.get_attribute('aria-label')
                if aria_label and aria_label.strip():
                    # 🐛 DEBUG: Log extracted aria-label
                    logger.info(f"🔍 LIKE COUNT Element [{idx}] aria-label: '{aria_label.strip()[:200]}'")
                    count = self._extract_count_from_text(aria_label.strip())
                    if count >= 0:  # 0 là valid count
                        logger.warning(f"🎯 EXTRACTED LIKE COUNT={count} from aria-label: '{aria_label.strip()[:100]}'")
                        return count
                        
            except Exception as e:
                logger.debug(f"⚠️ Element [{idx}] extraction failed: {e}")
                continue
        return None
    
    async def _extract_text_from_elements(self, elements: List) -> Optional[str]:
        """
        Extract text content từ danh sách elements
        
        Args:
            elements: Danh sách elements
            
        Returns:
            Text content hoặc None
        """
        for element in elements:
            try:
                text = await element.text_content()
                if text and text.strip():
                    return text.strip()
            except (PlaywrightError, AttributeError) as e:
                logger.debug(f"Failed to extract text from element: {e}")
                continue
        return None
    
    async def _extract_url_from_elements(self, elements: List) -> Optional[str]:
        """
        Extract URL từ danh sách elements
        
        Args:
            elements: Danh sách elements
            
        Returns:
            URL hoặc None
        """
        for element in elements:
            try:
                # Thử get href attribute
                href = await element.get_attribute('href')
                if href:
                    return self._clean_post_url(href)
                
                # Thử get src attribute (for images)
                src = await element.get_attribute('src')
                if src:
                    return src
                    
            except (PlaywrightError, AttributeError) as e:
                logger.debug(f"Failed to extract URL from element: {e}")
                continue
        return None
    
    def _extract_count_from_text(self, text: str) -> int:
        """
        Extracts numerical count from text, handling suffixes like 'K' and 'M'.
        
        Refactored: Sử dụng pattern list thay vì duplicate logic.
        
        Args:
            text: Text chứa count
            
        Returns:
            Số count (int)
        """
        if not text:
            return 0
        
        text_lower = text.lower().strip()
        
        # Danh sách patterns theo thứ tự ưu tiên - REACTIONS + COMMENTS
        patterns = [
            # REACTIONS (total reactions count)
            r'all\s+reactions?:\s*(\d+[\.,]?\d*)([km]?)',        # English "All reactions: 3" (PRIORITY 1)
            r'tất cả cảm xúc:\s*(\d+[\.,]?\d*)([km]?)',          # Vietnamese "Tất cả cảm xúc: 3" (PRIORITY 2)
            r'(\d+[\.,]?\d*)([km]?)\s*cảm\s*xúc',               # "3 cảm xúc" (Vietnamese reverse)
            r'(\d+[\.,]?\d*)([km]?)\s*reactions?',               # "3 reactions" (English reverse)
            
            # COMMENTS (OCT 1 2025 FIX)
            r'(\d+[\.,]?\d*)([km]?)\s*bình\s*luận',             # "13 bình luận" (Vietnamese)
            r'(\d+[\.,]?\d*)([km]?)\s*comments?',                # "13 comments" (English)
            r'bình\s*luận:\s*(\d+[\.,]?\d*)([km]?)',            # "Bình luận: 13" (Vietnamese reverse)
            r'comments?:\s*(\d+[\.,]?\d*)([km]?)',               # "Comments: 13" (English reverse)
            
            # SHARES (for completeness)
            r'(\d+[\.,]?\d*)([km]?)\s*(lượt\s*)?chia\s*sẻ',     # "18 lượt chia sẻ" or "18 chia sẻ" (Vietnamese)
            r'(\d+[\.,]?\d*)([km]?)\s*shares?',                  # "18 shares" (English)
            
            r'(\d+[\.,]?\d*)([km]?)'                             # Fallback: any number
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                try:
                    result = self._parse_number_with_suffix(match)
                    # 🐛 DEBUG: Log which pattern matched and full text
                    logger.info(f"🎯 LIKE Pattern '{pattern[:30]}...' matched in text: '{text[:100]}'")
                    logger.warning(f"✅ LIKE Parsed count: {result} from full text: '{text[:200]}'")
                    return result
                except (ValueError, TypeError):
                    continue  # Thử pattern tiếp theo
        
        logger.info(f"❌ LIKE: No pattern matched for text: '{text[:100]}'")
        return 0
    
    def _parse_number_with_suffix(self, match: re.Match) -> int:
        """
        Helper để parse số với suffix K/M.
        
        Args:
            match: Regex match object với groups (number, suffix)
            
        Returns:
            Parsed integer value
        """
        value_str, suffix = match.groups()
        value_str = value_str.replace(',', '.')
        count = float(value_str)
        
        # Apply multiplier
        multipliers = {'k': 1_000, 'm': 1_000_000}
        count *= multipliers.get(suffix, 1)
        
        return int(count)
    
    def _clean_post_url(self, url: str) -> str:
        """
        Clean và normalize post URL
        
        Args:
            url: Raw URL
            
        Returns:
            Cleaned URL
        """
        if not url:
            return ""
        
        # Remove Facebook tracking parameters
        tracking_params = [
            '__cft__[0]', '__tn__', 'eid', 'hc_ref', 'fref',
            '__xts__[0]', 'hc_location', 'fb_dtsg', 'jazoest'
        ]
        
        # Convert relative URLs to absolute
        if url.startswith('/'):
            url = f"https://facebook.com{url}"
        
        # Remove tracking parameters
        for param in tracking_params:
            if param in url:
                url = re.sub(rf'[&?]{re.escape(param)}=[^&]*', '', url)
        
        # Clean up multiple consecutive separators
        url = re.sub(r'[&?]+', lambda m: '?' if '?' in m.group() else '&', url)
        url = url.rstrip('&?')
        
        return url
    
    async def extract_post_details(self, post_element) -> Optional[Dict[str, Any]]:
        """
        Extract tất cả post details từ một post element
        
        Args:
            post_element: Post element
            
        Returns:
            Dict chứa post details hoặc None nếu lỗi
        """
        try:
            post_data = {}
            
            # Extract basic fields
            fields_to_extract = [
                'author_name', 'author_url', 'post_content', 'like_count',
                'comment_count', 'share_count', 'post_url'
            ]
            
            for field in fields_to_extract:
                value = await self.extract_data(post_element, field)
                if value is not None:
                    post_data[field] = value
            
            # Extract additional metadata
            try:
                # Post timestamp
                timestamp_element = await post_element.query_selector('time')
                if timestamp_element:
                    datetime_attr = await timestamp_element.get_attribute('datetime')
                    if datetime_attr:
                        post_data['timestamp'] = datetime_attr
                
                # Data-ft attribute for post ID extraction
                data_ft = await post_element.get_attribute('data-ft')
                if data_ft:
                    post_id = self._extract_post_id_from_data_ft(data_ft)
                    if post_id:
                        post_data['post_id'] = post_id
                        
            except Exception as e:
                logger.debug(f"⚠️ Could not extract metadata: {e}")
            
            return post_data if post_data else None
            
        except Exception as e:
            logger.error(f"❌ Error extracting post details: {e}")
            return None
    
    def _extract_post_id_from_data_ft(self, data_ft: str) -> Optional[str]:
        """
        Extract post ID từ data-ft attribute
        
        Args:
            data_ft: data-ft attribute string
            
        Returns:
            Post ID hoặc None
        """
        try:
            # Parse data-ft JSON
            import json
            data = json.loads(data_ft)
            
            # Try different possible keys for post ID
            possible_keys = ['fbid', 'page_id', 'mf_story_key', 'top_level_post_id']
            
            for key in possible_keys:
                if key in data:
                    return str(data[key])
                    
            return None
            
        except Exception as e:
            logger.debug(f"Could not parse data-ft: {e}")
            return None
    
    def _extract_user_id_from_url(self, url: str) -> str:
        """
        Extract user ID hoặc username từ Facebook URL
        
        Args:
            url: Facebook profile URL
            
        Returns:
            User ID/username
        """
        if not url:
            return "unknown"
        
        # Pattern for numeric user ID
        numeric_match = re.search(r'facebook\.com/profile\.php\?id=(\d+)', url)
        if numeric_match:
            return numeric_match.group(1)
        
        # Pattern for username
        username_match = re.search(r'facebook\.com/([^/?]+)', url)
        if username_match:
            username = username_match.group(1)
            # Filter out common Facebook paths
            if username not in ['pages', 'groups', 'events', 'photo.php', 'photos']:
                return username
        
        return "unknown"
    
    async def generate_post_signature(self, post_element) -> Optional[str]:
        """
        Generate unique signature cho post để identify
        
        Args:
            post_element: Post element
            
        Returns:
            Post signature hoặc None
        """
        try:
            # Ưu tiên data-ft attribute
            data_ft = await post_element.get_attribute('data-ft')
            if data_ft:
                post_id = self._extract_post_id_from_data_ft(data_ft)
                if post_id:
                    return f"fb_{post_id}"
            
            # Fallback: dùng href của post
            post_link = await post_element.query_selector('a[href*="/posts/"], a[href*="story_fbid"]')
            if post_link:
                href = await post_link.get_attribute('href')
                if href:
                    # Extract unique parts from URL
                    url_match = re.search(r'(?:posts/|story_fbid=)([^&/?]+)', href)
                    if url_match:
                        return f"fb_{url_match.group(1)}"
            
            # Last resort: hash của content + author
            author = await self.extract_data(post_element, 'author_name')
            content = await self.extract_data(post_element, 'post_content')
            
            if author or content:
                import hashlib
                signature_text = f"{author or 'unknown'}:{content or 'no_content'}"
                signature_hash = hashlib.md5(signature_text.encode()).hexdigest()[:12]
                return f"fb_{signature_hash}"
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error generating post signature: {e}")
            return None
    
    def _track_strategy_success(self, field_name: str, strategy_index: int, strategy_desc: str):
        """Track successful strategy usage"""
        if field_name not in self.strategy_stats:
            self.strategy_stats[field_name] = {'success': {}, 'total_attempts': 0}
        
        if strategy_desc not in self.strategy_stats[field_name]['success']:
            self.strategy_stats[field_name]['success'][strategy_desc] = 0
        
        self.strategy_stats[field_name]['success'][strategy_desc] += 1
        self.strategy_stats[field_name]['total_attempts'] += 1
        
        # Remove from failed selectors if it succeeded
        self.failed_selectors.discard(field_name)
    
    def _track_strategy_failure(self, field_name: str, validation_config: Dict):
        """Track strategy failure"""
        if field_name not in self.strategy_stats:
            self.strategy_stats[field_name] = {'success': {}, 'total_attempts': 0}
        
        self.strategy_stats[field_name]['total_attempts'] += 1
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """Get strategy performance statistics"""
        return {
            'strategy_stats': self.strategy_stats,
            'failed_selectors_count': len(self.failed_selectors),
            'total_fields_tracked': len(self.strategy_stats)
        }
