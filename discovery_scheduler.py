#!/usr/bin/env python3
"""
Discovery Scheduler for Facebook Post Monitor - Enterprise Edition Phase 3.1
Bộ lập lịch chuyên trách khám phá posts mới từ target URLs

Vai trò:
- Producer chuyên biệt cho DISCOVERY queue
- Scan target URLs để tìm posts mới với tần suất thấp (30 phút/lần)
- Tái sử dụng TargetManager và Redis infrastructure
- Không theo dõi interactions, chỉ khám phá posts mới
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
from typing import Optional
from utils.async_patterns import AsyncSchedulingPatterns
import uuid
from datetime import datetime
from core.target_manager import TargetManager
from multi_queue_config import (
    MultiQueueConfig, QueueType, create_discovery_task
)
from logging_config import get_logger

# Get module logger from centralized logging
logger = get_logger(__name__)


class DiscoveryScheduler:
    """
    Specialized producer cho Discovery workflow
    
    Tái sử dụng pattern từ scheduler.py hiện có nhưng chuyên biệt cho discovery
    """
    
    def __init__(
        self, 
        redis_client: Optional[redis.Redis] = None,
        target_manager: Optional[TargetManager] = None,
        config: Optional[MultiQueueConfig] = None,
        redis_host: str = "localhost", 
        redis_port: int = 6379, 
        redis_db: int = 0
    ):
        """
        Khởi tạo DiscoveryScheduler với dependency injection
        
        Args:
            redis_client: Redis client instance (injectable)
            target_manager: Target manager instance (injectable)
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
        
        self.queue_name = QueueType.DISCOVERY.value
        scheduler_config = self.config.get_scheduler_config(QueueType.DISCOVERY)
        self.schedule_interval = scheduler_config['schedule_interval']  # 30 phút
        
        # Target manager - use injected or create default
        if target_manager:
            self.target_manager = target_manager
        else:
            self.target_manager = TargetManager("targets.json")
        
        self.target_urls = self.target_manager.get_active_urls()
        
        # Target reload counter (tái sử dụng pattern từ scheduler.py)
        self.target_reload_counter = 0
        self.target_reload_interval = 10  # Check targets mỗi 10 chu kỳ
        
        logger.info(f"🔍 DiscoveryScheduler khởi tạo với queue: {self.queue_name}")
        logger.info(f"⏰ Schedule interval: {self.schedule_interval} giây (30 phút)")
        logger.info(f"🎯 Target URLs: {len(self.target_urls)}")    
    def connect_redis(self) -> bool:
        """
        Kết nối đến Redis server (tái sử dụng từ scheduler.py)
        
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
    
    def push_discovery_tasks(self) -> int:
        """
        Tạo và đẩy discovery tasks cho target URLs
        
        Returns:
            Số lượng tasks đã đẩy thành công
        """
        if not self.redis_client:
            logger.error("❌ Redis client chưa được khởi tạo")
            return 0
        
        tasks_pushed = 0
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"🔍 Bắt đầu discovery tasks lúc {current_time}")
        logger.info(f"📤 Tạo discovery tasks cho {len(self.target_urls)} targets")
        
        for url in self.target_urls:
            try:
                # Tạo trace_id duy nhất cho task này
                trace_id = str(uuid.uuid4())
                
                # Ghi log với trace_id ngay sau khi tạo
                logger.info(f"[TraceID: {trace_id}] Creating discovery task for target {url[:50]}...")
                
                # Tạo discovery task với format chuẩn
                task = create_discovery_task(target_url=url)
                
                # Thêm thông tin đặc biệt cho discovery
                task['scheduler'] = 'discovery_scheduler'
                task['discovery_cycle'] = current_time
                
                # Tạo cấu trúc message mới với trace_id và payload
                message = {
                    "trace_id": trace_id,
                    "payload": task
                }
                
                # Đẩy vào DISCOVERY queue với cấu trúc mới
                task_json = json.dumps(message)
                self.redis_client.lpush(self.queue_name, task_json)
                tasks_pushed += 1
                
                logger.debug(f"[TraceID: {trace_id}] 🔍 Discovery task: {task['task_id']} for {url[:50]}...")
                
            except Exception as e:
                logger.error(f"❌ Lỗi tạo discovery task cho {url}: {e}")
                continue
        
        logger.info(f"✅ Đã đẩy {tasks_pushed} discovery tasks vào queue '{self.queue_name}'")
        
        # Hiển thị thống kê queue
        try:
            queue_length = self.redis_client.llen(self.queue_name)
            logger.info(f"📊 Discovery queue hiện có {queue_length} tasks đang chờ")
        except Exception as e:
            logger.debug(f"Không thể lấy queue length: {e}")
        
        return tasks_pushed
    
    def get_queue_stats(self) -> dict:
        """
        Lấy thống kê về Discovery queue
        
        Returns:
            Dict chứa stats
        """
        try:
            stats = {
                'discovery_queue_length': self.redis_client.llen(self.queue_name),
                'redis_memory': self.redis_client.info('memory'),
                'connected_clients': self.redis_client.info('clients')['connected_clients'],
                'target_count': len(self.target_urls)
            }
            return stats
        except Exception as e:
            logger.error(f"❌ Lỗi lấy queue stats: {e}")
            return {}
    
    def clear_queue(self):
        """Xóa tất cả tasks trong discovery queue - dùng để debug"""
        try:
            cleared = self.redis_client.delete(self.queue_name)
            logger.info(f"🗑️ Đã xóa discovery queue '{self.queue_name}': {cleared} keys")
        except Exception as e:
            logger.error(f"❌ Lỗi xóa queue: {e}")
    
    def reload_targets_if_needed(self) -> bool:
        """
        Hot-reload targets nếu cần (tái sử dụng từ scheduler.py)
        
        Returns:
            True nếu có thay đổi targets
        """
        self.target_reload_counter += 1
        
        if self.target_reload_counter >= self.target_reload_interval:
            old_count = len(self.target_urls)
            config_changed = self.target_manager.reload_config()
            
            if config_changed:
                self.target_urls = self.target_manager.get_active_urls()
                new_count = len(self.target_urls)
                logger.info(f"🔄 Hot-reload targets: {old_count} → {new_count}")
                
                if abs(new_count - old_count) >= 1:
                    stats = self.target_manager.get_stats()
                    logger.info(f"🎯 Target distribution: {stats['pages']} pages, {stats['groups']} groups")
                
                self.target_reload_counter = 0
                return True
            
            self.target_reload_counter = 0
        
        return False
    
    async def run_forever(self):
        """
        Chạy discovery scheduler trong vòng lặp vô tận
        """
        logger.info("🚀 BẮT ĐẦU DISCOVERY SCHEDULER")
        logger.info("=" * 60)
        logger.info(f"🔍 Target URLs: {len(self.target_urls)}")
        logger.info(f"⏰ Schedule interval: {self.schedule_interval} giây (30 phút)")
        logger.info(f"📡 Redis queue: {self.queue_name}")
        logger.info("=" * 60)
        
        # Kết nối Redis
        if not self.connect_redis():
            logger.error("💥 Không thể kết nối Redis. Thoát discovery scheduler.")
            return
        
        # --- FIX: THỰC HIỆN LẦN CHẠY ĐẦU TIÊN NGAY LẬP TỨC ---
        logger.info("🚀 Performing initial discovery run before starting the main loop...")
        self.push_discovery_tasks()
        logger.info("✅ Initial discovery run completed.")
        logger.info("-" * 40)
        # --- END FIX ---

        cycle_count = 0
        
        try:
            while True:
                # Ngủ đến cycle tiếp theo (30 phút)
                logger.info(f"😴 Ngủ {self.schedule_interval}s đến discovery cycle tiếp theo...")
                await AsyncSchedulingPatterns.discovery_cycle(self.schedule_interval, "discovery scheduler")

                cycle_count += 1
                cycle_start = time.time()
                
                logger.info(f"🔄 DISCOVERY CYCLE {cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Đẩy discovery tasks
                self.push_discovery_tasks()
                
                # Hot-reload targets nếu cần
                targets_changed = self.reload_targets_if_needed()
                if targets_changed:
                    logger.info(f"🎯 Targets reloaded, new count: {len(self.target_urls)}")
                
                # Hiển thị stats
                stats = self.get_queue_stats()
                if stats:
                    logger.info(f"📊 Queue: {stats['discovery_queue_length']} tasks, {stats['connected_clients']} clients")
                    logger.info(f"📊 Targets: {stats['target_count']} active URLs")
                
                cycle_duration = time.time() - cycle_start
                logger.info(f"⏱️ Discovery cycle {cycle_count} hoàn thành trong {cycle_duration:.2f}s")
                
                logger.info("-" * 40)
                
        except KeyboardInterrupt:
            logger.info("🛑 Discovery scheduler bị dừng bởi người dùng")
        except Exception as e:
            logger.error(f"💥 Lỗi nghiêm trọng trong discovery scheduler: {e}")
        finally:
            if self.redis_client:
                self.redis_client.close()
            logger.info("👋 Discovery scheduler đã thoát")


def main():
    """Hàm main để chạy discovery scheduler với dependency injection mặc định"""
    from logging_config import setup_application_logging
    from dependency_injection import ServiceManager
    import argparse
    
    # Setup centralized logging
    setup_application_logging()
    
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║               DISCOVERY SCHEDULER PHASE 3.1                  ║")
    print("║                                                              ║")
    print("║  🔍 Chuyên trách khám phá posts mới từ target URLs          ║")
    print("║  ⏰ Tần suất thấp: 30 phút/lần                               ║")
    print("║  📤 Producer cho DISCOVERY queue                             ║")
    print("║  🎯 Target management với hot-reload                         ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    print("⚠️ YÊU CẦU:")
    print("• Redis server phải đang chạy")
    print("• targets.json phải có target URLs")
    print("• Cài đặt: pip install redis>=4.5.0")
    print()
    
    print("🔧 CẤU HÌNH DISCOVERY:")
    print("• Queue name: fb_discovery_tasks")
    print("• Schedule interval: 1800 giây (30 phút)")
    print("• Redis: redis:6379")
    print("• Targets: targets.json")
    print()
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="Discovery Scheduler")
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--clear-queue', action='store_true', help='Clear the discovery queue')
    
    args = parser.parse_args()
    
    # Tùy chọn debug
    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        print("🔍 DEBUG MODE ENABLED")
    
    if args.clear_queue:
        scheduler = DiscoveryScheduler()
        if scheduler.connect_redis():
            scheduler.clear_queue()
        return
    
    print("💉 Using dependency injection (default)")
    
    # Initialize ServiceManager
    service_manager = ServiceManager()
    container = service_manager.container
    
    # Get dependencies from container
    redis_client = container.get_optional('redis_client')
    target_manager = container.get_optional('target_manager')
    config = container.get_optional('multi_queue_config')
    
    # Create scheduler with injected dependencies
    scheduler = DiscoveryScheduler(
        redis_client=redis_client,
        target_manager=target_manager,
        config=config
    )
    
    # Tạo và chạy discovery scheduler
    asyncio.run(scheduler.run_forever())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Discovery scheduler bị dừng")
    except Exception as e:
        print(f"\n💥 Lỗi: {e}")
        import traceback
        traceback.print_exc()


