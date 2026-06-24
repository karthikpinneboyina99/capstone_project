"""Root conftest.py — adds backend/ to sys.path so tests can import from app.*"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
