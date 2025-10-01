#!/usr/bin/env python3
"""
Facebook Post Monitor - Post Deep Dive Analysis
Phase 3.1 & 3.2 - Chi tiết phân tích từng bài viết cụ thể
"""

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
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
                
                tab1, tab2, tab3 = st.tabs(["📈 Tích lũy (Cumulative)", "📊 Thay đổi (Delta)", "🔍 Chi tiết"])
                
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
