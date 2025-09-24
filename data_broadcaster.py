#!/usr/bin/env python3
"""
Data Broadcaster for Facebook Post Monitor - Enterprise Edition Phase 3.2

Phát hiện thay đổi trong database và broadcast qua Redis Pub/Sub

Vai trò:
- Monitor database changes using PostgreSQL LISTEN/NOTIFY (replaced polling)
- Detect new interactions và post updates in real-time
- Broadcast events qua Redis Pub/Sub cho WebSocket clients
- Tái sử dụng DatabaseManager cho data access

Performance Improvement:
- Replaced database polling with PostgreSQL LISTEN/NOTIFY
- Near-zero database load for change detection
- Sub-second latency for real-time updates
"""

import asyncio
import json
import logging
from logging_config import get_logger, setup_application_logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set

import redis.asyncio as aioredis
import psycopg2  # type: ignore
from psycopg2.extras import RealDictCursor  # type: ignore

from core.database_manager import DatabaseManager

# Initialize centralized logging for data broadcasting
setup_application_logging()
logger = get_logger(__name__)


class DataBroadcaster:
    """
    Service để phát hiện và broadcast database changes.

    Sử dụng PostgreSQL LISTEN/NOTIFY để detect changes trong interactions table
    và broadcast qua Redis Pub/Sub cho real-time updates với near-zero database load
    """

    def __init__(self, redis_host: str = "redis", redis_port: int = 6379):
        """
        Khởi tạo DataBroadcaster.

        Args:
            redis_host: Redis server host
            redis_port: Redis server port
        """
        self.redis_host = redis_host
        self.redis_port = redis_port

        # Components
        self.db_manager: Optional[DatabaseManager] = None
        self.redis_client: Optional[aioredis.Redis] = None
        self.listen_connection: Optional[psycopg2.extensions.connection] = None

        # LISTEN/NOTIFY configuration
        self.notify_channel = "new_interaction"
        self.listen_timeout = 5.0  # Timeout cho LISTEN (seconds)

        # State tracking
        self.known_posts: Set[str] = set()  # Track posts đã biết
        self.last_stats_broadcast = 0  # Timestamp stats broadcast cuối
        self.stats_broadcast_interval = 30  # Broadcast stats mỗi 30s
        self.running = False  # Control flag for graceful shutdown

        # Metrics
        self.interactions_processed = 0
        self.broadcasts_sent = 0
        self.errors_count = 0
        self.notifications_received = 0

        logger.info("📡 DataBroadcaster khởi tạo (LISTEN/NOTIFY mode)")
        logger.info("📻 LISTEN channel: %s", self.notify_channel)
        logger.info("📊 Stats broadcast: mỗi %ss", self.stats_broadcast_interval)

    async def setup_redis(self) -> bool:
        """Setup Redis connection."""
        try:
            self.redis_client = aioredis.from_url(
                f"redis://{self.redis_host}:{self.redis_port}",
                decode_responses=True
            )

            # Test connection
            if self.redis_client:
                await self.redis_client.ping()
            logger.info("✅ Redis connection established")
            return True

        except Exception as e:
            logger.error("❌ Redis connection failed: %s", e)
            return False

    def setup_database(self) -> bool:
        """Setup Database Manager."""
        try:
            self.db_manager = DatabaseManager()
            logger.info("✅ Database Manager initialized")
            return True
        except Exception as e:
            logger.error("❌ Database Manager initialization failed: %s", e)
            return False

    def setup_listen_connection(self) -> bool:
        """
        Setup separate PostgreSQL connection for LISTEN/NOTIFY.

        This connection is used exclusively for LISTEN operations
        and cannot be shared with other database operations

        Returns:
            True if connection established successfully, False otherwise
        """
        try:
            if not self.db_manager:
                logger.error("❌ Database Manager not initialized")
                return False

            # Get connection parameters from db_manager config
            db_config = self.db_manager.db_config

            connection_params = {
                'host': db_config.host,
                'port': db_config.port,
                'user': db_config.user,
                'password': db_config.password,
                'dbname': db_config.name,
                'connect_timeout': db_config.connection_timeout,
                'cursor_factory': RealDictCursor
            }

            self.listen_connection = psycopg2.connect(**connection_params)
            # Set to autocommit mode for LISTEN operations
            self.listen_connection.autocommit = True

            # Start listening on the notification channel
            cursor = self.listen_connection.cursor()
            cursor.execute(f"LISTEN {self.notify_channel}")

            logger.info(
                "✅ LISTEN connection established on channel '%s'",
                self.notify_channel
            )
            return True

        except Exception as e:
            logger.error("❌ Failed to setup LISTEN connection: %s", e)
            return False

    def listen_for_notifications(self) -> List[Dict[str, Any]]:
        """
        Listen for PostgreSQL NOTIFY messages on the configured channel.

        This method blocks until notifications are received or timeout occurs

        Returns:
            List of interaction data from notifications
        """
        if not self.listen_connection:
            logger.error("❌ LISTEN connection not established")
            return []

        try:
            import select
            
            # Use select to wait for notifications with timeout
            if select.select([self.listen_connection], [], [], self.listen_timeout) == ([], [], []):
                # Timeout occurred, no notifications
                return []
            
            # Poll the connection for any pending notifications
            self.listen_connection.poll()
            
            notifications = []
            while self.listen_connection.notifies:
                notify = self.listen_connection.notifies.popleft()
                self.notifications_received += 1

                try:
                    # Parse the JSON payload from the notification
                    interaction_data = json.loads(notify.payload)
                    notifications.append(interaction_data)

                    logger.debug(
                        "📥 Received notification: %s... (ID: %s)",
                        interaction_data['post_signature'][:20],
                        interaction_data['id']
                    )

                except json.JSONDecodeError as e:
                    logger.error("❌ Invalid JSON in notification payload: %s", e)
                    self.errors_count += 1
                    continue

            return notifications

        except Exception as e:
            logger.error("❌ Error listening for notifications: %s", e)
            self.errors_count += 1
            return []

    async def broadcast_interaction_update(self, interaction: Dict[str, Any]):
        """
        Broadcast interaction update qua Redis Pub/Sub.

        Args:
            interaction: Interaction record từ database
        """
        if not self.redis_client:
            return

        try:
            # Tạo broadcast message
            message = {
                "type": "interaction_update",
                "post_signature": interaction["post_signature"],
                "interaction": {
                    "id": interaction["id"],
                    "timestamp": interaction["log_timestamp_utc"],
                    "like_count": interaction["like_count"],
                    "comment_count": interaction["comment_count"],
                    "total_engagement": (interaction["like_count"] +
                                         interaction["comment_count"])
                },
                "broadcast_time": datetime.now(timezone.utc).isoformat()
            }

            # Publish qua Redis Pub/Sub
            await self.redis_client.publish("post_updates", json.dumps(message))

            self.broadcasts_sent += 1
            self.interactions_processed += 1

            logger.debug(
                "📡 Broadcasted interaction for %s...",
                interaction['post_signature'][:20]
            )

        except Exception as e:
            logger.error("❌ Error broadcasting interaction: %s", e)
            self.errors_count += 1

    async def broadcast_new_post(self, post_signature: str):
        """
        Broadcast thông báo có post mới được discovered.

        Args:
            post_signature: Signature của post mới
        """
        if not self.redis_client or not self.db_manager:
            return

        try:
            # Lấy thông tin post từ database
            post_info = self.db_manager.get_post_by_signature(post_signature)

            if post_info:
                message = {
                    "type": "new_post_discovered",
                    "post_signature": post_signature,
                    "post_info": post_info,
                    "broadcast_time": datetime.now(timezone.utc).isoformat()
                }

                # Publish qua Redis Pub/Sub
                await self.redis_client.publish("post_updates", json.dumps(message))

                self.broadcasts_sent += 1
                logger.info(
                    "📡 Broadcasted new post discovery: %s...",
                    post_signature[:20]
                )

        except Exception as e:
            logger.error("❌ Error broadcasting new post: %s", e)
            self.errors_count += 1

    async def broadcast_system_stats(self):
        """Broadcast system statistics."""
        if not self.redis_client or not self.db_manager:
            return

        try:
            # Lấy database stats
            db_stats = self.db_manager.get_stats()

            # Thêm broadcaster metrics
            current_time = time.time()
            uptime = current_time - getattr(self, 'start_time', current_time)

            stats = {
                **db_stats,
                "broadcaster_metrics": {
                    "interactions_processed": self.interactions_processed,
                    "broadcasts_sent": self.broadcasts_sent,
                    "errors_count": self.errors_count,
                    "notifications_received": self.notifications_received,
                    "uptime_seconds": uptime,
                    "known_posts_count": len(self.known_posts),
                    "listen_mode": "LISTEN/NOTIFY",
                    "listen_channel": self.notify_channel
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            # Publish system stats
            await self.redis_client.publish("system_stats", json.dumps(stats))

            logger.debug(
                "📊 Broadcasted system stats: %s interactions, %s tracking posts",
                stats['total_interactions'], stats['tracking_posts']
            )

        except Exception as e:
            logger.error("❌ Error broadcasting system stats: %s", e)
            self.errors_count += 1

    async def detect_new_posts(self, interactions: List[Dict[str, Any]]):
        """
        Phát hiện posts mới từ interactions và broadcast.

        Args:
            interactions: List interactions vừa được fetch
        """
        new_posts = set()

        for interaction in interactions:
            post_signature = interaction["post_signature"]

            if post_signature not in self.known_posts:
                new_posts.add(post_signature)
                self.known_posts.add(post_signature)

        # Broadcast các posts mới
        for post_signature in new_posts:
            await self.broadcast_new_post(post_signature)

    async def initialize_known_posts(self):
        """Initialize danh sách posts đã biết từ database."""
        if not self.db_manager:
            return

        try:
            # Lấy tất cả active posts
            active_posts = self.db_manager.get_active_tracking_posts()

            self.known_posts = {post["post_signature"] for post in active_posts}

            logger.info("📋 Initialized %d known posts", len(self.known_posts))

        except Exception as e:
            logger.error("❌ Error initializing known posts: %s", e)

    def check_listen_connection(self) -> bool:
        """
        Check if LISTEN connection is still alive and reconnect if needed.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            if not self.listen_connection or self.listen_connection.closed:
                logger.warning("⚠️ LISTEN connection lost, attempting to reconnect...")
                return self.setup_listen_connection()

            # Test connection with a simple query
            cursor = self.listen_connection.cursor()
            cursor.execute("SELECT 1")
            return True

        except Exception as e:
            logger.error("❌ LISTEN connection health check failed: %s", e)
            return self.setup_listen_connection()

    async def run_listen_loop(self):
        """Main LISTEN loop để detect và broadcast changes in real-time."""
        logger.info("🔄 Starting LISTEN loop...")

        self.start_time = time.time()
        self.running = True

        # Start stats broadcasting in background
        asyncio.create_task(self.stats_broadcast_task())

        while self.running:
            try:
                # Check LISTEN connection health
                if not self.check_listen_connection():
                    logger.error(
                        "❌ Failed to establish LISTEN connection, "
                        "waiting before retry..."
                    )
                    await asyncio.sleep(5.0)
                    continue

                # Listen for notifications (this is blocking but has timeout)
                loop = asyncio.get_event_loop()
                new_interactions = await loop.run_in_executor(
                    None, self.listen_for_notifications
                )

                if new_interactions:
                    # Detect new posts
                    await self.detect_new_posts(new_interactions)

                    # Broadcast each interaction
                    for interaction in new_interactions:
                        await self.broadcast_interaction_update(interaction)

                # Small delay to prevent tight loop when no notifications
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("❌ Error in LISTEN loop: %s", e)
                self.errors_count += 1
                await asyncio.sleep(2.0)

    async def stats_broadcast_task(self):
        """Background task để broadcast system stats định kỳ."""
        while self.running:
            try:
                await asyncio.sleep(self.stats_broadcast_interval)
                if self.running:
                    await self.broadcast_system_stats()

            except Exception as e:
                logger.error("❌ Error in stats broadcast task: %s", e)
                self.errors_count += 1

    async def run_forever(self):
        """Run data broadcaster trong vòng lặp vô tận với LISTEN/NOTIFY."""
        logger.info("🚀 BẮT ĐẦU DATA BROADCASTER (LISTEN/NOTIFY)")
        logger.info("=" * 60)
        logger.info("📡 Redis Pub/Sub channels: post_updates, system_stats")
        logger.info("📻 PostgreSQL LISTEN channel: %s", self.notify_channel)
        logger.info("📊 Stats broadcast: mỗi %ss", self.stats_broadcast_interval)
        logger.info("🎯 Real-time notifications with near-zero database load")
        logger.info("=" * 60)

        # Setup components
        if not self.setup_database():
            logger.error("💥 Không thể setup database. Thoát broadcaster.")
            return

        if not await self.setup_redis():
            logger.error("💥 Không thể setup Redis. Thoát broadcaster.")
            return

        if not self.setup_listen_connection():
            logger.error("💥 Không thể setup LISTEN connection. Thoát broadcaster.")
            return

        # Initialize state
        await self.initialize_known_posts()

        try:
            # Start LISTEN loop
            await self.run_listen_loop()

        except KeyboardInterrupt:
            logger.info("🛑 Data broadcaster bị dừng bởi người dùng")
        except Exception as e:
            logger.error("💥 Lỗi nghiêm trọng trong data broadcaster: %s", e)
        finally:
            self.running = False
            if self.redis_client:
                await self.redis_client.close()
            if self.listen_connection:
                self.listen_connection.close()
            if self.db_manager:
                self.db_manager.close()
            logger.info("👋 Data broadcaster đã thoát")


import sys
import io

# Fix encoding cho Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def main():
    """Hàm main để chạy data broadcaster với LISTEN/NOTIFY."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Data Broadcaster for Facebook Post Monitor (LISTEN/NOTIFY mode)"
    )
    parser.add_argument(
        "--stats-interval",
        type=int,
        default=30,
        help="Stats broadcast interval in seconds (default: 30)"
    )
    parser.add_argument(
        "--listen-timeout",
        type=float,
        default=5.0,
        help="LISTEN timeout in seconds (default: 5.0)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║                  DATA BROADCASTER PHASE 3.2                 ║")
    print("║                                                              ║")
    print("║  📻 PostgreSQL LISTEN/NOTIFY real-time detection            ║")
    print("║  📡 Redis Pub/Sub broadcasting                              ║")
    print("║  📊 WebSocket client notifications                          ║")
    print("║  ⚡ Zero-latency interaction updates                         ║")
    print("║  🎯 Near-zero database load                                 ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    print(f"📻 LISTEN timeout: {args.listen_timeout}s")
    print(f"📊 Stats broadcast: mỗi {args.stats_interval}s")
    print("📡 Redis channels: post_updates, system_stats")
    print("🔧 PostgreSQL channel: new_interaction")
    print()

    # Tạo broadcaster với custom config
    broadcaster = DataBroadcaster()
    broadcaster.stats_broadcast_interval = args.stats_interval
    broadcaster.listen_timeout = args.listen_timeout

    # Run broadcaster
    asyncio.run(broadcaster.run_forever())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Data broadcaster bị dừng")
    except Exception as e:
        print(f"\n💥 Lỗi: {e}")
        import traceback
        traceback.print_exc()