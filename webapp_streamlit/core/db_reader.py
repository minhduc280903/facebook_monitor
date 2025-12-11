#!/usr/bin/env python3
"""Database Reader for Facebook Post Monitor - Streamlit Dashboard.

Phase 3.1 & 3.2 - Interactive Dashboard Core Module

Chịu trách nhiệm:
- Kết nối và truy vấn PostgreSQL database
- Cung cấp functions cho Streamlit dashboard
- Xử lý dữ liệu với pandas cho visualization
- Cache optimization cho Streamlit
"""

import json
import logging
import os
import sys
import warnings
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd

# Add parent directory to path để import database_manager
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.database_manager import DatabaseManager

# Try to import sqlalchemy, fallback gracefully if not available
try:
    from sqlalchemy import create_engine
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    warnings.warn("SQLAlchemy not available, using psycopg2 fallback")

logger = logging.getLogger(__name__)

# Suppress pandas SQLAlchemy warnings
warnings.filterwarnings(
    "ignore", 
    message="pandas only supports SQLAlchemy connectable"
)


class DatabaseReader:
    """Database Reader cho Streamlit Dashboard.
    
    Tối ưu cho read-only operations với caching
    Sử dụng DatabaseManager với PostgreSQL và SQLAlchemy engine
    """

    def __init__(self) -> None:
        """Khởi tạo DatabaseReader với DatabaseManager và SQLAlchemy engine."""
        self.db_manager = DatabaseManager()
        self.engine = None
        self.targets_mapping: Dict[str, str] = {}
        
        self._init_sqlalchemy_engine()
        self._load_targets_mapping()
        logger.info("📖 DatabaseReader initialized với PostgreSQL + SQLAlchemy")

    def _init_sqlalchemy_engine(self) -> None:
        """Tạo SQLAlchemy engine để fix pandas warning."""
        if not SQLALCHEMY_AVAILABLE:
            logger.warning("⚠️ SQLAlchemy not available, using psycopg2 fallback")
            return
            
        try:
            db_config = self.db_manager.db_config
            connection_string = (
                f"postgresql://{db_config.user}:{db_config.password}"
                f"@{db_config.host}:{db_config.port}/{db_config.name}"
            )
            self.engine = create_engine(connection_string, echo=False)
            logger.info("✅ SQLAlchemy engine initialized")
        except Exception as e:
            logger.warning(f"⚠️ SQLAlchemy engine failed: {e}")
            self.engine = None

    def _load_targets_mapping(self) -> None:
        """Load targets mapping từ targets.json để hiển thị tên nhóm."""
        self.targets_mapping = {}
        
        # ✅ FIX: Tìm targets.json ở nhiều locations
        possible_paths = [
            "targets.json",  # Current dir
            os.path.join(parent_dir, "targets.json"),  # Parent dir
            "/app/targets.json",  # Absolute path for VPS deployment
        ]
        
        targets_path = None
        for path in possible_paths:
            if os.path.exists(path):
                targets_path = path
                break
        
        if not targets_path:
            logger.warning("⚠️ targets.json not found - friendly names won't be available")
            return
        
        try:
            with open(targets_path, 'r', encoding='utf-8') as f:
                targets_data = json.load(f)
                for target in targets_data.get('targets', []):
                    url = target.get('url', '')
                    name = target.get('name', target.get('id', ''))
                    if url:
                        self.targets_mapping[url] = name
            logger.info(f"📋 Loaded {len(self.targets_mapping)} targets from {targets_path}")
        except Exception as e:
            logger.error(f"❌ Failed to load targets mapping: {e}")
            self.targets_mapping = {}

    def get_friendly_source_name(self, source_url: str) -> str:
        """Lấy tên thân thiện của source từ targets mapping hoặc extract từ URL.

        Args:
            source_url: URL của source

        Returns:
            Tên thân thiện để hiển thị
        """
        if not source_url:
            return "Unknown Source"

        # Kiểm tra trong targets mapping trước
        if source_url in self.targets_mapping:
            return self.targets_mapping[source_url]

        # Extract name từ URL
        try:
            if '/groups/' in source_url:
                # Facebook group URL
                parts = source_url.split('/groups/')
                if len(parts) > 1:
                    group_id = parts[1].rstrip('/').split('/')[0]
                    return f"FB Group {group_id}"
            elif 'facebook.com/' in source_url:
                # Facebook page URL
                parts = source_url.split('facebook.com/')
                if len(parts) > 1:
                    page_name = parts[1].rstrip('/').split('/')[0]
                    return f"FB Page {page_name}"

            # Fallback: return domain + path
            parsed = urlparse(source_url)
            if parsed.path:
                path = parsed.path[:20]
                if len(parsed.path) > 20:
                    path += "..."
                return f"{parsed.netloc}{path}"
            return parsed.netloc
        except Exception:
            if len(source_url) > 30:
                return source_url[:30] + "..."
            return source_url

    def _filter_low_quality_content(self, df: pd.DataFrame) -> pd.DataFrame:
        """Lọc bỏ nội dung chất lượng thấp.

        Args:
            df: DataFrame chứa posts

        Returns:
            DataFrame đã được lọc
        """
        if df.empty or 'post_content_preview' not in df.columns:
            return df

        # Các từ khóa chất lượng thấp
        low_quality_keywords = [
            'facebook', 'fb', '???', '...', 'không có nội dung',
            'xem thêm', 'loading', 'error', 'null', 'undefined'
        ]

        # Filter logic
        mask = df['post_content_preview'].apply(
            lambda content: self._is_quality_content(content, low_quality_keywords)
        )

        return df[mask]

    def _is_quality_content(
        self, 
        content: str, 
        low_quality_keywords: List[str]
    ) -> bool:
        """Kiểm tra content có chất lượng hay không.

        Args:
            content: Nội dung cần kiểm tra
            low_quality_keywords: Danh sách từ khóa chất lượng thấp

        Returns:
            True nếu content có chất lượng, False nếu không
        """
        if not content or pd.isna(content):
            return False

        content_str = str(content).strip().lower()

        # Quá ngắn
        if len(content_str) < 10:
            return False

        # Chỉ có ký tự đặc biệt
        if content_str.replace(' ', '') in ['', '...', '???', '---']:
            return False

        # Chỉ chứa từ khóa chất lượng thấp
        if content_str in low_quality_keywords:
            return False

        # Nếu toàn bộ content chỉ là một từ khóa chất lượng thấp
        if len(content_str.split()) == 1 and content_str in low_quality_keywords:
            return False

        return True

    def _execute_pandas_query(
        self, 
        query: str, 
        params: Optional[tuple] = None
    ) -> pd.DataFrame:
        """Execute query using SQLAlchemy engine or psycopg2 fallback.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            DataFrame with results
        """
        try:
            if self.engine is not None:
                return pd.read_sql_query(query, self.engine, params=params)
            else:
                # Fallback to DatabaseManager's thread-safe connection pool
                with self.db_manager.get_connection() as conn:
                    df = pd.read_sql_query(query, conn, params=params)
                return df
        except Exception as e:
            logger.error(f"❌ Query execution failed: {e}")
            return pd.DataFrame()

    def get_connection(self):
        """Lấy connection từ DatabaseManager context manager."""
        return self.db_manager.get_connection()

    def get_system_overview(self) -> Dict[str, Any]:
        """Lấy tổng quan hệ thống cho dashboard chính.

        Returns:
            Dict chứa các metrics: tracking_posts, total_interactions, etc.
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Posts statistics
                cursor.execute("SELECT COUNT(*) as count FROM posts WHERE status = 'TRACKING'")
                tracking_posts = cursor.fetchone()['count']

                cursor.execute("SELECT COUNT(*) as count FROM posts WHERE status = 'EXPIRED'")
                expired_posts = cursor.fetchone()['count']

                # Interactions statistics
                cursor.execute("SELECT COUNT(*) as count FROM interactions")
                total_interactions = cursor.fetchone()['count']

                # Today's statistics (simplified PostgreSQL queries)
                cursor.execute("SELECT COUNT(*) as count FROM posts WHERE first_seen_utc::date = CURRENT_DATE")
                today_new_posts = cursor.fetchone()['count']

                cursor.execute("SELECT COUNT(*) as count FROM interactions WHERE log_timestamp_utc::date = CURRENT_DATE")
                today_interactions = cursor.fetchone()['count']

                # Recent activity (last 24h) - fix timestamp comparison
                cursor.execute("SELECT COUNT(*) as count FROM interactions WHERE log_timestamp_utc::timestamp > NOW() - INTERVAL '24 hours'")
                last_24h_interactions = cursor.fetchone()['count']

            return {
                'tracking_posts': tracking_posts,
                'expired_posts': expired_posts,
                'total_interactions': total_interactions,
                'today_new_posts': today_new_posts,
                'today_interactions': today_interactions,
                'last_24h_interactions': last_24h_interactions
            }

        except Exception as e:
            logger.error(f"❌ Lỗi lấy system overview: {e}")
            return {}

    def get_top_viral_posts(
        self, 
        source_url: Optional[str] = None, 
        limit: int = 10,
        apply_quality_filter: bool = False
    ) -> pd.DataFrame:
        """Lấy danh sách posts viral nhất.

        Args:
            source_url: Lọc theo nguồn cụ thể (None = tất cả)
            limit: Số lượng posts tối đa
            apply_quality_filter: Có áp dụng quality filter không (default False)

        Returns:
            DataFrame với columns: post_signature, author_name, post_url, etc.
        """
        try:
            placeholder = self.db_manager._get_placeholder()

            # PostgreSQL syntax
            length_func = "LENGTH"
            substr_func = "SUBSTR"
            max_datetime = "MAX(log_timestamp_utc::timestamp)"

            query = f"""
            WITH latest_interactions AS (
                SELECT 
                    post_signature,
                    MAX(like_count) as max_likes,
                    MAX(comment_count) as max_comments,
                    COUNT(*) as interaction_count,
                    {max_datetime} as latest_time
                FROM interactions
                GROUP BY post_signature
            ),
            post_viral_scores AS (
                SELECT 
                    p.post_signature,
                    p.author_name,
                    p.post_url,
                    CASE 
                        WHEN {length_func}(p.post_content) > 100 
                        THEN {substr_func}(p.post_content, 1, 100) || '...'
                        ELSE p.post_content
                    END as post_content_preview,
                    p.post_content as full_content,
                    p.source_url,
                    p.first_seen_utc,
                    li.max_likes as latest_likes,
                    li.max_comments as latest_comments,
                    li.interaction_count,
                    li.latest_time,
                    (li.max_likes + li.max_comments * 2 + li.interaction_count) as viral_score
                FROM posts p
                INNER JOIN latest_interactions li ON p.post_signature = li.post_signature
                WHERE p.status = 'TRACKING'
            """

            params = []
            if source_url:
                query += f" AND p.source_url = {placeholder}"
                params.append(source_url)

            query += f"""
            )
            SELECT * FROM post_viral_scores
            ORDER BY viral_score DESC, latest_likes DESC
            LIMIT {limit}
            """

            # Convert params list to tuple for SQLAlchemy
            params_tuple = tuple(params) if params else None
            df = self._execute_pandas_query(query, params_tuple)

            # Format datetime columns with ISO8601 support
            if not df.empty and 'first_seen_utc' in df.columns:
                df['first_seen_utc'] = pd.to_datetime(df['first_seen_utc'], format='ISO8601', errors='coerce')
            if not df.empty and 'latest_time' in df.columns:
                df['latest_time'] = pd.to_datetime(df['latest_time'], format='ISO8601', errors='coerce')

            # Quality filter (optional)
            if not df.empty and apply_quality_filter:
                original_count = len(df)
                df = self._filter_low_quality_content(df)
                filtered_count = len(df)
                if filtered_count < original_count:
                    logger.info(f"🧹 Filtered {original_count - filtered_count} low-quality posts")
            elif not df.empty:
                logger.info("📋 No quality filtering applied - showing all posts")

            # Add friendly source names
            if not df.empty and 'source_url' in df.columns:
                df['source_name'] = df['source_url'].apply(self.get_friendly_source_name)

            logger.info(f"📊 Loaded {len(df)} viral posts (source_url={source_url})")
            return df

        except Exception as e:
            logger.error(f"❌ Lỗi lấy viral posts: {e}")
            return pd.DataFrame()

    def get_source_urls(self) -> List[str]:
        """Lấy danh sách tất cả source_urls có trong database.

        Returns:
            List các source_url unique
        """
        try:
            query = "SELECT DISTINCT source_url FROM posts ORDER BY source_url"
            df = self._execute_pandas_query(query)
            
            if not df.empty:
                source_urls = df['source_url'].dropna().tolist()
                logger.info(f"📋 Found {len(source_urls)} unique source URLs")
                return source_urls
            return []

        except Exception as e:
            logger.error(f"❌ Lỗi lấy source URLs: {e}")
            return []

    def get_post_details(self, post_signature: str) -> Optional[Dict[str, Any]]:
        """Lấy chi tiết đầy đủ của một post.

        Args:
            post_signature: Chữ ký post

        Returns:
            Dict chứa thông tin post hoặc None nếu không tìm thấy
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            placeholder = self.db_manager._get_placeholder()
            cursor.execute(
                f"SELECT * FROM posts WHERE post_signature = {placeholder}", 
                (post_signature,)
            )
            result = cursor.fetchone()

            if result:
                return dict(result)
            return None

        except Exception as e:
            logger.error(f"❌ Lỗi lấy post details: {e}")
            return None

    def get_post_chart_data(self, post_signature: str) -> Dict[str, pd.DataFrame]:
        """Lấy dữ liệu cho vẽ biểu đồ tương tác của post.

        Args:
            post_signature: Chữ ký post

        Returns:
            Dict với keys 'cumulative' và 'delta'
        """
        try:
            placeholder = self.db_manager._get_placeholder()
            order_by_sql = self.db_manager._get_datetime_cast_sql('log_timestamp_utc')
            
            query = f"""
            SELECT 
                log_timestamp_utc,
                like_count,
                comment_count
            FROM interactions
            WHERE post_signature = {placeholder}
            ORDER BY {order_by_sql}
            """

            df = self._execute_pandas_query(query, (post_signature,))

            if df.empty:
                logger.warning(f"⚠️ Không tìm thấy data cho post: {post_signature[:20]}...")
                return {'cumulative': pd.DataFrame(), 'delta': pd.DataFrame()}

            # Convert timestamp to datetime with ISO8601 format support
            df['timestamp'] = pd.to_datetime(df['log_timestamp_utc'], format='ISO8601')

            # Cumulative data
            cumulative_df = df[['timestamp', 'like_count', 'comment_count']].copy()
            cumulative_df.columns = ['timestamp', 'likes', 'comments']

            # Delta data
            delta_df = df[['timestamp', 'like_count', 'comment_count']].copy()
            delta_df['likes_delta'] = delta_df['like_count'].diff().fillna(0)
            delta_df['comments_delta'] = delta_df['comment_count'].diff().fillna(0)

            # Remove negative deltas
            delta_df['likes_delta'] = delta_df['likes_delta'].clip(lower=0)
            delta_df['comments_delta'] = delta_df['comments_delta'].clip(lower=0)

            delta_result = delta_df[['timestamp', 'likes_delta', 'comments_delta']].copy()

            logger.info(f"📈 Loaded chart data: {len(cumulative_df)} points")

            return {
                'cumulative': cumulative_df,
                'delta': delta_result
            }

        except Exception as e:
            logger.error(f"❌ Lỗi lấy chart data: {e}")
            return {'cumulative': pd.DataFrame(), 'delta': pd.DataFrame()}

    def get_all_targets_comparison_data(self) -> pd.DataFrame:
        """Lấy dữ liệu so sánh cho TẤT CẢ targets trong 1 query.

        Returns:
            DataFrame với columns: source_url, total_posts, etc.
        """
        try:
            query = """
                WITH latest_interactions AS (
                    SELECT 
                        post_signature,
                        MAX(like_count) as max_likes,
                        MAX(comment_count) as max_comments,
                        COUNT(*) as interaction_count
                    FROM interactions
                    GROUP BY post_signature
                ),
                post_viral_scores AS (
                    SELECT 
                        p.source_url,
                        p.post_signature,
                        li.max_likes,
                        li.max_comments,
                        li.interaction_count,
                        (li.max_likes + li.max_comments * 2 + li.interaction_count) as viral_score
                    FROM posts p
                    INNER JOIN latest_interactions li ON p.post_signature = li.post_signature
                    WHERE p.status = 'TRACKING'
                )
                SELECT
                    source_url,
                    COUNT(post_signature) as total_posts,
                    SUM(max_likes) as total_likes,
                    SUM(max_comments) as total_comments,
                    SUM(viral_score) as total_viral_score,
                    ROUND(AVG(viral_score), 1) as avg_viral_score,
                    MAX(viral_score) as top_post_score
                FROM post_viral_scores
                GROUP BY source_url
                ORDER BY total_viral_score DESC
                """

            df = self._execute_pandas_query(query)

            # Add friendly source names
            if not df.empty:
                df['source_name'] = df['source_url'].apply(self.get_friendly_source_name)

            logger.info(f"🚀 OPTIMIZED: Loaded comparison data for {len(df)} targets")
            return df

        except Exception as e:
            logger.error(f"❌ Lỗi lấy targets comparison data: {e}")
            return pd.DataFrame()

    def search_posts_by_content(self, search_term: str, limit: int = 20) -> pd.DataFrame:
        """Tìm kiếm posts theo nội dung.

        Args:
            search_term: Từ khóa tìm kiếm
            limit: Số lượng kết quả tối đa

        Returns:
            DataFrame với thông tin posts matching search term
        """
        try:
            query = f"""
            SELECT 
                p.post_signature,
                p.author_name,
                p.post_content,
                p.source_url,
                p.first_seen_utc,
                MAX(i.like_count) as latest_likes,
                MAX(i.comment_count) as latest_comments
            FROM posts p
            LEFT JOIN interactions i ON p.post_signature = i.post_signature
            WHERE p.post_content LIKE %s
            GROUP BY p.post_signature
            ORDER BY latest_likes DESC, latest_comments DESC
            LIMIT {limit}
            """

            search_param = f"%{search_term}%"
            df = self._execute_pandas_query(query, (search_param,))

            if not df.empty:
                df['first_seen_utc'] = pd.to_datetime(df['first_seen_utc'], format='ISO8601')
                df['source_name'] = df['source_url'].apply(self.get_friendly_source_name)

            logger.info(f"🔍 Found {len(df)} posts matching '{search_term}'")
            return df

        except Exception as e:
            logger.error(f"❌ Lỗi search posts: {e}")
            return pd.DataFrame()

    def get_forex_data(
        self, 
        timeframe: str = '1H', 
        source_url: Optional[str] = None, 
        limit: int = 1000
    ) -> pd.DataFrame:
        """Lấy dữ liệu cho biểu đồ forex từ interactions data.

        Args:
            timeframe: Khung thời gian ('15T', '1H', '4H', '1D')
            source_url: Lọc theo nguồn cụ thể (None = tất cả)
            limit: Số lượng candles tối đa

        Returns:
            DataFrame với OHLC data và volume
        """
        try:
            # Build base query
            where_clause = ""
            params = []
            
            if source_url:
                where_clause = "WHERE p.source_url = %s"
                params.append(source_url)

            query = f"""
            SELECT 
                i.log_timestamp_utc,
                i.like_count,
                i.comment_count,
                i.post_signature
            FROM interactions i
            INNER JOIN posts p ON i.post_signature = p.post_signature
            {where_clause}
            ORDER BY i.log_timestamp_utc ASC
            LIMIT {limit * 10}
            """

            df = self._execute_pandas_query(query, tuple(params) if params else None)

            if df.empty:
                logger.warning("⚠️ Không có dữ liệu interactions cho forex chart")
                return pd.DataFrame()

            # Convert timestamp to datetime with ISO8601 format support
            df['timestamp'] = pd.to_datetime(df['log_timestamp_utc'], format='ISO8601')
            df.set_index('timestamp', inplace=True)

            # Resample theo timeframe và tạo OHLC data
            # Sử dụng like_count như "price", comment_count như "volume"
            ohlc_data = df.groupby('post_signature')['like_count'].resample(timeframe.replace('H', 'h')).agg({
                'open': 'first',
                'high': 'max', 
                'low': 'min',
                'close': 'last'
            }).reset_index()

            # Volume data (sum của comments trong mỗi timeframe)
            volume_data = df.groupby('post_signature')['comment_count'].resample(timeframe.replace('H', 'h')).sum().reset_index()
            volume_data.rename(columns={'comment_count': 'volume'}, inplace=True)

            # Merge OHLC với volume
            forex_df = pd.merge(
                ohlc_data,
                volume_data,
                on=['post_signature', 'timestamp'],
                how='left'
            )

            # Fill NaN values
            forex_df = forex_df.ffill().fillna(0)

            # Aggregate tất cả posts thành một "market"
            market_data = forex_df.groupby('timestamp').agg({
                'open': 'mean',
                'high': 'max',
                'low': 'min', 
                'close': 'mean',
                'volume': 'sum'
            }).reset_index()

            # Sort by timestamp
            market_data.sort_values('timestamp', inplace=True)

            logger.info(f"💹 Generated {len(market_data)} forex candles for timeframe {timeframe}")
            return market_data

        except Exception as e:
            logger.error(f"❌ Lỗi generate forex data: {e}")
            return pd.DataFrame()

    def close(self) -> None:
        """✅ FIX: Cleanup database connections and SQLAlchemy engine."""
        try:
            if self.engine:
                self.engine.dispose()
                logger.info("🔒 SQLAlchemy engine disposed")
            if self.db_manager:
                self.db_manager.close()
                logger.info("🔒 DatabaseManager closed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

    def __del__(self) -> None:
        """✅ FIX: Destructor to ensure cleanup on object deletion."""
        self.close()


# Singleton instance for use across Streamlit app
db_reader = DatabaseReader()


# Helper functions for easy import in Streamlit pages
def get_system_overview() -> Dict[str, Any]:
    """Wrapper function cho system overview."""
    return db_reader.get_system_overview()


def get_top_viral_posts(
    source_url: Optional[str] = None, 
    limit: int = 10, 
    apply_quality_filter: bool = False
) -> pd.DataFrame:
    """Wrapper function cho viral posts."""
    return db_reader.get_top_viral_posts(
        source_url=source_url, 
        limit=limit, 
        apply_quality_filter=apply_quality_filter
    )


def get_source_urls() -> List[str]:
    """Wrapper function cho source URLs."""
    return db_reader.get_source_urls()


def get_post_details(post_signature: str) -> Optional[Dict[str, Any]]:
    """Wrapper function cho post details."""
    return db_reader.get_post_details(post_signature)


def get_post_chart_data(post_signature: str) -> Dict[str, pd.DataFrame]:
    """Wrapper function cho chart data."""
    return db_reader.get_post_chart_data(post_signature)


def get_all_targets_comparison_data() -> pd.DataFrame:
    """Wrapper function cho targets comparison data."""
    return db_reader.get_all_targets_comparison_data()


def search_posts_by_content(search_term: str, limit: int = 20) -> pd.DataFrame:
    """Wrapper function cho search posts."""
    return db_reader.search_posts_by_content(search_term, limit)


def get_forex_data(timeframe: str = '1H', source_url: Optional[str] = None, limit: int = 1000) -> pd.DataFrame:
    """Wrapper function cho forex data."""
    return db_reader.get_forex_data(timeframe=timeframe, source_url=source_url, limit=limit)


if __name__ == "__main__":
    # Test functions
    logging.basicConfig(level=logging.INFO)

    print("🧪 Testing DatabaseReader...")

    # Test system overview
    overview = get_system_overview()
    print(f"✅ System Overview: {overview}")

    # Test viral posts
    viral_posts = get_top_viral_posts(limit=5)
    print(f"✅ Top Viral Posts: {len(viral_posts)} found")

    # Test source URLs
    sources = get_source_urls()
    print(f"✅ Source URLs: {len(sources)} found")

    print("🎉 DatabaseReader test completed!")