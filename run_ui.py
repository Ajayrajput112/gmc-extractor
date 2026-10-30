"""
run_ui.py - 1-Click Launch Script for GMC Policy Intelligence Dashboard
Starts FastAPI + Uvicorn server and automatically launches your browser.
"""

import os
import sys
import time
import threading
import webbrowser
from dotenv import load_dotenv

# Ensure root directory is in sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv()


def open_browser_delayed(url: str, delay_sec: float = 1.2):
    """Opens browser after server has bound to port."""
    time.sleep(delay_sec)
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        pass


def main():
    import uvicorn

    os.makedirs(os.path.join(ROOT_DIR, "outputs"), exist_ok=True)
    os.makedirs(os.path.join(ROOT_DIR, "samples"), exist_ok=True)

    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"

    print("\n" + "=" * 70)
    print("🛡️  GMC Intelligence Dashboard — AI Policy Document Analyzer")
    print("=" * 70)
    print(f" • Dashboard URL : {url}")
    print(f" • API Health    : {url}/api/health")
    print(f" • Live API Docs : {url}/docs")
    print(f" • Model Target  : {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}")
    print("=" * 70)

    # Launch browser in background thread
    threading.Thread(target=open_browser_delayed, args=(url,), daemon=True).start()

    # Start FastAPI Uvicorn Server
    try:
        uvicorn.run("web.server:app", host=host, port=port, reload=True)
    except KeyboardInterrupt:
        print("\n👋 Dashboard stopped safely.")


if __name__ == "__main__":
    main()
