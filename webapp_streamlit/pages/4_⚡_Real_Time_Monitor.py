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
        # Read from environment variable for Docker, fallback for local dev
        self.api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
        if api_base_url:  # Allow overriding for specific instances
            self.api_base_url = api_base_url
    
    def check_api_health(self):
        """Kiểm tra xem server API có đang chạy không."""
        try:
            response = requests.get(f"{self.api_base_url}/api/health", timeout=5)
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
                    except:
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
    """Render Simple Line Chart showing Likes and Comments together."""
    
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
                # Convert to Unix timestamp (seconds since epoch)
                unix_timestamp = int(timestamp.timestamp())
            except:
                # Fallback to current time
                unix_timestamp = int(datetime.now().timestamp())
            
            # Get actual values
            like_count = max(0, interaction.get('like_count', 0))
            comment_count = max(0, interaction.get('comment_count', 0))
            
            likes_data.append({
                "time": unix_timestamp,
                "value": like_count
            })
            
            comments_data.append({
                "time": unix_timestamp,
                "value": comment_count
            })
    
    likes_json = json.dumps(likes_data)
    comments_json = json.dumps(comments_data)
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Facebook Engagement Chart</title>
        <script src="https://cdn.jsdelivr.net/npm/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
        <style>
            body {{ margin: 0; background: #0d1421; font-family: 'Segoe UI', sans-serif; }}
            .chart-container {{ width: 100%; height: 500px; position: relative; }}
            .chart-title {{ 
                position: absolute; top: 10px; left: 10px; z-index: 100;
                color: #f0f3fa; font-size: 18px; font-weight: 600;
            }}
            .legend {{ 
                position: absolute; top: 10px; right: 10px; z-index: 100;
                color: #f0f3fa; font-size: 14px;
            }}
            .legend-item {{ 
                display: inline-block; margin-left: 15px;
            }}
            .legend-color {{ 
                display: inline-block; width: 12px; height: 12px; 
                border-radius: 2px; margin-right: 5px; vertical-align: middle;
            }}
        </style>
    </head>
    <body>
        <div class="chart-container">
            <div class="chart-title">📈 Facebook Engagement - Live Data ({len(likes_data)} points)</div>
            <div class="legend">
                <span class="legend-item">
                    <span class="legend-color" style="background: #00ff88;"></span>
                    👍 Likes
                </span>
                <span class="legend-item">
                    <span class="legend-color" style="background: #ff6b6b;"></span>
                    💬 Comments
                </span>
            </div>
            <div id="{chart_id}" style="width: 100%; height: 100%;"></div>
        </div>
        
        <script>
            const chartContainer = document.getElementById('{chart_id}');
            
            // Simple Line Chart for Easy Understanding
            const chart = LightweightCharts.createChart(chartContainer, {{
                width: chartContainer.clientWidth,
                height: 500,
                layout: {{
                    background: {{ type: 'solid', color: 'transparent' }},
                    textColor: '#d1d4dc',
                    fontSize: 12,
                    fontFamily: 'Segoe UI, sans-serif'
                }},
                grid: {{
                    vertLines: {{ color: 'rgba(197, 203, 206, 0.1)' }},
                    horzLines: {{ color: 'rgba(197, 203, 206, 0.1)' }}
                }},
                crosshair: {{
                    mode: LightweightCharts.CrosshairMode.Normal,
                }},
                rightPriceScale: {{
                    borderColor: 'rgba(197, 203, 206, 0.5)',
                    visible: true,
                    title: 'Số lượng',
                }},
                timeScale: {{
                    borderColor: 'rgba(197, 203, 206, 0.5)',
                    timeVisible: true,
                    secondsVisible: false,
                }},
            }});
            
            // Likes Line Series (Green) - đúng theo TradingView docs
            const likesSeries = chart.addSeries(LightweightCharts.LineSeries);
            likesSeries.applyOptions({{
                color: '#00ff88',
                lineWidth: 3,
                priceLineVisible: false,
                lastValueVisible: true,
            }});
            
            // Comments Line Series (Red) - đúng theo TradingView docs  
            const commentsSeries = chart.addSeries(LightweightCharts.LineSeries);
            commentsSeries.applyOptions({{
                color: '#ff6b6b', 
                lineWidth: 3,
                priceLineVisible: false,
                lastValueVisible: true,
            }});
            
            // Load real data - TradingView format validation
            const likesData = {likes_json};
            const commentsData = {comments_json};
            
            // Debug: Log data format for validation
            console.log('📊 Chart Data Debug:');
            console.log('Likes data sample:', likesData.slice(0, 2));
            console.log('Comments data sample:', commentsData.slice(0, 2));
            console.log('Total data points:', likesData.length);
            
            // Set data using TradingView API with error handling
            try {{
                likesSeries.setData(likesData);
                commentsSeries.setData(commentsData);
                console.log('✅ Chart data loaded successfully');
            }} catch (error) {{
                console.error('❌ Error loading chart data:', error);
                console.log('Data format issue - check timestamp format');
            }}
            
            // Auto-resize
            new ResizeObserver(entries => {{
                if (entries.length === 0 || entries[0].target !== chartContainer) return;
                const newRect = entries[0].contentRect;
                chart.applyOptions({{ width: newRect.width }});
            }}).observe(chartContainer);
            
            // Auto-fit content
            setTimeout(() => {{
                chart.timeScale().fitContent();
                chart.timeScale().applyOptions({{
                    timeVisible: true,
                    secondsVisible: false,
                }});
            }}, 100);
            
            // Add hover tooltips
            chart.subscribeCrosshairMove((param) => {{
                if (param && param.time) {{
                    // Show detailed info on hover
                    const likesData = param.seriesData.get(likesSeries);
                    const commentsData = param.seriesData.get(commentsSeries);
                    
                    if (likesData && commentsData) {{
                        // Could add custom tooltip here
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    components.html(html_template, height=650)

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
