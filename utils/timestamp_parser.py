#!/usr/bin/env python3
"""
Facebook Timestamp Parser - Simplified Strategy Pattern
Xử lý các định dạng timestamp khác nhau từ Facebook

✅ NEW: GMT+7 timezone conversion utilities
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from logging_config import get_logger

logger = get_logger(__name__)


class FacebookTimestampParser:
    """
    Strategy Pattern - mỗi pattern parsing là một strategy riêng.
    Dễ mở rộng và maintain hơn hàm 125 dòng lồng nhau.
    """
    
    def __init__(self):
        # Danh sách các parser theo thứ tự ưu tiên
        self.parsers = [
            self._parse_relative_time,
            self._parse_special_words,
            self._parse_month_day,
            self._parse_iso_date
        ]
    
    def parse(self, time_string: str) -> Optional[datetime]:
        """
        Thử từng parser cho đến khi có kết quả.
        
        Args:
            time_string: Chuỗi thời gian từ Facebook
            
        Returns:
            datetime object hoặc None nếu không thể phân tích
        """
        if not time_string:
            return None
        
        time_string = time_string.strip().lower()
        
        for parser in self.parsers:
            try:
                result = parser(time_string)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Parser {parser.__name__} failed: {e}")
                continue
        
        logger.warning(f"⚠️ Không thể phân tích timestamp: '{time_string}'")
        return None
    
    def _parse_relative_time(self, text: str) -> Optional[datetime]:
        """
        Parse '2 hours ago', '3 days ago', '5 minutes ago'
        
        Args:
            text: Text chứa relative time
            
        Returns:
            datetime object hoặc None
        """
        pattern = r'(\d+)\s*(minute|hour|day|week)s?\s*ago'
        match = re.search(pattern, text)
        if not match:
            return None
        
        value, unit = int(match.group(1)), match.group(2)
        
        deltas = {
            'minute': timedelta(minutes=value),
            'hour': timedelta(hours=value),
            'day': timedelta(days=value),
            'week': timedelta(weeks=value)
        }
        
        if unit in deltas:
            result = datetime.now() - deltas[unit]
            logger.debug(f"✅ Parsed relative time: '{text}' -> {result}")
            return result
        
        return None
    
    def _parse_special_words(self, text: str) -> Optional[datetime]:
        """
        Parse 'yesterday', 'today', 'now', 'just now'
        
        Args:
            text: Text chứa special words
            
        Returns:
            datetime object hoặc None
        """
        if 'yesterday' in text or 'hôm qua' in text:
            return datetime.now() - timedelta(days=1)
        
        if any(word in text for word in ['today', 'now', 'hôm nay', 'just']):
            return datetime.now()
        
        return None
    
    def _parse_month_day(self, text: str) -> Optional[datetime]:
        """
        Parse 'September 18', '18 Thg 9', 'Jan 5'
        Sử dụng dateutil.parser để tránh duplicate logic
        
        Args:
            text: Text chứa month và day
            
        Returns:
            datetime object hoặc None
        """
        try:
            # Sử dụng dateutil.parser - battle-tested library
            from dateutil import parser as date_parser
            
            # fuzzy=True cho phép parse text có nhiễu
            result = date_parser.parse(text, fuzzy=True, default=datetime.now())
            
            # Handle edge case: nếu tháng lớn hơn tháng hiện tại -> năm ngoái
            now = datetime.now()
            if result.month > now.month:
                result = result.replace(year=now.year - 1)
            # Handle edge case: cùng tháng nhưng ngày lớn hơn -> năm ngoái
            elif result.month == now.month and result.day > now.day:
                result = result.replace(year=now.year - 1)
            
            logger.debug(f"✅ Parsed month/day: '{text}' -> {result}")
            return result
            
        except (ImportError, ValueError, OverflowError):
            # Fallback: manual parsing nếu dateutil không có
            return self._parse_month_day_manual(text)
    
    def _parse_month_day_manual(self, text: str) -> Optional[datetime]:
        """
        Manual parsing cho month/day khi dateutil không available.
        
        Args:
            text: Text chứa month và day
            
        Returns:
            datetime object hoặc None
        """
        month_map = {
            'jan': 1, 'january': 1, 'thg 1': 1, 'tháng 1': 1,
            'feb': 2, 'february': 2, 'thg 2': 2, 'tháng 2': 2,
            'mar': 3, 'march': 3, 'thg 3': 3, 'tháng 3': 3,
            'apr': 4, 'april': 4, 'thg 4': 4, 'tháng 4': 4,
            'may': 5, 'may': 5, 'thg 5': 5, 'tháng 5': 5,
            'jun': 6, 'june': 6, 'thg 6': 6, 'tháng 6': 6,
            'jul': 7, 'july': 7, 'thg 7': 7, 'tháng 7': 7,
            'aug': 8, 'august': 8, 'thg 8': 8, 'tháng 8': 8,
            'sep': 9, 'september': 9, 'thg 9': 9, 'tháng 9': 9,
            'oct': 10, 'october': 10, 'thg 10': 10, 'tháng 10': 10,
            'nov': 11, 'november': 11, 'thg 11': 11, 'tháng 11': 11,
            'dec': 12, 'december': 12, 'thg 12': 12, 'tháng 12': 12,
        }
        
        # Regex để bắt "tháng ngày" hoặc "ngày tháng"
        pattern = '|'.join(month_map.keys())
        match = re.search(r'(\d{1,2})?\s*(' + pattern + r')\s*(\d{1,2})?', text)
        
        if not match:
            return None
        
        parts = [p for p in match.groups() if p and p.strip()]
        if len(parts) < 2:
            return None
        
        # Phân tích tháng và ngày
        month_str = None
        day_str = None
        
        for part in parts:
            if part in month_map:
                month_str = part
            elif part.isdigit():
                day_str = part
        
        if not (month_str and day_str):
            return None
        
        try:
            day = int(day_str)
            month = month_map[month_str]
            year = datetime.now().year
            
            # Handle edge case: post date in future -> last year
            test_date = datetime(year, month, day)
            if test_date > datetime.now():
                year -= 1
            
            return datetime(year, month, day)
        except (ValueError, KeyError):
            return None
    
    def _parse_iso_date(self, text: str) -> Optional[datetime]:
        """
        Parse ISO dates '2025-09-19', '19/09/2025'
        
        Args:
            text: Text chứa ISO date
            
        Returns:
            datetime object hoặc None
        """
        patterns = [
            # YYYY-MM-DD or YYYY/MM/DD
            (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', 
             lambda m: datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
            
            # DD-MM-YYYY or DD/MM/YYYY
            (r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', 
             lambda m: datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))),
        ]
        
        for pattern, constructor in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    result = constructor(match)
                    logger.debug(f"✅ Parsed ISO date: '{text}' -> {result}")
                    return result
                except (ValueError, TypeError):
                    continue
        
        return None


# Singleton instance để reuse
_parser_instance = FacebookTimestampParser()


def parse_facebook_timestamp(time_string: str) -> Optional[datetime]:
    """
    Convenience function để parse Facebook timestamp.
    
    Args:
        time_string: Chuỗi thời gian từ Facebook
        
    Returns:
        datetime object hoặc None
    """
    return _parser_instance.parse(time_string)


# ============================================================================
# ✅ GMT+7 TIMEZONE CONVERSION UTILITIES
# ============================================================================

def convert_utc_to_gmt7(utc_time: datetime) -> datetime:
    """
    Convert UTC datetime to GMT+7 (Asia/Bangkok timezone).
    
    ✅ SAFE: Pure utility function, no side effects
    
    Args:
        utc_time: Datetime in UTC (naive or aware)
        
    Returns:
        Datetime in GMT+7 timezone
        
    Examples:
        >>> utc_time = datetime(2025, 10, 4, 10, 30, 0, tzinfo=timezone.utc)
        >>> gmt7_time = convert_utc_to_gmt7(utc_time)
        >>> print(gmt7_time)  # 2025-10-04 17:30:00+07:00
    """
    try:
        # Try pytz first (more reliable)
        from pytz import timezone as pytz_timezone
        gmt7_tz = pytz_timezone('Asia/Bangkok')
        
        # If naive datetime, assume UTC
        if utc_time.tzinfo is None:
            utc_time = utc_time.replace(tzinfo=timezone.utc)
        
        # Convert to GMT+7
        return utc_time.astimezone(gmt7_tz)
        
    except ImportError:
        # Fallback: manual offset (+7 hours)
        logger.debug("⚠️ pytz not available, using manual GMT+7 offset")
        
        # If naive datetime, assume UTC
        if utc_time.tzinfo is None:
            utc_time = utc_time.replace(tzinfo=timezone.utc)
        
        # Add 7 hours for GMT+7
        from datetime import timedelta, timezone as dt_timezone
        gmt7_offset = dt_timezone(timedelta(hours=7))
        return utc_time.astimezone(gmt7_offset)


def format_timestamp_gmt7(utc_time: datetime, format_string: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format UTC timestamp as GMT+7 string.
    
    ✅ SAFE: Pure utility function for display
    
    Args:
        utc_time: Datetime in UTC
        format_string: strftime format string
        
    Returns:
        Formatted string in GMT+7
        
    Examples:
        >>> utc_time = datetime(2025, 10, 4, 10, 30, 0, tzinfo=timezone.utc)
        >>> formatted = format_timestamp_gmt7(utc_time)
        >>> print(formatted)  # "2025-10-04 17:30:00"
    """
    if not utc_time:
        return "N/A"
    
    try:
        gmt7_time = convert_utc_to_gmt7(utc_time)
        return gmt7_time.strftime(format_string)
    except Exception as e:
        logger.warning(f"⚠️ Error formatting timestamp: {e}")
        return str(utc_time)


def parse_iso_to_gmt7(iso_string: str) -> Optional[datetime]:
    """
    Parse ISO timestamp string and convert to GMT+7.
    
    ✅ SAFE: Combines parsing + conversion
    
    Args:
        iso_string: ISO format timestamp string (e.g., "2025-10-04T10:30:00Z")
        
    Returns:
        Datetime in GMT+7 or None if parsing fails
        
    Examples:
        >>> iso_str = "2025-10-04T10:30:00Z"
        >>> gmt7_time = parse_iso_to_gmt7(iso_str)
        >>> print(gmt7_time)  # 2025-10-04 17:30:00+07:00
    """
    if not iso_string:
        return None
    
    try:
        # Parse ISO string (handles 'Z' and '+00:00' suffixes)
        utc_time = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        
        # Convert to GMT+7
        return convert_utc_to_gmt7(utc_time)
        
    except (ValueError, TypeError) as e:
        logger.warning(f"⚠️ Error parsing ISO timestamp '{iso_string}': {e}")
        return None


def get_current_time_gmt7() -> datetime:
    """
    Get current time in GMT+7.
    
    ✅ SAFE: Simple utility
    
    Returns:
        Current datetime in GMT+7
    """
    return convert_utc_to_gmt7(datetime.now(timezone.utc))
