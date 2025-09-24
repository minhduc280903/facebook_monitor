#!/usr/bin/env python3
"""Test PostgreSQL connection with detailed error information."""

import psycopg2

def test_connection():
    """Test PostgreSQL connection with various combinations."""
    
    # Test parameters
    host = "127.0.0.1"
    port = 5432
    user = "postgres"
    password = "fbmonitor123"
    
    print("Testing PostgreSQL connections...")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"User: {user}")
    print()
    
    # Test 1: Connect to default postgres database with password
    try:
        print("Test 1: postgres database with password")
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname="postgres"
        )
        print("✅ SUCCESS: Connected to postgres database!")
        conn.close()
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    print()
    
    # Test 2: Connect to facebook_monitor database with password
    try:
        print("Test 2: facebook_monitor database with password")
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname="facebook_monitor"
        )
        print("✅ SUCCESS: Connected to facebook_monitor database!")
        conn.close()
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    print()
    
    # Test 3: Connect without password (trust mode)
    try:
        print("Test 3: facebook_monitor database without password")
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            dbname="facebook_monitor"
        )
        print("✅ SUCCESS: Connected without password!")
        conn.close()
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    print()
    
    # Test 4: Connect with different password
    try:
        print("Test 4: facebook_monitor database with empty password")
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password="",
            dbname="facebook_monitor"
        )
        print("✅ SUCCESS: Connected with empty password!")
        conn.close()
    except Exception as e:
        print(f"❌ FAILED: {e}")

if __name__ == "__main__":
    test_connection()
