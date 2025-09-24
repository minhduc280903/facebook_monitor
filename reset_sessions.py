#!/usr/bin/env python3
"""
Reset Sessions and Proxies Script
Utility để reset tất cả sessions và proxies về trạng thái READY
"""

import json
import os
from datetime import datetime

def reset_sessions(status_file="session_status.json"):
    """Reset all sessions to READY status"""
    if not os.path.exists(status_file):
        print(f"❌ File {status_file} không tồn tại")
        return False
    
    try:
        with open(status_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        reset_count = 0
        for session_id, session_data in data.items():
            if session_data.get('status') != 'READY':
                old_status = session_data.get('status', 'unknown')
                session_data['status'] = 'READY'
                session_data['consecutive_failures'] = 0
                session_data['quarantine_until_timestamp'] = None
                session_data['quarantine_reason'] = None
                reset_count += 1
                print(f"✅ Session {session_id}: {old_status} → READY")
        
        if reset_count > 0:
            with open(status_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"🔄 Reset {reset_count} sessions thành công")
        else:
            print("✨ Tất cả sessions đã ở trạng thái READY")
            
        return True
        
    except Exception as e:
        print(f"❌ Lỗi reset sessions: {e}")
        return False

def reset_proxies(status_file="proxy_status.json"):
    """Reset all proxies to READY status"""
    if not os.path.exists(status_file):
        print(f"❌ File {status_file} không tồn tại")
        return False
    
    try:
        with open(status_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        reset_count = 0
        for proxy_id, proxy_data in data.items():
            if proxy_data.get('status') != 'READY':
                old_status = proxy_data.get('status', 'unknown')
                proxy_data['status'] = 'READY'
                proxy_data['consecutive_failures'] = 0
                proxy_data['quarantine_until_timestamp'] = None
                proxy_data['quarantine_reason'] = None
                reset_count += 1
                print(f"✅ Proxy {proxy_id}: {old_status} → READY")
        
        if reset_count > 0:
            with open(status_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"🔄 Reset {reset_count} proxies thành công")
        else:
            print("✨ Tất cả proxies đã ở trạng thái READY")
            
        return True
        
    except Exception as e:
        print(f"❌ Lỗi reset proxies: {e}")
        return False

def show_status():
    """Show current status of sessions and proxies"""
    print("📊 CURRENT STATUS:")
    print("=" * 50)
    
    # Sessions status
    if os.path.exists("session_status.json"):
        with open("session_status.json", 'r') as f:
            sessions = json.load(f)
        print(f"🔐 SESSIONS ({len(sessions)} total):")
        for sid, data in sessions.items():
            status = data.get('status', 'unknown')
            role = data.get('role', 'unknown')
            print(f"  - {sid}: {status} ({role})")
    
    print()
    
    # Proxies status  
    if os.path.exists("proxy_status.json"):
        with open("proxy_status.json", 'r') as f:
            proxies = json.load(f)
        print(f"🌐 PROXIES ({len(proxies)} total):")
        for pid, data in proxies.items():
            status = data.get('status', 'unknown')
            host = data.get('metadata', {}).get('config', {}).get('host', 'unknown')
            print(f"  - {pid}: {status} ({host})")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Reset Sessions and Proxies to READY status")
    parser.add_argument("--sessions", action="store_true", help="Reset sessions only")
    parser.add_argument("--proxies", action="store_true", help="Reset proxies only") 
    parser.add_argument("--status", action="store_true", help="Show current status only")
    parser.add_argument("--all", action="store_true", help="Reset both sessions and proxies")
    
    args = parser.parse_args()
    
    if args.status:
        show_status()
    elif args.sessions:
        reset_sessions()
    elif args.proxies:
        reset_proxies() 
    elif args.all or (not args.sessions and not args.proxies and not args.status):
        # Default: reset both
        print("🔄 Resetting both sessions and proxies...")
        reset_sessions()
        reset_proxies()
        print("\n📊 Final status:")
        show_status()
    
    print("\n✅ Done! You can now run manual_scrape_test.py")
