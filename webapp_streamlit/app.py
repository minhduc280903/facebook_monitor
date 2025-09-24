#!/usr/bin/env python3
"""
Facebook Post Monitor - Phase 1 Complete Dashboard  
🎉 Advanced Forex Chart Engine với Mobile-Optimized Interface

Main Entry Point: System Overview với professional metrics và mobile support
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import logging
import sys
import os

# Add parent directory to Python path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from logging_config import get_simple_logger, setup_application_logging
except ImportError:
    def setup_application_logging():
        logging.basicConfig(level=logging.INFO)

try:
    import redis
except ImportError:
    redis = None

# Import database reader
try:
    from webapp_streamlit.core.db_reader import (
        get_system_overview, 
        get_top_viral_posts
    )
except ImportError:
    def get_system_overview():
        return {
            'tracking_posts': 0, 
            'total_interactions': 0,
            'today_interactions': 0,
            'today_new_posts': 0
        }
    
    def get_top_viral_posts(source_url=None, limit=10, apply_quality_filter=False):
        return pd.DataFrame()

# Import mobile optimization - Simple fallback
try:
    from components.mobile_styles import (
        inject_mobile_styles, 
        apply_mobile_layout_fixes,
        get_mobile_plotly_config,
        mobile_container
    )
except ImportError:
    # Simple fallbacks
    def inject_mobile_styles():
        pass
    def apply_mobile_layout_fixes():
        pass
    def get_mobile_plotly_config():
        return {}
    def mobile_container(func):
        return func

# Configure page - Mobile-optimized
st.set_page_config(
    page_title="Forex Monitor - Phase 1 Complete",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/your-repo/issues',
        'Report a bug': 'https://github.com/your-repo/issues',
        'About': """
        # Facebook Post Monitor - Phase 1 Complete
        Advanced Forex Chart Engine với Mobile Support
        
        **Features:**
        - Real-time forex-style charts
        - Advanced chart controls & export
        - Mobile-responsive design  
        - Professional trading interface
        
        **Phase 1 Complete:** Ready for production deployment!
        """
    }
)

# Initialize centralized logging for Streamlit app
setup_application_logging()

def format_number(num):
    """Format large numbers for display"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return str(num)

@st.cache_data(ttl=60)  # Cache for 1 minute
def load_system_overview():
    """Load system overview with caching"""
    return get_system_overview()

@st.cache_data(ttl=300)  # Cache for 5 minutes  
def load_top_viral_posts(limit=10, apply_quality_filter=False):
    """Load top viral posts with caching"""
    return get_top_viral_posts(limit=limit, apply_quality_filter=apply_quality_filter)

@st.cache_data(ttl=30)  # Cache for 30 seconds (frequent updates needed)
def load_broken_selectors():
    """Load broken selectors from Redis"""
    try:
        # Read Redis config from environment variables for Docker compatibility
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_client = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)
        
        # Get broken selectors SET
        broken_selectors = redis_client.smembers("broken_selectors")
        
        if not broken_selectors:
            return None
        
        # Get details for each broken selector
        alerts_data = []
        for selector in broken_selectors:
            details = redis_client.hgetall(f"broken_selector_details:{selector}")
            if details:
                alerts_data.append({
                    'selector': selector,
                    'first_failed': details.get('first_failed', 'Unknown'),
                    'failure_count': details.get('failure_count', '0'),
                    'last_trace_id': details.get('last_trace_id', 'N/A'),
                    'worker_id': details.get('worker_id', 'Unknown'),
                    'healed_at': details.get('healed_at'),
                    'status': 'HEALED' if details.get('healed_at') else 'BROKEN'
                })
            else:
                # Selector in set but no details
                alerts_data.append({
                    'selector': selector,
                    'first_failed': 'Unknown',
                    'failure_count': '1',
                    'last_trace_id': 'N/A',
                    'worker_id': 'Unknown',
                    'healed_at': None,
                    'status': 'BROKEN'
                })
        
        return alerts_data
        
    except Exception as e:
        st.error(f"❌ Cannot connect to Redis for alerts: {e}")
        return None

@mobile_container
def main():
    """Main dashboard application - Phase 1 Complete with Mobile Support"""
    
    # Inject mobile-optimized styles
    inject_mobile_styles()
    apply_mobile_layout_fixes()
    
    # Header with Phase 1 completion status
    st.title("📈 Forex Monitor Dashboard")
    st.markdown("**🎉 Phase 1 Complete** - Advanced Chart Engine với Mobile Support")
    
    # Phase 1 completion banner
    st.success("✅ **PHASE 1 HOÀN THÀNH 100%** - Professional Forex Trading Interface Ready for Production!")
    
    # ✅ IMPROVED UI: Thêm hướng dẫn sử dụng ngay từ đầu
    with st.expander("💡 Hướng dẫn sử dụng Dashboard", expanded=False):
        st.markdown("""
        **🏠 Trang System Overview (hiện tại):**
        - Xem tổng quan hệ thống: posts đang tracking, tương tác tổng cộng
        - Top viral posts từ tất cả nguồn
        - Biểu đồ phân tích nhanh theo nguồn
        
        **🎯 Target Analysis (Sidebar):**  
        - Phân tích chi tiết từng nhóm/trang Facebook
        - So sánh performance giữa các nguồn
        - Timeline posts và top authors
        
        **📊 Post Deep Dive (Sidebar):**
        - Phân tích chi tiết từng bài viết cụ thể
        - Biểu đồ timeline tương tác (likes, comments)
        - Tìm kiếm posts theo nội dung
        
        **🔍 Cách sử dụng:**
        1. Xem tổng quan ở trang này
        2. Click vào sidebar để chuyển trang phân tích
        3. Chọn posts từ bảng để xem chi tiết
        """)
    
    st.divider()
    
    # Add refresh button and quality filter toggle
    col1, col2, col3, col4 = st.columns([1, 1, 2, 2])
    with col1:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    with col2:
        # ✅ Quality filter toggle
        quality_filter = st.checkbox(
            "🧹 Quality Filter", 
            value=False,
            help="Lọc bỏ posts có nội dung chất lượng thấp (chỉ có 'Facebook', quá ngắn, v.v.)"
        )
    
    with col3:
        st.markdown(f"*Cập nhật lúc: {datetime.now().strftime('%H:%M:%S')}*")
        
    with col4:
        if quality_filter:
            st.info("🧹 Đang áp dụng quality filter")
        else:
            st.success("📋 Hiển thị tất cả posts")
    
    st.divider()
    
    # Load data
    try:
        overview_data = load_system_overview()
        viral_posts_df = load_top_viral_posts(limit=15, apply_quality_filter=quality_filter)
        
        if not overview_data:
            st.error("❌ Không thể kết nối đến database. Vui lòng kiểm tra database_manager.py")
            st.stop()
            
    except Exception as e:
        st.error(f"❌ Lỗi load dữ liệu: {e}")
        st.stop()
    
    # === SYSTEM OVERVIEW METRICS ===
    st.subheader("📊 System Overview")
    
    # Create metric cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="🎯 Posts Đang Tracking", 
            value=format_number(overview_data.get('tracking_posts', 0)),
            delta=f"+{overview_data.get('today_new_posts', 0)} hôm nay"
        )
    
    with col2:
        st.metric(
            label="💬 Tổng Interactions",
            value=format_number(overview_data.get('total_interactions', 0)),
            delta=f"+{format_number(overview_data.get('today_interactions', 0))} hôm nay"
        )
    
    with col3:
        st.metric(
            label="🔥 Hoạt động 24h",
            value=format_number(overview_data.get('last_24h_interactions', 0)),
            delta="interactions"
        )
    
    with col4:
        st.metric(
            label="📈 Posts Đã Hết hạn",
            value=format_number(overview_data.get('expired_posts', 0)),
            delta="completed tracking"
        )
    
    # === SYSTEM STATUS INDICATORS ===
    st.subheader("🚦 System Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Database status
        if overview_data.get('tracking_posts', 0) > 0:
            st.success("✅ Database: Connected & Active")
        else:
            st.warning("⚠️ Database: No active posts")
    
    with col2:
        # Data freshness
        if overview_data.get('today_interactions', 0) > 0:
            st.success("✅ Data Collection: Active")
        else:
            st.info("ℹ️ Data Collection: No new data today")
    
    with col3:
        # System health
        total_posts = overview_data.get('tracking_posts', 0) + overview_data.get('expired_posts', 0)
        if total_posts > 0:
            st.success(f"✅ System Health: {total_posts} total posts processed")
        else:
            st.error("❌ System Health: No posts found")
    
    st.divider()
    
    # === SCRAPING ALERTS (RESILIENT SYSTEM) ===
    st.subheader("🚨 Scraping Health Alerts")
    
    try:
        broken_selectors_data = load_broken_selectors()
        
        if broken_selectors_data:
            # Count active vs healed alerts
            active_alerts = [alert for alert in broken_selectors_data if alert['status'] == 'BROKEN']
            healed_alerts = [alert for alert in broken_selectors_data if alert['status'] == 'HEALED']
            
            # Alert summary
            alert_col1, alert_col2, alert_col3 = st.columns(3)
            
            with alert_col1:
                if active_alerts:
                    st.error(f"🚨 {len(active_alerts)} Active Alerts")
                else:
                    st.success("✅ No Active Alerts")
            
            with alert_col2:
                if healed_alerts:
                    st.info(f"🎉 {len(healed_alerts)} Self-Healed")
                else:
                    st.info("🔄 No Self-Healing Activity")
            
            with alert_col3:
                st.metric(
                    label="🔧 Total Monitored",
                    value=len(broken_selectors_data),
                    delta="selectors"
                )
            
            # Show active alerts in prominent way
            if active_alerts:
                st.error("⚠️ **CRITICAL ALERTS - Requires Attention:**")
                
                alerts_df = pd.DataFrame(active_alerts)
                st.dataframe(
                    alerts_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "selector": st.column_config.TextColumn("Broken Selector", width="large"),
                        "first_failed": st.column_config.TextColumn("First Failed", width="medium"),
                        "failure_count": st.column_config.NumberColumn("Failures", width="small"),
                        "last_trace_id": st.column_config.TextColumn("Last Trace ID", width="medium"),
                        "worker_id": st.column_config.TextColumn("Worker", width="medium")
                    }
                )
                
                st.markdown("""
                **🔧 Action Required:**
                1. Inspect the failing selectors above
                2. Use browser DevTools to find new working selectors
                3. Update `selectors.json` with new strategies
                4. System will auto-heal when new selectors work
                """)
            
            # Show healed alerts in collapsible section
            if healed_alerts:
                with st.expander(f"🎉 Recently Self-Healed Selectors ({len(healed_alerts)})", expanded=False):
                    healed_df = pd.DataFrame(healed_alerts)
                    st.dataframe(
                        healed_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "selector": st.column_config.TextColumn("Healed Selector", width="large"),
                            "healed_at": st.column_config.TextColumn("Healed At", width="medium"),
                            "failure_count": st.column_config.NumberColumn("Had Failures", width="small")
                        }
                    )
                    st.success("✅ These selectors have automatically recovered using fallback strategies!")
        else:
            # No alerts - system healthy
            st.success("✅ **All Scraping Selectors Healthy** - No alerts detected!")
            st.info("💡 The resilient scraping system is monitoring selector health automatically.")
            
            # Show some helpful info
            with st.expander("ℹ️ About Resilient Scraping System", expanded=False):
                st.markdown("""
                **🛡️ How the Resilient Scraping System Works:**
                
                1. **Multiple Strategies**: Each data field (like_count, comment_count, etc.) has multiple fallback strategies
                2. **Auto-Detection**: When a primary selector fails, the system automatically tries backup selectors
                3. **Self-Healing**: When a failed selector starts working again, alerts are automatically cleared
                4. **Real-time Monitoring**: This dashboard shows the health status in real-time
                
                **🔍 Monitored Fields:**
                - `like_count` - Like/reaction counts
                - `comment_count` - Comment counts  
                - `post_content` - Post text content
                - `author_name` - Author names
                - `post_url` - Post URLs
                - `post_containers` - Post container elements
                
                **🚨 When Alerts Appear:**
                - A required field fails ALL its fallback strategies
                - Manual intervention needed to add new working selectors
                - System continues working with other fields
                """)
    
    except Exception as e:
        st.error(f"❌ Error loading scraping alerts: {e}")
        st.info("💡 Make sure Redis is running and accessible for alert monitoring.")
    
    st.divider()
    
    # === TOP VIRAL POSTS ===
    st.subheader("🔥 Top Viral Posts (Toàn hệ thống)")
    
    if viral_posts_df.empty:
        if quality_filter:
            st.warning("⚠️ Không có posts nào pass quality filter. Thử tắt Quality Filter để xem tất cả posts.")
            st.info("💡 Quality filter loại bỏ posts có nội dung quá ngắn hoặc chỉ chứa từ khóa như 'Facebook'")
        else:
            st.warning("⚠️ Không có dữ liệu posts trong database. Hệ thống có thể chưa thu thập được dữ liệu.")
    else:
        # Add selection functionality
        st.markdown("*Click vào một bài viết để xem chi tiết trong trang **Post Deep Dive***")
        
        # Format the dataframe for display
        display_df = viral_posts_df.copy()
        
        # Safely convert numeric columns
        try:
            display_df['viral_score'] = pd.to_numeric(display_df['viral_score'], errors='coerce').fillna(0).astype(int)
            display_df['latest_likes'] = pd.to_numeric(display_df['latest_likes'], errors='coerce').fillna(0).astype(int) 
            display_df['latest_comments'] = pd.to_numeric(display_df['latest_comments'], errors='coerce').fillna(0).astype(int)
        except Exception as e:
            st.error(f"❌ Lỗi xử lý dữ liệu số: {e}")
            
        # Safely format datetime column
        try:
            if 'first_seen_utc' in display_df.columns and display_df['first_seen_utc'].notna().any():
                display_df['first_seen_utc'] = display_df['first_seen_utc'].dt.strftime('%m/%d %H:%M')
        except Exception as e:
            st.error(f"❌ Lỗi format datetime: {e}")
            display_df['first_seen_utc'] = display_df['first_seen_utc'].astype(str)
        
        # Use source_name if available, otherwise use source_url
        if 'source_name' in display_df.columns:
            source_display_col = 'source_name'
        else:
            source_display_col = 'source_url'
        
        # Rename columns for display
        column_mapping = {
            'author_name': 'Tác giả',
            'post_content_preview': 'Nội dung',
            'post_url': 'Link Post',
            source_display_col: 'Nguồn',
            'latest_likes': 'Likes',
            'latest_comments': 'Comments', 
            'viral_score': 'Viral Score',
            'first_seen_utc': 'Thời gian',
            'interaction_count': 'Theo dõi'
        }
        
        display_columns = ['author_name', 'post_content_preview', 'post_url', source_display_col, 
                          'latest_likes', 'latest_comments', 'viral_score', 
                          'first_seen_utc', 'interaction_count']
        
        # Only include columns that exist
        available_columns = [col for col in display_columns if col in display_df.columns]
        final_df = display_df[available_columns].rename(columns=column_mapping)
        
        # Display table with selection
        st.dataframe(
            final_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Nội dung": st.column_config.TextColumn(width="large"),
                "Link Post": st.column_config.LinkColumn(width="medium", help="Click để xem bài viết gốc"),
                "Nguồn": st.column_config.TextColumn(width="medium"),
                "Viral Score": st.column_config.NumberColumn(
                    format="%d",
                    help="Điểm viral = likes + comments×2 + tracking_count"
                )
            }
        )
        
        # Store post signatures for deep dive page
        if 'viral_posts_data' not in st.session_state:
            st.session_state.viral_posts_data = {}
        
        for idx, row in viral_posts_df.iterrows():
            st.session_state.viral_posts_data[idx] = row['post_signature']
    
    st.divider()
    
    # === QUICK STATS CHARTS ===
    st.subheader("📈 Quick Analytics")
    
    if not viral_posts_df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # Top sources chart - use source_name if available
            group_col = 'source_name' if 'source_name' in viral_posts_df.columns else 'source_url'
            source_stats = viral_posts_df.groupby(group_col).agg({
                'latest_likes': 'sum',
                'latest_comments': 'sum', 
                'viral_score': 'sum'
            }).reset_index()
            
            # Use friendly names or truncate URLs
            if group_col == 'source_name':
                source_stats['source_display'] = source_stats['source_name']
            else:
                source_stats['source_display'] = source_stats['source_url'].apply(
                    lambda x: x.split('/')[-1] if len(x) > 30 else x
                )
            
            fig_sources = px.bar(
                source_stats.head(10),
                x='source_display',
                y='viral_score',
                title="🎯 Top Sources by Viral Score",
                labels={'source_display': 'Source', 'viral_score': 'Total Viral Score'}
            )
            fig_sources.update_xaxes(tickangle=45)
            st.plotly_chart(fig_sources, use_container_width=True, config=get_mobile_plotly_config())
        
        with col2:
            # Engagement distribution
            fig_engagement = go.Figure()
            fig_engagement.add_trace(go.Scatter(
                x=viral_posts_df['latest_likes'],
                y=viral_posts_df['latest_comments'],
                mode='markers',
                marker=dict(
                    size=viral_posts_df['viral_score'] / 50,  # Size by viral score
                    color=viral_posts_df['viral_score'],
                    colorscale='Viridis',
                    showscale=True,
                    colorbar=dict(title="Viral Score")
                ),
                text=viral_posts_df['author_name'],
                hovertemplate="<b>%{text}</b><br>Likes: %{x}<br>Comments: %{y}<extra></extra>"
            ))
            
            fig_engagement.update_layout(
                title="💬 Engagement Distribution",
                xaxis_title="Likes",
                yaxis_title="Comments"
            )
            st.plotly_chart(fig_engagement, use_container_width=True, config=get_mobile_plotly_config())
    

if __name__ == "__main__":
    main()
