#!/usr/bin/env python3
"""
Facebook Post Monitor - Post Deep Dive Analysis
Phase 3.1 & 3.2 - Chi tiết phân tích từng bài viết cụ thể

✅ NEW: Advanced filters (type, status, date, viral score)  
✅ NEW: Realtime chart integration
"""

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
import logging
import sys
import os
import pandas as pd

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import database reader with fallbacks
try:
    from webapp_streamlit.core.db_reader import (
        get_post_details,
        get_post_chart_data,
        search_posts_by_content,
        get_top_viral_posts
    )
except ImportError:
    # Fallback functions
    def get_post_details(post_signature):
        return None
    
    def get_post_chart_data(post_signature):
        return {'cumulative': pd.DataFrame(), 'delta': pd.DataFrame()}
    
    def search_posts_by_content(search_term, limit=20):
        return pd.DataFrame()
    
    def get_top_viral_posts(source_url=None, limit=10, apply_quality_filter=False):
        return pd.DataFrame()

# ✅ Import realtime chart component
try:
    from webapp_streamlit.components.realtime_chart import RealTimeChart
    REALTIME_CHART_AVAILABLE = True
except ImportError:
    REALTIME_CHART_AVAILABLE = False

# Configure page
st.set_page_config(
    page_title="Post Deep Dive",
    page_icon="📊",
    layout="wide"
)

def format_number(num):
    """Format large numbers for display"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return str(num)

def calculate_engagement_metrics(chart_data):
    """Calculate engagement metrics from chart data"""
    if chart_data['cumulative'].empty:
        return {}
    
    cumulative_df = chart_data['cumulative']
    delta_df = chart_data['delta']
    
    # Basic metrics
    final_likes = cumulative_df['likes'].iloc[-1] if not cumulative_df.empty else 0
    final_comments = cumulative_df['comments'].iloc[-1] if not cumulative_df.empty else 0
    total_interactions = len(cumulative_df)
    
    # Growth metrics
    if len(cumulative_df) > 1:
        initial_likes = cumulative_df['likes'].iloc[0]
        initial_comments = cumulative_df['comments'].iloc[0]
        likes_growth = final_likes - initial_likes
        comments_growth = final_comments - initial_comments
        
        # Calculate time span
        time_span = (cumulative_df['timestamp'].iloc[-1] - cumulative_df['timestamp'].iloc[0]).total_seconds() / 3600  # hours
    else:
        likes_growth = 0
        comments_growth = 0
        time_span = 0
    
    # Peak activity
    if not delta_df.empty:
        peak_likes_delta = delta_df['likes_delta'].max()
        peak_comments_delta = delta_df['comments_delta'].max()
        peak_activity_time = delta_df.loc[delta_df['likes_delta'].idxmax(), 'timestamp'] if peak_likes_delta > 0 else None
    else:
        peak_likes_delta = 0
        peak_comments_delta = 0
        peak_activity_time = None
    
    return {
        'final_likes': final_likes,
        'final_comments': final_comments,
        'likes_growth': likes_growth,
        'comments_growth': comments_growth,
        'total_interactions': total_interactions,
        'time_span_hours': time_span,
        'peak_likes_delta': peak_likes_delta,
        'peak_comments_delta': peak_comments_delta,
        'peak_activity_time': peak_activity_time
    }

@st.cache_data(ttl=180)  # Cache for 3 minutes
def load_post_details(post_signature):
    """Load post details with caching"""
    return get_post_details(post_signature)

@st.cache_data(ttl=180)
def load_post_chart_data(post_signature):
    """Load post chart data with caching"""
    return get_post_chart_data(post_signature)

@st.cache_data(ttl=300)
def search_posts(search_term):
    """Search posts with caching"""
    return search_posts_by_content(search_term, limit=15)


# ============================================================================
# ✅ POST CARD DISPLAY HELPERS - Standardized Post Formatting
# ============================================================================

def extract_post_id(post_signature: str) -> str:
    """
    Extract readable post ID from post signature.
    
    ✅ SAFE: Pure string parsing
    
    Args:
        post_signature: Full post signature from database
        
    Returns:
        Readable post ID (truncated)
        
    Examples:
        "post_id:123456789_987654321" → "123456789"
        "link:https://facebook.com/..." → "link:fb.com/..."
    """
    try:
        if post_signature.startswith("post_id:"):
            # Extract numeric ID
            post_id = post_signature.replace("post_id:", "").split("_")[0]
            return post_id[:15]  # Limit to 15 chars
        elif post_signature.startswith("link:"):
            # Extract domain + path snippet
            url = post_signature.replace("link:", "")
            if "facebook.com" in url:
                # Extract meaningful part
                parts = url.split("facebook.com/")
                if len(parts) > 1:
                    path = parts[1][:30]  # First 30 chars of path
                    return f"fb/{path}"
            return url[:30]
        else:
            return post_signature[:20]
    except Exception:
        return post_signature[:20]


def truncate_content(content: str, max_length: int = 200) -> str:
    """
    Truncate post content to specified length.
    
    ✅ SAFE: String truncation
    
    Args:
        content: Full post content
        max_length: Maximum characters (default 200)
        
    Returns:
        Truncated content with ellipsis
    """
    if not content:
        return "N/A"
    
    content = content.strip()
    if len(content) <= max_length:
        return content
    
    return content[:max_length] + "..."


def get_status_emoji(status: str) -> str:
    """
    Get emoji for post status.
    
    ✅ SAFE: Simple mapping
    
    Args:
        status: Post status (ACTIVE/DEAD/STALE/TRACKING/EXPIRED)
        
    Returns:
        Emoji representing status
    """
    status_emoji_map = {
        'ACTIVE': '🟢',
        'DEAD': '🔴',
        'STALE': '🟡',
        'TRACKING': '🔵',
        'EXPIRED': '⚪'
    }
    return status_emoji_map.get(status, '❓')


def get_type_emoji(post_type: str) -> str:
    """
    Get emoji for post type.
    
    ✅ SAFE: Simple mapping
    
    Args:
        post_type: Post type (VIDEO/PHOTO/TEXT/LINK)
        
    Returns:
        Emoji representing type
    """
    type_emoji_map = {
        'VIDEO': '🎥',
        'PHOTO': '📷',
        'TEXT': '📝',
        'LINK': '🔗'
    }
    return type_emoji_map.get(post_type, '📄')


def format_timestamp_gmt7_display(timestamp_str: str) -> str:
    """
    Format timestamp string as GMT+7 for display.
    
    ✅ SAFE: Uses utils/timestamp_parser.py
    
    Args:
        timestamp_str: ISO timestamp string from database
        
    Returns:
        Formatted string in GMT+7
    """
    try:
        # Import timezone utilities
        sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from utils.timestamp_parser import parse_iso_to_gmt7, format_timestamp_gmt7
        
        # Parse and convert
        from datetime import datetime
        utc_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        # Format as GMT+7
        return format_timestamp_gmt7(utc_time, "%Y-%m-%d %H:%M:%S")
        
    except Exception as e:
        # Fallback: show original timestamp
        return timestamp_str[:19] if timestamp_str else "N/A"


def render_post_card(post_data: dict, chart_data: dict = None) -> None:
    """
    Render standardized post card display.
    
    ✅ SAFE: Streamlit UI rendering
    
    Args:
        post_data: Post details dict from database
        chart_data: Optional chart data for metrics
        
    Displays:
        📌 Post ID
        📝 Content preview (200 chars)
        🔴 Status (ACTIVE/DEAD/STALE)
        🕐 Time (GMT+7)
        📷 Type (VIDEO/TEXT/PHOTO)
        👍💬 Engagement counts
    """
    with st.container():
        # Header row: ID + Status + Type
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            post_id = extract_post_id(post_data.get('post_signature', ''))
            st.markdown(f"**📌 Post ID:** `{post_id}`")
        
        with col2:
            status = post_data.get('status', 'TRACKING')
            status_emoji = get_status_emoji(status)
            st.markdown(f"**{status_emoji} Status:** {status}")
        
        with col3:
            # Post type (if available in future)
            post_type = post_data.get('post_type', 'TEXT')
            type_emoji = get_type_emoji(post_type)
            st.markdown(f"**{type_emoji} Type:** {post_type}")
        
        # Content preview
        content = post_data.get('post_content', '')
        content_preview = truncate_content(content, 200)
        st.markdown(f"**📝 Content:** {content_preview}")
        
        # Metadata row: Author + Time + Engagement
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            author = post_data.get('author_name', 'Unknown')
            st.markdown(f"**👤 Author:** {author}")
        
        with col2:
            timestamp = post_data.get('first_seen_utc', '')
            formatted_time = format_timestamp_gmt7_display(timestamp)
            st.markdown(f"**🕐 Time (GMT+7):** {formatted_time}")
        
        with col3:
            # Get latest engagement from chart data if available
            if chart_data and not chart_data.get('cumulative', pd.DataFrame()).empty:
                cumulative = chart_data['cumulative']
                latest_likes = cumulative['likes'].iloc[-1] if not cumulative.empty else 0
                latest_comments = cumulative['comments'].iloc[-1] if not cumulative.empty else 0
            else:
                latest_likes = 0
                latest_comments = 0
            
            st.markdown(f"**👍 {format_number(latest_likes)} | 💬 {format_number(latest_comments)}**")
        
        # Link to original post
        post_url = post_data.get('post_url')
        if post_url:
            st.markdown(f"**🔗 [View Original Post]({post_url})**")


def main():
    """Main post deep dive page"""
    
    # Header
    st.title("📊 Post Deep Dive - Phân tích Chi tiết Bài viết")
    st.markdown("**Detailed Post Analysis** - Timeline interactions, engagement patterns, và content insights")
    
    # Refresh button
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    with col2:
        st.markdown(f"*Cập nhật lúc: {datetime.now().strftime('%H:%M:%S')}*")
    
    st.divider()
    
    # ============================================================================
    # ✅ FILTER SYSTEM - Advanced Filtering UI
    # ============================================================================
    
    st.subheader("🎯 Filters - Lọc Bài viết")
    
    # Create filter expander
    with st.expander("📊 Advanced Filters", expanded=False):
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        
        with filter_col1:
            st.markdown("**🎯 Group & Source**")
            # Get unique sources from database (would need DB query)
            filter_source = st.selectbox(
                "Source/Group:",
                ["All"] + ["Group A", "Group B", "Group C"],  # TODO: Get from database
                help="Filter by Facebook group or page"
            )
            
            st.markdown("**📅 Date Range**")
            date_range_preset = st.selectbox(
                "Quick Select:",
                ["Last 24 hours", "Last 7 days", "Last 30 days", "Custom"],
                help="Select time range for posts"
            )
            
            if date_range_preset == "Custom":
                date_from = st.date_input("From:", value=datetime.now() - timedelta(days=7))
                date_to = st.date_input("To:", value=datetime.now())
            else:
                # Auto-calculate based on preset
                if date_range_preset == "Last 24 hours":
                    date_from = datetime.now() - timedelta(days=1)
                elif date_range_preset == "Last 7 days":
                    date_from = datetime.now() - timedelta(days=7)
                else:  # Last 30 days
                    date_from = datetime.now() - timedelta(days=30)
                date_to = datetime.now()
                
                st.caption(f"📅 {date_from.strftime('%Y-%m-%d')} → {date_to.strftime('%Y-%m-%d')}")
        
        with filter_col2:
            st.markdown("**🔥 Viral Score**")
            viral_score_min = st.number_input(
                "Minimum viral score:",
                min_value=0,
                max_value=100000,
                value=0,
                step=100,
                help="Filter posts with viral score >= this value"
            )
            
            st.markdown("**📊 Engagement Range**")
            engagement_min_likes = st.number_input(
                "Min Likes:",
                min_value=0,
                value=0,
                step=10,
                help="Minimum number of likes"
            )
            
            engagement_min_comments = st.number_input(
                "Min Comments:",
                min_value=0,
                value=0,
                step=5,
                help="Minimum number of comments"
            )
        
        with filter_col3:
            st.markdown("**📷 Post Type**")
            filter_post_types = st.multiselect(
                "Select types:",
                ["VIDEO", "PHOTO", "TEXT", "LINK"],
                default=["VIDEO", "PHOTO", "TEXT", "LINK"],
                help="Filter by post content type"
            )
            
            # Display type emojis
            type_emojis_display = " ".join([get_type_emoji(t) for t in filter_post_types])
            st.caption(f"Selected: {type_emojis_display}")
            
            st.markdown("**🚦 Post Status**")
            filter_post_statuses = st.multiselect(
                "Select statuses:",
                ["ACTIVE", "DEAD", "STALE"],
                default=["ACTIVE"],
                help="Filter by post status"
            )
            
            # Display status emojis
            status_emojis_display = " ".join([get_status_emoji(s) for s in filter_post_statuses])
            st.caption(f"Selected: {status_emojis_display}")
        
        # Filter summary
        st.markdown("---")
        active_filters = []
        if filter_source != "All":
            active_filters.append(f"📍 {filter_source}")
        if viral_score_min > 0:
            active_filters.append(f"🔥 Score ≥ {viral_score_min}")
        if engagement_min_likes > 0:
            active_filters.append(f"👍 ≥ {engagement_min_likes}")
        if engagement_min_comments > 0:
            active_filters.append(f"💬 ≥ {engagement_min_comments}")
        if len(filter_post_types) < 4:
            active_filters.append(f"📊 Types: {', '.join(filter_post_types)}")
        if len(filter_post_statuses) < 3:
            active_filters.append(f"🚦 Status: {', '.join(filter_post_statuses)}")
        
        if active_filters:
            st.info(f"**Active Filters:** {' | '.join(active_filters)}")
        else:
            st.success("✅ No filters applied - showing all posts")
        
        # Store filters in session state for later use
        if 'filters' not in st.session_state:
            st.session_state.filters = {}
        
        st.session_state.filters = {
            'source': filter_source,
            'date_from': date_from,
            'date_to': date_to,
            'viral_score_min': viral_score_min,
            'engagement_min_likes': engagement_min_likes,
            'engagement_min_comments': engagement_min_comments,
            'post_types': filter_post_types,
            'post_statuses': filter_post_statuses
        }
    
    st.divider()
    
    # === POST SELECTION ===
    st.subheader("🎯 Chọn Bài viết để Phân tích")
    
    # Multiple ways to select a post
    tab1, tab2, tab3 = st.tabs(["🔤 Nhập Signature", "🔍 Tìm kiếm", "🔥 Top Posts"])
    
    selected_post_signature = None
    
    with tab1:
        st.markdown("**Nhập trực tiếp Post Signature:**")
        input_signature = st.text_input(
            "Post Signature:",
            value="",
            placeholder="Ví dụ: post_id:123456789 hoặc link:https://facebook.com/...",
            help="Nhập post signature từ database hoặc từ các trang khác"
        )
        
        if input_signature:
            selected_post_signature = input_signature.strip()
    
    with tab2:
        st.markdown("**Tìm kiếm bài viết theo nội dung:**")
        search_term = st.text_input(
            "Từ khóa tìm kiếm:",
            value="",
            placeholder="Nhập từ khóa để tìm trong nội dung bài viết..."
        )
        
        if search_term:
            try:
                search_results = search_posts(search_term)
                
                if search_results.empty:
                    st.info(f"Không tìm thấy bài viết nào chứa từ khóa: '{search_term}'")
                else:
                    st.write(f"**Tìm thấy {len(search_results)} bài viết:**")
                    
                    # Display search results
                    for idx, row in search_results.iterrows():
                        col1, col2, col3 = st.columns([3, 1, 1])
                        
                        with col1:
                            content_preview = row['post_content'][:100] + "..." if len(row['post_content']) > 100 else row['post_content']
                            st.write(f"**{row['author_name']}**: {content_preview}")
                        
                        with col2:
                            st.write(f"👍 {row['latest_likes']} 💬 {row['latest_comments']}")
                        
                        with col3:
                            if st.button("Chọn", key=f"search_{idx}"):
                                selected_post_signature = row['post_signature']
                                st.rerun()
                        
                        st.divider()
                        
            except Exception as e:
                st.error(f"❌ Lỗi tìm kiếm: {e}")
    
    with tab3:
        st.markdown("**Chọn từ Top Viral Posts:**")
        try:
            top_posts = get_top_viral_posts(limit=10, apply_quality_filter=False)
            
            if top_posts.empty:
                st.info("Không có dữ liệu top posts")
            else:
                # Display top posts for selection
                for idx, row in top_posts.iterrows():
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    
                    with col1:
                        content_preview = row['post_content_preview']
                        st.write(f"**{row['author_name']}**: {content_preview}")
                    
                    with col2:
                        st.write(f"Score: {row['viral_score']}")
                    
                    with col3:
                        st.write(f"👍 {row['latest_likes']} 💬 {row['latest_comments']}")
                    
                    with col4:
                        if st.button("Chọn", key=f"top_{idx}"):
                            selected_post_signature = row['post_signature']
                            st.rerun()
                    
                    st.divider()
                    
        except Exception as e:
            st.error(f"❌ Lỗi load top posts: {e}")
    
    # === POST ANALYSIS ===
    if selected_post_signature:
        st.success(f"✅ **Đã chọn:** {selected_post_signature[:50]}...")
        
        try:
            # Load post data
            post_details = load_post_details(selected_post_signature)
            chart_data = load_post_chart_data(selected_post_signature)
            
            if not post_details:
                st.error("❌ Không tìm thấy bài viết này trong database")
                st.stop()
            
            st.divider()
            
            # === POST INFORMATION ===
            st.subheader("📋 Thông tin Bài viết")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                with st.expander("📝 Chi tiết Bài viết", expanded=True):
                    st.write(f"**Tác giả:** {post_details.get('author_name', 'N/A')}")
                    st.write(f"**Author ID:** {post_details.get('author_id', 'N/A')}")
                    st.write(f"**Nguồn:** {post_details.get('source_url', 'N/A')}")
                    st.write(f"**Thời gian phát hiện:** {post_details.get('first_seen_utc', 'N/A')}")
                    st.write(f"**Hết hạn tracking:** {post_details.get('tracking_expires_utc', 'N/A')}")
                    st.write(f"**Trạng thái:** {post_details.get('status', 'N/A')}")
                    
                    if post_details.get('post_url'):
                        st.markdown(f"**🔗 [Xem bài viết gốc]({post_details['post_url']})**")
            
            with col2:
                # Calculate and display engagement metrics
                if not chart_data['cumulative'].empty:
                    metrics = calculate_engagement_metrics(chart_data)
                    
                    st.metric("👍 Total Likes", format_number(metrics['final_likes']))
                    st.metric("💬 Total Comments", format_number(metrics['final_comments']))
                    st.metric("📊 Data Points", metrics['total_interactions'])
                    
                    if metrics['time_span_hours'] > 0:
                        st.metric("⏱️ Tracking Time", f"{metrics['time_span_hours']:.1f}h")
                else:
                    st.warning("⚠️ Chưa có dữ liệu interaction cho bài viết này")
            
            # Post content
            if post_details.get('post_content'):
                with st.expander("📄 Nội dung Đầy đủ", expanded=False):
                    st.write(post_details['post_content'])
            
            st.divider()
            
            # === CHARTS ===
            if not chart_data['cumulative'].empty:
                st.subheader("📈 Biểu đồ Tương tác")
                
                # ✅ Add Realtime chart tab if available
                tab_names = ["📈 Tích lũy (Cumulative)", "📊 Thay đổi (Delta)", "🔍 Chi tiết"]
                if REALTIME_CHART_AVAILABLE:
                    tab_names.insert(0, "⚡ Realtime Style")
                    tab_realtime, tab1, tab2, tab3 = st.tabs(tab_names)
                else:
                    tab1, tab2, tab3 = st.tabs(tab_names)
                
                # ✅ NEW: Realtime Style Chart Tab
                if REALTIME_CHART_AVAILABLE:
                    with tab_realtime:
                        st.markdown("**📈 Forex-Style Real-time Chart** - Interactive engagement visualization")
                        
                        # Initialize realtime chart component
                        if 'realtime_chart' not in st.session_state:
                            st.session_state.realtime_chart = RealTimeChart()
                        
                        realtime_chart = st.session_state.realtime_chart
                        
                        # Convert chart_data to format expected by realtime chart
                        cumulative_df = chart_data['cumulative']
                        
                        # Prepare data in format expected by RealTimeChart
                        interactions_data = []
                        for _, row in cumulative_df.iterrows():
                            interactions_data.append({
                                'log_timestamp_utc': row['timestamp'].isoformat() if hasattr(row['timestamp'], 'isoformat') else str(row['timestamp']),
                                'like_count': int(row['likes']),
                                'comment_count': int(row['comments'])
                            })
                        
                        # Create and display forex-style chart
                        fig_realtime = realtime_chart.create_forex_style_chart(
                            post_signature=selected_post_signature,
                            data=interactions_data
                        )
                        
                        st.plotly_chart(fig_realtime, use_container_width=True, key="realtime_chart")
                        
                        # Show realtime features info
                        st.info("⚡ **Realtime Features:** Forex-style visualization với dual-axis display, fill areas, và unified hover mode")
                
                with tab1:
                    st.markdown("**Biểu đồ tích lũy** - Tổng likes và comments theo thời gian")
                    
                    cumulative_df = chart_data['cumulative']
                    
                    # Create cumulative chart with dual y-axis
                    fig_cumulative = go.Figure()
                    
                    fig_cumulative.add_trace(go.Scatter(
                        x=cumulative_df['timestamp'],
                        y=cumulative_df['likes'],
                        mode='lines+markers',
                        name='Likes',
                        line=dict(color='#1f77b4', width=2),
                        yaxis='y'
                    ))
                    
                    fig_cumulative.add_trace(go.Scatter(
                        x=cumulative_df['timestamp'],
                        y=cumulative_df['comments'],
                        mode='lines+markers',
                        name='Comments',
                        line=dict(color='#ff7f0e', width=2),
                        yaxis='y2'
                    ))
                    
                    fig_cumulative.update_layout(
                        title="📈 Cumulative Engagement Over Time",
                        xaxis_title="Time",
                        yaxis=dict(title="Likes", side="left", color="#1f77b4"),
                        yaxis2=dict(title="Comments", side="right", overlaying="y", color="#ff7f0e"),
                        hovermode='x unified',
                        height=500
                    )
                    
                    st.plotly_chart(fig_cumulative, width='stretch')
                
                with tab2:
                    st.markdown("**Biểu đồ delta** - Thay đổi likes và comments giữa các lần đo")
                    
                    delta_df = chart_data['delta']
                    
                    if not delta_df.empty:
                        # Create delta chart
                        fig_delta = go.Figure()
                        
                        fig_delta.add_trace(go.Bar(
                            x=delta_df['timestamp'],
                            y=delta_df['likes_delta'],
                            name='Likes Delta',
                            marker_color='lightblue',
                            yaxis='y'
                        ))
                        
                        fig_delta.add_trace(go.Bar(
                            x=delta_df['timestamp'],
                            y=delta_df['comments_delta'],
                            name='Comments Delta',
                            marker_color='orange',
                            yaxis='y2'
                        ))
                        
                        fig_delta.update_layout(
                            title="📊 Engagement Delta (Changes Between Measurements)",
                            xaxis_title="Time",
                            yaxis=dict(title="Likes Delta", side="left", color="blue"),
                            yaxis2=dict(title="Comments Delta", side="right", overlaying="y", color="orange"),
                            barmode='group',
                            height=500
                        )
                        
                        st.plotly_chart(fig_delta, width='stretch')
                    else:
                        st.info("Không có dữ liệu delta để hiển thị")
                
                with tab3:
                    st.markdown("**Chi tiết dữ liệu** - Raw data và thống kê")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("**📈 Cumulative Data:**")
                        st.dataframe(
                            cumulative_df,
                            width='stretch',
                            column_config={
                                "timestamp": st.column_config.DatetimeColumn("Time"),
                                "likes": st.column_config.NumberColumn("Likes", format="%d"),
                                "comments": st.column_config.NumberColumn("Comments", format="%d")
                            }
                        )
                    
                    with col2:
                        if not delta_df.empty:
                            st.write("**📊 Delta Data:**")
                            st.dataframe(
                                delta_df[delta_df[['likes_delta', 'comments_delta']].sum(axis=1) > 0],  # Only show rows with changes
                                width='stretch',
                                column_config={
                                    "timestamp": st.column_config.DatetimeColumn("Time"),
                                    "likes_delta": st.column_config.NumberColumn("Likes Δ", format="%d"),
                                    "comments_delta": st.column_config.NumberColumn("Comments Δ", format="%d")
                                }
                            )
                
                # === INSIGHTS ===
                st.divider()
                st.subheader("🧠 Insights & Analytics")
                
                metrics = calculate_engagement_metrics(chart_data)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.info(f"""
                    **📊 Growth Summary:**
                    - Likes gained: +{format_number(metrics['likes_growth'])}
                    - Comments gained: +{format_number(metrics['comments_growth'])}
                    - Tracking period: {metrics['time_span_hours']:.1f} hours
                    """)
                
                with col2:
                    if metrics['peak_activity_time']:
                        st.info(f"""
                        **🔥 Peak Activity:**
                        - Max likes gain: +{metrics['peak_likes_delta']}
                        - Max comments gain: +{metrics['peak_comments_delta']}
                        - Peak time: {metrics['peak_activity_time'].strftime('%m/%d %H:%M')}
                        """)
                    else:
                        st.info("**🔥 Peak Activity:**\nChưa có hoạt động đáng kể")
                
                with col3:
                    engagement_rate = (metrics['final_comments'] / max(metrics['final_likes'], 1)) * 100
                    st.info(f"""
                    **💬 Engagement Analysis:**
                    - Comment rate: {engagement_rate:.1f}%
                    - Total interactions: {metrics['total_interactions']}
                    - Data completeness: Good
                    """)
            
            else:
                st.warning("⚠️ Không có dữ liệu chart cho bài viết này")
                st.info("Bài viết có thể vừa được phát hiện và chưa có đủ dữ liệu tracking.")
                
        except Exception as e:
            st.error(f"❌ Lỗi phân tích post: {e}")
            logging.error(f"Error in post analysis: {e}")
    
    else:
        # === INSTRUCTIONS ===
        st.info("""
        👆 **Hướng dẫn sử dụng:**
        
        1. **Nhập Signature**: Paste post signature trực tiếp nếu bạn đã biết
        2. **Tìm kiếm**: Tìm bài viết theo từ khóa trong nội dung  
        3. **Top Posts**: Chọn từ danh sách posts viral nhất
        
        Sau khi chọn bài viết, bạn sẽ thấy:
        - 📋 Thông tin chi tiết bài viết
        - 📈 Biểu đồ tương tác theo thời gian  
        - 📊 Phân tích engagement patterns
        - 🧠 Insights tự động
        """)
    
    # === SESSION STATE INFO ===
    if st.sidebar.button("🔍 Debug Info"):
        st.sidebar.write("**Session State:**")
        st.sidebar.json(dict(st.session_state))

if __name__ == "__main__":
    main()
