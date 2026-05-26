"""Sample module for auto-commit merge test."""
import os
import sys
import logging

def greet(name: str) -> str:
    """Return a greeting for ``name``."""
    return f'hello, {name}'

def farewell(name: str) -> str:
    return f'goodbye, {name}'
if __name__ == '__main__':
    print(greet('world'))