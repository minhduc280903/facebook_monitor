#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Reaction Selectors với HTML thực tế
"""

import sys
import io

# Force UTF-8 encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from lxml import html
import re

# HTML thực tế từ user
test_html = '''
<div aria-label="Thích: 2 người" class="x1i10hfl x1qjc9v5..." role="button" tabindex="0">
    <img height="18" role="presentation" src="data:image/svg+xml..." width="18">
</div>

<div aria-label="Yêu thích: 1 người" class="x1i10hfl x1qjc9v5..." role="button" tabindex="0">
    <img height="18" role="presentation" src="data:image/svg+xml..." width="18">
</div>

<div class="x1i10hfl xjbqb8w..." role="button" tabindex="0">
    <div class="x9f619 x1ja2u2z...">
        <div class="...">Tất cả cảm xúc:</div>
        <span aria-hidden="true" class="x1rg5ohu xxymvpz x1fiuzfb"></span>
    </div>
    <span aria-hidden="true" class="x1kmio9f x6ikm8r...">
        <span><span class="xt0b8zv x135b78x">3</span></span>
    </span>
</div>
'''

# Parse HTML
tree = html.fromstring(test_html)

print("=" * 60)
print("TESTING REACTION SELECTORS")
print("=" * 60)

# Test XPath từ selectors.json
xpaths = [
    {
        "priority": 1,
        "desc": "aria-label='Thích: X người'",
        "path": ".//div[@aria-label[contains(., 'Thích:')]]"
    },
    {
        "priority": 2,
        "desc": "aria-label='Like: X people'",
        "path": ".//div[@aria-label[contains(., 'Like:')]]"
    },
    {
        "priority": 3,
        "desc": "'Tất cả cảm xúc:' following span",
        "path": ".//div[contains(text(), 'Tất cả cảm xúc:')]/following-sibling::span//span[string-length(text()) > 0 and string-length(text()) < 10]"
    }
]

for xpath_config in xpaths:
    print(f"\n{'='*60}")
    print(f"Priority {xpath_config['priority']}: {xpath_config['desc']}")
    print(f"XPath: {xpath_config['path']}")
    
    try:
        elements = tree.xpath(xpath_config['path'])
        print(f"✅ Found {len(elements)} elements")
        
        for idx, elem in enumerate(elements):
            # Try text_content
            text = elem.text_content() if hasattr(elem, 'text_content') else elem.text
            aria_label = elem.get('aria-label')
            
            print(f"   Element {idx}:")
            if text:
                print(f"     - text_content: '{text.strip()[:100]}'")
            if aria_label:
                print(f"     - aria-label: '{aria_label}'")
                
                # Extract count
                match = re.search(r'(\d+)\s*người', aria_label)
                if match:
                    count = int(match.group(1))
                    print(f"     - 🎯 EXTRACTED COUNT: {count}")
                    
    except Exception as e:
        print(f"❌ Error: {e}")

print("\n" + "=" * 60)
print("CONCLUSION:")
print("=" * 60)

# Test the actual extraction logic
def extract_count_from_text(text: str) -> int:
    """Giống logic trong content_extractor.py"""
    if not text:
        return 0
    
    text_lower = text.lower().strip()
    
    patterns = [
        r'all\s+reactions?:\s*(\d+[\.,]?\d*)([km]?)',
        r'tất cả cảm xúc:\s*(\d+[\.,]?\d*)([km]?)',
        r'(\d+[\.,]?\d*)([km]?)\s*cảm\s*xúc',
        r'(\d+[\.,]?\d*)([km]?)\s*reactions?',
        r'(\d+[\.,]?\d*)([km]?)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            value_str, suffix = match.groups()
            value_str = value_str.replace(',', '.')
            count = float(value_str)
            
            multipliers = {'k': 1_000, 'm': 1_000_000}
            count *= multipliers.get(suffix, 1)
            
            return int(count)
    
    return 0

# Test aria-label extraction - CHỈ TỔNG REACTIONS
test_aria_labels = [
    ("All reactions: 3", 3, "✅ English total"),
    ("Tất cả cảm xúc: 5", 5, "✅ Vietnamese total"),
    ("All reactions: 1.2K", 1200, "✅ English with K suffix"),
    ("Tất cả cảm xúc: 2.5M", 2500000, "✅ Vietnamese with M suffix"),
    ("3 reactions", 3, "✅ Reverse English"),
    ("5 cảm xúc", 5, "✅ Reverse Vietnamese"),
    # Các pattern này sẽ KHÔNG match vì đã loại bỏ
    ("Thích: 2 người", 2, "❌ SHOULD NOT MATCH - Individual Like"),
    ("Like: 14 people", 14, "❌ SHOULD NOT MATCH - Individual Like"),
]

print("\nTesting count extraction (CHỈ TỔNG REACTIONS):")
print("="*60)
for label, expected, description in test_aria_labels:
    count = extract_count_from_text(label)
    status = "✅ PASS" if count == expected else f"❌ FAIL (expected {expected}, got {count})"
    print(f"  {status} | '{label}' -> {count} | {description}")

