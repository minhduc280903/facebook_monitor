#!/usr/bin/env python3
"""
Validation Helpers for Facebook Post Monitor - Resilient Scraping System
Hệ thống validation cho dữ liệu được extract từ scraping

Chức năng:
- Validate extracted data theo các rules trong selectors.json
- Hỗ trợ multiple validation types
- Logging chi tiết cho debugging
"""

import re
from logging_config import get_logger
from typing import Any, Dict
from urllib.parse import urlparse

logger = get_logger(__name__)


class ValidationError(Exception):
    """Custom exception cho validation errors"""
    pass


class DataValidator:
    """
    Main validator class cho extracted data
    
    Hỗ trợ các validation types:
    - integer: Kiểm tra số nguyên với min/max values
    - text_not_empty: Kiểm tra text không rỗng với length limits
    - url: Kiểm tra URL hợp lệ với required content
    - elements_found: Kiểm tra số lượng elements tìm được
    """
    
    @staticmethod
    def validate_data(data: Any, validation_config: Dict[str, Any], field_name: str) -> Dict[str, Any]:
        """
        Validate dữ liệu theo configuration
        
        Args:
            data: Dữ liệu cần validate
            validation_config: Config validation từ selectors.json
            field_name: Tên field để logging
            
        Returns:
            Dict với keys: is_valid, cleaned_data, error_message
        """
        try:
            validation_type = validation_config.get('type', 'text_not_empty')
            is_required = validation_config.get('required', False)
            
            # Kiểm tra required field
            if is_required and (data is None or data == ""):
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": f"Required field '{field_name}' is empty"
                }
            
            # Nếu không required và data rỗng, cho phép
            if not is_required and (data is None or data == ""):
                return {
                    "is_valid": True,
                    "cleaned_data": None,
                    "error_message": None
                }
            
            # Dispatch to specific validator
            if validation_type == "integer":
                return DataValidator._validate_integer(data, validation_config, field_name)
            elif validation_type == "text_not_empty":
                return DataValidator._validate_text(data, validation_config, field_name)
            elif validation_type == "url":
                return DataValidator._validate_url(data, validation_config, field_name)
            elif validation_type == "elements_found":
                return DataValidator._validate_elements(data, validation_config, field_name)
            else:
                logger.warning(f"Unknown validation type '{validation_type}' for field '{field_name}'")
                return {
                    "is_valid": True,
                    "cleaned_data": data,
                    "error_message": None
                }
                
        except Exception as e:
            logger.error(f"Validation error for field '{field_name}': {e}")
            return {
                "is_valid": False,
                "cleaned_data": None,
                "error_message": f"Validation exception: {str(e)}"
            }
    
    @staticmethod
    def _validate_integer(data: Any, config: Dict[str, Any], field_name: str) -> Dict[str, Any]:
        """Validate integer data với min/max bounds"""
        try:
            # Convert to integer
            if isinstance(data, str):
                # Clean string data (remove commas, extract numbers)
                cleaned_str = re.sub(r'[^\d]', '', data)
                if not cleaned_str:
                    raise ValueError("No numeric data found in string")
                integer_value = int(cleaned_str)
            elif isinstance(data, (int, float)):
                integer_value = int(data)
            else:
                raise ValueError(f"Cannot convert {type(data)} to integer")
            
            # Check bounds
            min_value = config.get('min_value', float('-inf'))
            max_value = config.get('max_value', float('inf'))
            
            if integer_value < min_value:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": f"Value {integer_value} below minimum {min_value}"
                }
            
            if integer_value > max_value:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": f"Value {integer_value} above maximum {max_value}"
                }
            
            return {
                "is_valid": True,
                "cleaned_data": integer_value,
                "error_message": None
            }
            
        except (ValueError, TypeError) as e:
            return {
                "is_valid": False,
                "cleaned_data": None,
                "error_message": f"Invalid integer format: {str(e)}"
            }
    
    @staticmethod
    def _validate_text(data: Any, config: Dict[str, Any], field_name: str) -> Dict[str, Any]:
        """Validate text data với length constraints"""
        try:
            # Convert to string and clean
            if data is None:
                text_value = ""
            else:
                text_value = str(data).strip()
            
            # Check if empty
            if not text_value:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": "Text is empty after cleaning"
                }
            
            # Check length constraints
            min_length = config.get('min_length', 0)
            max_length = config.get('max_length', float('inf'))
            
            if len(text_value) < min_length:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": f"Text length {len(text_value)} below minimum {min_length}"
                }
            
            if len(text_value) > max_length:
                # Truncate instead of failing
                text_value = text_value[:max_length]
                logger.warning(f"Text truncated to {max_length} characters for field '{field_name}'")
            
            return {
                "is_valid": True,
                "cleaned_data": text_value,
                "error_message": None
            }
            
        except Exception as e:
            return {
                "is_valid": False,
                "cleaned_data": None,
                "error_message": f"Text validation error: {str(e)}"
            }
    
    @staticmethod
    def _validate_url(data: Any, config: Dict[str, Any], field_name: str) -> Dict[str, Any]:
        """Validate URL với required content checks"""
        try:
            if data is None:
                url_value = ""
            else:
                url_value = str(data).strip()
            
            if not url_value:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": "URL is empty"
                }
            
            # Ensure full URL
            if not url_value.startswith(('http://', 'https://')):
                if url_value.startswith('/'):
                    url_value = "https://www.facebook.com" + url_value
                else:
                    url_value = "https://www.facebook.com/" + url_value
            
            # Parse URL
            try:
                parsed = urlparse(url_value)
                if not parsed.netloc:
                    raise ValueError("Invalid URL structure")
            except Exception as e:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": f"URL parsing failed: {str(e)}"
                }
            
            # Check required content
            must_contain = config.get('must_contain', [])
            for required_content in must_contain:
                if required_content not in url_value:
                    return {
                        "is_valid": False,
                        "cleaned_data": None,
                        "error_message": f"URL missing required content: '{required_content}'"
                    }
            
            return {
                "is_valid": True,
                "cleaned_data": url_value,
                "error_message": None
            }
            
        except Exception as e:
            return {
                "is_valid": False,
                "cleaned_data": None,
                "error_message": f"URL validation error: {str(e)}"
            }
    
    @staticmethod
    def _validate_elements(data: Any, config: Dict[str, Any], field_name: str) -> Dict[str, Any]:
        """Validate số lượng elements tìm được"""
        try:
            # Data should be a list or count
            if isinstance(data, list):
                count = len(data)
                elements = data
            elif isinstance(data, int):
                count = data
                elements = None
            else:
                count = 0
                elements = None
            
            min_count = config.get('min_count', 0)
            max_count = config.get('max_count', float('inf'))
            
            if count < min_count:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": f"Element count {count} below minimum {min_count}"
                }
            
            if count > max_count:
                return {
                    "is_valid": False,
                    "cleaned_data": None,
                    "error_message": f"Element count {count} above maximum {max_count}"
                }
            
            return {
                "is_valid": True,
                "cleaned_data": elements if elements is not None else count,
                "error_message": None
            }
            
        except Exception as e:
            return {
                "is_valid": False,
                "cleaned_data": None,
                "error_message": f"Elements validation error: {str(e)}"
            }


class FieldExtractor:
    """
    Helper class để extract và clean text từ Playwright elements
    """
    
    @staticmethod
    def extract_count_from_text(text: str) -> int:
        """
        Extract numeric count từ text như '123 cảm xúc', '1.2K likes'
        
        Hỗ trợ:
        - Numbers with commas: "1,234"
        - K notation: "1.2K" -> 1200
        - M notation: "2.5M" -> 2500000
        """
        try:
            if not text:
                return 0
            
            # Clean text and find numbers
            text = text.strip().replace(',', '')
            
            # Handle K/M notation
            k_match = re.search(r'(\d+(?:\.\d+)?)\s*K', text, re.IGNORECASE)
            if k_match:
                return int(float(k_match.group(1)) * 1000)
            
            m_match = re.search(r'(\d+(?:\.\d+)?)\s*M', text, re.IGNORECASE)
            if m_match:
                return int(float(m_match.group(1)) * 1000000)
            
            # Regular numbers
            numbers = re.findall(r'\d+', text)
            if numbers:
                return int(numbers[0])
            
            return 0
            
        except (ValueError, TypeError, AttributeError):
            return 0
    
    @staticmethod
    def clean_text_content(text: str) -> str:
        """Clean và normalize text content"""
        if not text:
            return ""
        
        # Basic cleaning
        cleaned = text.strip()
        
        # Remove multiple spaces and newlines
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Remove common social media artifacts
        artifacts = [
            'Translate', 'See translation', 'See more', 'See less',
            'Xem thêm', 'Xem bản dịch', 'Dịch'
        ]
        
        for artifact in artifacts:
            cleaned = cleaned.replace(artifact, '').strip()
        
        return cleaned
    
    @staticmethod
    def is_metadata_text(text: str) -> bool:
        """Kiểm tra xem text có phải là metadata không (likes, comments, timestamps)"""
        if not text:
            return False
        
        text_lower = text.lower()
        metadata_keywords = [
            'like', 'thích', 'comment', 'bình luận', 'share', 'chia sẻ',
            'ago', 'giờ', 'ngày', 'phút', 'yesterday', 'hôm qua',
            'reaction', 'cảm xúc', 'view', 'lượt xem', 'minute', 'hour',
            'day', 'week', 'month', 'year', 'sponsored', 'tài trợ'
        ]
        
        return any(keyword in text_lower for keyword in metadata_keywords)


# Test function
def test_validation():
    """Test các validation functions"""
    logger.info("🧪 Testing validation system...")
    
    # Test integer validation
    int_config = {"type": "integer", "required": True, "min_value": 0, "max_value": 1000000}
    
    test_cases = [
        ("123", True),
        ("1,234", True),
        ("1.2K comments", False),  # Should be handled by extract_count_from_text first
        (-5, False),
        (2000000, False),
        ("", False)
    ]
    
    for test_data, expected_valid in test_cases:
        result = DataValidator.validate_data(test_data, int_config, "test_field")
        print(f"Input: {test_data} | Valid: {result['is_valid']} | Expected: {expected_valid}")
        if result['is_valid'] != expected_valid:
            print(f"  ERROR: {result['error_message']}")
    
    # Test text validation
    text_config = {"type": "text_not_empty", "required": True, "min_length": 2, "max_length": 50}
    
    text_test_cases = [
        ("Valid text", True),
        ("A", False),
        ("", False),
        ("Very long text that exceeds the maximum allowed length for this field", True)  # Should truncate
    ]
    
    for test_data, expected_valid in text_test_cases:
        result = DataValidator.validate_data(test_data, text_config, "test_text")
        print(f"Text: '{test_data}' | Valid: {result['is_valid']} | Expected: {expected_valid}")
        if result['cleaned_data']:
            print(f"  Cleaned: '{result['cleaned_data']}'")
    
    print("✅ Validation tests completed!")


if __name__ == "__main__":
    from logging_config import setup_application_logging, get_logger
    setup_application_logging()
    test_logger = get_logger(__name__, level="DEBUG")
    test_validation()
