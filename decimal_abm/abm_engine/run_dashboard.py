"""
run_dashboard.py
────────────────
Launch the ABM dashboard.
Run from the decimal_abm folder:
  python run_dashboard.py
Then open http://localhost:5000 in Chrome.
"""
import sys
import os

# Add current dir to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from abm_engine.dashboard.app import run_dashboard

if __name__ == "__main__":
    run_dashboard()
