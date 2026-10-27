"""
Standalone CLI tool to verify MySQL connectivity and initialize tables.
Reads MYSQL_PASSWORD from the environment.
Usage:
    # In PowerShell:
    $env:MYSQL_PASSWORD="your_password_here"
    python test_mysql_connection.py

    # Or in CMD:
    set MYSQL_PASSWORD=your_password_here
    python test_mysql_connection.py
"""

import sys
import os

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.mysql_database import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE,
    test_mysql_connection, create_mysql_tables
)

def main():
    print("=" * 65)
    print("SmartHome AI — MySQL Database Connection & Schema Verification")
    print("=" * 65)
    print(f"Target Host:     {MYSQL_HOST}:{MYSQL_PORT}")
    print(f"Target User:     {MYSQL_USER}")
    print(f"Target Database: {MYSQL_DATABASE}")
    print(f"Password Status: {'[OK] Set in environment' if MYSQL_PASSWORD else '[MISSING] Not set in environment'}")
    print("-" * 65)

    if not MYSQL_PASSWORD:
        print("\n[!] Error: 'MYSQL_PASSWORD' environment variable is not set.\n")
        print("To test the connection, set the environment variable in your terminal:")
        print("  In PowerShell:")
        print("    $env:MYSQL_PASSWORD = 'your_actual_password'")
        print("    py -3.15 test_mysql_connection.py\n")
        print("  In Command Prompt (CMD):")
        print("    set MYSQL_PASSWORD=your_actual_password")
        print("    python test_mysql_connection.py\n")
        sys.exit(1)

    print("\n[1/2] Testing MySQL connection...")
    success, msg, details = test_mysql_connection()
    if not success:
        print(f"\n[X] Connection Failed:\n    {msg}\n")
        sys.exit(1)

    print(f"[✓] {msg}")
    print(f"    - Server Version:  {details.get('server_version')}")
    print(f"    - Database Exists: {details.get('database_exists')}")
    print(f"    - Existing Tables: {details.get('existing_tables')}")

    print("\n[2/2] Checking and initializing tables in MySQL 'smarthome' database...")
    created_ok, created_msg, tables = create_mysql_tables()
    if not created_ok:
        print(f"\n[X] Table Creation Failed:\n    {created_msg}\n")
        sys.exit(1)

    print(f"[✓] {created_msg}")
    print("    Verified Tables in MySQL 'smarthome':")
    for tbl in tables:
        print(f"      • {tbl}")

    print("\n" + "=" * 65)
    print("[SUCCESS] MySQL database is ready and verified.")
    print("=" * 65)

if __name__ == "__main__":
    main()
