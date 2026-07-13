"""Standalone dashboard launcher. Run: python run_dashboard.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from abm_engine.dashboard.app import run_dashboard
if __name__ == "__main__":
    run_dashboard()
