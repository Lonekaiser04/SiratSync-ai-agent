# keep_alive.py
import requests
import time
import threading
import os

def keep_render_alive():
    """Ping Render service every 10 minutes to prevent spin-down"""
    url = os.environ.get("RENDER_URL", "https://siratsync-api.onrender.com/health")
    
    def ping():
        while True:
            try:
                response = requests.get(url, timeout=5)
                print(f"Keep-alive ping: {response.status_code}")
            except Exception as e:
                print(f"⚠️ Keep-alive failed: {e}")
            time.sleep(600)  # 10 minutes
    
    thread = threading.Thread(target=ping, daemon=True)
    thread.start()
    print(" Keep-alive service started (pings every 10 min)")