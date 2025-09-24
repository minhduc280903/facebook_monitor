#!/usr/bin/env python3
"""
Test script để verify PostgreSQL LISTEN/NOTIFY implementation

Kiểm tra:
1. Trigger function đã được tạo đúng chưa
2. LISTEN/NOTIFY hoạt động khi có INSERT vào interactions table
3. data_broadcaster nhận notification correctly
"""

import json
import logging
import psycopg2
import time
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor

from core.database_manager import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_trigger_exists():
    """Test xem trigger function đã được tạo chưa."""
    try:
        db_manager = DatabaseManager()
        cursor = db_manager.connection.cursor()
        
        # Check trigger function exists
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM pg_proc 
                WHERE proname = 'notify_new_interaction'
            );
        """)
        
        function_exists = cursor.fetchone()[0]
        logger.info("✅ Trigger function exists: %s", function_exists)
        
        # Check trigger exists
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.triggers 
                WHERE trigger_name = 'trigger_notify_new_interaction'
                AND event_object_table = 'interactions'
            );
        """)
        
        trigger_exists = cursor.fetchone()[0]
        logger.info("✅ Trigger exists: %s", trigger_exists)
        
        db_manager.close()
        return function_exists and trigger_exists
        
    except Exception as e:
        logger.error("❌ Error checking trigger: %s", e)
        return False


def test_manual_notify():
    """Test manual NOTIFY to verify LISTEN works."""
    try:
        db_manager = DatabaseManager()
        
        # Create separate connection for LISTEN
        db_config = db_manager.db_config
        listen_conn = psycopg2.connect(
            host=db_config.host,
            port=db_config.port,
            user=db_config.user,
            password=db_config.password,
            dbname=db_config.name,
            cursor_factory=RealDictCursor
        )
        listen_conn.autocommit = True
        
        # Start listening
        listen_cursor = listen_conn.cursor()
        listen_cursor.execute("LISTEN new_interaction")
        logger.info("📻 Started LISTEN on new_interaction channel")
        
        # Send manual NOTIFY from main connection  
        main_cursor = db_manager.connection.cursor()
        test_payload = {
            "id": 999999,
            "post_signature": "test_signature_123",
            "log_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "like_count": 100,
            "comment_count": 50
        }
        
        main_cursor.execute(
            "SELECT pg_notify('new_interaction', %s)",
            (json.dumps(test_payload),)
        )
        db_manager.connection.commit()
        logger.info("📡 Sent manual NOTIFY with test payload")
        
        # Listen for notification
        import select
        if select.select([listen_conn], [], [], 5.0) != ([], [], []):
            listen_conn.poll()
            
            if listen_conn.notifies:
                notify = listen_conn.notifies.popleft()
                payload = json.loads(notify.payload)
                logger.info("✅ Received notification: %s", payload)
                
                listen_conn.close()
                db_manager.close()
                return True
            else:
                logger.error("❌ No notifications received")
                
        else:
            logger.error("❌ LISTEN timeout - no notifications")
            
        listen_conn.close()
        db_manager.close()
        return False
        
    except Exception as e:
        logger.error("❌ Error testing manual notify: %s", e)
        return False


def test_trigger_notify():
    """Test trigger NOTIFY by inserting real interaction."""
    try:
        db_manager = DatabaseManager()
        
        # Create separate connection for LISTEN
        db_config = db_manager.db_config
        listen_conn = psycopg2.connect(
            host=db_config.host,
            port=db_config.port,
            user=db_config.user,
            password=db_config.password,
            dbname=db_config.name,
            cursor_factory=RealDictCursor
        )
        listen_conn.autocommit = True
        
        # Start listening
        listen_cursor = listen_conn.cursor()
        listen_cursor.execute("LISTEN new_interaction")
        logger.info("📻 Started LISTEN on new_interaction channel")
        
        # Insert test interaction to trigger NOTIFY
        test_signature = f"test_trigger_{int(time.time())}"
        test_timestamp = datetime.now(timezone.utc).isoformat()
        
        success = db_manager.log_interaction(
            post_signature=test_signature,
            log_timestamp_utc=test_timestamp,
            like_count=123,
            comment_count=45
        )
        
        if not success:
            logger.error("❌ Failed to insert test interaction")
            return False
            
        logger.info("✅ Inserted test interaction: %s", test_signature)
        
        # Listen for notification from trigger
        import select
        if select.select([listen_conn], [], [], 5.0) != ([], [], []):
            listen_conn.poll()
            
            if listen_conn.notifies:
                notify = listen_conn.notifies.popleft()
                payload = json.loads(notify.payload)
                logger.info("✅ Received trigger notification: %s", payload)
                
                # Verify payload contains expected data
                if payload.get('post_signature') == test_signature:
                    logger.info("✅ Trigger notification payload is correct")
                    listen_conn.close()
                    db_manager.close()
                    return True
                else:
                    logger.error("❌ Trigger notification payload incorrect")
                    
            else:
                logger.error("❌ No trigger notifications received")
                
        else:
            logger.error("❌ LISTEN timeout - no trigger notifications")
            
        listen_conn.close()
        db_manager.close()
        return False
        
    except Exception as e:
        logger.error("❌ Error testing trigger notify: %s", e)
        return False


def main():
    """Run all tests."""
    logger.info("🧪 Testing PostgreSQL LISTEN/NOTIFY implementation")
    logger.info("=" * 60)
    
    # Test 1: Check trigger exists
    logger.info("Test 1: Checking trigger function and trigger exist...")
    if not test_trigger_exists():
        logger.error("❌ Trigger not properly set up!")
        return False
    
    # Test 2: Manual NOTIFY
    logger.info("\nTest 2: Testing manual NOTIFY...")
    if not test_manual_notify():
        logger.error("❌ Manual NOTIFY test failed!")
        return False
    
    # Test 3: Trigger NOTIFY
    logger.info("\nTest 3: Testing trigger NOTIFY...")
    if not test_trigger_notify():
        logger.error("❌ Trigger NOTIFY test failed!")
        return False
    
    logger.info("\n✅ All LISTEN/NOTIFY tests passed!")
    logger.info("🎯 data_broadcaster.py should now work with real-time notifications")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
