#!/usr/bin/env python3
"""
Admin Panel for Facebook Post Monitor
Quản lý proxies và accounts/sessions centralized trên VPS
"""

import streamlit as st
import pandas as pd
import sys
import os
import subprocess
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.database_manager import DatabaseManager
from core.session_manager import SessionManager
from core.proxy_manager import ProxyManager
from core.session_proxy_binder import SessionProxyBinder

# Page config
st.set_page_config(
    page_title="Admin Panel",
    page_icon="⚙️",
    layout="wide"
)

st.title("⚙️ Admin Panel")
st.markdown("*Quản lý Proxies, Accounts & Sessions*")

# Initialize managers
@st.cache_resource
def get_managers():
    db = DatabaseManager()
    session_mgr = SessionManager()
    proxy_mgr = ProxyManager(db_manager=db)
    binder = SessionProxyBinder(db_manager=db)
    return db, session_mgr, proxy_mgr, binder

db, session_mgr, proxy_mgr, binder = get_managers()

# Tabs
tab1, tab2, tab3 = st.tabs(["🌐 Proxies", "👤 Accounts & Sessions", "📊 System Status"])

# ========== TAB 1: PROXY MANAGEMENT ==========
with tab1:
    st.header("🌐 Proxy Management")
    
    # Proxy stats
    proxy_stats = proxy_mgr.get_stats()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Proxies", proxy_stats['total'])
    col2.metric("Ready", proxy_stats['ready'])
    col3.metric("In Use", proxy_stats['in_use'])
    col4.metric("Quarantined", proxy_stats['quarantined'])
    
    st.divider()
    
    # Actions
    col_add, col_bulk, col_test = st.columns(3)
    
    with col_add:
        with st.expander("➕ Add Single Proxy"):
            with st.form("add_proxy_form"):
                host = st.text_input("Host/IP")
                port = st.number_input("Port", min_value=1, max_value=65535, value=8080)
                username = st.text_input("Username (optional)")
                password = st.text_input("Password (optional)", type="password")
                proxy_type = st.selectbox("Type", ["http", "https", "socks5"])
                
                if st.form_submit_button("Add Proxy"):
                    if host and port:
                        proxy_id = db.add_proxy(host, port, username, password, proxy_type)
                        if proxy_id:
                            # Auto-test on add
                            proxy_config = {
                                'host': host,
                                'port': port,
                                'username': username,
                                'password': password,
                                'type': proxy_type,
                                'proxy_id': f'proxy_{proxy_id}'
                            }
                            is_healthy = proxy_mgr.health_check_proxy(proxy_config)
                            status = "READY" if is_healthy else "FAILED"
                            db.update_proxy_status(proxy_id, status)
                            
                            st.success(f"✅ Proxy added (ID: {proxy_id}, Status: {status})")
                            st.rerun()
                        else:
                            st.error("❌ Failed to add proxy (may already exist)")
                    else:
                        st.error("Host and Port are required")
    
    with col_bulk:
        with st.expander("📋 Bulk Add Proxies"):
            st.markdown("*Paste proxies in format: `host:port:username:password` or `host:port`*")
            bulk_text = st.text_area("Proxies (one per line)", height=150)
            
            if st.button("Import Bulk", key="import_bulk_proxies"):
                if bulk_text:
                    lines = bulk_text.strip().split('\n')
                    added = 0
                    errors = 0
                    for line in lines:
                        parts = line.strip().split(':')
                        if len(parts) >= 2:
                            try:
                                host = parts[0].strip()
                                port = int(parts[1].strip())
                                username = parts[2].strip() if len(parts) > 2 else None
                                password = parts[3].strip() if len(parts) > 3 else None
                                
                                proxy_id = db.add_proxy(host, port, username, password)
                                if proxy_id:
                                    added += 1
                                else:
                                    errors += 1
                            except Exception as e:
                                st.warning(f"⚠️ Error parsing line '{line}': {e}")
                                errors += 1
                    
                    if added > 0:
                        st.success(f"✅ Added {added} proxies")
                    if errors > 0:
                        st.warning(f"⚠️ {errors} proxies skipped (duplicates or errors)")
                    st.rerun()
    
    with col_test:
        with st.expander("🔍 Test All Proxies"):
            if st.button("Run Health Check", key="proxy_health_check"):
                with st.spinner("Testing all proxies..."):
                    result = proxy_mgr.run_comprehensive_health_check()
                    st.success(f"✅ Checked {result['checked_count']} proxies")
                    st.info(f"Healthy: {result['healthy_count']}, Unhealthy: {result['unhealthy_count']}")
                    st.rerun()
    
    st.divider()
    
    # Proxy list
    st.subheader("📋 Proxy List")
    
    # Filter
    status_filter = st.selectbox("Filter by Status", ["All", "READY", "IN_USE", "QUARANTINED", "FAILED", "DISABLED"])
    
    # Load proxies
    if status_filter == "All":
        proxies = db.get_all_proxies()
    else:
        proxies = db.get_all_proxies(status_filter=status_filter)
    
    if proxies:
        df = pd.DataFrame(proxies)
        
        # Display table
        st.dataframe(
            df[['id', 'host', 'port', 'proxy_type', 'status', 'success_rate', 'total_tasks', 'consecutive_failures', 'response_time']],
            use_container_width=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "host": st.column_config.TextColumn("Host", width="medium"),
                "port": st.column_config.NumberColumn("Port", width="small"),
                "success_rate": st.column_config.ProgressColumn("Success Rate", min_value=0, max_value=1),
                "response_time": st.column_config.NumberColumn("Response (s)", format="%.2f")
            }
        )
        
        # Actions on selected proxy
        st.markdown("### Actions")
        proxy_id_to_action = st.number_input("Proxy ID", min_value=1, step=1)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🧪 Test Proxy", key="test_single_proxy"):
                proxy = db.get_proxy_by_id(proxy_id_to_action)
                if proxy:
                    with st.spinner(f"Testing proxy {proxy_id_to_action}..."):
                        proxy_config = {
                            'host': proxy['host'],
                            'port': proxy['port'],
                            'username': proxy['username'],
                            'password': proxy['password'],
                            'type': proxy['proxy_type'],
                            'proxy_id': f'proxy_{proxy_id_to_action}'
                        }
                        is_healthy = proxy_mgr.health_check_proxy(proxy_config)
                        status = "READY" if is_healthy else "FAILED"
                        db.update_proxy_status(proxy_id_to_action, status)
                        st.success(f"✅ Test complete: {status}")
                        st.rerun()
                else:
                    st.error(f"❌ Proxy ID {proxy_id_to_action} not found")
        
        with col2:
            if st.button("🔄 Reset Status", key="reset_proxy_status"):
                if db.update_proxy_status(proxy_id_to_action, "READY", metadata={'consecutive_failures': 0}):
                    st.success("✅ Reset to READY")
                    st.rerun()
        
        with col3:
            if st.button("🗑️ Delete Proxy", key="delete_proxy"):
                if db.delete_proxy(proxy_id_to_action):
                    st.success("✅ Deleted")
                    st.rerun()
    else:
        st.info("No proxies found")

# ========== TAB 2: ACCOUNT & SESSION MANAGEMENT ==========
with tab2:
    st.header("👤 Account & Session Management")
    
    # Quick Start Section
    st.info("💡 **Quick Start:** After adding proxies & accounts, click button below to auto-login all accounts")
    
    col_quick1, col_quick2 = st.columns(2)
    
    with col_quick1:
        if st.button("🚀 Test All Proxies & Auto Login", key="quick_start_all", type="primary"):
            st.info("🔄 Step 1: Testing all proxies...")
            
            try:
                # Step 1: Test proxies
                with st.spinner("Testing proxies..."):
                    result = proxy_mgr.run_comprehensive_health_check()
                    st.success(f"✅ Proxies checked: {result['healthy_count']}/{result['checked_count']} healthy")
                
                # Step 2: Run auto_login
                st.info("🔄 Step 2: Running auto_login for all accounts...")
                
                import subprocess
                # Run via xvfb-run for headless X server
                result = subprocess.run(
                    ["xvfb-run", "-a", "/opt/facebook-scraper/venv/bin/python", "auto_login.py"],
                    cwd="/opt/facebook-scraper",
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env={**subprocess.os.environ, "DISPLAY": ":99"}
                )
                
                if result.returncode == 0:
                    st.success("✅ Auto login completed! All accounts logged in.")
                    with st.expander("📋 View Login Output"):
                        st.code(result.stdout, language="text")
                    st.rerun()
                else:
                    st.error("❌ Auto login failed!")
                    st.code(result.stderr, language="text")
                    
            except subprocess.TimeoutExpired:
                st.error("⏱️ Timeout (>10 minutes)")
            except Exception as e:
                st.error(f"❌ Error: {e}")
    
    with col_quick2:
        if st.button("🔐 Auto Login Only", key="login_only"):
            st.info("🚀 Running auto_login for all accounts...")
            
            try:
                import subprocess
                # Run via xvfb-run for headless X server
                result = subprocess.run(
                    ["xvfb-run", "-a", "/opt/facebook-scraper/venv/bin/python", "auto_login.py"],
                    cwd="/opt/facebook-scraper",
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env={**subprocess.os.environ, "DISPLAY": ":99"}
                )
                
                if result.returncode == 0:
                    st.success("✅ Auto login completed!")
                    with st.expander("📋 View Output"):
                        st.code(result.stdout, language="text")
                    st.rerun()
                else:
                    st.error("❌ Auto login failed!")
                    st.code(result.stderr, language="text")
                    
            except subprocess.TimeoutExpired:
                st.error("⏱️ Timeout (>10 minutes)")
            except Exception as e:
                st.error(f"❌ Error: {e}")
    
    st.divider()
    
    # Account stats
    accounts = db.get_all_accounts(is_active=True)
    account_stats = {
        'total': len(accounts),
        'active': len([a for a in accounts if a['status'] == 'ACTIVE']),
        'logged_in': len([a for a in accounts if a['session_status'] == 'LOGGED_IN']),
        'needs_login': len([a for a in accounts if a['session_status'] in ['NOT_CREATED', 'NEEDS_LOGIN']])
    }
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Accounts", account_stats['total'])
    col2.metric("Active", account_stats['active'])
    col3.metric("Logged In", account_stats['logged_in'])
    col4.metric("Need Login", account_stats['needs_login'])
    
    st.divider()
    
    # Actions
    col_add, col_bulk, col_import = st.columns(3)
    
    with col_add:
        with st.expander("➕ Add Single Account"):
            with st.form("add_account_form"):
                facebook_id = st.text_input("Facebook ID *", help="Required")
                email = st.text_input("Email (optional)")
                password = st.text_input("Password (optional)", type="password")
                totp_secret = st.text_input("2FA Secret (optional)")
                cookies = st.text_area("Cookies (optional)", height=100, help="Format: c_user=xxx;xs=yyy")
                
                if st.form_submit_button("Add Account"):
                    if facebook_id:
                        account_id = db.add_account(
                            facebook_id=facebook_id,
                            email=email,
                            password=password,
                            totp_secret=totp_secret,
                            cookies=cookies
                        )
                        if account_id:
                            st.success(f"✅ Account added (ID: {account_id})")
                            st.info("💡 Use 'Run Login' button below to create session")
                            st.rerun()
                        else:
                            st.error("❌ Failed to add account (may already exist)")
                    else:
                        st.error("Facebook ID is required")
    
    with col_bulk:
        with st.expander("📋 Bulk Add Accounts"):
            st.markdown("*Paste accounts in format: `id|password|2fa|cookies|email`*")
            bulk_text = st.text_area("Accounts (one per line)", height=150)
            
            if st.button("Import Bulk", key="import_bulk_accounts"):
                if bulk_text:
                    lines = bulk_text.strip().split('\n')
                    added = 0
                    errors = 0
                    
                    for line in lines:
                        parts = line.strip().split('|')
                        if len(parts) >= 1:
                            try:
                                facebook_id = parts[0].strip()
                                password = parts[1].strip() if len(parts) > 1 else None
                                totp_secret = parts[2].strip() if len(parts) > 2 else None
                                cookies = parts[3].strip() if len(parts) > 3 else None
                                email = parts[4].strip() if len(parts) > 4 else None
                                
                                account_id = db.add_account(
                                    facebook_id=facebook_id,
                                    email=email,
                                    password=password,
                                    totp_secret=totp_secret,
                                    cookies=cookies
                                )
                                
                                if account_id:
                                    added += 1
                                else:
                                    errors += 1
                            except Exception as e:
                                st.warning(f"⚠️ Error parsing line '{line[:50]}...': {e}")
                                errors += 1
                    
                    if added > 0:
                        st.success(f"✅ Added {added} accounts")
                    if errors > 0:
                        st.warning(f"⚠️ {errors} accounts skipped (duplicates or errors)")
                    st.rerun()
    
    with col_import:
        with st.expander("📤 Import from account.txt"):
            st.markdown("""
            Upload account.txt để import accounts vào database
            
            Format: `id|password|2fa|cookies|email|...`
            """)
            
            uploaded_file = st.file_uploader("Upload account.txt", type=['txt'])
            
            if uploaded_file:
                content = uploaded_file.read().decode('utf-8')
                st.text_area("Preview", content, height=100, disabled=True)
                
                if st.button("Import to Database", key="import_from_account_txt"):
                    # Parse and import
                    lines = content.strip().split('\n')
                    imported = 0
                    
                    for line in lines:
                        if line.strip() and not line.startswith('#'):
                            parts = line.strip().split('|')
                            if len(parts) >= 1:
                                account_id = db.add_account(
                                    facebook_id=parts[0].strip(),
                                    password=parts[1].strip() if len(parts) > 1 else None,
                                    totp_secret=parts[2].strip() if len(parts) > 2 else None,
                                    cookies=parts[3].strip() if len(parts) > 3 else None,
                                    email=parts[4].strip() if len(parts) > 4 else None
                                )
                                if account_id:
                                    imported += 1
                    
                    st.success(f"✅ Imported {imported} accounts to database")
                    st.rerun()
    
    st.divider()
    
    # Account list
    st.subheader("📋 Account List")
    
    # Filter
    status_filter = st.selectbox("Filter by Status", ["All", "ACTIVE", "INACTIVE", "BANNED", "CHECKPOINT"], key="account_status_filter")
    
    # Load accounts
    if status_filter == "All":
        all_accounts = db.get_all_accounts()
    else:
        all_accounts = db.get_all_accounts(status_filter=status_filter)
    
    if all_accounts:
        df_accounts = pd.DataFrame(all_accounts)
        
        # Display table
        display_cols = ['id', 'facebook_id', 'email', 'session_status', 'status', 'last_login_at', 'login_attempts']
        available_cols = [col for col in display_cols if col in df_accounts.columns]
        
        st.dataframe(
            df_accounts[available_cols],
            use_container_width=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "facebook_id": st.column_config.TextColumn("FB ID", width="medium"),
                "email": st.column_config.TextColumn("Email", width="medium"),
                "session_status": st.column_config.TextColumn("Session", width="small"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "last_login_at": st.column_config.DatetimeColumn("Last Login", width="medium"),
                "login_attempts": st.column_config.NumberColumn("Login Attempts", width="small")
            }
        )
        
        # Account actions
        st.markdown("### Actions on Account")
        account_id_to_action = st.number_input("Account ID", min_value=1, step=1, key="account_action_id")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("✅ Mark Active", key="mark_active"):
                if db.update_account_status(account_id_to_action, "ACTIVE", is_active=True):
                    st.success("✅ Marked as ACTIVE")
                    st.rerun()
        
        with col2:
            if st.button("🚫 Deactivate", key="deactivate_account"):
                if db.update_account_status(account_id_to_action, "INACTIVE", is_active=False):
                    st.success("✅ Deactivated")
                    st.rerun()
        
        with col3:
            if st.button("🗑️ Delete Account", key="delete_account"):
                if db.delete_account(account_id_to_action):
                    st.success("✅ Deleted")
                    st.rerun()
    else:
        st.info("No accounts found. Add accounts using the forms above.")
    
    st.divider()
    
    # Account-Proxy Relationships
    st.subheader("🔗 Account-Proxy Bindings")
    
    # Get accounts with proxy bindings
    bound_accounts = [a for a in all_accounts if a.get('proxy_id')]
    
    if bound_accounts:
        binding_data = []
        for account in bound_accounts:
            proxy = db.get_proxy_by_id(account['proxy_id'])
            binding_data.append({
                'Account ID': account['id'],
                'FB ID': account['facebook_id'],
                'Proxy ID': account['proxy_id'],
                'Proxy': f"{proxy['host']}:{proxy['port']}" if proxy else 'N/A',
                'Session': account.get('session_status', 'N/A')
            })
        
        st.dataframe(pd.DataFrame(binding_data), use_container_width=True)
        st.info(f"📊 Total: {len(binding_data)} account-proxy bindings")
    else:
        st.info("No account-proxy bindings found. Bindings are created during login.")

# ========== TAB 3: SYSTEM STATUS ==========
with tab3:
    st.header("📊 System Status")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Proxy Performance")
        best_proxies = proxy_mgr.get_best_performers(limit=5)
        if best_proxies:
            st.table(pd.DataFrame(best_proxies))
        else:
            st.info("No performance data yet")
    
    with col2:
        st.subheader("Session Performance")
        best_sessions = session_mgr.get_best_performers(limit=5)
        if best_sessions:
            st.table(pd.DataFrame(best_sessions))
        else:
            st.info("No performance data yet")
    
    st.divider()
    
    # Quick actions
    st.subheader("⚡ Quick Actions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Reset All Proxies", key="reset_all_proxies"):
            proxy_mgr.reset_all_proxies()
            st.success("✅ All proxies reset to READY")
            st.rerun()
    
    with col2:
        if st.button("🔄 Reset All Sessions", key="reset_all_sessions"):
            session_mgr.reset_all_sessions()
            st.success("✅ All sessions reset to READY")
            st.rerun()
    
    with col3:
        if st.button("🧹 Clean Quarantines", key="clean_quarantines"):
            proxy_released = proxy_mgr.check_cooldowns()
            session_released = session_mgr.check_cooldowns()
            st.success(f"✅ Released: {proxy_released} proxies, {session_released} sessions")
            st.rerun()

