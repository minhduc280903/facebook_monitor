#!/usr/bin/env python3
"""
Test script để verify và benchmark tracking query optimization

Kiểm tra:
1. Active tracking posts table được tạo đúng chưa
2. Triggers hoạt động đúng khi INSERT/UPDATE/DELETE posts
3. Performance improvement so với query gốc
4. Fallback mechanism hoạt động
"""

import time
import logging
import statistics
from datetime import datetime, timezone, timedelta

from core.database_manager import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_optimization_setup():
    """Test xem optimization infrastructure đã được setup chưa."""
    logger.info("🧪 Test 1: Checking optimization setup...")
    
    try:
        db_manager = DatabaseManager()
        cursor = db_manager.connection.cursor()
        
        # Check active_tracking_posts table exists
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'active_tracking_posts'
            );
        """)
        table_exists = cursor.fetchone()[0]
        logger.info("✅ active_tracking_posts table exists: %s", table_exists)
        
        # Check trigger function exists
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM pg_proc 
                WHERE proname = 'sync_active_tracking_posts'
            );
        """)
        function_exists = cursor.fetchone()[0]
        logger.info("✅ sync_active_tracking_posts function exists: %s", function_exists)
        
        # Check trigger exists
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.triggers 
                WHERE trigger_name = 'trigger_sync_active_tracking_posts'
                AND event_object_table = 'posts'
            );
        """)
        trigger_exists = cursor.fetchone()[0]
        logger.info("✅ trigger_sync_active_tracking_posts exists: %s", trigger_exists)
        
        # Check cleanup function exists
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM pg_proc 
                WHERE proname = 'cleanup_expired_tracking_posts'
            );
        """)
        cleanup_exists = cursor.fetchone()[0]
        logger.info("✅ cleanup_expired_tracking_posts function exists: %s", cleanup_exists)
        
        # Check tracking_stats view exists
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.views 
                WHERE table_name = 'tracking_stats'
            );
        """)
        view_exists = cursor.fetchone()[0]
        logger.info("✅ tracking_stats view exists: %s", view_exists)
        
        db_manager.close()
        return all([table_exists, function_exists, trigger_exists, cleanup_exists, view_exists])
        
    except Exception as e:
        logger.error("❌ Error checking optimization setup: %s", e)
        return False


def test_trigger_functionality():
    """Test trigger synchronization between posts and active_tracking_posts."""
    logger.info("🧪 Test 2: Testing trigger functionality...")
    
    try:
        db_manager = DatabaseManager()
        cursor = db_manager.connection.cursor()
        
        # Create test post
        test_signature = f"test_optimization_{int(time.time())}"
        test_url = "http://example.com/test"
        test_source = "http://example.com/group"
        
        # Insert new TRACKING post
        success = db_manager.add_new_post(
            post_signature=test_signature,
            post_url=test_url,
            source_url=test_source
        )
        
        if not success:
            logger.error("❌ Failed to insert test post")
            return False
        
        # Check if post appears in active_tracking_posts
        cursor.execute("""
            SELECT COUNT(*) FROM active_tracking_posts 
            WHERE post_signature = %s
        """, (test_signature,))
        
        count = cursor.fetchone()[0]
        logger.info("✅ Post automatically added to active_tracking_posts: %s", count == 1)
        
        # Update post to EXPIRED
        cursor.execute("""
            UPDATE posts 
            SET status = 'EXPIRED' 
            WHERE post_signature = %s
        """, (test_signature,))
        db_manager.connection.commit()
        
        # Check if post removed from active_tracking_posts
        cursor.execute("""
            SELECT COUNT(*) FROM active_tracking_posts 
            WHERE post_signature = %s
        """, (test_signature,))
        
        count_after = cursor.fetchone()[0]
        logger.info("✅ Post automatically removed from active_tracking_posts: %s", count_after == 0)
        
        db_manager.close()
        return count == 1 and count_after == 0
        
    except Exception as e:
        logger.error("❌ Error testing trigger functionality: %s", e)
        return False


def benchmark_query_performance(num_runs: int = 10):
    """Benchmark performance của optimized vs original query."""
    logger.info("🧪 Test 3: Benchmarking query performance (%d runs)...", num_runs)
    
    try:
        db_manager = DatabaseManager()
        cursor = db_manager.connection.cursor()
        
        # Get current active posts count
        cursor.execute("SELECT COUNT(*) FROM posts WHERE status = 'TRACKING'")
        total_posts = cursor.fetchone()[0]
        logger.info("📊 Total TRACKING posts in database: %s", total_posts)
        
        if total_posts == 0:
            logger.warning("⚠️ No TRACKING posts found for benchmarking")
            return False
        
        # Benchmark optimized query
        optimized_times = []
        for i in range(num_runs):
            start_time = time.perf_counter()
            posts = db_manager.get_active_tracking_posts()
            end_time = time.perf_counter()
            
            optimized_times.append(end_time - start_time)
            logger.debug("Run %d: Optimized query took %.4fs, returned %d posts", 
                        i+1, optimized_times[-1], len(posts))
        
        # Benchmark fallback query
        fallback_times = []
        for i in range(num_runs):
            start_time = time.perf_counter()
            posts = db_manager._get_active_tracking_posts_fallback()
            end_time = time.perf_counter()
            
            fallback_times.append(end_time - start_time)
            logger.debug("Run %d: Fallback query took %.4fs, returned %d posts", 
                        i+1, fallback_times[-1], len(posts))
        
        # Calculate statistics
        optimized_avg = statistics.mean(optimized_times)
        optimized_median = statistics.median(optimized_times)
        fallback_avg = statistics.mean(fallback_times)
        fallback_median = statistics.median(fallback_times)
        
        improvement_factor = fallback_avg / optimized_avg if optimized_avg > 0 else 0
        
        logger.info("📊 Performance Results:")
        logger.info("  Optimized Query:")
        logger.info("    Average: %.4fs", optimized_avg)
        logger.info("    Median:  %.4fs", optimized_median)
        logger.info("  Fallback Query:")
        logger.info("    Average: %.4fs", fallback_avg)
        logger.info("    Median:  %.4fs", fallback_median)
        logger.info("  Performance Improvement: %.2fx faster", improvement_factor)
        
        db_manager.close()
        return improvement_factor > 1.0
        
    except Exception as e:
        logger.error("❌ Error benchmarking performance: %s", e)
        return False


def test_priority_functionality():
    """Test priority score functionality."""
    logger.info("🧪 Test 4: Testing priority functionality...")
    
    try:
        db_manager = DatabaseManager()
        
        # Get some active posts for testing
        active_posts = db_manager.get_active_tracking_posts()
        
        if not active_posts:
            logger.warning("⚠️ No active posts found for priority testing")
            return True  # Not a failure, just no data
        
        test_post = active_posts[0]
        post_signature = test_post['post_signature']
        
        # Test updating priority
        success = db_manager.update_post_priority(post_signature, 85)
        logger.info("✅ Priority update successful: %s", success)
        
        # Test getting tracking stats
        stats = db_manager.get_tracking_stats()
        logger.info("✅ Tracking stats: %s", stats)
        
        db_manager.close()
        return success and bool(stats)
        
    except Exception as e:
        logger.error("❌ Error testing priority functionality: %s", e)
        return False


def test_cleanup_functionality():
    """Test cleanup function for expired posts."""
    logger.info("🧪 Test 5: Testing cleanup functionality...")
    
    try:
        db_manager = DatabaseManager()
        
        # Create a test post that's already expired
        test_signature = f"test_expired_{int(time.time())}"
        
        # Add post with expired tracking time
        expired_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        
        cursor = db_manager.connection.cursor()
        cursor.execute("""
            INSERT INTO posts (
                post_signature, post_url, source_url, 
                first_seen_utc, tracking_expires_utc, status
            ) VALUES (%s, %s, %s, %s, %s, 'TRACKING')
        """, (test_signature, "http://test.com", "http://test.com/group", 
              expired_time, expired_time))
        db_manager.connection.commit()
        
        # Test cleanup
        expired_count = db_manager.expire_old_posts()
        logger.info("✅ Cleanup removed %d expired posts", expired_count)
        
        # Verify test post was moved to EXPIRED
        cursor.execute("""
            SELECT status FROM posts WHERE post_signature = %s
        """, (test_signature,))
        result = cursor.fetchone()
        
        if result:
            final_status = result[0]
            logger.info("✅ Test post final status: %s", final_status)
            cleanup_success = final_status == 'EXPIRED'
        else:
            cleanup_success = False
        
        db_manager.close()
        return cleanup_success
        
    except Exception as e:
        logger.error("❌ Error testing cleanup functionality: %s", e)
        return False


def main():
    """Run all optimization tests."""
    logger.info("🚀 Testing Tracking Query Optimization")
    logger.info("=" * 60)
    
    tests = [
        ("Optimization Setup", test_optimization_setup),
        ("Trigger Functionality", test_trigger_functionality),
        ("Query Performance", lambda: benchmark_query_performance(5)),
        ("Priority Functionality", test_priority_functionality),
        ("Cleanup Functionality", test_cleanup_functionality),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        logger.info(f"\n🧪 Running: {test_name}")
        try:
            result = test_func()
            results.append((test_name, result))
            
            if result:
                logger.info(f"✅ {test_name}: PASSED")
            else:
                logger.error(f"❌ {test_name}: FAILED")
                
        except Exception as e:
            logger.error(f"💥 {test_name}: ERROR - {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info("\n📊 Test Results Summary:")
    logger.info("=" * 40)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {status} {test_name}")
    
    logger.info("=" * 40)
    logger.info(f"📈 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tracking optimization tests passed!")
        logger.info("🚀 Tracking scheduler should now be significantly faster!")
    else:
        logger.warning("⚠️ Some tests failed. Check logs for details.")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
