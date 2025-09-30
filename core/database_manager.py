#!/usr/bin/env python3
"""
Database Manager for Facebook Post Monitor - Enterprise Edition.

(Full Data Phase 3.0 - Complete Data Schema)

Chịu trách nhiệm:
- Khởi tạo kết nối đến PostgreSQL database
- Tạo và quản lý hai bảng: posts (dữ liệu tĩnh) và interactions (time-series)
- Cung cấp methods cho logic Dual-Stream: ghi posts một lần,
  theo dõi interactions liên tục
- Quản lý lifecycle của posts (TRACKING → EXPIRED)
"""

# Add project root to Python path for imports
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# PostgreSQL-only database imports
import psycopg2
from psycopg2 import pool # Thêm import này
from psycopg2.extras import RealDictCursor

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from config import settings

logger = get_logger(__name__)

# Constants
DEFAULT_INTERACTION_HISTORY_LIMIT = 100
DEFAULT_CLEANUP_DAYS = 30
DB_PLACEHOLDER_POSTGRES = "%s"


class DatabaseManager:
    """
    Lớp quản lý cơ sở dữ liệu PostgreSQL cho Facebook Post Monitor
    (Production Ready - PostgreSQL Only)

    Thiết kế schema Full Data:
    - posts: Lưu thông tin chi tiết của bài viết
      (ghi MỘT LẦN khi phát hiện)
    - interactions: Lưu dữ liệu time-series tương tác
      (ghi LIÊN TỤC theo dõi)

    Logic Dual-Stream:
    1. Phát hiện post mới → Ghi vào bảng posts với status='TRACKING'
    2. Thu thập interactions → Ghi liên tục vào bảng interactions
    3. Hết hạn theo dõi → Chuyển posts sang status='EXPIRED'
    """

    def __init__(self) -> None:
        """
        Khởi tạo DatabaseManager với PostgreSQL.
        
        Thiết lập kết nối tới database và tạo schema nếu cần thiết.
        """
        self.db_config = settings.database
        self.connection_pool = None
        self.connection_timeout = self.db_config.connection_timeout
        self.max_retries = self.db_config.max_retries
        
        logger.info("🗄️ Khởi tạo DatabaseManager với PostgreSQL: %s@%s:%d/%s", 
                   self.db_config.user, self.db_config.host, 
                   self.db_config.port, self.db_config.name)

        # Khởi tạo kết nối và tạo bảng
        self._initialize_database()

    def _initialize_database(self) -> None:
        """
        Khởi tạo kết nối PostgreSQL và tạo bảng nếu chưa tồn tại.
        
        Raises:
            Exception: Nếu không thể kết nối tới database
        """
        try:
            self.connection_pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=self.db_config.pool_size, # Use from config
                host=self.db_config.host,
                port=self.db_config.port,
                user=self.db_config.user,
                password=self.db_config.password,
                dbname=self.db_config.name,
                cursor_factory=RealDictCursor
            )
            logger.info("✅ Khởi tạo PostgreSQL ThreadedConnectionPool (Thread-Safe) thành công.")

            with self.get_connection() as conn:
                self._create_tables(conn)

        except Exception as e:
            logger.error("❌ Lỗi khởi tạo database pool: %s", e)
            raise

    @contextmanager
    def get_connection(self):
        """
        Context manager an toàn để lấy và trả kết nối từ pool.
        
        FIX: Ensures connection is ALWAYS returned to pool, even if commit fails.
        
        Yields:
            Connection object from pool
            
        Raises:
            RuntimeError: If connection pool not initialized
        """
        if not self.connection_pool:
            raise RuntimeError("Connection pool chưa được khởi tạo")

        connection = None
        try:
            connection = self.connection_pool.getconn()
            yield connection
        except Exception:
            # Rollback nếu có exception từ yield block
            if connection:
                try:
                    connection.rollback()
                except Exception as rollback_error:
                    logger.error("❌ Rollback failed: %s", rollback_error)
            raise  # Re-raise original exception
        else:
            # ✅ FIX: Only commit if yield block succeeded (no exception)
            # This runs before finally, so if commit fails, we still return connection
            if connection:
                try:
                    connection.commit()
                except Exception as commit_error:
                    logger.error("❌ Commit failed: %s", commit_error)
                    # Try to rollback after failed commit
                    try:
                        connection.rollback()
                    except Exception as rollback_error:
                        logger.error("❌ Rollback after commit failure failed: %s", rollback_error)
                    raise  # Re-raise commit error
        finally:
            # ✅ GUARANTEED: Always return connection to pool
            if connection:
                try:
                    self.connection_pool.putconn(connection)
                except Exception as putconn_error:
                    logger.error("❌ Failed to return connection to pool: %s", putconn_error)

    def _create_tables(self, connection) -> None:
        """
        Tạo bảng posts và interactions theo schema PostgreSQL.
        """
        try:
            with connection.cursor() as cursor:
                # ===== BẢNG POSTS - DỮ LIỆU TĨNH CHI TIẾT =====
                posts_table_sql = """
                CREATE TABLE IF NOT EXISTS posts (
                    post_signature TEXT PRIMARY KEY,
                    post_url TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    author_name TEXT,
                    author_id TEXT,
                    post_content TEXT,
                    first_seen_utc TEXT NOT NULL,
                    tracking_expires_utc TEXT NOT NULL,
                    status TEXT DEFAULT 'TRACKING'
                        CHECK(status IN ('TRACKING', 'EXPIRED'))
                )
                """

                # ===== BẢNG INTERACTIONS - DỮ LIỆU TIME-SERIES =====
                interactions_table_sql = """
                CREATE TABLE IF NOT EXISTS interactions (
                    id SERIAL PRIMARY KEY,
                    post_signature TEXT,
                    log_timestamp_utc TEXT,
                    like_count INTEGER,
                    comment_count INTEGER
                )
                """

                # ===== BẢNG SYSTEM_SETTINGS - CÀI ĐẶT HỆ THỐNG =====
                system_settings_table_sql = """
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                """

                cursor.execute(posts_table_sql)
                cursor.execute(interactions_table_sql)
                cursor.execute(system_settings_table_sql)

                # ===== TẠO INDEX ĐỂ TĂNG TỐC TRUY VẤN =====
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_tracking_expires ON posts(tracking_expires_utc)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_first_seen ON posts(first_seen_utc)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_post_signature ON interactions(post_signature)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON interactions(log_timestamp_utc)")
                
                # ===== ADD UNIQUE CONSTRAINT TO PREVENT DUPLICATES =====
                # Unique constraint on (post_signature, log_timestamp_utc) to prevent
                # duplicate interaction logs for same post at same time
                cursor.execute("""
                    DO $$ 
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint 
                            WHERE conname = 'unique_post_timestamp'
                        ) THEN
                            ALTER TABLE interactions
                            ADD CONSTRAINT unique_post_timestamp 
                            UNIQUE (post_signature, log_timestamp_utc);
                        END IF;
                    END $$;
                """)

            logger.info("✅ Tạo bảng posts, interactions, system_settings và index thành công (PostgreSQL)")

        except Exception as e:
            logger.error("❌ Lỗi tạo bảng: %s", e)
            raise

    def is_post_new(self, post_signature: str) -> bool:
        """
        Kiểm tra xem bài viết có phải là mới hay không.
        
        Args:
            post_signature: Signature của post cần kiểm tra
            
        Returns:
            True nếu post chưa tồn tại (mới), False nếu đã tồn tại hoặc có lỗi
        """
        sql = "SELECT 1 FROM posts WHERE post_signature = %s LIMIT 1"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (post_signature,))
                    result = cur.fetchone()
                    is_new = result is None
                    logger.debug("🔍 Post signature '%s...': %s", post_signature[:50], 'MỚI' if is_new else 'ĐÃ TỒN TẠI')
                    return is_new
        except Exception as e:
            logger.error("❌ Database error checking if post is new (%s): %s", post_signature[:30], e, exc_info=False)
            # Return False on error (treat as existing to avoid duplicate processing)
            return False
    
    def get_existing_post_signatures_batch(self, signatures: List[str]) -> set:
        """
        Batch check existing posts - FIX for N+1 query problem.
        
        Args:
            signatures: List of post signatures to check
            
        Returns:
            Set of signatures that already exist in database
        """
        if not signatures:
            return set()
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Use ANY for efficient batch lookup
                    sql = "SELECT post_signature FROM posts WHERE post_signature = ANY(%s)"
                    cur.execute(sql, (signatures,))
                    existing = {row['post_signature'] for row in cur.fetchall()}
                    logger.debug(f"📊 Batch check: {len(existing)}/{len(signatures)} posts exist")
                    return existing
        except Exception as e:
            logger.error(f"❌ Batch signature check failed: {e}")
            return set()

    def add_new_post(self, post_signature: str, post_url: str, source_url: str, author_name: Optional[str] = None, author_id: Optional[str] = None, post_content: Optional[str] = None) -> bool:
        """Thêm bài viết mới vào bảng posts với thông tin chi tiết."""
        now_utc = datetime.now(timezone.utc)
        tracking_days = settings.scraping.post_tracking_days
        expires_utc = now_utc + timedelta(days=tracking_days)
        first_seen_utc = now_utc.isoformat()
        tracking_expires_utc = expires_utc.isoformat()

        sql = """
        INSERT INTO posts (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'TRACKING')
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc))
            logger.info("✅ Post added: %s... (expires: %s)", post_signature[:30], expires_utc.strftime('%Y-%m-%d %H:%M'))
            return True
        except Exception as e:
            logger.error(f"❌ Lỗi thêm post mới: {e}")
            return False

    def get_post_by_signature(self, post_signature: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin chi tiết của một post từ bảng posts."""
        sql = "SELECT * FROM posts WHERE post_signature = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (post_signature,))
                    result = cur.fetchone()
                    return dict(result) if result else None
        except Exception as e:
            logger.error("❌ Lỗi lấy thông tin post: %s", e)
            return None

    def log_interaction(self, post_signature: str, log_timestamp_utc: str, like_count: int, comment_count: int) -> bool:
        """
        Ghi log tương tác vào bảng interactions với duplicate prevention.
        
        ENHANCED: Sử dụng unique constraint trên (post_signature, rounded_timestamp)
        để tránh duplicate entries trong cùng khoảng thời gian (~1 phút)
        
        Args:
            post_signature: Signature của post
            log_timestamp_utc: Timestamp UTC (ISO format)
            like_count: Số lượng likes
            comment_count: Số lượng comments
            
        Returns:
            True nếu ghi thành công, False nếu có lỗi
        """
        # Round timestamp to nearest minute để tránh duplicate khi retry
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(log_timestamp_utc.replace('Z', '+00:00'))
            # Round to minute
            dt = dt.replace(second=0, microsecond=0)
            rounded_timestamp = dt.isoformat()
        except Exception as e:
            logger.warning("⚠️ Error rounding timestamp, using original: %s", e)
            rounded_timestamp = log_timestamp_utc
        
        # Use ON CONFLICT DO UPDATE to prevent duplicates
        sql = """
        INSERT INTO interactions (post_signature, log_timestamp_utc, like_count, comment_count)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT unique_post_timestamp 
        DO UPDATE SET 
            like_count = EXCLUDED.like_count,
            comment_count = EXCLUDED.comment_count
        """
        
        # Fallback query nếu constraint chưa tồn tại
        fallback_sql = """
        INSERT INTO interactions (post_signature, log_timestamp_utc, like_count, comment_count)
        VALUES (%s, %s, %s, %s)
        """
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    try:
                        cursor.execute(sql, (post_signature, rounded_timestamp, like_count, comment_count))
                    except psycopg2.errors.UndefinedObject:
                        # Constraint chưa tồn tại, dùng fallback
                        cursor.execute(fallback_sql, (post_signature, rounded_timestamp, like_count, comment_count))
            
            logger.debug("✅ Logged interaction: %s likes, %s comments for post %s...", like_count, comment_count, post_signature[:30])
            return True
        except Exception as e:
            logger.error("❌ Database error logging interaction for post %s: %s", post_signature[:30], e, exc_info=False)
            return False
    
    def log_interactions_batch(self, interactions: List[Dict[str, Any]]) -> int:
        """
        Batch insert interactions - FIX for N+1 query problem.
        
        Args:
            interactions: List of dicts with keys: post_signature, log_timestamp_utc, like_count, comment_count
            
        Returns:
            Number of interactions successfully inserted/updated
        """
        if not interactions:
            return 0
        
        try:
            # Round all timestamps
            processed_interactions = []
            for item in interactions:
                try:
                    dt = datetime.fromisoformat(item['log_timestamp_utc'].replace('Z', '+00:00'))
                    dt = dt.replace(second=0, microsecond=0)
                    processed_interactions.append((
                        item['post_signature'],
                        dt.isoformat(),
                        item['like_count'],
                        item['comment_count']
                    ))
                except:
                    # Skip invalid entries
                    continue
            
            if not processed_interactions:
                return 0
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Use executemany for batch insert
                    sql = """
                    INSERT INTO interactions (post_signature, log_timestamp_utc, like_count, comment_count)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT ON CONSTRAINT unique_post_timestamp 
                    DO UPDATE SET 
                        like_count = EXCLUDED.like_count,
                        comment_count = EXCLUDED.comment_count
                    """
                    cursor.executemany(sql, processed_interactions)
                    
            logger.info(f"📊 Batch logged {len(processed_interactions)} interactions")
            return len(processed_interactions)
            
        except Exception as e:
            logger.error(f"❌ Batch interaction logging failed: {e}")
            return 0

    def add_new_post_with_interaction(self, post_signature: str, post_url: str, source_url: str, like_count: int, comment_count: int, author_name: Optional[str] = None, author_id: Optional[str] = None, post_content: Optional[str] = None) -> bool:
        """Thêm post mới và interaction đầu tiên trong một transaction duy nhất."""
        now_utc = datetime.now(timezone.utc)
        tracking_days = settings.scraping.post_tracking_days
        expires_utc = now_utc + timedelta(days=tracking_days)
        first_seen_utc = now_utc.isoformat()
        tracking_expires_utc = expires_utc.isoformat()

        post_sql = """
        INSERT INTO posts (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'TRACKING')
        """
        interaction_sql = """
        INSERT INTO interactions (post_signature, log_timestamp_utc, like_count, comment_count)
        VALUES (%s, %s, %s, %s)
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(post_sql, (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc))
                    cursor.execute(interaction_sql, (post_signature, first_seen_utc, like_count, comment_count))
            logger.info("✅ Atomic dual-stream: post + interaction added for %s... (%d likes, %d comments)", post_signature[:30], like_count, comment_count)
            return True
        except Exception as e:
            logger.error(f"❌ Lỗi atomic add_new_post_with_interaction: {e}")
            return False

    def get_interaction_history(self, post_signature: str, limit: int = DEFAULT_INTERACTION_HISTORY_LIMIT) -> List[Dict[str, Any]]:
        """Lấy lịch sử tương tác của một post."""
        sql = "SELECT * FROM interactions WHERE post_signature = %s ORDER BY log_timestamp_utc DESC LIMIT %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (post_signature, limit))
                    results = cur.fetchall()
                    return [dict(row) for row in results]
        except Exception as e:
            logger.error("❌ Lỗi lấy lịch sử tương tác: %s", e)
            return []

    def get_stats(self) -> Dict[str, int]:
        """Lấy thống kê tổng quan database."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) as count FROM posts")
                    total_posts = cur.fetchone()['count']
                    cur.execute("SELECT COUNT(*) as count FROM posts WHERE status = 'TRACKING'")
                    tracking_posts = cur.fetchone()['count']
                    cur.execute("SELECT COUNT(*) as count FROM posts WHERE status = 'EXPIRED'")
                    expired_posts = cur.fetchone()['count']
                    cur.execute("SELECT COUNT(*) as count FROM interactions")
                    total_interactions = cur.fetchone()['count']
                    cur.execute("SELECT COUNT(*) as count FROM interactions WHERE log_timestamp_utc::date = CURRENT_DATE")
                    today_interactions = cur.fetchone()['count']
                    cur.execute("SELECT COUNT(*) as count FROM posts WHERE first_seen_utc::date = CURRENT_DATE")
                    today_new_posts = cur.fetchone()['count']
                    cur.execute("SELECT COUNT(DISTINCT post_signature) as count FROM posts")
                    unique_posts = cur.fetchone()['count']
                    stats = {
                        'total_posts': total_posts,
                        'tracking_posts': tracking_posts,
                        'expired_posts': expired_posts,
                        'unique_posts': unique_posts,
                        'total_interactions': total_interactions,
                        'today_interactions': today_interactions,
                        'today_new_posts': today_new_posts
                    }
                    logger.info(f"📊 Stats (Full Data): {total_posts} posts ({unique_posts} unique, {tracking_posts} tracking, {expired_posts} expired), {total_interactions} interactions, {today_new_posts} new posts hôm nay")
                    return stats
        except Exception as e:
            logger.error(f"❌ Lỗi lấy stats: {e}")
            return {}

    def cleanup_old_interactions(self, days_to_keep: int = DEFAULT_CLEANUP_DAYS) -> int:
        """
        Dọn dẹp các interactions cũ một cách an toàn.
        
        Args:
            days_to_keep: Số ngày giữ lại data (phải từ 1-3650)
            
        Returns:
            Số lượng interactions đã xóa
        """
        # Validate input nghiêm ngặt với upper bound
        if not isinstance(days_to_keep, int) or days_to_keep < 1 or days_to_keep > 3650:
            logger.error("Invalid days_to_keep value: %s (must be 1-3650)", days_to_keep)
            return 0
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Fix SQL Injection: Sử dụng timedelta thay vì string interpolation
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
                    
                    # Count old interactions
                    select_sql = "SELECT COUNT(*) as count FROM interactions WHERE log_timestamp_utc::timestamp < %s"
                    cursor.execute(select_sql, (cutoff_date,))
                    old_count = cursor.fetchone()['count']

                    if old_count > 0:
                        # Delete old interactions
                        delete_sql = "DELETE FROM interactions WHERE log_timestamp_utc::timestamp < %s"
                        cursor.execute(delete_sql, (cutoff_date,))
                        logger.info("🗑️ Đã dọn dẹp %d interactions cũ hơn %d ngày (cutoff: %s)", 
                                   old_count, days_to_keep, cutoff_date.isoformat())
                        return old_count
            return 0
        except Exception as e:
            logger.error("❌ Lỗi dọn dẹp interactions cũ: %s", e)
            return 0

    def get_active_tracking_posts(self) -> List[Dict[str, Any]]:
        """Lấy danh sách các posts đang được theo dõi."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    current_utc = datetime.now(timezone.utc).isoformat()
                    # Try optimized query first
                    # Use posts table directly (active_tracking_posts table doesn't exist)
                    sql = """
                        SELECT post_signature, post_url, source_url, tracking_expires_utc, first_seen_utc, 0 as priority_score
                        FROM posts
                        WHERE status = 'TRACKING' AND tracking_expires_utc > %s
                        ORDER BY first_seen_utc DESC
                    """
                    cursor.execute(sql, (current_utc,))
                    results = cursor.fetchall()
                    posts = [dict(row) for row in results]
                    logger.debug("📋 Tìm thấy %d posts đang được tracking (optimized)", len(posts))
                    return posts
        except Exception as e:
            logger.warning("⚠️ Optimized query failed, falling back to original: %s", e)
            return self._get_active_tracking_posts_fallback()

    def _get_active_tracking_posts_fallback(self) -> List[Dict[str, Any]]:
        """Fallback method using original posts table query."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    current_utc = datetime.now(timezone.utc).isoformat()
                    sql = """
                        SELECT post_signature, post_url, source_url, tracking_expires_utc, first_seen_utc, 0 as priority_score
                        FROM posts
                        WHERE status = 'TRACKING' AND tracking_expires_utc > %s
                        ORDER BY first_seen_utc DESC
                    """
                    cursor.execute(sql, (current_utc,))
                    results = cursor.fetchall()
                    posts = [dict(row) for row in results]
                    logger.debug("📋 Tìm thấy %d posts đang được tracking (fallback)", len(posts))
                    return posts
        except Exception as e:
            logger.error("❌ Lỗi lấy active tracking posts (fallback): %s", e)
            return []

    def expire_old_posts(self) -> int:
        """Chuyển các posts đã hết hạn theo dõi sang 'EXPIRED'."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Try optimized cleanup function first
                    try:
                        cursor.execute("SELECT cleanup_expired_tracking_posts()")
                        expired_count = cursor.fetchone()[0]
                        if expired_count > 0:
                            logger.info("🕐 Đã chuyển %d posts sang trạng thái EXPIRED (optimized)", expired_count)
                        return expired_count
                    except Exception:
                        return self._expire_old_posts_fallback(conn)
        except Exception as e:
            logger.error("❌ Lỗi expire old posts: %s", e)
            return 0

    def _expire_old_posts_fallback(self, conn) -> int:
        """Fallback method for expiring old posts."""
        with conn.cursor() as cursor:
            current_utc = datetime.now(timezone.utc).isoformat()
            sql_count = "SELECT COUNT(*) as count FROM posts WHERE status = 'TRACKING' AND tracking_expires_utc <= %s"
            cursor.execute(sql_count, (current_utc,))
            expired_count = cursor.fetchone()['count']

            if expired_count > 0:
                sql_update = "UPDATE posts SET status = 'EXPIRED' WHERE status = 'TRACKING' AND tracking_expires_utc <= %s"
                cursor.execute(sql_update, (current_utc,))
                logger.info("🕐 Đã chuyển %d posts sang trạng thái EXPIRED (fallback)", expired_count)
            return expired_count

    def update_post_priority(self, post_signature: str, priority_score: int) -> bool:
        """Cập nhật priority score cho một post."""
        # Use posts table since active_tracking_posts doesn't exist
        # Note: posts table doesn't have priority_score or last_updated_utc columns
        logger.warning("⚠️ update_post_priority called but posts table doesn't support priority_score")
        return True  # Return success to avoid breaking the flow

    def get_tracking_stats(self) -> Dict[str, Any]:
        """Lấy thống kê về active tracking posts."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    try:
                        cursor.execute("SELECT * FROM tracking_stats")
                        result = cursor.fetchone()
                        if result:
                            stats = dict(result)
                            logger.debug("📊 Tracking stats (optimized): %s", stats)
                            return stats
                    except Exception:
                        pass
                    
                    cursor.execute("""SELECT COUNT(*) as total_active_posts, COUNT(*) FILTER (WHERE tracking_expires_utc > NOW()::text) as valid_posts, COUNT(*) FILTER (WHERE tracking_expires_utc <= NOW()::text) as expired_posts FROM posts WHERE status = 'TRACKING'""")
                    result = cursor.fetchone()
                    if result:
                        stats = dict(result)
                        stats['avg_priority'] = 0
                        logger.debug("📊 Tracking stats (fallback): %s", stats)
                        return stats
            return {}
        except Exception as e:
            logger.error("❌ Lỗi lấy tracking stats: %s", e)
            return {}

    def set_setting(self, key: str, value: str) -> bool:
        """Lưu hoặc cập nhật một cài đặt hệ thống."""
        sql = "INSERT INTO system_settings (key, value, updated_at) VALUES (%s, %s, NOW()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (key, value))
                    logger.debug(f"✅ Set setting '{key}' = '{value}'")
                    return True
        except Exception as e:
            logger.error(f"❌ Lỗi khi set setting '{key}': {e}")
            return False

    def get_setting(self, key: str) -> Optional[str]:
        """
        Lấy một cài đặt hệ thống.
        
        Args:
            key: Key của setting cần lấy
            
        Returns:
            Value của setting hoặc None nếu không tìm thấy
        """
        sql = "SELECT value FROM system_settings WHERE key = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (key,))
                    result = cur.fetchone()
                    if result:
                        # FIX: Use dict key instead of index for RealDictCursor
                        value = result['value']
                        logger.debug("🔍 Got setting '%s' = '%s'", key, value)
                        return value
                    else:
                        logger.debug("🔍 Setting '%s' not found", key)
                        return None
        except Exception as e:
            logger.error("❌ Database error getting setting '%s': %s", key, e, exc_info=False)
            return None

    def _get_placeholder(self) -> str:
        """Return database placeholder for PostgreSQL."""
        return DB_PLACEHOLDER_POSTGRES

    def close(self) -> None:
        """Đóng toàn bộ connection pool."""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("🔒 Đã đóng PostgreSQL connection pool.")

    def __enter__(self) -> 'DatabaseManager':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
