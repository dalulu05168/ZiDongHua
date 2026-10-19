"""Packaged XiaoBaWang localhost API launcher; no shell, no external messaging."""
import os
import uvicorn
from backend.app import app

if __name__ == "__main__":
    port = int(os.environ.get("XBW_API_PORT", "3100"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
