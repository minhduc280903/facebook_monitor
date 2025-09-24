#!/usr/bin/env python3
"""
Tracking Scheduler for Facebook Post Monitor - Enterprise Edition Phase 3.1
Bộ lập lịch thông minh cho high-frequency và low-frequency tracking

Vai trò:
- Producer thông minh cho HIGH_FREQ_UPDATE và LOW_FREQ_UPDATE queues
- Phân loại posts dựa trên tuổi và tương tác để chọn tần suất phù hợp
- Tracking posts đang active với tần suất cao (5 giây cho hot posts)
- Tái sử dụng DatabaseManager để lấy active posts
"""

import redis
import sys
import io

# Fix encoding cho Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


import json
import time
import asyncio
from typing import Optional, Dict, Any
from utils.async_patterns import AsyncSchedulingPatterns
import uuid
from datetime import datetime, timezone
from core.database_manager import DatabaseManager
from multi_queue_config import (
    MultiQueueConfig, QueueType, TaskType, 
    create_tracking_task
)
from logging_config import get_logger

# Get module logger from centralized logging
logger = get_logger(__name__)


class TrackingScheduler:
    """
    Intelligent producer cho tracking workflow
    
    Phân tích posts để xác định tần suất tracking phù hợp:
    - High-frequency: Posts mới (< 24h) và có tương tác cao
    - Low-frequency: Posts cũ hơn hoặc tương tác thấp
    """
    
    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        db_manager: Optional[DatabaseManager] = None,
        config: Optional[MultiQueueConfig] = None,
        redis_host: str = "localhost", 
        redis_port: int = 6379, 
        redis_db: int = 0
    ):
        """
        Khởi tạo TrackingScheduler với dependency injection
        
        Args:
            redis_client: Redis client instance (injectable)
            db_manager: Database manager instance (injectable)
            config: Multi-queue configuration (injectable)
            redis_host: Redis server host (fallback)
            redis_port: Redis server port (fallback)
            redis_db: Redis database number (fallback)
        """
        # Use injected dependencies or create defaults
        if redis_client:
            self.redis_client = redis_client
            self.redis_host = None
            self.redis_port = None
            self.redis_db = None
        else:
            self.redis_client = None
            self.redis_host = redis_host
            self.redis_port = redis_port
            self.redis_db = redis_db
        
        # Multi-queue configuration - use injected or create default
        if config:
            self.config = config
        else:
            self.config = MultiQueueConfig()
        
        # Simplified queue configuration
        self.tracking_queue = QueueType.TRACKING.value
        
        # Simplified scheduler configuration
        self.tracking_config = self.config.get_scheduler_config(QueueType.TRACKING)
        
        # Schedule interval
        self.tracking_interval = self.tracking_config['schedule_interval']  # 5 phút đều đặn
        
        # Database Manager - use injected or will create later
        self.db_manager = db_manager
        
        # Simplified cycle counter
        self.cycle_count = 0
        
        logger.info("📈 TrackingScheduler khởi tạo (SIMPLIFIED VERSION)")
        logger.info(f"⚡ Unified tracking queue: {self.tracking_queue} (mỗi {self.tracking_interval}s)")
        logger.info("🎯 Tất cả posts đều quan trọng như nhau - tracking đều đặn")    
    def connect_redis(self) -> bool:
        """
        Kết nối đến Redis server
        
        Returns:
            True nếu kết nối thành công, False nếu thất bại
        """
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            # Test connection
            self.redis_client.ping()
            
            logger.info(f"✅ Kết nối Redis thành công: {self.redis_host}:{self.redis_port}")
            return True
            
        except redis.ConnectionError as e:
            logger.error(f"❌ Không thể kết nối Redis: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Lỗi kết nối Redis: {e}")
            return False
    
    def setup_database(self) -> bool:
        """
        Khởi tạo Database Manager
        
        Returns:
            True nếu thành công
        """
        try:
            self.db_manager = DatabaseManager()
            logger.info("✅ Database Manager khởi tạo thành công")
            return True
        except Exception as e:
            logger.error(f"❌ Không thể khởi tạo Database Manager: {e}")
            return False
    
    def analyze_post_for_frequency(self, post: Dict[str, Any]) -> TaskType:
        """
        Phân tích post để xác định tần suất tracking
        
        Args:
            post: Dict chứa thông tin post từ database
            
        Returns:
            TaskType.TRACKING (simplified - luôn luôn)
        """
        try:
            # Parse first_seen_utc để tính tuổi post
            first_seen_str = post.get('first_seen_utc', '')
            if first_seen_str:
                first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                post_age_hours = (now - first_seen).total_seconds() / 3600
            else:
                post_age_hours = 48  # Default to old post
            
            # Lấy interaction data gần nhất để tính interaction rate
            interaction_rate = 0.0
            try:
                recent_interactions = self.db_manager.get_interaction_history(
                    post['post_signature'], limit=5
                )
                
                if recent_interactions and len(recent_interactions) >= 2:
                    # Tính average interactions từ 2 data points gần nhất
                    latest = recent_interactions[0]
                    previous = recent_interactions[1]
                    
                    latest_total = latest.get('like_count', 0) + latest.get('comment_count', 0)
                    previous_total = previous.get('like_count', 0) + previous.get('comment_count', 0)
                    
                    # Estimate interaction rate per hour
                    interaction_diff = latest_total - previous_total
                    if interaction_diff > 0:
                        interaction_rate = interaction_diff  # Simplified rate
                
            except Exception as e:
                logger.debug(f"Không thể tính interaction rate cho {post['post_signature']}: {e}")
            
            # SIMPLIFIED: Sử dụng logic đơn giản từ MultiQueueConfig
            task_type = MultiQueueConfig.determine_tracking_frequency(
                post_age_hours, interaction_rate
            )
            
            return task_type
            
        except Exception as e:
            logger.error(f"❌ Lỗi phân tích post {post.get('post_signature', 'unknown')}: {e}")
            # Default to low frequency khi có lỗi
            return TaskType.LOW_FREQ_TRACKING
    
    def push_tracking_tasks(self) -> int:
        """
        Tạo và đẩy tracking tasks (SIMPLIFIED - đều đặn)
        
        Returns:
            Số lượng tasks đã đẩy thành công
        """
        try:
            # Lấy posts đang active
            active_posts = self.db_manager.get_active_tracking_posts()
            
            tasks_pushed = 0
            # SIMPLIFIED: Tất cả posts đều tracking
            
            # Phân loại posts cho high-frequency
            for post in active_posts:
                task_type = self.analyze_post_for_frequency(post)
                
                if task_type == TaskType.HIGH_FREQ_TRACKING:
                    active_posts.append(post)
            
            # Limit số lượng tasks per cycle
            max_tasks = self.tracking_config.get('max_tasks_per_cycle', 100)
            limited_posts = active_posts[:max_tasks]
            
            logger.debug(f"⚡ High-freq candidates: {len(active_posts)}, processing: {len(limited_posts)}")
            
            # Tạo tasks cho high-frequency posts
            for post in limited_posts:
                try:
                    # Tạo trace_id duy nhất cho task này
                    trace_id = str(uuid.uuid4())
                    
                    # Ghi log với trace_id ngay sau khi tạo
                    logger.info(f"[TraceID: {trace_id}] Creating high-freq tracking task for post {post['post_signature']}")
                    
                    task = create_tracking_task(
                        post_signature=post['post_signature'],
                        post_url=post['post_url'],
                        task_type=TaskType.HIGH_FREQ_TRACKING
                    )
                    
                    # Thêm metadata
                    task['scheduler'] = 'tracking_scheduler_unified'
                    task['post_age_estimated'] = 'recent'  # Simplified metadata
                    
                    # Tạo cấu trúc message mới với trace_id và payload
                    message = {
                        "trace_id": trace_id,
                        "payload": task
                    }
                    
                    # Đẩy vào HIGH_FREQ queue với cấu trúc mới
                    task_json = json.dumps(message)
                    self.redis_client.lpush(self.tracking_queue, task_json)
                    tasks_pushed += 1
                    
                except Exception as e:
                    logger.error(f"❌ Lỗi tạo high-freq task cho {post['post_signature']}: {e}")
                    continue
            
            if tasks_pushed > 0:
                logger.info(f"⚡ Đã đẩy {tasks_pushed} high-frequency tasks")
            
            return tasks_pushed
            
        except Exception as e:
            logger.error(f"❌ Lỗi push high-freq tasks: {e}")
            return 0
    
    # REMOVED: push_low_freq_tasks - now using unified push_tracking_tasks
    
    
    def get_queue_stats(self) -> dict:
        """
        Lấy thống kê về unified Tracking queue
        
        Returns:
            Dict chứa stats
        """
        try:
            stats = {
                'tracking_queue_length': self.redis_client.llen(self.tracking_queue),
                'redis_memory': self.redis_client.info('memory'),
                'connected_clients': self.redis_client.info('clients')['connected_clients']
            }
            
            # Thêm database stats
            if self.db_manager:
                db_stats = self.db_manager.get_stats()
                stats.update({
                    'active_posts': db_stats.get('tracking_posts', 0),
                    'total_interactions': db_stats.get('total_interactions', 0)
                })
            
            return stats
        except Exception as e:
            logger.error(f"❌ Lỗi lấy queue stats: {e}")
            return {}
    
    def clear_queues(self):
        """Xóa tất cả tasks trong tracking queue - dùng để debug"""
        try:
            cleared = self.redis_client.delete(self.tracking_queue)
            logger.info(f"🗑️ Đã xóa tracking queue: {cleared}")
        except Exception as e:
            logger.error(f"❌ Lỗi xóa queues: {e}")
    
    async def run_forever(self):
        """
        Chạy tracking scheduler trong vòng lặp vô tận
        """
        logger.info("🚀 BẮT ĐẦU TRACKING SCHEDULER (SIMPLIFIED)")
        logger.info("=" * 60)
        logger.info(f"⚡ Unified tracking: mỗi {self.tracking_interval}s đều đặn")
        logger.info(f"📡 Redis queue: {self.tracking_queue}")
        logger.info("🎯 Tất cả posts đều quan trọng như nhau")
        logger.info("=" * 60)
        
        # Kết nối Redis
        if not self.connect_redis():
            logger.error("💥 Không thể kết nối Redis. Thoát tracking scheduler.")
            return
        
        # Khởi tạo Database Manager
        if not self.setup_database():
            logger.error("💥 Không thể khởi tạo Database Manager. Thoát tracking scheduler.")
            return
        
        self.cycle_count = 0
        
        try:
            while True:
                self.cycle_count += 1
                cycle_start = time.time()
                
                # SIMPLIFIED: Chỉ chạy unified tracking tasks
                self.push_tracking_tasks()
                logger.debug(f"🔄 TRACKING CYCLE {self.cycle_count} - Unified tracking")
                
                # Maintenance: expire old posts occasionally
                if self.cycle_count % 720 == 0:  # Mỗi 720 cycles (1 giờ)
                    try:
                        expired_count = self.db_manager.expire_old_posts()
                        if expired_count > 0:
                            logger.info(f"🕐 Maintenance: Đã expire {expired_count} posts")
                    except Exception as e:
                        logger.error(f"❌ Lỗi maintenance: {e}")
                
                # Hiển thị stats định kỳ
                if self.cycle_count % 60 == 0:  # Mỗi 60 cycles (5 phút)
                    stats = self.get_queue_stats()
                    if stats:
                        logger.info(f"📊 Tracking queue: {stats['tracking_queue_length']} tasks")
                        logger.info(f"📊 Active posts: {stats.get('active_posts', 0)}")
                
                cycle_duration = time.time() - cycle_start
                
                if self.cycle_count % 60 == 0:  # Log summary mỗi 5 phút
                    logger.info(f"⏱️ Cycle {self.cycle_count} completed in {cycle_duration:.2f}s")
                
                # Ngủ đến cycle tiếp theo (5 phút đều đặn)
                # Non-blocking tracking interval
                await AsyncSchedulingPatterns.discovery_cycle(self.tracking_interval, "tracking scheduler")
                
        except KeyboardInterrupt:
            logger.info("🛑 Tracking scheduler bị dừng bởi người dùng")
        except Exception as e:
            logger.error(f"💥 Lỗi nghiêm trọng trong tracking scheduler: {e}")
        finally:
            if self.redis_client:
                self.redis_client.close()
            if self.db_manager:
                self.db_manager.close()
            logger.info("👋 Tracking scheduler đã thoát")


def main():
    """Hàm main để chạy tracking scheduler với dependency injection mặc định"""
    from logging_config import setup_application_logging
    from dependency_injection import ServiceManager
    import argparse
    
    # Setup centralized logging
    setup_application_logging()
    
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║       TRACKING SCHEDULER PHASE 3.1 - SIMPLIFIED            ║")
    print("║                                                              ║")
    print("║  📈 Unified tracking - đều đặn mỗi 5 phút                   ║")
    print("║  🎯 Tất cả posts đều quan trọng như nhau                    ║")
    print("║  ⚡ Không phân biệt high/low frequency                       ║")
    print("║  🔄 Đơn giản và hiệu quả                                    ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    print("⚠️ YÊU CẦU:")
    print("• Redis server phải đang chạy")
    print("• PostgreSQL database phải có posts đang tracking")
    print("• Cài đặt: pip install redis>=4.5.0")
    print()
    
    print("🔧 CẤU HÌNH TRACKING (SIMPLIFIED):")
    print("• Unified tracking queue: fb_tracking_tasks (5min)")
    print("• Tất cả posts đều tracking đều đặn")
    print("• Redis: redis:6379")
    print("• Database: PostgreSQL")
    print()
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="Tracking Scheduler")
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--clear-queues', action='store_true', help='Clear tracking queue')
    
    args = parser.parse_args()
    
    # Tùy chọn debug
    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        print("🔍 DEBUG MODE ENABLED")
    
    if args.clear_queues:
        scheduler = TrackingScheduler()
        if scheduler.connect_redis():
            scheduler.clear_queues()
        return
    
    print("💉 Using dependency injection (default)")
    
    # Initialize ServiceManager
    service_manager = ServiceManager()
    container = service_manager.container
    
    # Get dependencies from container
    redis_client = container.get_optional('redis_client')
    db_manager = container.get_optional('database_manager')
    config = container.get_optional('multi_queue_config')
    
    # Create scheduler with injected dependencies
    scheduler = TrackingScheduler(
        redis_client=redis_client,
        db_manager=db_manager,
        config=config
    )
    
    # Tạo và chạy tracking scheduler
    asyncio.run(scheduler.run_forever())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Tracking scheduler bị dừng")
    except Exception as e:
        print(f"\n💥 Lỗi: {e}")
        import traceback
        traceback.print_exc()


