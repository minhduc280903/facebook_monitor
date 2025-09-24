#!/usr/bin/env python3
"""
Facebook Post Monitor - Target Analysis Page
Phase 3.1 & 3.2 - Phân tích theo Trang/Nhóm cụ thể
"""

import streamlit as st
import plotly.express as px
from datetime import datetime
import sys
import os
import pandas as pd

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import database reader with fallbacks
try:
    from webapp_streamlit.core.db_reader import (
        get_top_viral_posts,
        get_source_urls,
        get_all_targets_comparison_data
    )
except ImportError:
    # Fallback functions
    def get_top_viral_posts(source_url=None, limit=10, apply_quality_filter=False):
        return pd.DataFrame()
    
    def get_source_urls():
        return []
    
    def get_all_targets_comparison_data():
        return pd.DataFrame()

# Configure page
st.set_page_config(
    page_title="Target Analysis",
    page_icon="🎯", 
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

def extract_source_name(url):
    """Extract readable name from Facebook URL (deprecated - using db_reader method)"""
    # Import the db_reader instance to use its method
    from webapp_streamlit.core.db_reader import db_reader
    return db_reader.get_friendly_source_name(url)

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_source_urls():
    """Load source URLs with caching"""
    return get_source_urls()

@st.cache_data(ttl=180)  # Cache for 3 minutes
def load_target_posts(source_url, limit=20):
    """Load posts for specific target with caching"""
    return get_top_viral_posts(source_url=source_url, limit=limit, apply_quality_filter=False)

@st.cache_data(ttl=60)
def load_all_targets_comparison():
    """🔥 OPTIMIZED: Load comparison data for all targets using 1 query instead of N+1
    
    PERFORMANCE IMPROVEMENT:
    - Before: N+1 queries (1 for source_urls + N for each get_top_viral_posts)
    - After: 1 optimized SQL query with GROUP BY source_url
    - Speed improvement: ~10-50x faster for 10-50+ targets
    """
    # 🚀 CRITICAL FIX: Thay vì vòng lặp N queries, chỉ cần 1 query duy nhất
    comparison_df = get_all_targets_comparison_data()
    
    if not comparison_df.empty:
        # source_name should already be included from db_reader
        if 'source_name' not in comparison_df.columns:
            comparison_df['source_name'] = comparison_df['source_url'].apply(extract_source_name)
        
        # Add active_posts column (same as total_posts in optimized version)
        comparison_df['active_posts'] = comparison_df['total_posts']
        
        # Reorder columns to match original format
        column_order = ['source_url', 'source_name', 'total_posts', 'total_likes', 
                       'total_comments', 'total_viral_score', 'avg_viral_score', 
                       'top_post_score', 'active_posts']
        available_columns = [col for col in column_order if col in comparison_df.columns]
        comparison_df = comparison_df[available_columns]
    
    return comparison_df

def main():
    """Main target analysis page"""
    
    # Header
    st.title("🎯 Target Analysis - Phân tích theo Trang/Nhóm")
    st.markdown("**Detailed Performance Analysis** - Phân tích chi tiết từng nguồn dữ liệu")
    
    # Refresh button
    col1, col2, col3 = st.columns([1, 1, 4])
    with col1:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    with col2:
        st.markdown(f"*Cập nhật lúc: {datetime.now().strftime('%H:%M:%S')}*")
    
    st.divider()
    
    # Load data
    try:
        source_urls = load_source_urls()
        
        if not source_urls:
            st.warning("⚠️ Không tìm thấy source URLs trong database.")
            st.stop()
            
    except Exception as e:
        st.error(f"❌ Lỗi load dữ liệu: {e}")
        st.stop()
    
    # === TARGET SELECTION ===
    st.subheader("🎯 Chọn Target để Phân tích")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Create display options
        source_options = ["📊 Tất cả (So sánh)"] + [f"🔗 {extract_source_name(url)}" for url in source_urls]
        selected_option = st.selectbox(
            "Chọn nguồn dữ liệu:",
            source_options,
            help="Chọn 'Tất cả' để xem so sánh, hoặc chọn một nguồn cụ thể"
        )
        
        # Determine selected source
        if selected_option.startswith("📊"):
            selected_source = None  # All sources comparison
        else:
            # Find corresponding source URL
            selected_index = source_options.index(selected_option) - 1
            selected_source = source_urls[selected_index]
    
    with col2:
        st.info(f"**Tổng số nguồn:** {len(source_urls)}")
    
    st.divider()
    
    # === DISPLAY CONTENT BASED ON SELECTION ===
    if selected_source is None:
        # === ALL TARGETS COMPARISON ===
        st.subheader("📊 So sánh Tất cả Targets")
        
        try:
            comparison_df = load_all_targets_comparison()
            
            if comparison_df.empty:
                st.warning("⚠️ Không có dữ liệu để so sánh.")
            else:
                # Display metrics
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("🎯 Tổng Targets", len(comparison_df))
                
                with col2:
                    st.metric("📝 Tổng Posts", format_number(comparison_df['total_posts'].sum()))
                
                with col3:
                    st.metric("👍 Tổng Likes", format_number(comparison_df['total_likes'].sum()))
                
                with col4:
                    st.metric("💬 Tổng Comments", format_number(comparison_df['total_comments'].sum()))
                
                st.divider()
                
                # Comparison table
                st.subheader("📋 Bảng So sánh Chi tiết")
                
                display_df = comparison_df.copy()
                display_df['avg_viral_score'] = display_df['avg_viral_score'].round(1)
                
                column_config = {
                    "source_name": "Target",
                    "total_posts": st.column_config.NumberColumn("Posts", format="%d"),
                    "total_likes": st.column_config.NumberColumn("Total Likes", format="%d"),
                    "total_comments": st.column_config.NumberColumn("Total Comments", format="%d"), 
                    "total_viral_score": st.column_config.NumberColumn("Total Viral", format="%d"),
                    "avg_viral_score": st.column_config.NumberColumn("Avg Viral", format="%.1f"),
                    "top_post_score": st.column_config.NumberColumn("Best Post", format="%d")
                }
                
                selected_columns = ['source_name', 'total_posts', 'total_likes', 
                                  'total_comments', 'total_viral_score', 'avg_viral_score', 'top_post_score']
                
                st.dataframe(
                    display_df[selected_columns],
                    column_config=column_config,
                    use_container_width=True,
                    hide_index=True
                )
                
                # Charts
                st.subheader("📈 Visualization")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Viral score comparison
                    fig_viral = px.bar(
                        comparison_df.head(10),
                        x='source_name',
                        y='total_viral_score',
                        title="🔥 Total Viral Score by Target",
                        labels={'source_name': 'Target', 'total_viral_score': 'Total Viral Score'}
                    )
                    fig_viral.update_xaxes(tickangle=45)
                    st.plotly_chart(fig_viral, use_container_width=True)
                
                with col2:
                    # Posts vs Performance
                    fig_performance = px.scatter(
                        comparison_df,
                        x='total_posts',
                        y='avg_viral_score',
                        size='total_viral_score',
                        hover_name='source_name',
                        title="📊 Posts Count vs Average Performance",
                        labels={
                            'total_posts': 'Number of Posts',
                            'avg_viral_score': 'Average Viral Score'
                        }
                    )
                    st.plotly_chart(fig_performance, use_container_width=True)
                
        except Exception as e:
            st.error(f"❌ Lỗi load comparison data: {e}")
    
    else:
        # === SPECIFIC TARGET ANALYSIS ===
        source_name = extract_source_name(selected_source)
        st.subheader(f"📊 Phân tích: {source_name}")
        
        try:
            posts_df = load_target_posts(selected_source, limit=30)
            
            if posts_df.empty:
                st.warning(f"⚠️ Không tìm thấy posts nào từ nguồn: {source_name}")
            else:
                # Target metrics
                total_likes = posts_df['latest_likes'].sum()
                total_comments = posts_df['latest_comments'].sum() 
                avg_viral = posts_df['viral_score'].mean()
                best_post = posts_df['viral_score'].max()
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("📝 Total Posts", len(posts_df))
                
                with col2:
                    st.metric("👍 Total Likes", format_number(total_likes))
                
                with col3:
                    st.metric("💬 Total Comments", format_number(total_comments))
                
                with col4:
                    st.metric("⭐ Avg Viral Score", f"{avg_viral:.1f}")
                
                st.divider()
                
                # Target URL info
                with st.expander("🔗 Target Information"):
                    st.write(f"**URL:** {selected_source}")
                    st.write(f"**Display Name:** {source_name}")
                    st.write(f"**Posts Found:** {len(posts_df)}")
                    st.write(f"**Best Post Score:** {best_post}")
                
                st.divider()
                
                # Posts table for this target
                st.subheader(f"🔥 Viral Posts từ {source_name}")
                
                display_df = posts_df.copy()
                display_df['viral_score'] = display_df['viral_score'].astype(int)
                display_df['latest_likes'] = display_df['latest_likes'].astype(int)
                display_df['latest_comments'] = display_df['latest_comments'].astype(int)
                display_df['first_seen_utc'] = display_df['first_seen_utc'].dt.strftime('%m/%d %H:%M')
                
                column_mapping = {
                    'author_name': 'Tác giả',
                    'post_content_preview': 'Nội dung', 
                    'latest_likes': 'Likes',
                    'latest_comments': 'Comments',
                    'viral_score': 'Viral Score',
                    'first_seen_utc': 'Thời gian',
                    'interaction_count': 'Tracking Count'
                }
                
                display_columns = ['author_name', 'post_content_preview', 'latest_likes', 
                                 'latest_comments', 'viral_score', 'first_seen_utc', 'interaction_count']
                
                final_df = display_df[display_columns].rename(columns=column_mapping)
                
                st.dataframe(
                    final_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Nội dung": st.column_config.TextColumn(width="large"),
                        "Viral Score": st.column_config.NumberColumn(
                            format="%d",
                            help="Điểm viral = likes + comments×2 + tracking_count"
                        )
                    }
                )
                
                # Target-specific charts
                st.subheader("📈 Target Analytics")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Timeline of posts
                    posts_df['first_seen_date'] = posts_df['first_seen_utc'].dt.date
                    timeline_data = posts_df.groupby('first_seen_date').agg({
                        'viral_score': ['count', 'sum', 'mean']
                    }).reset_index()
                    timeline_data.columns = ['date', 'post_count', 'total_viral', 'avg_viral']
                    
                    fig_timeline = px.line(
                        timeline_data,
                        x='date',
                        y='post_count',
                        title="📅 Posts Timeline",
                        labels={'date': 'Date', 'post_count': 'Number of Posts'}
                    )
                    st.plotly_chart(fig_timeline, use_container_width=True)
                
                with col2:
                    # Author performance
                    author_stats = posts_df.groupby('author_name').agg({
                        'viral_score': ['count', 'sum', 'mean']
                    }).reset_index()
                    author_stats.columns = ['author', 'post_count', 'total_viral', 'avg_viral']
                    author_stats = author_stats.sort_values('total_viral', ascending=False).head(10)
                    
                    fig_authors = px.bar(
                        author_stats,
                        x='author',
                        y='total_viral', 
                        title="👥 Top Authors by Viral Score",
                        labels={'author': 'Author', 'total_viral': 'Total Viral Score'}
                    )
                    fig_authors.update_xaxes(tickangle=45)
                    st.plotly_chart(fig_authors, use_container_width=True)
                
        except Exception as e:
            st.error(f"❌ Lỗi load target data: {e}")
    
    # === NAVIGATION TIPS ===
    st.divider()
    st.info("""
    💡 **Tips:**
    - Chọn "📊 Tất cả" để so sánh performance giữa các targets
    - Chọn một target cụ thể để xem phân tích chi tiết
    - Sử dụng **Post Deep Dive** (sidebar) để xem timeline chi tiết của từng bài viết
    """)

if __name__ == "__main__":
    main()
