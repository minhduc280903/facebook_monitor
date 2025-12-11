#!/usr/bin/env python3
"""
One-time migration script: proxies.txt + proxy_status.json → PostgreSQL

Run once during deployment:
    python migrations/migrate_proxies_to_db.py
"""

import sys
import os
import json
import shutil
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database_manager import DatabaseManager
from core.proxy_manager import ProxyManager
from logging_config import get_logger, setup_application_logging

setup_application_logging()
logger = get_logger(__name__)

def backup_files():
    """Backup original files"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    files_to_backup = ['proxies.txt', 'proxy_status.json']
    
    for filename in files_to_backup:
        if os.path.exists(filename):
            backup_name = f"{filename}.backup_{timestamp}"
            shutil.copy2(filename, backup_name)
            logger.info(f"📦 Backed up: {filename} → {backup_name}")

def migrate_proxies():
    """Main migration logic"""
    logger.info("🚀 Starting proxy migration to PostgreSQL...")
    
    # Check if proxies.txt exists
    if not os.path.exists('proxies.txt'):
        logger.warning("⚠️ proxies.txt not found - skipping migration")
        logger.info("💡 You can add proxies via Admin Panel UI instead")
        return True
    
    # Check if file is empty
    with open('proxies.txt', 'r') as f:
        content = f.read().strip()
        if not content or content.startswith('#'):
            logger.warning("⚠️ proxies.txt is empty - skipping migration")
            logger.info("💡 You can add proxies via Admin Panel UI instead")
            return True
    
    # Step 1: Backup files
    backup_files()
    
    # Step 2: Load existing data
    pm = ProxyManager()
    db = DatabaseManager()
    
    # Step 3: Read proxies from file
    proxies = pm._load_proxies_from_file()
    logger.info(f"📥 Loaded {len(proxies)} proxies from proxies.txt")
    
    # Step 4: Read status metadata from proxy_status.json
    try:
        with open('proxy_status.json', 'r') as f:
            proxy_status = json.load(f)
        logger.info(f"📥 Loaded status for {len(proxy_status)} proxies")
    except FileNotFoundError:
        proxy_status = {}
        logger.warning("⚠️ proxy_status.json not found, using defaults")
    
    # Step 5: Migrate to database
    migrated_count = 0
    for i, proxy_config in enumerate(proxies):
        proxy_id_key = f"proxy_{i+1}"
        
        # Get metadata if exists
        metadata = proxy_status.get(proxy_id_key, {})
        
        # Extract geolocation if exists
        geolocation = None
        if isinstance(metadata, dict) and 'metadata' in metadata:
            geolocation = metadata['metadata'].get('geolocation')
        
        # Insert into DB
        db_proxy_id = db.add_proxy(
            host=proxy_config['host'],
            port=proxy_config['port'],
            username=proxy_config.get('username'),
            password=proxy_config.get('password'),
            proxy_type=proxy_config.get('type', 'http')
        )
        
        if db_proxy_id and isinstance(metadata, dict):
            # Update with performance metadata
            db.update_proxy_status(
                proxy_id=db_proxy_id,
                status=metadata.get('status', 'READY'),
                metadata={
                    'consecutive_failures': metadata.get('consecutive_failures', 0),
                    'total_tasks': metadata.get('total_tasks', 0),
                    'successful_tasks': metadata.get('successful_tasks', 0),
                    'success_rate': metadata.get('success_rate', 1.0),
                    'geolocation': geolocation
                }
            )
        
        if db_proxy_id:
            migrated_count += 1
            logger.info(f"✅ Migrated proxy {proxy_id_key}: {proxy_config['host']}:{proxy_config['port']} → DB ID {db_proxy_id}")
    
    # Step 6: Summary
    logger.info("=" * 60)
    logger.info(f"✅ MIGRATION COMPLETE")
    logger.info(f"   Total proxies migrated: {migrated_count}/{len(proxies)}")
    logger.info(f"   Backup files created with timestamp")
    logger.info("=" * 60)
    logger.info("🎉 You can now use Admin Panel to manage proxies!")
    
    return migrated_count == len(proxies)

if __name__ == "__main__":
    try:
        success = migrate_proxies()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

