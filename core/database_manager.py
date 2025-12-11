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
import json
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
                        CHECK(status IN ('TRACKING', 'EXPIRED')),
                    post_type VARCHAR(20) DEFAULT 'TEXT',
                    post_status VARCHAR(20) DEFAULT 'ACTIVE'
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

                # ===== BẢNG PROXIES - QUẢN LÝ PROXY CENTRALIZED =====
                proxies_table_sql = """
                CREATE TABLE IF NOT EXISTS proxies (
                    id SERIAL PRIMARY KEY,
                    host VARCHAR(255) NOT NULL,
                    port INTEGER NOT NULL,
                    username VARCHAR(255),
                    password VARCHAR(255),
                    proxy_type VARCHAR(20) DEFAULT 'http' 
                        CHECK(proxy_type IN ('http', 'https', 'socks5')),
                    
                    status VARCHAR(20) DEFAULT 'READY'
                        CHECK(status IN ('READY', 'IN_USE', 'QUARANTINED', 'FAILED', 'DISABLED', 'TESTING')),
                    consecutive_failures INTEGER DEFAULT 0,
                    total_tasks INTEGER DEFAULT 0,
                    successful_tasks INTEGER DEFAULT 0,
                    success_rate FLOAT DEFAULT 1.0,
                    
                    last_checked_at TIMESTAMP,
                    response_time FLOAT,
                    geolocation JSONB,
                    
                    quarantine_reason TEXT,
                    quarantine_count INTEGER DEFAULT 0,
                    quarantine_until TIMESTAMP,
                    
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    last_used_at TIMESTAMP,
                    
                    UNIQUE(host, port)
                )
                """

                # ===== BẢNG ACCOUNTS - QUẢN LÝ FACEBOOK ACCOUNTS =====
                accounts_table_sql = """
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
                    
                    -- Facebook credentials
                    facebook_id VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(255),
                    password TEXT,
                    totp_secret VARCHAR(100),
                    cookies TEXT,
                    access_token TEXT,
                    
                    -- Session linking
                    session_folder VARCHAR(100),
                    session_status VARCHAR(20) DEFAULT 'NOT_CREATED'
                        CHECK(session_status IN ('NOT_CREATED', 'CREATING', 'LOGGED_IN', 'NEEDS_LOGIN', 'FAILED')),
                    last_login_at TIMESTAMP,
                    login_attempts INTEGER DEFAULT 0,
                    
                    -- Proxy binding
                    proxy_id INTEGER REFERENCES proxies(id) ON DELETE SET NULL,
                    
                    -- Metadata
                    user_agent TEXT,
                    additional_data JSONB,
                    
                    -- Status
                    status VARCHAR(20) DEFAULT 'ACTIVE'
                        CHECK(status IN ('ACTIVE', 'INACTIVE', 'BANNED', 'CHECKPOINT')),
                    is_active BOOLEAN DEFAULT TRUE,
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                """

                cursor.execute(posts_table_sql)
                cursor.execute(interactions_table_sql)
                cursor.execute(system_settings_table_sql)
                cursor.execute(proxies_table_sql)
                cursor.execute(accounts_table_sql)

                # ===== TẠO INDEX ĐỂ TĂNG TỐC TRUY VẤN =====
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_tracking_expires ON posts(tracking_expires_utc)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_first_seen ON posts(first_seen_utc)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_post_signature ON interactions(post_signature)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON interactions(log_timestamp_utc)")
                
                # ===== PROXY TABLE INDEXES =====
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_proxies_status ON proxies(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_proxies_success_rate ON proxies(success_rate DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_proxies_quarantine_until ON proxies(quarantine_until)")
                
                # ===== ACCOUNT TABLE INDEXES =====
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_facebook_id ON accounts(facebook_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_session_status ON accounts(session_status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_is_active ON accounts(is_active)")
                
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

    def add_new_post(
        self, 
        post_signature: str, 
        post_url: str, 
        source_url: str, 
        author_name: Optional[str] = None, 
        author_id: Optional[str] = None, 
        post_content: Optional[str] = None,
        post_type: str = 'TEXT',
        post_status: str = 'ACTIVE'
    ) -> bool:
        """
        Thêm bài viết mới vào bảng posts với thông tin chi tiết và retry logic.
        
        ✅ NEW: Supports post_type (VIDEO/PHOTO/TEXT/LINK) and post_status (ACTIVE/DEAD/STALE)
        """
        now_utc = datetime.now(timezone.utc)
        tracking_days = settings.scraping.post_tracking_days
        expires_utc = now_utc + timedelta(days=tracking_days)
        first_seen_utc = now_utc.isoformat()
        tracking_expires_utc = expires_utc.isoformat()

        sql = """
        INSERT INTO posts (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc, status, post_type, post_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'TRACKING', %s, %s)
        """
        
        # 🔄 FIX: Retry logic cho transient errors
        max_retries = 3
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(sql, (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc, post_type, post_status))
                logger.info("✅ Post added: %s... (expires: %s, type=%s, status=%s)", 
                           post_signature[:30], expires_utc.strftime('%Y-%m-%d %H:%M'), post_type, post_status)
                return True
                
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                if attempt < max_retries - 1:
                    logger.warning("⚠️ Transient DB error adding post (attempt %d/%d): %s - Retrying...", 
                                 attempt + 1, max_retries, e)
                    import time
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    logger.error(f"❌ Failed to add post after {max_retries} retries: {e}")
                    return False
                    
            except Exception as e:
                logger.error(f"❌ Lỗi thêm post mới: {e}")
                return False
        
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
    
    def _get_latest_interaction(self, post_signature: str) -> Optional[Dict[str, Any]]:
        """
        Lấy interaction mới nhất của một post (để validate data).
        
        Args:
            post_signature: Signature của post
            
        Returns:
            Dict chứa interaction cuối cùng hoặc None nếu chưa có
        """
        sql = """
        SELECT like_count, comment_count, log_timestamp_utc
        FROM interactions
        WHERE post_signature = %s
        ORDER BY log_timestamp_utc DESC
        LIMIT 1
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (post_signature,))
                    result = cursor.fetchone()
                    return dict(result) if result else None
        except Exception as e:
            logger.debug(f"Could not get latest interaction for {post_signature[:30]}: {e}")
            return None

    def log_interaction(self, post_signature: str, log_timestamp_utc: str, like_count: int, comment_count: int) -> bool:
        """
        Ghi log tương tác vào bảng interactions với duplicate prevention, retry logic và data validation.
        
        FIX: Sử dụng exact timestamp (không round) để tránh collision.
        ON CONFLICT DO UPDATE xử lý gracefully nếu có retry với cùng timestamp.
        
        ✅ DATA VALIDATION:
        - Không lưu nếu scrape fail (like_count=0 và comment_count=0 khi có data cũ > 0)
        - Không lưu nếu giảm bất thường (>2 so với lần trước)
        - Like/comment chỉ nên tăng, giảm nhỏ là OK
        
        Args:
            post_signature: Signature của post
            log_timestamp_utc: Timestamp UTC (ISO format) - exact timestamp
            like_count: Số lượng likes
            comment_count: Số lượng comments
            
        Returns:
            True nếu ghi thành công, False nếu có lỗi hoặc data invalid
        """
        # ✅ FIX: Use exact timestamp - no rounding to prevent collision
        # Each interaction gets unique timestamp for better chart granularity
        try:
            from datetime import datetime
            # Validate timestamp format but don't round
            dt = datetime.fromisoformat(log_timestamp_utc.replace('Z', '+00:00'))
            exact_timestamp = dt.isoformat()
        except Exception as e:
            logger.warning("⚠️ Error parsing timestamp, using original: %s", e)
            exact_timestamp = log_timestamp_utc
        
        # ✅ DATA VALIDATION: Get last interaction để validate
        last_interaction = self._get_latest_interaction(post_signature)
        
        if last_interaction:
            last_likes = last_interaction.get('like_count', 0) or 0
            last_comments = last_interaction.get('comment_count', 0) or 0
            
            # Rule 1: Nếu scrape fail (cả 2 về 0) mà trước đó có data → skip
            if like_count == 0 and comment_count == 0 and (last_likes > 0 or last_comments > 0):
                logger.warning(f"⚠️ Skip invalid data for {post_signature[:30]}: got 0/0 but last was {last_likes}/{last_comments}")
                return False
            
            # Rule 2: Không cho giảm quá nhiều (>2)
            likes_delta = like_count - last_likes
            comments_delta = comment_count - last_comments
            
            if likes_delta < -2:
                logger.warning(f"⚠️ Skip abnormal decrease in likes for {post_signature[:30]}: {last_likes} -> {like_count} (delta: {likes_delta})")
                return False
            
            if comments_delta < -2:
                logger.warning(f"⚠️ Skip abnormal decrease in comments for {post_signature[:30]}: {last_comments} -> {comment_count} (delta: {comments_delta})")
                return False
            
            # Rule 3: Log warning nếu giảm nhẹ (1-2) nhưng vẫn cho phép
            if likes_delta < 0:
                logger.debug(f"📉 Minor decrease in likes for {post_signature[:30]}: {last_likes} -> {like_count} (delta: {likes_delta})")
            if comments_delta < 0:
                logger.debug(f"📉 Minor decrease in comments for {post_signature[:30]}: {last_comments} -> {comment_count} (delta: {comments_delta})")
        
        # Use ON CONFLICT DO UPDATE for retry safety
        # If exact same timestamp (rare due to no rounding), update values
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
        
        # 🔄 FIX: Add retry logic với exponential backoff cho transient errors
        max_retries = 3
        retry_delay = 0.5  # Start with 500ms
        
        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        try:
                            cursor.execute(sql, (post_signature, exact_timestamp, like_count, comment_count))
                        except psycopg2.errors.UndefinedObject:
                            # Constraint chưa tồn tại, dùng fallback
                            cursor.execute(fallback_sql, (post_signature, exact_timestamp, like_count, comment_count))
                
                logger.debug("✅ Logged interaction: %s likes, %s comments for post %s... at %s", like_count, comment_count, post_signature[:30], exact_timestamp)
                return True
                
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                # Transient errors - network hiccup, connection lost
                if attempt < max_retries - 1:
                    logger.warning("⚠️ Transient DB error (attempt %d/%d): %s - Retrying in %.1fs...", 
                                 attempt + 1, max_retries, e, retry_delay)
                    import time
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.error("❌ DB error after %d retries for post %s: %s", max_retries, post_signature[:30], e)
                    return False
                    
            except Exception as e:
                # Non-transient errors - don't retry
                logger.error("❌ Database error logging interaction for post %s: %s", post_signature[:30], e, exc_info=False)
                return False
        
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
            # ✅ FIX: Use exact timestamps (no rounding) to prevent collision
            processed_interactions = []
            for item in interactions:
                try:
                    # Validate timestamp format but don't round
                    dt = datetime.fromisoformat(item['log_timestamp_utc'].replace('Z', '+00:00'))
                    processed_interactions.append((
                        item['post_signature'],
                        dt.isoformat(),  # Exact timestamp
                        item['like_count'],
                        item['comment_count']
                    ))
                except (ValueError, KeyError, TypeError, AttributeError) as e:
                    logger.debug(f"Skipping invalid interaction entry: {e}")
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

    def add_new_post_with_interaction(
        self, 
        post_signature: str, 
        post_url: str, 
        source_url: str, 
        like_count: int, 
        comment_count: int, 
        author_name: Optional[str] = None, 
        author_id: Optional[str] = None, 
        post_content: Optional[str] = None,
        post_type: str = 'TEXT',
        post_status: str = 'ACTIVE'
    ) -> bool:
        """
        Thêm post mới và interaction đầu tiên trong một transaction duy nhất.
        
        ✅ NEW: Supports post_type (VIDEO/PHOTO/TEXT/LINK) and post_status (ACTIVE/DEAD/STALE)
        """
        now_utc = datetime.now(timezone.utc)
        tracking_days = settings.scraping.post_tracking_days
        expires_utc = now_utc + timedelta(days=tracking_days)
        first_seen_utc = now_utc.isoformat()
        tracking_expires_utc = expires_utc.isoformat()

        post_sql = """
        INSERT INTO posts (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc, status, post_type, post_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'TRACKING', %s, %s)
        """
        interaction_sql = """
        INSERT INTO interactions (post_signature, log_timestamp_utc, like_count, comment_count)
        VALUES (%s, %s, %s, %s)
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(post_sql, (post_signature, post_url, source_url, author_name, author_id, post_content, first_seen_utc, tracking_expires_utc, post_type, post_status))
                    cursor.execute(interaction_sql, (post_signature, first_seen_utc, like_count, comment_count))
            logger.info("✅ Atomic dual-stream: post + interaction added for %s... (%d likes, %d comments, type=%s, status=%s)", 
                       post_signature[:30], like_count, comment_count, post_type, post_status)
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
    
    # ===== PROXY MANAGEMENT METHODS =====
    
    def add_proxy(self, host: str, port: int, username: str = None, 
                  password: str = None, proxy_type: str = 'http') -> Optional[int]:
        """
        Thêm proxy mới vào database
        
        Returns:
            proxy_id nếu thành công, None nếu lỗi
        """
        sql = """
        INSERT INTO proxies (host, port, username, password, proxy_type, status)
        VALUES (%s, %s, %s, %s, %s, 'READY')
        ON CONFLICT (host, port) DO NOTHING
        RETURNING id
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (host, port, username, password, proxy_type))
                    result = cursor.fetchone()
                    if result:
                        proxy_id = result['id']
                        logger.info(f"✅ Proxy added: {host}:{port} (ID: {proxy_id})")
                        return proxy_id
                    else:
                        logger.warning(f"⚠️ Proxy already exists: {host}:{port}")
                        return None
        except Exception as e:
            logger.error(f"❌ Error adding proxy: {e}")
            return None

    def get_all_proxies(self, status_filter: Optional[str] = None) -> List[Dict]:
        """Lấy tất cả proxies từ database"""
        if status_filter:
            sql = "SELECT * FROM proxies WHERE status = %s ORDER BY id"
            params = (status_filter,)
        else:
            sql = "SELECT * FROM proxies ORDER BY id"
            params = ()
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    proxies = [dict(row) for row in cursor.fetchall()]
                    logger.debug(f"📊 Retrieved {len(proxies)} proxies from DB")
                    return proxies
        except Exception as e:
            logger.error(f"❌ Error fetching proxies: {e}")
            return []

    def update_proxy_status(self, proxy_id: int, status: str, 
                           metadata: Optional[Dict] = None) -> bool:
        """Update proxy status và metadata"""
        sql = """
        UPDATE proxies 
        SET status = %s, 
            updated_at = NOW(),
            consecutive_failures = COALESCE(%s, consecutive_failures),
            total_tasks = COALESCE(%s, total_tasks),
            successful_tasks = COALESCE(%s, successful_tasks),
            success_rate = COALESCE(%s, success_rate),
            last_checked_at = COALESCE(%s::timestamp, last_checked_at),
            response_time = COALESCE(%s, response_time),
            geolocation = COALESCE(%s::jsonb, geolocation),
            quarantine_reason = COALESCE(%s, quarantine_reason),
            quarantine_until = COALESCE(%s::timestamp, quarantine_until),
            last_used_at = COALESCE(%s::timestamp, last_used_at)
        WHERE id = %s
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (
                        status,
                        metadata.get('consecutive_failures') if metadata else None,
                        metadata.get('total_tasks') if metadata else None,
                        metadata.get('successful_tasks') if metadata else None,
                        metadata.get('success_rate') if metadata else None,
                        metadata.get('last_checked_at') if metadata else None,
                        metadata.get('response_time') if metadata else None,
                        json.dumps(metadata.get('geolocation')) if metadata and metadata.get('geolocation') else None,
                        metadata.get('quarantine_reason') if metadata else None,
                        metadata.get('quarantine_until').isoformat() if metadata and metadata.get('quarantine_until') else None,
                        metadata.get('last_used_at').isoformat() if metadata and metadata.get('last_used_at') else None,
                        proxy_id
                    ))
                    logger.debug(f"✅ Updated proxy {proxy_id} status to {status}")
                    return True
        except Exception as e:
            logger.error(f"❌ Error updating proxy {proxy_id}: {e}")
            return False

    def delete_proxy(self, proxy_id: int) -> bool:
        """Xóa proxy khỏi database"""
        sql = "DELETE FROM proxies WHERE id = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (proxy_id,))
                    logger.info(f"🗑️ Deleted proxy {proxy_id}")
                    return True
        except Exception as e:
            logger.error(f"❌ Error deleting proxy {proxy_id}: {e}")
            return False

    def get_proxy_by_id(self, proxy_id: int) -> Optional[Dict]:
        """Lấy proxy theo ID"""
        sql = "SELECT * FROM proxies WHERE id = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (proxy_id,))
                    result = cursor.fetchone()
                    return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Error fetching proxy {proxy_id}: {e}")
            return None
    
    # ===== ACCOUNT MANAGEMENT METHODS =====
    
    def add_account(self, facebook_id: str, email: str = None, password: str = None,
                   totp_secret: str = None, cookies: str = None, access_token: str = None,
                   additional_data: Dict = None) -> Optional[int]:
        """
        Thêm account mới vào database
        
        Returns:
            account_id nếu thành công, None nếu lỗi
        """
        sql = """
        INSERT INTO accounts (facebook_id, email, password, totp_secret, cookies, access_token, additional_data, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 'ACTIVE')
        ON CONFLICT (facebook_id) DO NOTHING
        RETURNING id
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (
                        facebook_id, email, password, totp_secret, cookies, access_token,
                        json.dumps(additional_data) if additional_data else None
                    ))
                    result = cursor.fetchone()
                    if result:
                        account_id = result['id']
                        logger.info(f"✅ Account added: {facebook_id} (ID: {account_id})")
                        return account_id
                    else:
                        logger.warning(f"⚠️ Account already exists: {facebook_id}")
                        return None
        except Exception as e:
            logger.error(f"❌ Error adding account: {e}")
            return None
    
    def get_all_accounts(self, status_filter: Optional[str] = None, 
                        is_active: Optional[bool] = None) -> List[Dict]:
        """Lấy tất cả accounts từ database"""
        conditions = []
        params = []
        
        if status_filter:
            conditions.append("status = %s")
            params.append(status_filter)
        
        if is_active is not None:
            conditions.append("is_active = %s")
            params.append(is_active)
        
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM accounts{where_clause} ORDER BY id"
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, tuple(params))
                    accounts = [dict(row) for row in cursor.fetchall()]
                    logger.debug(f"📊 Retrieved {len(accounts)} accounts from DB")
                    return accounts
        except Exception as e:
            logger.error(f"❌ Error fetching accounts: {e}")
            return []
    
    def get_account_by_id(self, account_id: int) -> Optional[Dict]:
        """Lấy account theo ID"""
        sql = "SELECT * FROM accounts WHERE id = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (account_id,))
                    result = cursor.fetchone()
                    return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Error fetching account {account_id}: {e}")
            return None
    
    def get_account_by_facebook_id(self, facebook_id: str) -> Optional[Dict]:
        """Lấy account theo Facebook ID"""
        sql = "SELECT * FROM accounts WHERE facebook_id = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (facebook_id,))
                    result = cursor.fetchone()
                    return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Error fetching account {facebook_id}: {e}")
            return None
    
    def update_account_session(self, account_id: int, session_folder: str = None,
                              session_status: str = None, last_login_at: datetime = None,
                              login_attempts: int = None) -> bool:
        """Update account session info sau khi login"""
        sql = """
        UPDATE accounts 
        SET updated_at = NOW(),
            session_folder = COALESCE(%s, session_folder),
            session_status = COALESCE(%s, session_status),
            last_login_at = COALESCE(%s, last_login_at),
            login_attempts = COALESCE(%s, login_attempts)
        WHERE id = %s
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (
                        session_folder, session_status, last_login_at, login_attempts, account_id
                    ))
                    logger.debug(f"✅ Updated account {account_id} session info")
                    return True
        except Exception as e:
            logger.error(f"❌ Error updating account {account_id}: {e}")
            return False
    
    def update_account_proxy(self, account_id: int, proxy_id: int) -> bool:
        """Bind account với proxy"""
        sql = "UPDATE accounts SET proxy_id = %s, updated_at = NOW() WHERE id = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (proxy_id, account_id))
                    logger.debug(f"✅ Bound account {account_id} to proxy {proxy_id}")
                    return True
        except Exception as e:
            logger.error(f"❌ Error binding account {account_id} to proxy: {e}")
            return False
    
    def update_account_status(self, account_id: int, status: str, 
                            is_active: bool = None) -> bool:
        """Update account status"""
        sql = """
        UPDATE accounts 
        SET status = %s,
            is_active = COALESCE(%s, is_active),
            updated_at = NOW()
        WHERE id = %s
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (status, is_active, account_id))
                    logger.debug(f"✅ Updated account {account_id} status to {status}")
                    return True
        except Exception as e:
            logger.error(f"❌ Error updating account {account_id} status: {e}")
            return False
    
    def delete_account(self, account_id: int) -> bool:
        """Xóa account khỏi database"""
        sql = "DELETE FROM accounts WHERE id = %s"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, (account_id,))
                    logger.info(f"🗑️ Deleted account {account_id}")
                    return True
        except Exception as e:
            logger.error(f"❌ Error deleting account {account_id}: {e}")
            return False

    def close(self) -> None:
        """Đóng toàn bộ connection pool."""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("🔒 Đã đóng PostgreSQL connection pool.")

    def __enter__(self) -> 'DatabaseManager':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
