#!/usr/bin/env python3
"""
Unit tests for validation_helpers module
Tests DataValidator and FieldExtractor functionality
"""

import pytest
from unittest.mock import Mock, patch

from utils.validation_helpers import DataValidator, FieldExtractor


@pytest.mark.unit
class TestDataValidator:
    """Test cases for DataValidator class"""
    
    def test_validate_integer_success(self):
        """Test validating valid integer values"""
        # Test normal integer
        result = DataValidator.validate_data(42, {"type": "integer", "min": 0, "max": 100}, "test_field")
        assert result["is_valid"] is True
        assert result["cleaned_data"] == 42
        
        # Test string that can be converted to integer
        result = DataValidator.validate_data("123", {"type": "integer"}, "test_field")
        assert result["is_valid"] is True
        assert result["cleaned_data"] == 123
        
        # Test with min/max constraints
        result = DataValidator.validate_data(50, {"type": "integer", "min": 10, "max": 100}, "test_field")
        assert result["is_valid"] is True
        assert result["cleaned_data"] == 50
    
    def test_validate_integer_failure(self):
        """Test validating invalid integer values"""
        # Test value below minimum
        result = DataValidator.validate_data(5, {"type": "integer", "min": 10}, "test_field")
        assert result["is_valid"] is False
        assert "below minimum" in result["error_message"].lower()
        
        # Test value above maximum
        result = DataValidator.validate_data(150, {"type": "integer", "max": 100}, "test_field")
        assert result["is_valid"] is False
        assert "above maximum" in result["error_message"].lower()
        
        # Test non-numeric string
        result = DataValidator.validate_data("not_a_number", {"type": "integer"}, "test_field")
        assert result["is_valid"] is False
        assert "cannot convert" in result["error_message"].lower()
    
    def test_validate_text_not_empty(self):
        """Test validating text fields"""
        # Test valid text
        result = DataValidator.validate_data("Hello World", {"type": "string", "min_length": 5}, "test_field")
        assert result["is_valid"] is True
        assert result["cleaned_data"] == "Hello World"
        
        # Test empty string with min_length requirement
        result = DataValidator.validate_data("", {"type": "string", "min_length": 1}, "test_field")
        assert result["is_valid"] is False
        assert "too short" in result["error_message"].lower()
        
        # Test string below min_length
        result = DataValidator.validate_data("Hi", {"type": "string", "min_length": 5}, "test_field")
        assert result["is_valid"] is False
        assert "too short" in result["error_message"].lower()
        
        # Test None value
        result = DataValidator.validate_data(None, {"type": "string", "min_length": 1}, "test_field")
        assert result["is_valid"] is False
    
    def test_validate_url(self):
        """Test validating URL fields"""
        # Test valid URLs
        valid_urls = [
            "https://www.facebook.com/groups/test",
            "http://example.com",
            "https://sub.domain.com/path?query=value"
        ]
        
        for url in valid_urls:
            result = DataValidator.validate_data(url, {"type": "url"}, "test_field")
            assert result["is_valid"] is True, f"URL {url} should be valid"
            assert result["cleaned_data"] == url
        
        # Test invalid URLs
        invalid_urls = [
            "not_a_url",
            "ftp://invalid-protocol.com",
            "http://",
            ""
        ]
        
        for url in invalid_urls:
            result = DataValidator.validate_data(url, {"type": "url"}, "test_field")
            assert result["is_valid"] is False, f"URL {url} should be invalid"
    
    def test_validate_with_no_validation_config(self):
        """Test validation with empty or missing config"""
        # Should pass through without validation
        result = DataValidator.validate_data("any_value", {}, "test_field")
        assert result["is_valid"] is True
        assert result["cleaned_data"] == "any_value"
        
        result = DataValidator.validate_data(123, None, "test_field")
        assert result["is_valid"] is True
        assert result["cleaned_data"] == 123


@pytest.mark.unit
class TestFieldExtractor:
    """Test cases for FieldExtractor class"""
    
    def test_extract_count_from_text(self):
        """Test extracting numeric counts from text strings"""
        # Test simple numbers
        assert FieldExtractor.extract_count("123 comments") == 123
        assert FieldExtractor.extract_count("5 likes") == 5
        
        # Test with comma separators
        assert FieldExtractor.extract_count("1,234 reactions") == 1234
        assert FieldExtractor.extract_count("10,000 views") == 10000
        
        # Test with K suffix
        assert FieldExtractor.extract_count("1.5K likes") == 1500
        assert FieldExtractor.extract_count("10K comments") == 10000
        assert FieldExtractor.extract_count("2.3k shares") == 2300
        
        # Test with M suffix
        assert FieldExtractor.extract_count("1M views") == 1000000
        assert FieldExtractor.extract_count("2.5M reactions") == 2500000
        assert FieldExtractor.extract_count("0.5m likes") == 500000
        
        # Test with B suffix
        assert FieldExtractor.extract_count("1B views") == 1000000000
        assert FieldExtractor.extract_count("1.2B likes") == 1200000000
        
        # Test edge cases
        assert FieldExtractor.extract_count("no numbers here") == 0
        assert FieldExtractor.extract_count("") == 0
        assert FieldExtractor.extract_count(None) == 0
        assert FieldExtractor.extract_count("0 likes") == 0
    
    def test_extract_text_from_html(self):
        """Test extracting clean text from HTML content"""
        # Test basic HTML removal
        assert FieldExtractor.extract_text("<p>Hello World</p>") == "Hello World"
        assert FieldExtractor.extract_text("<div><span>Nested</span> text</div>") == "Nested text"
        
        # Test with attributes
        assert FieldExtractor.extract_text('<a href="link">Click here</a>') == "Click here"
        
        # Test with special characters
        assert FieldExtractor.extract_text("Line 1<br>Line 2") == "Line 1 Line 2"
        assert FieldExtractor.extract_text("Text with &nbsp; spaces") == "Text with   spaces"
        
        # Test empty cases
        assert FieldExtractor.extract_text("") == ""
        assert FieldExtractor.extract_text(None) == ""
        assert FieldExtractor.extract_text("<div></div>") == ""
    
    def test_clean_text(self):
        """Test text cleaning and normalization"""
        # Test whitespace normalization
        assert FieldExtractor.clean_text("  Multiple   spaces  ") == "Multiple spaces"
        assert FieldExtractor.clean_text("Line1\n\nLine2") == "Line1 Line2"
        assert FieldExtractor.clean_text("\t\tTabbed\t\t") == "Tabbed"
        
        # Test special character handling
        assert FieldExtractor.clean_text("Text™ with® symbols©") == "Text with symbols"
        
        # Test emoji removal (if implemented)
        # Note: This depends on implementation details
        text_with_emoji = "Hello 😀 World 🌍"
        cleaned = FieldExtractor.clean_text(text_with_emoji)
        # Should either keep or remove emojis consistently
        assert len(cleaned) > 0
    
    def test_extract_url_from_text(self):
        """Test extracting URLs from text content"""
        # Test extracting single URL
        text = "Check out https://www.example.com for more info"
        urls = FieldExtractor.extract_urls(text)
        assert "https://www.example.com" in urls
        
        # Test extracting multiple URLs
        text = "Visit http://site1.com and https://site2.com"
        urls = FieldExtractor.extract_urls(text)
        assert len(urls) == 2
        assert "http://site1.com" in urls
        assert "https://site2.com" in urls
        
        # Test with no URLs
        text = "No URLs in this text"
        urls = FieldExtractor.extract_urls(text)
        assert len(urls) == 0
        
        # Test edge cases
        assert FieldExtractor.extract_urls("") == []
        assert FieldExtractor.extract_urls(None) == []
    
    def test_validate_facebook_url(self):
        """Test Facebook URL validation"""
        # Valid Facebook URLs
        valid_urls = [
            "https://www.facebook.com/groups/testgroup",
            "https://facebook.com/pages/testpage/123456",
            "https://m.facebook.com/profile.php?id=123456",
            "http://www.facebook.com/username"
        ]
        
        for url in valid_urls:
            assert FieldExtractor.is_facebook_url(url) is True, f"{url} should be valid"
        
        # Invalid URLs
        invalid_urls = [
            "https://www.google.com",
            "https://twitter.com/user",
            "not_a_url",
            "",
            None
        ]
        
        for url in invalid_urls:
            assert FieldExtractor.is_facebook_url(url) is False, f"{url} should be invalid"
    
    def test_extract_facebook_id(self):
        """Test extracting Facebook IDs from URLs"""
        # Test numeric ID extraction
        assert FieldExtractor.extract_facebook_id("https://facebook.com/profile.php?id=123456789") == "123456789"
        
        # Test username extraction
        assert FieldExtractor.extract_facebook_id("https://facebook.com/john.doe") == "john.doe"
        assert FieldExtractor.extract_facebook_id("https://www.facebook.com/pages/PageName/987654321") == "987654321"
        
        # Test group ID extraction
        assert FieldExtractor.extract_facebook_id("https://facebook.com/groups/123456789") == "123456789"
        assert FieldExtractor.extract_facebook_id("https://facebook.com/groups/groupname") == "groupname"
        
        # Test edge cases
        assert FieldExtractor.extract_facebook_id("not_a_facebook_url") is None
        assert FieldExtractor.extract_facebook_id("") is None
        assert FieldExtractor.extract_facebook_id(None) is None


@pytest.mark.unit
class TestDataValidatorIntegration:
    """Integration tests for DataValidator with complex scenarios"""
    
    def test_validate_post_data_structure(self):
        """Test validating a complete post data structure"""
        post_data = {
            "author": "John Doe",
            "content": "This is a test post with some content",
            "like_count": "1.5K",
            "comment_count": 42,
            "post_url": "https://facebook.com/posts/123456"
        }
        
        validation_rules = {
            "author": {"type": "string", "min_length": 1},
            "content": {"type": "string", "min_length": 10},
            "like_count": {"type": "integer", "min": 0},
            "comment_count": {"type": "integer", "min": 0},
            "post_url": {"type": "url"}
        }
        
        # Validate each field
        for field, value in post_data.items():
            if field in validation_rules:
                result = DataValidator.validate_data(value, validation_rules[field], field)
                
                if field == "like_count":
                    # Should convert "1.5K" to 1500
                    assert result["is_valid"] is True
                    assert result["cleaned_data"] == 1500
                else:
                    assert result["is_valid"] is True
    
    def test_batch_validation(self):
        """Test validating multiple fields at once"""
        data_batch = [
            {"value": 100, "rule": {"type": "integer", "min": 0, "max": 200}},
            {"value": "test@example.com", "rule": {"type": "email"}},
            {"value": "https://example.com", "rule": {"type": "url"}},
            {"value": "Short", "rule": {"type": "string", "min_length": 10}}
        ]
        
        results = []
        for item in data_batch:
            result = DataValidator.validate_data(item["value"], item["rule"], "batch_field")
            results.append(result["is_valid"])
        
        # First three should pass, last should fail (too short)
        assert results == [True, True, True, False]