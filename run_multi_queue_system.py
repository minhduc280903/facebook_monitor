#!/usr/bin/env python3
"""
Orchestrator Script for Unified SCAN Facebook Post Monitor System
Khởi chạy và quản lý toàn bộ hệ thống SCAN thống nhất

Chức năng:
- Khởi chạy Scan Scheduler + Multiple SCAN Workers  
- Quản lý lifecycle của các processes
- Monitoring và health checking
- Graceful shutdown
"""

import subprocess
import sys
import os
import time
import signal
import logging
import asyncio
from logging_config import get_logger, setup_application_logging
from utils.async_patterns import AsyncSystemManager
from typing import List, Dict, Optional
from datetime import datetime
import argparse

# Initialize centralized logging for multi-queue system
setup_application_logging()
logger = get_logger(__name__)


class ProcessManager:
    """Manager cho multiple processes của hệ thống"""

    def __init__(self):
        self.processes: List[subprocess.Popen] = []
        self.process_info: List[Dict] = []
        self.running = False

        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info("📡 Received signal %s, shutting down...", signum)
        # Note: Cannot use await in signal handler, will be handled elsewhere
        self.running = False
        sys.exit(0)

    async def start_process(
        self, command: List[str], name: str, cwd: Optional[str] = None
    ) -> bool:
        """
        Start một process mới

        Args:
            command: Command để chạy
            name: Tên description của process
            cwd: Working directory

        Returns:
            True nếu start thành công
        """
        try:
            logger.info("🚀 Starting %s...", name)
            logger.debug("Command: %s", ' '.join(command))

            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Kiểm tra process có start thành công không - Non-blocking
            await AsyncSystemManager.system_stabilization(2.0, "process startup check")
            if process.poll() is not None:
                # Process đã terminate
                stdout, stderr = process.communicate()
                logger.error("❌ %s failed to start:", name)
                logger.error("STDOUT: %s", stdout)
                logger.error("STDERR: %s", stderr)
                return False

            self.processes.append(process)
            self.process_info.append({
                'name': name,
                'command': command,
                'started_at': datetime.now(),
                'pid': process.pid
            })

            logger.info("✅ %s started successfully (PID: %s)", name, process.pid)
            return True

        except Exception as e:
            logger.error("❌ Failed to start %s: %s", name, e)
            return False

    def check_processes(self) -> Dict[str, int]:
        """
        Check health của tất cả processes

        Returns:
            Dict với statistics
        """
        stats = {'running': 0, 'failed': 0, 'total': len(self.processes)}

        for i, (process, info) in enumerate(zip(self.processes, self.process_info)):
            if process.poll() is None:
                # Process đang chạy
                stats['running'] += 1
            else:
                # Process đã terminate
                stats['failed'] += 1
                logger.warning("⚠️ Process %s has terminated (PID: %s)", info['name'], info['pid'])

                # Log output nếu có
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    if stderr:
                        logger.error("STDERR from %s: %s", info['name'], stderr)
                except (subprocess.TimeoutExpired, OSError, ValueError):
                    pass

        return stats

    async def shutdown(self):
        """Gracefully shutdown tất cả processes"""
        if not self.running:
            return

        logger.info("🛑 Shutting down all processes...")
        self.running = False

        # Send SIGTERM to all processes
        for process, info in zip(self.processes, self.process_info):
            if process.poll() is None:  # Process đang chạy
                logger.info("🛑 Terminating %s (PID: %s)", info['name'], info['pid'])
                try:
                    process.terminate()
                except (OSError, subprocess.SubprocessError):
                    pass

        # Wait for graceful shutdown - Non-blocking
        logger.info("⏳ Waiting for graceful shutdown...")
        await AsyncSystemManager.graceful_shutdown(5.0)

        # Force kill nếu cần
        for process, info in zip(self.processes, self.process_info):
            if process.poll() is None:  # Vẫn đang chạy
                logger.warning("🔨 Force killing %s (PID: %s)", info['name'], info['pid'])
                try:
                    process.kill()
                except (OSError, subprocess.SubprocessError):
                    pass

        logger.info("✅ All processes shutdown complete")

    async def run_monitoring_loop(self):
        """Main monitoring loop"""
        self.running = True
        last_check = time.time()

        logger.info("👁️ Starting monitoring loop...")

        try:
            while self.running:
                now = time.time()

                # Check processes every 30 seconds
                if now - last_check >= 30:
                    stats = self.check_processes()
                    logger.info("📊 Process stats: %s/%s running", stats['running'], stats['total'])

                    # Alert nếu có process failed
                    if stats['failed'] > 0:
                        logger.warning("⚠️ %s processes have failed!", stats['failed'])

                    last_check = now

                # Non-blocking health monitoring interval
                await asyncio.sleep(5.0)

        except KeyboardInterrupt:
            logger.info("👋 Monitoring loop interrupted")
        finally:
            await self.shutdown()


def check_prerequisites() -> bool:
    """Check xem tất cả prerequisites có sẵn không"""
    logger.info("🔍 Checking prerequisites...")

    # Check Python modules
    required_modules = ['redis', 'psycopg2', 'playwright']
    for module in required_modules:
        try:
            __import__(module)
            logger.debug("✅ Module %s available", module)
        except ImportError:
            logger.error("❌ Required module %s not found", module)
            logger.error("Install with: pip install %s", module)
            return False

    # Check Redis connection
    try:
        import redis
        r = redis.Redis(host='redis', port=6379, decode_responses=True)
        r.ping()
        logger.debug("✅ Redis connection OK")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        logger.error("Make sure Redis server is running on redis:6379")
        return False

    # Check required files
    required_files = [
        'multi_queue_config.py',
        'scan_scheduler.py',
        'multi_queue_worker.py',
        'core/database_manager.py',
        'core/session_manager.py',
        'core/proxy_manager.py'
    ]

    for file in required_files:
        if not os.path.exists(file):
            logger.error(f"❌ Required file not found: {file}")
            return False
        logger.debug(f"✅ File {file} exists")

    logger.info("✅ All prerequisites check passed")
    return True


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Run Multi-Queue Facebook Post Monitor System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example configurations (UNIFIED SCAN ARCHITECTURE):

1. Full system (recommended):
   python run_multi_queue_system.py --workers 8
   → Starts scan scheduler + 8 unified scan workers

2. Development setup:
   python run_multi_queue_system.py --workers 3
   → Lightweight setup for development

3. High-performance setup:
   python run_multi_queue_system.py --workers 15
   → Production setup for high traffic

4. Testing setup:
   python run_multi_queue_system.py --workers 1 --no-schedulers
   → Single worker for testing

UNIFIED SCAN ARCHITECTURE BENEFITS:
- Single queue (scan_queue) replaces old dual queues
- Time-based filtering with start_date management  
- Unified discovery + tracking logic in one process
- Simplified worker management
- Better resource utilization
        """
    )

    parser.add_argument("--workers", type=int, default=5,
                       help="Number of scan workers (default: 5)")
    parser.add_argument("--full", action="store_true",
                       help="Run full system with recommended worker count (8 workers)")
    parser.add_argument("--no-schedulers", action="store_true",
                       help="Run only workers, no schedulers (for testing)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Apply presets
    if args.full:
        args.workers = 8

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║           UNIFIED SCAN SYSTEM ORCHESTRATOR                  ║")
    print("║                                                              ║")
    print("║  🔍 Unified Scan Scheduler với Time-based Filtering         ║")
    print("║  📈 Single Queue Architecture (scan_queue)                  ║")
    print("║  🔄 Scan Workers với Integrated Discovery+Tracking          ║")
    print("║  📊 Real-time Monitoring và Health Checking                 ║")
    print("║  📅 Start Date Management cho Time-based Filtering          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # Check prerequisites
    if not check_prerequisites():
        logger.error("💥 Prerequisites check failed. Please fix the issues above.")
        sys.exit(1)

    # Configuration summary
    print("📋 Configuration (UNIFIED SCAN ARCHITECTURE):")
    print(f"  • Scan workers: {args.workers}")
    print(f"  • Scan scheduler: {'No' if args.no_schedulers else 'Yes'}")
    print(f"  • Queue: scan_queue (unified)")
    print(f"  • Architecture: Time-based filtering với start_date")
    print(f"  • Mode: Unified discovery + tracking logic")
    print()

    input("Press Enter to start the system...")

    # Start system
    manager = ProcessManager()

    try:
        # Start schedulers (nếu không có --no-schedulers)
        if not args.no_schedulers:
            # API Server (start first)
            if not await manager.start_process(
                [sys.executable, "api/main.py"],
                "API Server"
            ):
                logger.warning("⚠️ Failed to start API Server (non-critical)")
            
            # Unified Scan Scheduler
            if not await manager.start_process(
                [sys.executable, "scan_scheduler.py"],
                "Unified Scan Scheduler"
            ):
                logger.error("💥 Failed to start Scan Scheduler")
                sys.exit(1)

        # Start workers
        # Cho scheduler thời gian khởi động
        await AsyncSystemManager.system_stabilization(3.0, "scheduler")

        # Unified Scan workers
        logger.info(f"🆕 Starting {args.workers} unified scan workers")
        
        for i in range(args.workers):
            if not await manager.start_process(
                [sys.executable, "multi_queue_worker.py", "--queues", "scan"],
                f"Scan Worker {i+1}"
            ):
                logger.warning(f"⚠️ Failed to start Scan Worker {i+1}")

        # Check initial health - Non-blocking
        await AsyncSystemManager.system_stabilization(5.0, "initial health check")
        stats = manager.check_processes()

        if stats['running'] == 0:
            logger.error("💥 No processes started successfully!")
            sys.exit(1)

        logger.info("🎉 System started successfully!")
        logger.info(f"📊 {stats['running']}/{stats['total']} processes running")

        # Start monitoring loop
        await manager.run_monitoring_loop()

    except KeyboardInterrupt:
        logger.info("👋 System shutdown requested")
    except Exception as e:
        logger.error(f"💥 System error: {e}")
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
