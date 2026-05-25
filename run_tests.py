import pytest
import os
import sys

def run_tests():
    os.system("/home/xnihil0zer0/JanusMaskJR/.venv/bin/python -m pytest test_console_generated.py -k 'test_ConsoleStreamer_ or TestConsolestreamer' -q")

if __name__ == "__main__":
    run_tests()