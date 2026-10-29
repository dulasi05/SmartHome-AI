"""
Standalone CLI tool to verify MySQL connectivity, initialize tables,
and verify real-time sensor event ingestion directly in MySQL.
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
from datetime import datetime

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.mysql_database import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE,
    test_mysql_connection, create_mysql_tables, get_mysql_engine
)
from sqlalchemy import text

def main():
    print("=" * 68)
    print("SmartHome AI — MySQL Database Connection & Ingestion Verification")
    print("=" * 68)
    print(f"Target Host:     {MYSQL_HOST}:{MYSQL_PORT}")
    print(f"Target User:     {MYSQL_USER}")
    print(f"Target Database: {MYSQL_DATABASE}")
    print(f"Password Status: {'[OK] Set in environment' if MYSQL_PASSWORD else '[MISSING] Not set in environment'}")
    print("-" * 68)

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

    print("\n[1/3] Testing MySQL connection...")
    success, msg, details = test_mysql_connection()
    if not success:
        print(f"\n[X] Connection Failed:\n    {msg}\n")
        sys.exit(1)

    print(f"[✓] {msg}")
    print(f"    - Server Version:  {details.get('server_version')}")
    print(f"    - Database Exists: {details.get('database_exists')}")
    print(f"    - Existing Tables: {details.get('existing_tables')}")

    print("\n[2/3] Checking and initializing tables in MySQL 'smarthome' database...")
    created_ok, created_msg, tables = create_mysql_tables()
    if not created_ok:
        print(f"\n[X] Table Creation Failed:\n    {created_msg}\n")
        sys.exit(1)

    print(f"[✓] {created_msg}")
    print("    Verified Tables in MySQL 'smarthome':")
    for tbl in tables:
        print(f"      • {tbl}")

    print("\n[3/3] Ingesting test sensor event and verifying persistence in MySQL...")
    try:
        from app.models.db_models import SensorEvent
        from sqlalchemy.orm import sessionmaker

        engine = get_mysql_engine(include_db=True)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Count before
        count_before = session.query(SensorEvent).count()

        # Insert test event
        test_ev = SensorEvent(
            timestamp=datetime.utcnow(),
            sensor_id="PIR_TEST_MYSQL",
            sensor_type="motion",
            sensor_state="ON",
            resident_id="R1",
            source="hardware",
            raw_value=1.0,
        )
        session.add(test_ev)
        session.commit()
        session.refresh(test_ev)
        ev_id = test_ev.id
        session.close()

        # Verify via fresh raw SQL query directly to MySQL
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, timestamp, sensor_id, sensor_type, sensor_state, source, raw_value FROM sensor_events WHERE id = :id"),
                {"id": ev_id}
            ).fetchone()
            total_in_mysql = conn.execute(text("SELECT COUNT(*) FROM sensor_events")).scalar()

        if row:
            print(f"[✓] Successfully verified test event in MySQL 'sensor_events' table!")
            print(f"    - Event ID:     {row[0]}")
            print(f"    - Timestamp:    {row[1]}")
            print(f"    - Sensor ID:    {row[2]}")
            print(f"    - Type & State: {row[3]} ({row[4]})")
            print(f"    - Source:       {row[5]}")
            print(f"    - Raw Value:    {row[6]}")
            print(f"    - Total Rows in MySQL sensor_events: {total_in_mysql}")
        else:
            print(f"[X] Event was not found in MySQL query.")
            sys.exit(1)

    except Exception as err:
        print(f"[X] Sensor event verification in MySQL failed: {err}")
        sys.exit(1)

    print("\n" + "=" * 68)
    print("[SUCCESS] MySQL database is ACTIVE, connected, and sensor events are writing & reading successfully!")
    print("=" * 68)

if __name__ == "__main__":
    main()
