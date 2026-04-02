import time
from datetime import datetime
from services.business_structure_manager import (
    get_business_manager,
    get_pddy_business_manager,
)

def run_periodic_sync():
    print(f"\n[{datetime.now()}] Service started. Business structure sync task active.")
    
    managers = [
        ("default", get_business_manager()),
        ("pddy", get_pddy_business_manager()),
    ]
    
    # Run immediately on start if not already loaded or just specific sync
    # The manager.__init__ tried to load from local.
    # If we want to strictly follow "update every 72h", we should sleep first if data exists.
    # But often we want ensuring fresh data on service restart.
    
    # Since __init__ already handles "load local OR sync if missing",
    # we can consider the "initial state" ready.
    # We will sleep first, then sync. This avoids double-sync on startup if file was missing.
    
    while True:
        # 72 hours sleep
        print(f"[{datetime.now()}] Sleeping for 72 hours before next sync...")
        time.sleep(72 * 3600)

        try:
            print(f"\n[{datetime.now()}] Starting scheduled synchronization...")
            for manager_name, manager in managers:
                print(f"[{datetime.now()}] Starting scheduled synchronization for {manager_name}...")
                manager.sync_from_remote()
            print(f"[{datetime.now()}] Synchronization finished.")
        except Exception as e:
             print(f"Job crashed: {e}")

if __name__ == "__main__":
    run_periodic_sync()
