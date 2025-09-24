#!/usr/bin/env python3
"""Debug để tìm TOTAL REACTIONS thay vì chỉ like count"""

import asyncio
import json
import os
import re
from playwright.async_api import async_playwright
from logging_config import get_logger

logger = get_logger(__name__)
ACCOUNT_USERNAME = "61576976470676"

async def debug_total_reactions():
    """Tìm selector cho TỔNG reactions thay vì chỉ like"""
    
    async with async_playwright() as p:
        sessions_base_dir = os.path.join(os.getcwd(), "sessions")
        user_data_dir = os.path.join(sessions_base_dir, ACCOUNT_USERNAME)
        
        browser_context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            slow_mo=100,
        )
        
        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
        
        # Navigate 
        target_url = "https://www.facebook.com/groups/nguyenquyetthang/"
        logger.info(f"🌐 Navigating to: {target_url}")
        
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            logger.info("✅ Navigation successful")
        except Exception as e:
            logger.warning(f"⚠️ Navigation timeout, continuing anyway: {e}")
        
        # Scroll to get posts - MORE AGGRESSIVE
        logger.info("🔄 Scrolling to load MORE posts...")
        for i in range(8):  # More scrolls to find post with 69 reactions
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(4)
            
            current_posts = await page.query_selector_all("div[role='feed'] div[aria-posinset]")
            logger.info(f"  Scroll #{i+1}: Found {len(current_posts)} posts")
        
        # Get posts
        post_elements = await page.query_selector_all("div[role='feed'] div[aria-posinset]")
        logger.info(f"✅ Found {len(post_elements)} posts for total reactions analysis")
        
        logger.info(f"\n{'='*80}")
        logger.info("🔍 TÌEM TOTAL REACTIONS SELECTOR (KHÔNG CHỈ LIKE)")
        logger.info(f"{'='*80}")
        
        # Test each post - CHECK MORE POSTS
        for post_idx, post_element in enumerate(post_elements[:8]):
            logger.info(f"\n📄 POST #{post_idx + 1}:")
            logger.info("-" * 60)
            
            # 1. Tìm tất cả text có chứa numbers và reaction keywords
            logger.info(f"\n🔍 1. TÌM TẤT CẢ TEXT CÓ NUMBERS + REACTION KEYWORDS:")
            all_elements = await post_element.query_selector_all("*")
            
            reaction_candidates = []
            
            for elem in all_elements[:100]:  # Check first 100 elements
                try:
                    text = await elem.text_content()
                    aria_label = await elem.get_attribute('aria-label')
                    
                    # Check both text and aria-label for total reaction patterns
                    for content, content_type in [(text, "text"), (aria_label, "aria-label")]:
                        if not content:
                            continue
                            
                        content_lower = content.lower()
                        
                        # Look for patterns indicating TOTAL reactions (not just likes)
                        if any(pattern in content_lower for pattern in [
                            'all reactions',      # "All reactions: 69"
                            'total reaction',     # "Total reactions: 69" 
                            'tất cả cảm xúc',    # Vietnamese
                            'reaction',           # General reaction
                            'cảm xúc'            # Vietnamese emotion
                        ]):
                            # Extract numbers
                            numbers = re.findall(r'\d+', content)
                            if numbers and len(content) < 200:  # Reasonable length
                                reaction_candidates.append({
                                    'content': content,
                                    'content_type': content_type,
                                    'numbers': numbers,
                                    'tag': await elem.evaluate('el => el.tagName'),
                                    'is_total': True
                                })
                                
                        # Also look for high numbers (like 69) even without keywords
                        elif any(num in content for num in ['69', '68', '70', '71', '67']):
                            numbers = re.findall(r'\d+', content)
                            if numbers and len(content) < 100:
                                reaction_candidates.append({
                                    'content': content,
                                    'content_type': content_type, 
                                    'numbers': numbers,
                                    'tag': await elem.evaluate('el => el.tagName'),
                                    'is_total': False
                                })
                        
                except Exception:
                    continue
            
            if reaction_candidates:
                logger.info(f"    🎯 Found {len(reaction_candidates)} total reaction candidates:")
                
                # Sort by priority: total reactions first, then high numbers
                reaction_candidates.sort(key=lambda x: (not x['is_total'], len(x['content'])))
                
                for idx, candidate in enumerate(reaction_candidates[:5]):
                    is_total_flag = "🏆 TOTAL" if candidate['is_total'] else "📊 HIGH#"
                    logger.info(f"      #{idx+1} [{is_total_flag}] Tag: {candidate['tag']} | {candidate['content_type']}")
                    logger.info(f"        Content: '{candidate['content']}'")
                    logger.info(f"        Numbers: {candidate['numbers']}")
                    
                    # If this looks like total reactions, highlight it
                    if candidate['is_total'] and any(int(num) > 60 for num in candidate['numbers']):
                        logger.info(f"        🎯🎯🎯 THIS LOOKS LIKE TOTAL REACTIONS!")
                        
            else:
                logger.info(f"    ❌ No total reaction candidates found")
            
            # 2. Specific search for "All reactions" pattern
            logger.info(f"\n🔍 2. SPECIFIC SEARCH FOR 'ALL REACTIONS' PATTERN:")
            
            patterns_to_try = [
                "div:has-text('All reactions')",
                "span:has-text('All reactions')", 
                "*:has-text('reactions')",
                "div[aria-label*='All reactions']",
                "span[aria-label*='All reactions']",
                "*[aria-label*='cảm xúc']"
            ]
            
            for pattern in patterns_to_try:
                try:
                    elements = await post_element.query_selector_all(pattern)
                    logger.info(f"    Pattern '{pattern}': {len(elements)} elements")
                    
                    for elem in elements[:2]:
                        text = await elem.text_content()
                        aria_label = await elem.get_attribute('aria-label')
                        
                        if text or aria_label:
                            logger.info(f"      Text: '{text}' | Aria: '{aria_label}'")
                            
                except Exception as e:
                    logger.info(f"    Pattern '{pattern}': Failed - {e}")
            
            # 3. SPECIAL FOCUS: "Xem ai đã bày tỏ cảm xúc" element
            logger.info(f"\n🔍 3. SPECIAL INSPECTION: 'CẢM XÚC' ELEMENT:")
            
            emotion_elements = await post_element.query_selector_all("*[aria-label*='cảm xúc']")
            for idx, elem in enumerate(emotion_elements):
                try:
                    text = await elem.text_content()
                    aria_label = await elem.get_attribute('aria-label')
                    tag = await elem.evaluate('el => el.tagName')
                    outer_html = await elem.evaluate('el => el.outerHTML')
                    
                    logger.info(f"    Element #{idx+1}: Tag={tag}")
                    logger.info(f"      Text: '{text}'")
                    logger.info(f"      Aria-label: '{aria_label}'")
                    logger.info(f"      HTML: {outer_html[:200]}...")
                    
                    # Check parent and siblings for numbers
                    try:
                        parent = await elem.evaluate('el => el.parentElement')
                        if parent:
                            parent_text = await elem.evaluate('el => el.parentElement.textContent')
                            logger.info(f"      Parent text: '{parent_text[:100] if parent_text else 'None'}...'")
                            
                            # Look for siblings with numbers
                            siblings = await elem.evaluate('''el => {
                                const parent = el.parentElement;
                                if (!parent) return [];
                                return Array.from(parent.children).map(child => child.textContent).filter(t => t && /\\d/.test(t));
                            }''')
                            
                            if siblings:
                                logger.info(f"      Siblings with numbers: {siblings[:3]}")
                                
                    except Exception:
                        pass
                        
                except Exception as e:
                    logger.info(f"    Element #{idx+1}: Error - {e}")
        
        await browser_context.close()

if __name__ == "__main__":
    asyncio.run(debug_total_reactions())
