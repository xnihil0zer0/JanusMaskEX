import os
import sys
import time
import shutil
import threading
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import agy_pool
from harness.autowork_daemon import _agy_pool_busy_slots, _agy_pool_assign

def test_toctou_race():
    print("=== Testing TOCTOU Race Condition ===")
    state_dir = Path("/tmp/test_ghei_state")
    if state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True)
    
    # We want to simulate the gap between allocate_slot and pidfile writing.
    # In autowork_daemon.py:
    # 1. slot = agy_pool.allocate_slot(_agy_pool_busy_slots(state_dir), size)
    # 2. write A.slot
    # 3. (some time passes, spawn worker)
    # 4. write A.pid
    
    # Let's run two threads calling _agy_pool_assign concurrently.
    results = []
    def worker(task_id):
        slot = _agy_pool_assign(state_dir, task_id)
        results.append((task_id, slot))
        # Note: we do NOT write the pid file immediately to simulate the delay
        
    t1 = threading.Thread(target=worker, args=("task_1",))
    t2 = threading.Thread(target=worker, args=("task_2",))
    
    t1.start()
    # Wait a tiny bit but not enough for any pid file to be written (we are not writing them anyway)
    time.sleep(0.05)
    t2.start()
    
    t1.join()
    t2.join()
    
    print(f"Results of concurrent allocation without PID files: {results}")
    slots = [r[1] for r in results]
    if len(slots) == 2 and slots[0] == slots[1] and slots[0] is not None:
        print("FAIL: TOCTOU race condition confirmed! Both tasks got the same slot.")
    else:
        print("PASS/INCONCLUSIVE: No double allocation detected.")

def test_permanent_lockout():
    print("=== Testing Permanent Lockout when repo_root is passed ===")
    repo_root = Path("/tmp/test_ghei_repo")
    if repo_root.exists():
        shutil.rmtree(repo_root)
    repo_root.mkdir(parents=True)
    
    # 1. Allocate a slot passing repo_root (simulating if daemon passed it)
    print("Allocating slot 0 with repo_root...")
    slot1 = agy_pool.allocate_slot(busy=[], size=1, repo_root=str(repo_root))
    print(f"Allocated slot: {slot1}")
    
    # Verify lockfile exists
    lock_file = repo_root / ".agents" / "agy-pool" / "w0.lock"
    print(f"Lockfile exists: {lock_file.exists()}")
    if lock_file.exists():
        print(f"Lockfile content: {lock_file.read_text()}")
        
    # 2. Try to allocate slot 0 again in a separate call (since the first call returned, we simulate a subsequent iteration)
    print("Attempting to allocate slot 0 again (same daemon pid, simulating next task)...")
    try:
        slot2 = agy_pool.allocate_slot(busy=[], size=1, repo_root=str(repo_root))
    except RuntimeError:
        slot2 = None
    print(f"Second allocation result: {slot2}")
    if slot2 is None:
        print("FAIL: Permanent lockout confirmed! The slot remains locked even though the worker task is not running, because the lockfile holds the daemon's PID.")
    else:
        print("PASS: Slot was re-allocated.")

def test_stale_lock_and_pid_recycling():
    print("=== Testing Stale Lock and PID Recycling ===")
    repo_root = Path("/tmp/test_ghei_repo_stale")
    if repo_root.exists():
        shutil.rmtree(repo_root)
    repo_root.mkdir(parents=True)
    
    # Simulate a stale lock from a dead PID
    lock_dir = repo_root / ".agents" / "agy-pool"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "w0.lock"
    
    # Write a lock file with a dead PID (e.g. 999999)
    import json
    dead_pid = 999999
    # Let's ensure it's dead
    try:
        os.kill(dead_pid, 0)
        print(f"Warning: PID {dead_pid} is alive. Stale test may be inaccurate.")
    except ProcessLookupError:
        pass
        
    with open(lock_path, "w") as f:
        json.dump({"pid": dead_pid, "start_time": 100}, f)
        
    print("Lockfile created for dead PID.")
    print(f"Is lock stale? {agy_pool._is_lock_stale(lock_path)}")
    
    # Try to allocate. It should reclaim the stale lock.
    slot = agy_pool.allocate_slot(busy=[], size=1, repo_root=str(repo_root))
    print(f"Allocation with dead PID stale lock: {slot}")
    if slot == 0:
        print("PASS: Stale lock was successfully reclaimed.")
    else:
        print("FAIL: Stale lock was not reclaimed.")

    # Now simulate PID recycling.
    # Write a lock file with our own PID but a DIFFERENT start time.
    my_pid = os.getpid()
    wrong_start_time = 12345  # very unlikely to match our actual start time
    with open(lock_path, "w") as f:
        json.dump({"pid": my_pid, "start_time": wrong_start_time}, f)
        
    print(f"Lockfile created for current PID {my_pid} but wrong start time {wrong_start_time}.")
    print(f"Is lock stale (recycled PID)? {agy_pool._is_lock_stale(lock_path)}")
    
    slot = agy_pool.allocate_slot(busy=[], size=1, repo_root=str(repo_root))
    print(f"Allocation with recycled PID lock: {slot}")
    if slot == 0:
        print("PASS: Recycled PID lock was successfully reclaimed.")
    else:
        print("FAIL: Recycled PID lock was not reclaimed.")

if __name__ == "__main__":
    test_toctou_race()
    test_permanent_lockout()
    test_stale_lock_and_pid_recycling()
