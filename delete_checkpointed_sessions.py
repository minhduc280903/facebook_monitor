#!/usr/bin/env python3
"""
Script để xóa 2 sessions bị checkpoint
- 61578165133264
- 61578712612507

Xóa từ:
1. Session folders
2. Database (accounts table)
3. session_status.json
4. session_proxy_bindings.json
"""

import os
import json
import shutil
from core.database_manager import DatabaseManager

# Sessions to delete
CHECKPOINTED_SESSIONS = ["61578165133264", "61578712612507"]

def delete_sessions():
    print("="*80)
    print("DELETING CHECKPOINTED SESSIONS")
    print("="*80)
    
    db = DatabaseManager()
    deleted_count = 0
    
    for session_id in CHECKPOINTED_SESSIONS:
        print(f"\n🗑️  Processing session: {session_id}")
        
        # 1. Delete session folder
        session_folder = f"sessions/{session_id}"
        if os.path.exists(session_folder):
            try:
                shutil.rmtree(session_folder)
                print(f"  ✅ Deleted folder: {session_folder}")
            except Exception as e:
                print(f"  ❌ Error deleting folder: {e}")
        else:
            print(f"  ⚠️  Folder not found: {session_folder}")
        
        # 2. Delete from database (accounts table)
        try:
            # Get account by facebook_id
            accounts = db.get_all_accounts()
            account_id = None
            for acc in accounts:
                if acc['facebook_id'] == session_id:
                    account_id = acc['id']
                    break
            
            if account_id:
                # Delete account
                sql = "DELETE FROM accounts WHERE id = %s"
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(sql, (account_id,))
                    conn.commit()
                print(f"  ✅ Deleted from database (account ID: {account_id})")
            else:
                print(f"  ⚠️  Account not found in database")
        except Exception as e:
            print(f"  ❌ Error deleting from database: {e}")
        
        # 3. Remove from session_status.json
        try:
            if os.path.exists("session_status.json"):
                with open("session_status.json", "r") as f:
                    data = json.load(f)
                
                if session_id in data:
                    del data[session_id]
                    
                    with open("session_status.json", "w") as f:
                        json.dump(data, f, indent=2)
                    print(f"  ✅ Removed from session_status.json")
                else:
                    print(f"  ⚠️  Not found in session_status.json")
        except Exception as e:
            print(f"  ❌ Error updating session_status.json: {e}")
        
        # 4. Remove from session_proxy_bindings.json
        try:
            if os.path.exists("session_proxy_bindings.json"):
                with open("session_proxy_bindings.json", "r") as f:
                    data = json.load(f)
                
                bindings = data.get("bindings", {})
                if session_id in bindings:
                    del bindings[session_id]
                    data["bindings"] = bindings
                    
                    with open("session_proxy_bindings.json", "w") as f:
                        json.dump(data, f, indent=2)
                    print(f"  ✅ Removed from session_proxy_bindings.json")
                else:
                    print(f"  ⚠️  Not found in session_proxy_bindings.json")
        except Exception as e:
            print(f"  ❌ Error updating session_proxy_bindings.json: {e}")
        
        deleted_count += 1
        print(f"  ✅ Session {session_id} deleted successfully")
    
    print(f"\n{'='*80}")
    print(f"✅ Deleted {deleted_count}/{len(CHECKPOINTED_SESSIONS)} sessions")
    print(f"{'='*80}")

if __name__ == '__main__':
    delete_sessions()





