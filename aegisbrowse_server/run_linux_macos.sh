#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install -r requirements.txt
python3 -m uvicorn app:app --host 127.0.0.1 --port 8000
