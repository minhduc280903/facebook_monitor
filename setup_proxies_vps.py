#!/usr/bin/env python3
"""
Setup proxies and bindings on VPS with new stable identifier (host:port)
"""
import sys
sys.path.insert(0, '.')
from core.database_manager import DatabaseManager
from core.session_proxy_binder import SessionProxyBinder

# Proxy list with new credentials
proxies = [
    ('vtpro.ddns.net', 19450, 'Bui1', 'Ha@'),
    ('vtpro.ddns.net', 19451, 'Bui1', 'Ha@'),
    ('vtpro.ddns.net', 19452, 'Bui1', 'Ha@'),
    ('profpt.ddns.net', 18321, 'Bui1', 'Ha@'),
    ('profpt.ddns.net', 18323, 'Bui1', 'Ha@'),
    ('profpt.ddns.net', 18322, 'Bui1', 'Ha@'),
    ('profpt.ddns.net', 18324, 'Bui1', 'Ha@'),
    ('profpt.ddns.net', 18325, 'Bui1', 'Ha@'),
    ('profpt.ddns.net', 18326, 'Bui1', 'Ha@'),
    ('profpt.ddns.net', 18320, 'Bui1', 'Ha@'),
    ('vtpro.ddns.net', 19431, 'Bui1', 'Ha@'),
]

print('=' * 60)
print('SETUP PROXIES AND BINDINGS (host:port format)')
print('=' * 60)

db = DatabaseManager()

# 1. Delete old proxies
print('\n[1] Deleting old proxies...')
old_proxies = db.get_all_proxies()
for p in old_proxies:
    db.delete_proxy(p['id'])
    print(f'   Deleted: {p["host"]}:{p["port"]} (DB ID: {p["id"]})')

# 2. Add new proxies
print('\n[2] Adding new proxies...')
added_proxies = []
for host, port, user, pwd in proxies:
    try:
        proxy_id = db.add_proxy(
            proxy_type='http',
            host=host,
            port=port,
            username=user,
            password=pwd
        )
        print(f'   OK Added: {host}:{port} (DB ID: {proxy_id})')
        added_proxies.append(f'{host}:{port}')
    except Exception as e:
        print(f'   ERROR Failed: {host}:{port} - {e}')

# 3. Create binding: session -> proxy (host:port format)
print('\n[3] Creating session-proxy binding...')
binder = SessionProxyBinder(db_manager=db)

# Get session name (adjust if needed)
session_name = '61561866793639'
proxy_host_port = added_proxies[0] if added_proxies else None

if proxy_host_port:
    if binder.bind_session_atomic(session_name, proxy_host_port):
        print(f'   OK Bound: {session_name} -> {proxy_host_port}')
    else:
        print(f'   ERROR Failed to bind {session_name}')
else:
    print('   ERROR No proxies available for binding')

print('\n' + '=' * 60)
print('SETUP COMPLETED!')
print('=' * 60)
print(f'\nTotal proxies added: {len(added_proxies)}')
print('Binding format: host:port (stable identifier)')

