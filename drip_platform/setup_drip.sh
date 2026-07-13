#!/bin/bash
# macOS/Linux equivalent of setup_drip.bat
cd "$(dirname "$0")"
pip install -r requirements.txt
python3 setup_and_run.py
