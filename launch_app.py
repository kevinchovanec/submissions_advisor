"""
Local launcher for Submissions Advisor.

Starts the FastAPI server and opens the app in your browser.
Stop the server with Ctrl+C.

Usage (after activating the conda environment):
    python launch_app.py
"""

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
PORT = 8000
URL = f"http://localhost:{PORT}"

os.chdir(ROOT)

print(f"Starting Submissions Advisor...")
proc = subprocess.Popen(
    [
        sys.executable, "-m", "uvicorn",
        "api.main:app",
        "--host", "127.0.0.1",
        f"--port={PORT}",
        "--no-access-log",
    ],
    cwd=ROOT,
)

# Wait for the server to be ready
for i in range(10):
    time.sleep(1)
    try:
        import urllib.request
        urllib.request.urlopen(f"{URL}/api/health", timeout=1)
        break
    except Exception:
        pass

print(f"Opening {URL}")
webbrowser.open(URL)
print("Press Ctrl+C to stop.\n")

try:
    proc.wait()
except KeyboardInterrupt:
    print("\nStopping server...")
    proc.terminate()
    proc.wait()
