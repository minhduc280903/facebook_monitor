#!/usr/bin/env python3
"""
Comprehensive tests for Browser Configuration utilities
Tests browser fingerprinting, configuration consistency, and security features
"""

import pytest
from unittest.mock import Mock, patch
from typing import Dict, Any

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import browser config components
from utils.browser_config import (
    BrowserConfig, get_default_browser_config, get_stealth_browser_config,
    get_mobile_browser_config, validate_browser_config, 
    DEFAULT_USER_AGENT, DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT,
    STEALTH_USER_AGENTS, MOBILE_USER_AGENTS
)


@pytest.mark.unit
class TestBrowserConfigConstants:
    """Test browser configuration constants"""
    
    def test_default_user_agent_format(self):
        """Test default user agent has correct format"""
        assert DEFAULT_USER_AGENT.startswith('Mozilla/5.0')
        assert 'Chrome' in DEFAULT_USER_AGENT
        assert 'Safari' in DEFAULT_USER_AGENT
        assert 'Windows NT 10.0' in DEFAULT_USER_AGENT
    
    def test_default_viewport_dimensions(self):
        """Test default viewport dimensions are reasonable"""
        assert DEFAULT_VIEWPORT_WIDTH == 1366
        assert DEFAULT_VIEWPORT_HEIGHT == 768
        assert DEFAULT_VIEWPORT_WIDTH > 1000  # Reasonable desktop width
        assert DEFAULT_VIEWPORT_HEIGHT > 600   # Reasonable desktop height
    
    def test_stealth_user_agents_variety(self):
        """Test stealth user agents provide variety"""
        assert len(STEALTH_USER_AGENTS) >= 5  # Should have multiple options
        assert all(ua.startswith('Mozilla/5.0') for ua in STEALTH_USER_AGENTS)
        
        # Should have different browser types
        user_agent_text = ' '.join(STEALTH_USER_AGENTS)
        assert 'Chrome' in user_agent_text
        assert 'Firefox' in user_agent_text or 'Safari' in user_agent_text
    
    def test_mobile_user_agents_mobile_specific(self):
        """Test mobile user agents are mobile-specific"""
        assert len(MOBILE_USER_AGENTS) >= 3
        
        for ua in MOBILE_USER_AGENTS:
            assert any(mobile_indicator in ua for mobile_indicator in 
                      ['Mobile', 'Android', 'iPhone', 'iPad'])


@pytest.mark.unit
class TestBrowserConfig:
    """Test BrowserConfig class functionality"""
    
    def test_browser_config_initialization(self):
        """Test BrowserConfig initialization with default values"""
        config = BrowserConfig()
        
        assert config.user_agent == DEFAULT_USER_AGENT
        assert config.viewport_width == DEFAULT_VIEWPORT_WIDTH
        assert config.viewport_height == DEFAULT_VIEWPORT_HEIGHT
        assert config.locale == 'vi-VN'
        assert config.timezone == 'Asia/Ho_Chi_Minh'
        assert isinstance(config.extra_headers, dict)
    
    def test_browser_config_custom_values(self):
        """Test BrowserConfig with custom values"""
        custom_config = BrowserConfig(
            user_agent="Custom User Agent",
            viewport_width=1920,
            viewport_height=1080,
            locale='en-US',
            timezone='America/New_York',
            headless=False,
            extra_headers={'X-Custom': 'test'}
        )
        
        assert custom_config.user_agent == "Custom User Agent"
        assert custom_config.viewport_width == 1920
        assert custom_config.viewport_height == 1080
        assert custom_config.locale == 'en-US'
        assert custom_config.timezone == 'America/New_York'
        assert custom_config.headless is False
        assert custom_config.extra_headers['X-Custom'] == 'test'
    
    def test_to_playwright_config(self):
        """Test conversion to Playwright configuration"""
        config = BrowserConfig(
            user_agent="Test Agent",
            viewport_width=1280,
            viewport_height=720,
            locale='en-GB'
        )
        
        playwright_config = config.to_playwright_config()
        
        assert playwright_config['user_agent'] == "Test Agent"
        assert playwright_config['viewport']['width'] == 1280
        assert playwright_config['viewport']['height'] == 720
        assert playwright_config['locale'] == 'en-GB'
        assert 'extra_http_headers' in playwright_config
    
    def test_to_selenium_config(self):
        """Test conversion to Selenium configuration"""
        config = BrowserConfig(
            user_agent="Selenium Test Agent",
            headless=True,
            extra_headers={'Authorization': 'Bearer token'}
        )
        
        selenium_config = config.to_selenium_config()
        
        assert selenium_config['user_agent'] == "Selenium Test Agent"
        assert selenium_config['headless'] is True
        assert selenium_config['window_size'] == (DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT)
        assert 'extra_headers' in selenium_config
    
    def test_fingerprint_consistency(self):
        """Test browser fingerprint consistency"""
        config1 = BrowserConfig(user_agent="Same Agent", viewport_width=1366)
        config2 = BrowserConfig(user_agent="Same Agent", viewport_width=1366)
        
        fingerprint1 = config1.get_fingerprint()
        fingerprint2 = config2.get_fingerprint()
        
        # Same configuration should produce same fingerprint
        assert fingerprint1 == fingerprint2
        
        # Different configuration should produce different fingerprint
        config3 = BrowserConfig(user_agent="Different Agent", viewport_width=1366)
        fingerprint3 = config3.get_fingerprint()
        
        assert fingerprint1 != fingerprint3
    
    def test_security_headers(self):
        """Test security-related headers are included"""
        config = BrowserConfig()
        playwright_config = config.to_playwright_config()
        
        headers = playwright_config.get('extra_http_headers', {})
        
        # Should have security headers
        assert 'Accept' in headers
        assert 'Accept-Language' in headers
        assert 'Accept-Encoding' in headers
        assert 'DNT' in headers  # Do Not Track
    
    def test_clone_method(self):
        """Test config cloning functionality"""
        original = BrowserConfig(
            user_agent="Original Agent",
            viewport_width=1920,
            extra_headers={'X-Test': 'original'}
        )
        
        cloned = original.clone()
        
        # Should be identical but separate objects
        assert cloned.user_agent == original.user_agent
        assert cloned.viewport_width == original.viewport_width
        assert cloned.extra_headers == original.extra_headers
        assert cloned is not original
        assert cloned.extra_headers is not original.extra_headers


@pytest.mark.unit
class TestBrowserConfigFactories:
    """Test browser configuration factory functions"""
    
    def test_get_default_browser_config(self):
        """Test default browser configuration factory"""
        config = get_default_browser_config()
        
        assert isinstance(config, BrowserConfig)
        assert config.user_agent == DEFAULT_USER_AGENT
        assert config.viewport_width == DEFAULT_VIEWPORT_WIDTH
        assert config.viewport_height == DEFAULT_VIEWPORT_HEIGHT
        assert config.headless is True  # Default should be headless
        assert config.locale == 'vi-VN'
    
    def test_get_stealth_browser_config(self):
        """Test stealth browser configuration factory"""
        config = get_stealth_browser_config()
        
        assert isinstance(config, BrowserConfig)
        assert config.user_agent in STEALTH_USER_AGENTS
        assert config.stealth_mode is True
        assert config.disable_blink_features is True
        assert config.extra_headers.get('sec-ch-ua-platform')  # Should have Chrome hints
    
    def test_get_stealth_config_randomization(self):
        """Test stealth config produces different configurations"""
        configs = [get_stealth_browser_config() for _ in range(5)]
        
        # Should have some variation in user agents
        user_agents = [config.user_agent for config in configs]
        assert len(set(user_agents)) > 1  # Should not all be the same
    
    def test_get_mobile_browser_config(self):
        """Test mobile browser configuration factory"""
        config = get_mobile_browser_config()
        
        assert isinstance(config, BrowserConfig)
        assert config.user_agent in MOBILE_USER_AGENTS
        assert config.is_mobile is True
        assert config.viewport_width <= 414  # Mobile width
        assert config.viewport_height <= 896  # Mobile height
        assert 'Mobile' in config.user_agent or 'Android' in config.user_agent
    
    def test_get_mobile_config_device_types(self):
        """Test mobile config supports different device types"""
        # Test different mobile device types
        android_config = get_mobile_browser_config(device_type='android')
        ios_config = get_mobile_browser_config(device_type='ios')
        
        assert 'Android' in android_config.user_agent
        assert ('iPhone' in ios_config.user_agent or 'iPad' in ios_config.user_agent)
    
    def test_custom_config_parameters(self):
        """Test factory functions accept custom parameters"""
        config = get_default_browser_config(
            headless=False,
            viewport_width=1920,
            extra_headers={'X-Custom': 'test'}
        )
        
        assert config.headless is False
        assert config.viewport_width == 1920
        assert config.extra_headers['X-Custom'] == 'test'


@pytest.mark.unit
class TestBrowserConfigValidation:
    """Test browser configuration validation"""
    
    def test_validate_valid_config(self):
        """Test validation passes for valid configuration"""
        config = BrowserConfig(
            user_agent="Valid User Agent",
            viewport_width=1366,
            viewport_height=768,
            locale='vi-VN'
        )
        
        # Should not raise any exceptions
        validate_browser_config(config)
        
        # Test with dict format
        config_dict = config.to_playwright_config()
        validate_browser_config(config_dict)
    
    def test_validate_invalid_viewport_dimensions(self):
        """Test validation fails for invalid viewport dimensions"""
        with pytest.raises(ValueError) as exc_info:
            invalid_config = BrowserConfig(viewport_width=0, viewport_height=768)
            validate_browser_config(invalid_config)
        
        assert "viewport_width" in str(exc_info.value)
        
        with pytest.raises(ValueError) as exc_info:
            invalid_config = BrowserConfig(viewport_width=1366, viewport_height=0)
            validate_browser_config(invalid_config)
        
        assert "viewport_height" in str(exc_info.value)
    
    def test_validate_invalid_user_agent(self):
        """Test validation fails for invalid user agent"""
        with pytest.raises(ValueError) as exc_info:
            invalid_config = BrowserConfig(user_agent="")
            validate_browser_config(invalid_config)
        
        assert "user_agent" in str(exc_info.value)
        
        with pytest.raises(ValueError) as exc_info:
            invalid_config = BrowserConfig(user_agent=None)
            validate_browser_config(invalid_config)
        
        assert "user_agent" in str(exc_info.value)
    
    def test_validate_invalid_locale(self):
        """Test validation fails for invalid locale"""
        with pytest.raises(ValueError) as exc_info:
            invalid_config = BrowserConfig(locale="invalid-locale-format")
            validate_browser_config(invalid_config)
        
        assert "locale" in str(exc_info.value)
    
    def test_validate_oversized_viewport(self):
        """Test validation warns about oversized viewport"""
        # Very large viewport should trigger warning but not error
        large_config = BrowserConfig(viewport_width=5000, viewport_height=3000)
        
        with patch('utils.browser_config.logger') as mock_logger:
            validate_browser_config(large_config)
            mock_logger.warning.assert_called()


@pytest.mark.unit
class TestBrowserFingerprinting:
    """Test browser fingerprinting and anti-detection features"""
    
    def test_fingerprint_generation(self):
        """Test browser fingerprint generation"""
        config = BrowserConfig(user_agent="Test Agent")
        fingerprint = config.get_fingerprint()
        
        assert isinstance(fingerprint, str)
        assert len(fingerprint) > 10  # Should be reasonably long
        
        # Same config should generate same fingerprint
        fingerprint2 = config.get_fingerprint()
        assert fingerprint == fingerprint2
    
    def test_anti_detection_features(self):
        """Test anti-detection features in stealth config"""
        stealth_config = get_stealth_browser_config()
        playwright_config = stealth_config.to_playwright_config()
        
        # Should disable various detection vectors
        assert stealth_config.disable_blink_features is True
        assert stealth_config.stealth_mode is True
        
        # Should have randomized browser hints
        headers = playwright_config.get('extra_http_headers', {})
        assert 'sec-ch-ua' in headers or 'Sec-Ch-Ua' in headers
    
    def test_consistent_fingerprint_across_sessions(self):
        """Test fingerprint consistency across browser sessions"""
        # Same configuration should produce same fingerprint
        config_params = {
            'user_agent': "Consistent Agent",
            'viewport_width': 1366,
            'viewport_height': 768,
            'locale': 'vi-VN'
        }
        
        config1 = BrowserConfig(**config_params)
        config2 = BrowserConfig(**config_params)
        
        assert config1.get_fingerprint() == config2.get_fingerprint()
    
    def test_timezone_handling(self):
        """Test timezone configuration for fingerprinting"""
        config = BrowserConfig(timezone='America/New_York')
        playwright_config = config.to_playwright_config()
        
        assert playwright_config['timezone_id'] == 'America/New_York'
    
    def test_geolocation_spoofing(self):
        """Test geolocation configuration"""
        config = BrowserConfig(
            geolocation={'latitude': 21.0285, 'longitude': 105.8542}  # Hanoi
        )
        playwright_config = config.to_playwright_config()
        
        assert 'geolocation' in playwright_config
        assert playwright_config['geolocation']['latitude'] == 21.0285
        assert playwright_config['geolocation']['longitude'] == 105.8542


@pytest.mark.integration
class TestBrowserConfigIntegration:
    """Integration tests for browser configuration"""
    
    def test_playwright_integration_compatibility(self):
        """Test configuration is compatible with Playwright"""
        config = get_default_browser_config()
        playwright_config = config.to_playwright_config()
        
        # Check all required Playwright fields are present
        required_fields = ['user_agent', 'viewport', 'locale', 'timezone_id']
        for field in required_fields:
            assert field in playwright_config
        
        # Verify viewport format
        viewport = playwright_config['viewport']
        assert 'width' in viewport and 'height' in viewport
        assert isinstance(viewport['width'], int)
        assert isinstance(viewport['height'], int)
    
    def test_selenium_integration_compatibility(self):
        """Test configuration is compatible with Selenium"""
        config = get_default_browser_config()
        selenium_config = config.to_selenium_config()
        
        # Check required Selenium fields
        assert 'user_agent' in selenium_config
        assert 'headless' in selenium_config
        assert 'window_size' in selenium_config
        
        # Verify window size format
        window_size = selenium_config['window_size']
        assert isinstance(window_size, tuple)
        assert len(window_size) == 2
    
    def test_config_persistence_and_restoration(self):
        """Test configuration can be serialized and restored"""
        original_config = BrowserConfig(
            user_agent="Persistent Agent",
            viewport_width=1920,
            viewport_height=1080,
            extra_headers={'X-Session': 'test123'}
        )
        
        # Serialize to dict
        serialized = original_config.__dict__.copy()
        
        # Restore from dict
        restored_config = BrowserConfig(**serialized)
        
        # Should be identical
        assert restored_config.user_agent == original_config.user_agent
        assert restored_config.viewport_width == original_config.viewport_width
        assert restored_config.extra_headers == original_config.extra_headers
    
    def test_multi_session_configuration(self):
        """Test configuration for multiple concurrent sessions"""
        # Create configs for multiple sessions
        session_configs = []
        for i in range(5):
            config = get_stealth_browser_config()
            config.session_id = f"session_{i}"
            session_configs.append(config)
        
        # Each should have unique fingerprint
        fingerprints = [config.get_fingerprint() for config in session_configs]
        assert len(set(fingerprints)) == len(session_configs)
        
        # But all should be valid
        for config in session_configs:
            validate_browser_config(config)


@pytest.mark.unit
class TestBrowserConfigEdgeCases:
    """Test edge cases and error scenarios"""
    
    def test_empty_extra_headers(self):
        """Test handling of empty extra headers"""
        config = BrowserConfig(extra_headers={})
        playwright_config = config.to_playwright_config()
        
        assert 'extra_http_headers' in playwright_config
        assert isinstance(playwright_config['extra_http_headers'], dict)
    
    def test_none_values_handling(self):
        """Test handling of None values in configuration"""
        with pytest.raises((ValueError, TypeError)):
            BrowserConfig(user_agent=None)
        
        with pytest.raises((ValueError, TypeError)):
            BrowserConfig(locale=None)
    
    def test_extreme_viewport_dimensions(self):
        """Test handling of extreme viewport dimensions"""
        # Very small viewport
        small_config = BrowserConfig(viewport_width=100, viewport_height=100)
        validate_browser_config(small_config)  # Should work but might warn
        
        # Very large viewport
        large_config = BrowserConfig(viewport_width=4000, viewport_height=3000)
        validate_browser_config(large_config)  # Should work but might warn
    
    def test_special_characters_in_user_agent(self):
        """Test handling of special characters in user agent"""
        # Should handle reasonable special characters
        config = BrowserConfig(user_agent="Mozilla/5.0 (Test; Special-Chars_123)")
        validate_browser_config(config)
        
        # Should reject invalid characters
        with pytest.raises(ValueError):
            BrowserConfig(user_agent="Invalid\nUser\tAgent")
    
    def test_config_immutability_simulation(self):
        """Test configuration behaves as if immutable"""
        config = BrowserConfig(extra_headers={'X-Test': 'original'})
        
        # Get copy for modification
        modified_config = config.clone()
        modified_config.extra_headers['X-Test'] = 'modified'
        
        # Original should be unchanged
        assert config.extra_headers['X-Test'] == 'original'
        assert modified_config.extra_headers['X-Test'] == 'modified'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
