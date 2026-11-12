import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The engines log every suppressed/skipped rule; keep test output readable.
logging.getLogger("orange_lab").setLevel(logging.ERROR)
