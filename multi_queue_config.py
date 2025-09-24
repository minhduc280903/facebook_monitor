#!/usr/bin/env python3
"""
Multi-Queue Configuration for Facebook Post Monitor 
- Enterprise Edition Phase 3.1 - SIMPLIFIED VERSION
Cấu hình hệ thống đa hàng đợi cho Discovery và Unified Tracking

Mục đích:
- Định nghĩa các queue khác nhau với priority levels
- Cấu hình routing logic cho tasks
- Settings cho different worker types
- Tái sử dụng Redis infrastructure hiện có
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from logging_config import get_logger

logger = get_logger(__name__)


class QueueType(Enum):
    """Định nghĩa queue trong hệ thống (kiến trúc SCAN thống nhất)"""
    SCAN = "scan_queue"


class TaskType(Enum):
    """Định nghĩa loại task (kiến trúc SCAN thống nhất)"""
    SCAN = "scan"                  # Quét và cập nhật theo thời gian


class Priority(Enum):
    """Priority levels cho tasks (SIMPLIFIED VERSION)"""
    LOW = 1      # Discovery tasks
    NORMAL = 2   # Tracking tasks (đều quan trọng như nhau)
    CRITICAL = 3 # Emergency tasks


@dataclass
class QueueConfig:
    """Configuration cho một queue"""
    name: str
    priority: Priority
    max_workers: int
    poll_interval: float  # seconds
    retry_limit: int
    timeout: int  # seconds
    description: str


class MultiQueueConfig:
    """
    Centralized configuration cho multi-queue system
    
    Tái sử dụng Redis infrastructure từ scheduler.py và worker.py hiện có
    """
    
    # Queue configurations (SCAN only - unified architecture)
    QUEUE_CONFIGS = {
        QueueType.SCAN: QueueConfig(
            name=QueueType.SCAN.value,
            priority=Priority.NORMAL,
            max_workers=5,
            poll_interval=3.0,
            retry_limit=2,
            timeout=90,
            description="SCAN - unified scanning with time-based filtering"
        )
    }

    @staticmethod
    def get_queue_for_task(task_type: TaskType) -> QueueType:
        """
        Xác định queue phù hợp cho một task type (unified SCAN architecture)
        
        Args:
            task_type: Loại task
            
        Returns:
            QueueType: Luôn trả về SCAN queue
        """
        # Unified architecture - chỉ có SCAN queue
        return QueueType.SCAN
    
    @staticmethod
    def determine_tracking_frequency(post_age_hours: float, interaction_rate: float = 0.0) -> TaskType:
        """
        Unified architecture - tất cả đều là SCAN tasks
        
        Args:
            post_age_hours: Tuổi của post (giờ) - không còn dùng để phân loại
            interaction_rate: Tỷ lệ tương tác - không còn dùng để phân loại
            
        Returns:
            TaskType.SCAN (luôn luôn - kiến trúc thống nhất)
        """
        # Unified architecture: tất cả đều là SCAN tasks
        return TaskType.SCAN
    
    @staticmethod
    def get_worker_config(queue_type: QueueType) -> Dict[str, Any]:
        """
        Lấy worker configuration cho queue type
        
        Args:
            queue_type: Loại queue
            
        Returns:
            Dict config cho worker
        """
        config = MultiQueueConfig.QUEUE_CONFIGS[queue_type]
        
        return {
            "queue_name": config.name,
            "poll_interval": config.poll_interval,
            "timeout": config.timeout,
            "retry_limit": config.retry_limit,
            "priority": config.priority.value,
            "max_concurrent_tasks": 1,  # Mỗi worker xử lý 1 task tại một thời điểm
            "enable_circuit_breaker": True,
            "enable_proxy": True,       # Sử dụng ProxyManager
            "enable_session_pool": True # Sử dụng SessionManager
        }
    
    @staticmethod
    def get_scheduler_config(queue_type: QueueType) -> Dict[str, Any]:
        """
        Lấy scheduler configuration cho queue type (unified SCAN only)
        
        Args:
            queue_type: Loại queue (chỉ SCAN)
            
        Returns:
            Dict config cho scheduler
        """
        # Unified SCAN architecture
        return {
            "schedule_interval": 120,   # 2 phút 1 lần (demo mode)
            "target_urls_only": True,   # Chỉ scan target URLs
            "max_tasks_per_cycle": 20,
            "enable_backoff": True,
            "time_based_filtering": True, # Đặc trưng của kiến trúc mới
            "start_date_required": True   # Yêu cầu start_date
        }
    
    @staticmethod
    def get_all_queues() -> List[QueueType]:
        """Lấy danh sách tất cả queues (chỉ SCAN queue)"""
        return [QueueType.SCAN]
    
    @staticmethod
    def get_queue_stats_config() -> Dict[str, Any]:
        """Configuration cho queue monitoring và stats"""
        return {
            "stats_interval": 60,       # Log stats mỗi 60s
            "queue_size_warning": 1000, # Cảnh báo khi queue > 1000 tasks
            "queue_size_critical": 5000,# Critical khi queue > 5000 tasks
            "worker_timeout_warning": 300, # Cảnh báo worker timeout > 5 min
            "enable_metrics": True,     # Enable detailed metrics
            "retention_hours": 24       # Giữ metrics 24h
        }


# Utility function cho SCAN task creation


def create_scan_task(
    target_url: str, 
    task_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Tạo scan task cho kiến trúc mới (unified scanning với time-based filtering)
    
    Args:
        target_url: URL group/fanpage cần scan
        task_id: Optional task ID
        
    Returns:
        Dict task cho scan queue
    """
    import uuid
    from datetime import datetime
    
    config = MultiQueueConfig.QUEUE_CONFIGS[QueueType.SCAN]
    
    return {
        'task_id': task_id or str(uuid.uuid4()),
        'task_type': TaskType.SCAN.value,
        'url': target_url,
        'priority': config.priority.value,
        'created_at': datetime.now().isoformat(),
        'queue': QueueType.SCAN.value,
        'retries': 0,
        'timeout': config.timeout,
        'metadata': {
            'source': 'scan_scheduler',
            'architecture': 'unified_time_based',
            'target_type': 'group_or_fanpage'
        }
    }


# Test function
def test_multi_queue_config():
    """Test basic functionality của MultiQueueConfig (SCAN only)"""
    print("🧪 Testing MultiQueueConfig (SCAN unified architecture)...")
    
    # Test queue routing
    scan_queue = MultiQueueConfig.get_queue_for_task(TaskType.SCAN)
    print(f"✅ SCAN routing: {TaskType.SCAN} -> {scan_queue}")
    
    # Test frequency determination (unified)
    scan_freq = MultiQueueConfig.determine_tracking_frequency(2.0, 50.0)  # Always returns SCAN
    print(f"✅ Frequency determination (unified): Always -> {scan_freq}")
    
    # Test worker config
    worker_config = MultiQueueConfig.get_worker_config(QueueType.SCAN)
    print(f"✅ Worker config for SCAN: poll_interval={worker_config['poll_interval']}s")
    
    # Test task creation
    scan_task = create_scan_task("https://facebook.com/groups/test")
    print(f"✅ Task creation: scan={scan_task['task_type']}")
    
    print("✅ MultiQueueConfig test completed (unified SCAN architecture)!")


if __name__ == "__main__":
    test_multi_queue_config()




