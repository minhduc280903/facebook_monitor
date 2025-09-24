#!/usr/bin/env python3
"""
Scan Scheduler for Facebook Post Monitor - NEW ARCHITECTURE
Bộ lập lịch thống nhất cho mô hình "quét và cập nhật" theo thời gian

Vai trò:
- Producer cho SCAN queue thống nhất
- Scan target URLs với time-based filtering
- Đơn giản hóa từ mô hình 2-queue xuống 1-queue
- Tích hợp start_date và logic lọc theo thời gian
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
    MultiQueueConfig, QueueType, TaskType, create_scan_task
)
from logging_config import get_logger

# Get module logger from centralized logging
logger = get_logger(__name__)


class ScanScheduler:
    """
    Scheduler thống nhất cho kiến trúc mới
    
    Đơn giản hóa từ DiscoveryScheduler và TrackingScheduler thành một scheduler duy nhất
    sử dụng SCAN queue với time-based filtering
    """
    
    def __init__(
        self, 
        redis_client: Optional[redis.Redis] = None,
        target_manager: Optional[TargetManager] = None,
        config: Optional[MultiQueueConfig] = None,
        redis_host: str = "redis", 
        redis_port: int = 6379, 
        redis_db: int = 0
    ):
        """
        Khởi tạo ScanScheduler với dependency injection
        
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
        
        self.queue_name = QueueType.SCAN.value  # scan_queue
        scheduler_config = self.config.get_scheduler_config(QueueType.SCAN)
        self.schedule_interval = scheduler_config['schedule_interval']  # 30 phút
        
        # Target manager - use injected or create default
        if target_manager:
            self.target_manager = target_manager
        else:
            self.target_manager = TargetManager("targets.json")
        
        self.target_urls = self.target_manager.get_active_urls()
        
        # Target reload counter
        self.target_reload_counter = 0
        self.target_reload_interval = 10  # Check targets mỗi 10 chu kỳ
        
        logger.info(f"🔍 ScanScheduler khởi tạo với queue: {self.queue_name}")
        logger.info(f"⏰ Schedule interval: {self.schedule_interval} giây (30 phút)")
        logger.info(f"🎯 Target URLs: {len(self.target_urls)}")
        logger.info(f"🆕 KIẾN TRÚC MỚI: Unified scanning với time-based filtering")
    
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
    
    def push_scan_tasks(self) -> int:
        """
        Tạo và đẩy scan tasks cho target URLs với kiến trúc mới
        
        Returns:
            Số lượng tasks đã đẩy thành công
        """
        if not self.redis_client:
            logger.error("❌ Redis client chưa được khởi tạo")
            return 0
        
        tasks_pushed = 0
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"🔍 Bắt đầu scan tasks (KIẾN TRÚC MỚI) lúc {current_time}")
        logger.info(f"📤 Tạo scan tasks cho {len(self.target_urls)} targets")
        
        for url in self.target_urls:
            try:
                # Tạo trace_id duy nhất cho task này
                trace_id = str(uuid.uuid4())
                
                # Ghi log với trace_id ngay sau khi tạo
                logger.info(f"[TraceID: {trace_id}] Creating SCAN task for target {url[:50]}...")
                
                # Tạo scan task với format chuẩn cho kiến trúc mới
                task = create_scan_task(target_url=url)
                
                # Thêm thông tin đặc biệt cho scan scheduler
                task['scheduler'] = 'scan_scheduler'
                task['scan_cycle'] = current_time
                task['architecture'] = 'unified_time_based'
                
                # Tạo cấu trúc message với trace_id và payload
                message = {
                    "trace_id": trace_id,
                    "payload": task
                }
                
                # Đẩy vào SCAN queue
                task_json = json.dumps(message)
                self.redis_client.lpush(self.queue_name, task_json)
                tasks_pushed += 1
                
                logger.debug(f"[TraceID: {trace_id}] 🔍 SCAN task: {task['task_id']} for {url[:50]}...")
                
            except Exception as e:
                logger.error(f"❌ Lỗi tạo scan task cho {url}: {e}")
                continue
        
        logger.info(f"✅ Đã đẩy {tasks_pushed} scan tasks vào queue '{self.queue_name}'")
        
        # Hiển thị thống kê queue
        try:
            queue_length = self.redis_client.llen(self.queue_name)
            logger.info(f"📊 Scan queue hiện có {queue_length} tasks đang chờ")
        except Exception as e:
            logger.debug(f"Không thể lấy queue length: {e}")
        
        return tasks_pushed
    
    def get_queue_stats(self) -> dict:
        """
        Lấy thống kê về Scan queue
        
        Returns:
            Dict chứa stats
        """
        try:
            stats = {
                'scan_queue_length': self.redis_client.llen(self.queue_name),
                'redis_memory': self.redis_client.info('memory'),
                'connected_clients': self.redis_client.info('clients')['connected_clients'],
                'target_count': len(self.target_urls),
                'architecture': 'unified_time_based'
            }
            return stats
        except Exception as e:
            logger.error(f"❌ Lỗi lấy queue stats: {e}")
            return {}
    
    def clear_queue(self):
        """Xóa tất cả tasks trong scan queue - dùng để debug"""
        try:
            cleared = self.redis_client.delete(self.queue_name)
            logger.info(f"🗑️ Đã xóa scan queue '{self.queue_name}': {cleared} keys")
        except Exception as e:
            logger.error(f"❌ Lỗi xóa queue: {e}")
    
    def reload_targets_if_needed(self) -> bool:
        """
        Hot-reload targets nếu cần
        
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
        Chạy scan scheduler trong vòng lặp vô tận với kiến trúc mới
        """
        logger.info("🚀 BẮT ĐẦU SCAN SCHEDULER - KIẾN TRÚC MỚI")
        logger.info("=" * 70)
        logger.info(f"🔍 Target URLs: {len(self.target_urls)}")
        logger.info(f"⏰ Schedule interval: {self.schedule_interval} giây (30 phút)")
        logger.info(f"📡 Redis queue: {self.queue_name}")
        logger.info(f"🆕 Architecture: Unified time-based scanning")
        logger.info(f"📅 Start date: Được quản lý bởi ScraperCoordinator")
        logger.info("=" * 70)
        
        # Kết nối Redis
        if not self.connect_redis():
            logger.error("💥 Không thể kết nối Redis. Thoát scan scheduler.")
            return
        
        # Thực hiện lần chạy đầu tiên ngay lập tức
        logger.info("🚀 Performing initial scan run before starting the main loop...")
        self.push_scan_tasks()
        logger.info("✅ Initial scan run completed.")
        logger.info("-" * 50)

        cycle_count = 0
        
        try:
            while True:
                # Ngủ đến cycle tiếp theo (30 phút)
                logger.info(f"😴 Ngủ {self.schedule_interval}s đến scan cycle tiếp theo...")
                await AsyncSchedulingPatterns.discovery_cycle(self.schedule_interval, "scan scheduler")

                cycle_count += 1
                cycle_start = time.time()
                
                logger.info(f"🔄 SCAN CYCLE {cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Đẩy scan tasks
                self.push_scan_tasks()
                
                # Hot-reload targets nếu cần
                targets_changed = self.reload_targets_if_needed()
                if targets_changed:
                    logger.info(f"🎯 Targets reloaded, new count: {len(self.target_urls)}")
                
                # Hiển thị stats
                stats = self.get_queue_stats()
                if stats:
                    logger.info(f"📊 Queue: {stats['scan_queue_length']} tasks, {stats['connected_clients']} clients")
                    logger.info(f"📊 Targets: {stats['target_count']} active URLs")
                    logger.info(f"🆕 Architecture: {stats['architecture']}")
                
                cycle_duration = time.time() - cycle_start
                logger.info(f"⏱️ Scan cycle {cycle_count} hoàn thành trong {cycle_duration:.2f}s")
                
                logger.info("-" * 50)
                
        except KeyboardInterrupt:
            logger.info("🛑 Scan scheduler bị dừng bởi người dùng")
        except Exception as e:
            logger.error(f"💥 Lỗi nghiêm trọng trong scan scheduler: {e}")
        finally:
            if self.redis_client:
                self.redis_client.close()
            logger.info("👋 Scan scheduler đã thoát")


def main():
    """Hàm main để chạy scan scheduler với dependency injection mặc định"""
    from logging_config import setup_application_logging
    from dependency_injection import ServiceManager
    import argparse
    
    # Setup centralized logging
    setup_application_logging()
    
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║              SCAN SCHEDULER - NEW ARCHITECTURE               ║")
    print("║                                                              ║")
    print("║  🔍 Unified scanning với time-based filtering               ║")
    print("║  ⏰ Tần suất: 30 phút/lần                                    ║")
    print("║  📤 Producer cho SCAN queue thống nhất                       ║")
    print("║  🎯 Target management với hot-reload                         ║")
    print("║  📅 Tích hợp start_date filtering                            ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    print("⚠️ YÊU CẦU:")
    print("• Redis server phải đang chạy")
    print("• targets.json phải có target URLs")
    print("• Cài đặt: pip install redis>=4.5.0")
    print()
    
    print("🔧 CẤU HÌNH SCAN:")
    print("• Queue name: scan_queue")
    print("• Schedule interval: 1800 giây (30 phút)")
    print("• Redis: redis:6379")
    print("• Targets: targets.json")
    print("• Architecture: Unified time-based")
    print()
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="Scan Scheduler - New Architecture")
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--clear-queue', action='store_true', help='Clear the scan queue')
    
    args = parser.parse_args()
    
    # Tùy chọn debug
    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        print("🔍 DEBUG MODE ENABLED")
    
    if args.clear_queue:
        scheduler = ScanScheduler()
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
    scheduler = ScanScheduler(
        redis_client=redis_client,
        target_manager=target_manager,
        config=config
    )
    
    # Tạo và chạy scan scheduler
    asyncio.run(scheduler.run_forever())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Scan scheduler bị dừng")
    except Exception as e:
        print(f"\n💥 Lỗi: {e}")
        import traceback
        traceback.print_exc()

