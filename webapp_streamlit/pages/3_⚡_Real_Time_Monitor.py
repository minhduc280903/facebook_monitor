#!/usr/bin/env python3
"""
Real-time Monitor Page for Facebook Post Monitor Dashboard - Phase 3.1
"""

import streamlit as st
import time
import requests
from datetime import datetime, timedelta
import logging
import json
import os
import math
import random
from typing import Optional
import streamlit.components.v1 as components

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="Real-time Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0c0c0c 0%, #1a1a2e 100%);
    }
</style>
""", unsafe_allow_html=True)


class WebSocketManager:
    """Quản lý kết nối API (đơn giản hóa cho ví dụ này)."""
    
    def __init__(self, api_base_url: Optional[str] = None):
        # FIXED: Use container name for backend calls in Docker environment
        self.api_base_url = os.getenv("API_BASE_URL", "http://facebook-monitor-api:8000")
        if api_base_url:  # Allow overriding for specific instances
            self.api_base_url = api_base_url
    
    def check_api_health(self):
        """Kiểm tra xem server API có đang chạy không."""
        try:
            response = requests.get(f"{self.api_base_url}/health", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False
    
    def get_posts_list(self):
        """Lấy danh sách các bài post từ REST API với nội dung chi tiết."""
        try:
            # Add timestamp to prevent caching
            timestamp = int(datetime.now().timestamp())
            response = requests.get(
                f"{self.api_base_url}/api/posts?limit=20&_t={timestamp}", 
                timeout=10,
                headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
            )
            if response.status_code == 200:
                posts = response.json().get("posts", [])
                
                # Enrich each post with detailed content
                enriched_posts = []
                for post in posts:
                    try:
                        # Get detailed post info
                        _, post_info = self.get_post_interactions(post['post_signature'])
                        if post_info:
                            # Merge basic info with detailed info
                            enriched_post = {**post, **post_info}
                            enriched_posts.append(enriched_post)
                        else:
                            enriched_posts.append(post)
                    except (KeyError, TypeError, requests.RequestException) as e:
                        logger.debug(f"Failed to enrich post {post.get('post_signature', 'unknown')}: {e}")
                        # If detailed fetch fails, use basic info
                        enriched_posts.append(post)
                
                return enriched_posts
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách bài post: {e}")
        return []
    
    def get_post_interactions(self, post_signature: str):
        """Lấy lịch sử tương tác cho một bài post."""
        try:
            # Add timestamp to prevent caching
            timestamp = int(datetime.now().timestamp())
            response = requests.get(
                f"{self.api_base_url}/api/posts/{post_signature}/interactions?limit=100&_t={timestamp}",
                timeout=10,
                headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("interactions", []), data.get("post_info")
        except Exception as e:
            logger.error(f"Lỗi khi lấy dữ liệu tương tác: {e}")
        return [], None

def render_simple_engagement_chart(interactions_data: list, chart_id: str = "engagement-chart"):
    """Render Simple Line Chart showing Likes and Comments together using TradingView Lightweight Charts."""
    
    # Prepare data for simple line chart
    likes_data = []
    comments_data = []
    
    if not interactions_data:
        # No data available - show empty chart with current timestamp
        current_timestamp = int(datetime.now().timestamp())
        likes_data.append({
            "time": current_timestamp,
            "value": 0
        })
        comments_data.append({
            "time": current_timestamp, 
            "value": 0
        })
    else:
        # Use real interaction data - Always show real data
        sorted_data = sorted(interactions_data, key=lambda x: x['log_timestamp_utc'])
        
        # Track previous values to ensure monotonic or stable data
        prev_likes = 0
        prev_comments = 0
        
        for interaction in sorted_data:
            # Parse timestamp properly
            timestamp_str = interaction['log_timestamp_utc']
            if 'Z' in timestamp_str:
                timestamp_str = timestamp_str.replace('Z', '')
            if '+' in timestamp_str:
                timestamp_str = timestamp_str.split('+')[0]
            
            try:
                # Parse timestamp and convert to Unix timestamp for LightweightCharts
                timestamp = datetime.fromisoformat(timestamp_str)
                # Convert to Unix timestamp (seconds since epoch) - MUST be integer
                unix_timestamp = int(timestamp.timestamp())
            except Exception as e:
                # Fallback to current time
                logger.warning(f"Timestamp parse error: {e}, using current time")
                unix_timestamp = int(datetime.now().timestamp())
            
            # Get actual values - ensure non-negative and monotonic growth
            like_count = max(prev_likes, interaction.get('like_count', 0) or 0)
            comment_count = max(prev_comments, interaction.get('comment_count', 0) or 0)
            
            # Only add if value changed or first point
            if not likes_data or like_count != prev_likes:
                likes_data.append({
                    "time": unix_timestamp,
                    "value": like_count
                })
                prev_likes = like_count
            
            if not comments_data or comment_count != prev_comments:
                comments_data.append({
                    "time": unix_timestamp,
                    "value": comment_count
                })
                prev_comments = comment_count
    
    # Ensure we have at least 2 data points for proper chart display
    if len(likes_data) == 1:
        first_point = likes_data[0]
        likes_data.append({
            "time": first_point["time"] + 3600,  # Add 1 hour
            "value": first_point["value"]
        })
    
    if len(comments_data) == 1:
        first_point = comments_data[0]
        comments_data.append({
            "time": first_point["time"] + 3600,  # Add 1 hour
            "value": first_point["value"]
        })
    
    likes_json = json.dumps(likes_data)
    comments_json = json.dumps(comments_data)
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Facebook Engagement Chart - TradingView Lightweight Charts</title>
        <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ 
                margin: 0; 
                background: #0d1421; 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; 
                overflow: hidden;
            }}
            .chart-container {{ 
                width: 100%; 
                height: 550px; 
                position: relative; 
                padding: 10px;
            }}
            .chart-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 15px;
                background: rgba(13, 20, 33, 0.8);
                border-radius: 8px 8px 0 0;
                border-bottom: 2px solid #1a2332;
            }}
            .chart-title {{ 
                color: #f0f3fa; 
                font-size: 18px; 
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .chart-badge {{
                background: #00ff8844;
                color: #00ff88;
                padding: 3px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 500;
            }}
            .legend {{ 
                display: flex;
                gap: 20px;
                color: #f0f3fa; 
                font-size: 14px;
            }}
            .legend-item {{ 
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 4px 10px;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 6px;
                transition: background 0.2s;
            }}
            .legend-item:hover {{
                background: rgba(255, 255, 255, 0.1);
            }}
            .legend-color {{ 
                width: 14px; 
                height: 14px; 
                border-radius: 3px;
            }}
            #chart-wrapper {{
                background: #0d1421;
                border-radius: 0 0 8px 8px;
                overflow: hidden;
            }}
            #{chart_id} {{ 
                width: 100%; 
                height: 470px;
            }}
            .status-indicator {{
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #00ff88;
                animation: pulse 2s infinite;
            }}
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.5; }}
            }}
        </style>
    </head>
    <body>
        <div class="chart-container">
            <div class="chart-header">
                <div class="chart-title">
                    <span class="status-indicator"></span>
                    <span>📈 Facebook Engagement - Live Trading View</span>
                    <span class="chart-badge">{len(likes_data)} data points</span>
                </div>
                <div class="legend">
                    <div class="legend-item">
                        <span class="legend-color" style="background: #00ff88;"></span>
                        <span>👍 Likes</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color" style="background: #ff6b6b;"></span>
                        <span>💬 Comments</span>
                    </div>
                </div>
            </div>
            <div id="chart-wrapper">
                <div id="{chart_id}"></div>
            </div>
        </div>
        
        <script>
            // ============================================
            // TradingView Lightweight Charts™ Implementation
            // Using official API from: https://github.com/tradingview/lightweight-charts
            // ============================================
            
            const chartContainer = document.getElementById('{chart_id}');
            
            // PHASE 1: Initialize Chart with Professional Trading Interface
            const chart = LightweightCharts.createChart(chartContainer, {{
                width: chartContainer.clientWidth,
                height: 470,
                layout: {{
                    background: {{ type: 'solid', color: '#0d1421' }},
                    textColor: '#d1d4dc',
                    fontSize: 12,
                    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
                }},
                grid: {{
                    vertLines: {{ 
                        color: 'rgba(42, 46, 57, 0.5)',
                        style: 1,  // Dashed
                        visible: true
                    }},
                    horzLines: {{ 
                        color: 'rgba(42, 46, 57, 0.5)',
                        style: 1,  // Dashed
                        visible: true
                    }}
                }},
                crosshair: {{
                    mode: LightweightCharts.CrosshairMode.Normal,
                    vertLine: {{
                        width: 1,
                        color: 'rgba(224, 227, 235, 0.5)',
                        style: 0,  // Solid
                        labelBackgroundColor: '#131722'
                    }},
                    horzLine: {{
                        width: 1,
                        color: 'rgba(224, 227, 235, 0.5)',
                        style: 0,  // Solid
                        labelBackgroundColor: '#131722'
                    }}
                }},
                rightPriceScale: {{
                    borderColor: 'rgba(197, 203, 206, 0.3)',
                    visible: true,
                    scaleMargins: {{
                        top: 0.1,
                        bottom: 0.1
                    }},
                    borderVisible: true
                }},
                timeScale: {{
                    borderColor: 'rgba(197, 203, 206, 0.3)',
                    timeVisible: true,
                    secondsVisible: false,
                    rightOffset: 12,
                    barSpacing: 3,
                    fixLeftEdge: true,
                    fixRightEdge: true,
                    lockVisibleTimeRangeOnResize: true,
                    borderVisible: true
                }},
                handleScroll: {{
                    mouseWheel: true,
                    pressedMouseMove: true,
                    horzTouchDrag: true,
                    vertTouchDrag: true
                }},
                handleScale: {{
                    axisPressedMouseMove: true,
                    mouseWheel: true,
                    pinch: true
                }}
            }});
            
            // PHASE 2: Add Likes Series (Green) - Using CORRECT API from official docs
            const likesSeries = chart.addSeries(LightweightCharts.LineSeries, {{
                color: '#00ff88',
                lineWidth: 2,
                lineStyle: 0,  // Solid
                lineType: 0,   // Simple line
                crosshairMarkerVisible: true,
                crosshairMarkerRadius: 6,
                crosshairMarkerBorderColor: '#00ff88',
                crosshairMarkerBackgroundColor: '#00ff88',
                lastValueVisible: true,
                priceLineVisible: true,
                priceLineWidth: 1,
                priceLineColor: '#00ff88',
                priceLineStyle: 2,  // Dashed
                title: 'Likes',
                priceFormat: {{
                    type: 'volume',  // No decimals for counts
                }}
            }});
            
            // PHASE 3: Add Comments Series (Red) - Using CORRECT API from official docs  
            const commentsSeries = chart.addSeries(LightweightCharts.LineSeries, {{
                color: '#ff6b6b', 
                lineWidth: 2,
                lineStyle: 0,  // Solid
                lineType: 0,   // Simple line
                crosshairMarkerVisible: true,
                crosshairMarkerRadius: 6,
                crosshairMarkerBorderColor: '#ff6b6b',
                crosshairMarkerBackgroundColor: '#ff6b6b',
                lastValueVisible: true,
                priceLineVisible: true,
                priceLineWidth: 1,
                priceLineColor: '#ff6b6b',
                priceLineStyle: 2,  // Dashed
                title: 'Comments',
                priceFormat: {{
                    type: 'volume',  // No decimals for counts
                }}
            }});
            
            // PHASE 4: Load Real Data with Validation
            const likesData = {likes_json};
            const commentsData = {comments_json};
            
            // Debug: Comprehensive data validation
            console.log('========================================');
            console.log('📊 TradingView Lightweight Charts Data Loading');
            console.log('========================================');
            console.log('Likes data points:', likesData.length);
            console.log('Comments data points:', commentsData.length);
            console.log('First like:', likesData[0]);
            console.log('First comment:', commentsData[0]);
            
            // Data format validation
            function validateData(data, name) {{
                if (!Array.isArray(data) || data.length === 0) {{
                    console.error(`❌ ${{name}}: Empty or invalid array`);
                    return false;
                }}
                
                // Check first point format
                const first = data[0];
                if (typeof first.time !== 'number') {{
                    console.error(`❌ ${{name}}: Time must be Unix timestamp (number), got:`, typeof first.time);
                    return false;
                }}
                if (typeof first.value !== 'number') {{
                    console.error(`❌ ${{name}}: Value must be number, got:`, typeof first.value);
                    return false;
                }}
                
                // Check time ordering
                for (let i = 1; i < data.length; i++) {{
                    if (data[i].time <= data[i-1].time) {{
                        console.warn(`⚠️ ${{name}}: Time not strictly increasing at index ${{i}}`);
                    }}
                }}
                
                console.log(`✅ ${{name}}: Data format valid`);
                return true;
            }}
            
            // PHASE 5: Set Data with Error Handling
            try {{
                if (validateData(likesData, 'Likes')) {{
                    likesSeries.setData(likesData);
                    console.log('✅ Likes series loaded successfully');
                }}
                
                if (validateData(commentsData, 'Comments')) {{
                    commentsSeries.setData(commentsData);
                    console.log('✅ Comments series loaded successfully');
                }}
                
                console.log('========================================');
                console.log('✅ Chart initialized successfully!');
                console.log('========================================');
                
            }} catch (error) {{
                console.error('========================================');
                console.error('❌ CRITICAL ERROR loading chart data:');
                console.error(error.message);
                console.error(error.stack);
                console.error('========================================');
            }}
            
            // PHASE 6: Responsive Chart
            function resizeChart() {{
                const width = chartContainer.clientWidth;
                chart.applyOptions({{ width: width }});
            }}
            
            // Use ResizeObserver for smooth resizing
            const resizeObserver = new ResizeObserver(entries => {{
                if (entries.length === 0 || entries[0].target !== chartContainer) return;
                resizeChart();
            }});
            resizeObserver.observe(chartContainer);
            
            // Initial window resize handler
            window.addEventListener('resize', resizeChart);
            
            // PHASE 7: Auto-fit Content & Time Scale Settings
            setTimeout(() => {{
                chart.timeScale().fitContent();
                console.log('✅ Chart content fitted to view');
            }}, 150);
            
            // PHASE 8: Advanced Tooltip on Crosshair Move
            const tooltip = document.createElement('div');
            tooltip.style.cssText = `
                position: absolute;
                display: none;
                padding: 8px 12px;
                background: rgba(13, 20, 33, 0.95);
                border: 1px solid #2a2e39;
                border-radius: 6px;
                color: #f0f3fa;
                font-size: 13px;
                pointer-events: none;
                z-index: 1000;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            `;
            chartContainer.appendChild(tooltip);
            
            chart.subscribeCrosshairMove((param) => {{
                if (!param || !param.point || !param.time) {{
                    tooltip.style.display = 'none';
                    return;
                }}
                
                const likesValue = param.seriesData.get(likesSeries);
                const commentsValue = param.seriesData.get(commentsSeries);
                
                if (likesValue && commentsValue) {{
                    const date = new Date(param.time * 1000);
                    const dateStr = date.toLocaleString('vi-VN', {{
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                    }});
                    
                    tooltip.innerHTML = `
                        <div style="font-weight: 600; margin-bottom: 6px; color: #00bcd4;">${{dateStr}}</div>
                        <div style="display: flex; gap: 15px;">
                            <div>
                                <span style="color: #00ff88;">👍 Likes:</span>
                                <strong style="margin-left: 5px;">${{likesValue.value.toFixed(0)}}</strong>
                            </div>
                            <div>
                                <span style="color: #ff6b6b;">💬 Comments:</span>
                                <strong style="margin-left: 5px;">${{commentsValue.value.toFixed(0)}}</strong>
                            </div>
                        </div>
                    `;
                    
                    const x = param.point.x;
                    const y = param.point.y;
                    tooltip.style.left = x + 15 + 'px';
                    tooltip.style.top = y - 50 + 'px';
                    tooltip.style.display = 'block';
                }} else {{
                    tooltip.style.display = 'none';
                }}
            }});
            
            // PHASE 9: Cleanup on unload
            window.addEventListener('beforeunload', () => {{
                chart.remove();
                resizeObserver.disconnect();
            }});
        </script>
    </body>
    </html>
    """
    
    components.html(html_template, height=620)

def main():
    """Hàm chính của dashboard, kết nối với dữ liệu thật."""
    st.title("⚡ Real-time Facebook Monitor")
    st.markdown("*Sử dụng Lightweight Charts™ để hiển thị*")

    ws_manager = WebSocketManager()
    api_healthy = ws_manager.check_api_health()

    if not api_healthy:
        st.error("⚠️ FastAPI server không chạy. Hãy chắc chắn server API đang hoạt động.")
        return

    # Auto-refresh controls
    st.markdown("---")
    
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    
    with col1:
        st.markdown("## 📈 Live Post Monitoring")
    
    with col2:
        if st.button("🔄 Manual Refresh"):
            # Clear cache and rerun
            st.cache_data.clear()
            st.rerun()
    
    with col3:
        auto_refresh = st.checkbox("⚡ Auto Refresh", value=False, help="Tự động refresh mỗi 30 giây")
    
    with col4:
        if auto_refresh:
            refresh_interval = st.select_slider(
                "Interval", 
                options=[10, 30, 60, 120], 
                value=30,
                format_func=lambda x: f"{x}s"
            )
            st.success("🟢 LIVE")
        else:
            refresh_interval = 30
            st.info("⚪ Manual")
    
    posts = ws_manager.get_posts_list()
    
    if posts:
        st.info(f"📊 Tìm thấy {len(posts)} posts đang được theo dõi")
        
        # Hiển thị dropdown với thông tin có nghĩa
        post_options = {}
        for i, post in enumerate(posts):
            # Get enriched content
            post_content = post.get('post_content', '').strip()
            author_name = post.get('author_name', 'Unknown Author').strip()
            
            # Get latest interaction stats if available
            latest_likes = 0
            latest_comments = 0
            
            # Try to get current stats (skip to speed up loading)
            # Latest stats will be shown when user selects the post
            latest_likes = "?"
            latest_comments = "?"
            
            # Create meaningful display name
            if post_content and len(post_content) > 10:
                content_preview = post_content[:40] + "..." if len(post_content) > 40 else post_content
                display_name = f"📝 {author_name}: \"{content_preview}\""
            else:
                # Fallback to author and basic info
                display_name = f"📄 {author_name}: Post {post['post_signature'][-8:]}"
            
            # Add engagement stats
            display_name += f" ({latest_likes} likes, {latest_comments} comments)"
            
            post_options[display_name] = post['post_signature']
        
        selected_post_display = st.selectbox(
            "Chọn một bài post để theo dõi:",
            options=list(post_options.keys()),
            key="post_selector"
        )
        
        selected_post_signature = post_options[selected_post_display]

        interactions, post_info = ws_manager.get_post_interactions(selected_post_signature)
        
        # Show last update time
        current_time = datetime.now().strftime("%H:%M:%S")
        st.caption(f"📅 Last updated: {current_time}")
        
        if interactions and post_info:
            # Better title with post-specific info
            post_title = ""
            if post_info.get('post_text'):
                post_title = f"{post_info.get('post_text', '')[:60]}..."
            elif post_info.get('content'):
                post_title = f"{post_info.get('content', '')[:60]}..."
            elif post_info.get('message'):
                post_title = f"{post_info.get('message', '')[:60]}..."
            else:
                # Extract meaningful info from post_signature or timestamp
                post_sig = post_info.get('post_signature', '')
                post_title = f"Post ID: {post_sig[:20]}..." if post_sig else "Unknown Post"
                
            st.subheader(f"📊 Trading Analysis: {post_title}")
            
            # Chart info with latest data
            latest = interactions[0] if interactions else {}
            latest_timestamp = latest.get('log_timestamp_utc', 'N/A')
            st.info(f"📊 Hiển thị {len(interactions)} điểm dữ liệu thật từ Facebook")
            st.success(f"📈 Latest: {latest.get('like_count', 0)} likes, {latest.get('comment_count', 0)} comments at {latest_timestamp}")
            
            # Debug: Show sample of processed data for chart
            with st.expander("🔍 Debug: Chart Data Preview", expanded=False):
                st.json({
                    "sample_likes": interactions[0].get('like_count', 0) if interactions else 0,
                    "sample_comments": interactions[0].get('comment_count', 0) if interactions else 0,
                    "sample_timestamp": interactions[0].get('log_timestamp_utc', 'N/A') if interactions else 'N/A',
                    "total_data_points": len(interactions)
                })
            
            # Render Simple Line Chart
            render_simple_engagement_chart(interactions)
            # Hiển thị các số liệu mới nhất
            latest = interactions[0]
            metric_col1, metric_col2, metric_col3 = st.columns(3)
            with metric_col1:
                st.metric("Likes mới nhất", latest.get('like_count', 0))
            with metric_col2:
                st.metric("Comments mới nhất", latest.get('comment_count', 0))
            with metric_col3:
                total_engagement = latest.get('like_count', 0) + latest.get('comment_count', 0)
                st.metric("Tổng tương tác", total_engagement)

        else:
            if not interactions:
                st.warning("⚠️ Không tìm thấy interaction data")
            if not post_info:
                st.warning("⚠️ Không tìm thấy post info")
            st.info(f"Post signature: {selected_post_signature[:30]}...")
    
    else:
        st.warning("⚠️ Không có bài post nào đang được theo dõi trong cơ sở dữ liệu. Hãy dùng `manage_targets.py` để thêm.")

    # Auto-refresh logic
    if auto_refresh:
        st.markdown("---")
        # Progress bar countdown
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i in range(refresh_interval):
            progress = (i + 1) / refresh_interval
            progress_bar.progress(progress)
            remaining = refresh_interval - i - 1
            status_text.info(f"🔄 Next refresh in {remaining}s... (uncheck ⚡ Auto Refresh to stop)")
            time.sleep(1)
        
        # Clear cache and refresh
        st.cache_data.clear()
        st.rerun()

if __name__ == "__main__":
    main()
