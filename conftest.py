"""conftest.py — Add src/ to Python path for all tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
