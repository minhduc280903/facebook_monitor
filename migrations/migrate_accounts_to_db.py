#!/usr/bin/env python3
"""
One-time migration script: account.txt → PostgreSQL

Run once during deployment:
    python migrations/migrate_accounts_to_db.py
    
Format account.txt:
    Line format: id|password|2fa|cookies|email|...
    Example: 61577138955782|password123|TOTP_SECRET|c_user=xxx;xs=yyy|email@example.com
"""

import sys
import os
import json
import shutil
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database_manager import DatabaseManager
from logging_config import get_logger, setup_application_logging

setup_application_logging()
logger = get_logger(__name__)

def backup_files():
    """Backup original files"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    files_to_backup = ['account.txt']
    
    for filename in files_to_backup:
        if os.path.exists(filename):
            backup_name = f"{filename}.backup_{timestamp}"
            shutil.copy2(filename, backup_name)
            logger.info(f"📦 Backed up: {filename} → {backup_name}")

def parse_account_line(line: str) -> dict:
    """
    Parse account.txt line to account dict
    
    Format: id|password|2fa_secret|cookies|email|password_recovery|email_recovery|m_c508
    """
    parts = line.strip().split('|')
    
    if len(parts) < 2:
        return None
    
    account = {
        'facebook_id': parts[0].strip(),
        'password': parts[1].strip() if len(parts) > 1 else None,
        'totp_secret': parts[2].strip() if len(parts) > 2 and parts[2].strip() else None,
        'cookies': parts[3].strip() if len(parts) > 3 and parts[3].strip() else None,
        'email': parts[4].strip() if len(parts) > 4 and parts[4].strip() else None,
        'additional_data': {}
    }
    
    # Additional fields
    if len(parts) > 5 and parts[5].strip():
        account['additional_data']['password_recovery'] = parts[5].strip()
    if len(parts) > 6 and parts[6].strip():
        account['additional_data']['email_recovery'] = parts[6].strip()
    if len(parts) > 7 and parts[7].strip():
        account['additional_data']['m_c508'] = parts[7].strip()
    if len(parts) > 8 and parts[8].strip():
        account['additional_data']['device_id'] = parts[8].strip()
    
    return account

def load_accounts_from_file(file_path: str) -> list:
    """Load accounts from account.txt"""
    accounts = []
    
    if not os.path.exists(file_path):
        logger.warning(f"⚠️ Account file not found: {file_path}")
        return accounts
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            account = parse_account_line(line)
            if account:
                accounts.append(account)
            else:
                logger.warning(f"⚠️ Invalid account format at line {line_num}: {line[:50]}...")
        
        logger.info(f"📥 Loaded {len(accounts)} accounts from {file_path}")
        return accounts
        
    except Exception as e:
        logger.error(f"❌ Error loading account file: {e}")
        return []

def check_existing_sessions(account):
    """Check if session folder exists for this account"""
    facebook_id = account['facebook_id']
    session_folder = f"sessions/{facebook_id}"
    
    if os.path.exists(session_folder):
        return {
            'session_folder': session_folder,
            'session_status': 'LOGGED_IN'
        }
    else:
        return {
            'session_folder': None,
            'session_status': 'NOT_CREATED'
        }

def migrate_accounts():
    """Main migration logic"""
    logger.info("🚀 Starting account migration to PostgreSQL...")
    
    # Check if account.txt exists
    if not os.path.exists('account.txt'):
        logger.warning("⚠️ account.txt not found - skipping migration")
        logger.info("💡 You can add accounts via Admin Panel UI instead")
        return True
    
    # Check if file is empty or only has comments
    with open('account.txt', 'r') as f:
        lines = [line.strip() for line in f.readlines()]
        non_comment_lines = [line for line in lines if line and not line.startswith('#')]
        if not non_comment_lines:
            logger.warning("⚠️ account.txt is empty - skipping migration")
            logger.info("💡 You can add accounts via Admin Panel UI instead")
            return True
    
    # Step 1: Backup files
    backup_files()
    
    # Step 2: Load existing data
    db = DatabaseManager()
    accounts = load_accounts_from_file('account.txt')
    
    if not accounts:
        logger.warning("⚠️ No accounts found to migrate")
        return True
    
    # Step 3: Migrate to database
    migrated_count = 0
    skipped_count = 0
    
    for account in accounts:
        # Check if session exists
        session_info = check_existing_sessions(account)
        
        # Insert into DB
        account_id = db.add_account(
            facebook_id=account['facebook_id'],
            email=account.get('email'),
            password=account.get('password'),
            totp_secret=account.get('totp_secret'),
            cookies=account.get('cookies'),
            additional_data=account.get('additional_data')
        )
        
        if account_id:
            # Update session info if session exists
            if session_info['session_folder']:
                db.update_account_session(
                    account_id=account_id,
                    session_folder=session_info['session_folder'],
                    session_status=session_info['session_status']
                )
            
            migrated_count += 1
            logger.info(f"✅ Migrated account {account['facebook_id']} → DB ID {account_id} (session: {session_info['session_status']})")
        else:
            skipped_count += 1
            logger.warning(f"⚠️ Skipped account {account['facebook_id']} (already exists)")
    
    # Step 4: Summary
    logger.info("=" * 60)
    logger.info(f"✅ MIGRATION COMPLETE")
    logger.info(f"   Total accounts migrated: {migrated_count}")
    logger.info(f"   Skipped (duplicates): {skipped_count}")
    logger.info(f"   Backup files created with timestamp")
    logger.info("=" * 60)
    logger.info("🎉 You can now use Admin Panel to manage accounts!")
    
    return True

if __name__ == "__main__":
    try:
        success = migrate_accounts()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

