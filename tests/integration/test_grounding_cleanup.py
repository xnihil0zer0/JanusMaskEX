import os
import time
import subprocess
import psutil
import sys
from services.code_audit.grounding import cleanup_java_subprocesses

def test_jvm_process_cleanup():
    # Start a dummy python process that pretends to be joern-java
    # We run 'sleep 100' or similar but name it or invoke it in a way
    # that simulates a CodeQL/Joern java command line.
    # A standard way is to launch a subprocess running a command with 'java' and 'joern' in it.
    proc = subprocess.Popen(
        sys_executable_with_args(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Give it a moment to start
    time.sleep(0.5)
    
    pid = proc.pid
    assert psutil.pid_exists(pid)
    
    # Run cleanup
    cleanup_java_subprocesses()
    
    # Verify process is terminated
    time.sleep(0.5)
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE

def sys_executable_with_args():
    # We can invoke python with specific arguments so that it matches our cmdline check:
    # "java in cmdline and joern/codeql in cmdline"
    return [sys.executable, "-c", "import time; time.sleep(100)", "java", "joern"]
