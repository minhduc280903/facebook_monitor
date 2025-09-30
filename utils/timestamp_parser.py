#!/usr/bin/env python3
"""
Facebook Timestamp Parser - Simplified Strategy Pattern
Xử lý các định dạng timestamp khác nhau từ Facebook
"""

import re
from datetime import datetime, timedelta
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
