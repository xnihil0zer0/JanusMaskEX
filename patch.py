import ast
import sys

def patch():
    with open("harness/hooks/_common.py", "r") as f:
        src = f.read()
    
    # Actually, let's just append the previous worker's function to a copy of the module, and run pytest
    pass
