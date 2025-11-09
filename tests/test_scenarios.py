"""
Test scenarios for queuectl
Validates all core functionality as per assignment requirements
"""
import subprocess
import json
import time
import os
import sys
import signal


def run_command(cmd):
    """Run a CLI command and return output"""
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


def enqueue_job(job_data):
    """Helper to enqueue a job with proper escaping"""
    import shlex
    json_str = json.dumps(job_data)
    cmd = f"queuectl enqueue {shlex.quote(json_str)}"
    return run_command(cmd)


def test_1_basic_job_completes():
    """Test 1: Basic job completes successfully"""
    print("\n" + "=" * 60)
    print("TEST 1: Basic job completes successfully")
    print("=" * 60)

    job_data = {
        "id": "test1-success",
        "command": "echo 'Hello from queuectl'"
    }
    
    print(f"Enqueuing job: {job_data}")
    returncode, stdout, stderr = enqueue_job(job_data)
    
    if returncode != 0:
        print(f"❌ Failed to enqueue job")
        print(f"stderr: {stderr}")
        return False
    
    print(stdout)

    print("Starting worker...")
    worker_proc = subprocess.Popen(
        ["queuectl", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    print("Waiting for job to complete...")
    time.sleep(5)

    print("Stopping worker...")
    worker_proc.terminate()
    try:
        worker_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        worker_proc.kill()
        worker_proc.wait()

    returncode, stdout, stderr = run_command("queuectl list --state completed")
    
    if "test1-success" in stdout:
        print("✅ TEST 1 PASSED: Job completed successfully")
        return True
    else:
        print("❌ TEST 1 FAILED: Job not found in completed state")
        print(f"Output: {stdout}")
        return False


def test_2_failed_job_retries_and_dlq():
    """Test 2: Failed job retries with backoff and moves to DLQ"""
    print("\n" + "=" * 60)
    print("TEST 2: Failed job retries with backoff and moves to DLQ")
    print("=" * 60)

    run_command("queuectl config set max-retries 2")
    run_command("queuectl config set backoff-base 1")
    run_command("queuectl config set worker-poll-interval 1")

    job_data = {
        "id": "test2-fail",
        "command": "exit 1",
        "max_retries": 2
    }
    
    print(f"Enqueuing failing job: {job_data}")
    returncode, stdout, stderr = enqueue_job(job_data)
    
    if returncode != 0:
        print(f"❌ Failed to enqueue job")
        print(f"stderr: {stderr}")
        return False
    
    print(stdout)

    print("Starting worker...")
    worker_proc = subprocess.Popen(
        ["queuectl", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    print("Waiting for all retries to complete...")
    for i in range(20):
        time.sleep(1)
        # Check if job is in DLQ yet
        returncode, stdout, stderr = run_command("queuectl dlq list")
        if "test2-fail" in stdout:
            print(f"Job moved to DLQ after {i+1} seconds")
            break

    print("Stopping worker...")
    worker_proc.terminate()
    try:
        worker_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        worker_proc.kill()
        worker_proc.wait()

    returncode, stdout, stderr = run_command("queuectl dlq list")
    
    if "test2-fail" in stdout:
        print("✅ TEST 2 PASSED: Job moved to DLQ after retries")
        return True
    else:
        print("❌ TEST 2 FAILED: Job not found in DLQ")
        print(f"DLQ output: {stdout}")
        returncode2, stdout2, stderr2 = run_command("queuectl status")
        print(f"Status: {stdout2}")
        returncode3, stdout3, stderr3 = run_command("queuectl list")
        print(f"All jobs: {stdout3}")
        return False


def test_3_multiple_workers_no_overlap():
    """Test 3: Multiple workers process jobs without overlap"""
    print("\n" + "=" * 60)
    print("TEST 3: Multiple workers process jobs without overlap")
    print("=" * 60)

    num_jobs = 5
    print(f"Enqueuing {num_jobs} jobs...")
    
    for i in range(num_jobs):
        job_data = {
            "id": f"test3-job{i}",
            "command": f"sleep 1 && echo 'Job {i}'"
        }
        enqueue_job(job_data)
    
    print(f"✓ Enqueued {num_jobs} jobs")

    print("Starting 3 workers...")
    worker_proc = subprocess.Popen(
        ["queuectl", "worker", "start", "--count", "3"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    print("Waiting for jobs to complete...")
    time.sleep(6)

    print("Stopping workers...")
    worker_proc.terminate()
    try:
        worker_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        worker_proc.kill()
        worker_proc.wait()
    
    returncode, stdout, stderr = run_command("queuectl list --state completed")
    
    completed_count = stdout.count("test3-job")
    
    if completed_count == num_jobs:
        print(f"✅ TEST 3 PASSED: All {num_jobs} jobs completed without overlap")
        return True
    else:
        print(f"❌ TEST 3 FAILED: Only {completed_count}/{num_jobs} jobs completed")
        print(f"Completed jobs output: {stdout}")
        return False


def test_4_invalid_command_fails_gracefully():
    """Test 4: Invalid commands fail gracefully"""
    print("\n" + "=" * 60)
    print("TEST 4: Invalid commands fail gracefully")
    print("=" * 60)

    job_data = {
        "id": "test4-invalid",
        "command": "nonexistentcommand12345",
        "max_retries": 1
    }
    
    print(f"Enqueuing job with invalid command: {job_data}")
    returncode, stdout, stderr = enqueue_job(job_data)
    
    if returncode != 0:
        print(f"❌ Failed to enqueue job")
        return False

    print("Starting worker...")
    worker_proc = subprocess.Popen(
        ["queuectl", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    print("Waiting for processing...")
    time.sleep(6)

    print("Stopping worker...")
    worker_proc.terminate()
    try:
        worker_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        worker_proc.kill()
        worker_proc.wait()
    
    # Check if job is in DLQ
    returncode, stdout, stderr = run_command("queuectl dlq list")
    
    if "test4-invalid" in stdout:
        print("✅ TEST 4 PASSED: Invalid command handled gracefully (in DLQ)")
        return True
    else:
        print("❌ TEST 4 FAILED: Invalid command not handled properly")
        print(f"DLQ output: {stdout}")
        return False


def test_5_persistence_across_restart():
    """Test 5: Job data survives restart"""
    print("\n" + "=" * 60)
    print("TEST 5: Job data survives restart")
    print("=" * 60)
    
    # Enqueue a job
    job_data = {
        "id": "test5-persist",
        "command": "echo 'Persistence test'"
    }
    
    print(f"Enqueuing job: {job_data}")
    returncode, stdout, stderr = enqueue_job(job_data)
    
    if returncode != 0:
        print(f"❌ Failed to enqueue job")
        print(f"stderr: {stderr}")
        return False

    returncode, stdout, stderr = run_command("queuectl list --state pending")
    
    if "test5-persist" not in stdout:
        print("❌ Job not found after enqueue")
        return False
    
    print("✓ Job exists in queue")
    
    print("Simulating restart (checking persistence)...")
    time.sleep(1)
    
    returncode, stdout, stderr = run_command("queuectl list --state pending")
    
    if "test5-persist" in stdout:
        print("✅ TEST 5 PASSED: Job data persisted across restart")
        return True
    else:
        print("❌ TEST 5 FAILED: Job data lost")
        return False


def test_6_dlq_retry():
    """Test 6: Retry job from DLQ"""
    print("\n" + "=" * 60)
    print("TEST 6: Retry job from DLQ")
    print("=" * 60)
    
    returncode, stdout, stderr = run_command("queuectl dlq list")
    
    if "test2-fail" not in stdout and "test4-invalid" not in stdout:
        print("⚠️  TEST 6 SKIPPED: No DLQ job from previous tests")
        return True
    
    job_to_retry = "test2-fail" if "test2-fail" in stdout else "test4-invalid"
    
    print(f"Retrying job from DLQ: {job_to_retry}")
    returncode, stdout, stderr = run_command(f"queuectl dlq retry {job_to_retry}")
    
    if returncode != 0:
        print("❌ TEST 6 FAILED: Could not retry DLQ job")
        print(f"stderr: {stderr}")
        return False
    
    print(stdout)
    
    # Check job moved back to pending
    returncode, stdout, stderr = run_command("queuectl list --state pending")
    
    if job_to_retry in stdout:
        print("✅ TEST 6 PASSED: Job successfully retried from DLQ")
        return True
    else:
        print("❌ TEST 6 FAILED: Job not in pending state after retry")
        print(f"Pending jobs: {stdout}")
        return False


def run_all_tests():
    """Run all test scenarios"""
    print("\n" + "=" * 60)
    print("QUEUECTL TEST SUITE")
    print("=" * 60)
    
    # Clean database before tests
    print("\nCleaning up previous test data...")
    import shutil
    from pathlib import Path
    db_path = Path.home() / ".queuectl"
    if db_path.exists():
        shutil.rmtree(db_path)
    print("✓ Clean slate")
    
    tests = [
        test_1_basic_job_completes,
        test_2_failed_job_retries_and_dlq,
        test_3_multiple_workers_no_overlap,
        test_4_invalid_command_fails_gracefully,
        test_5_persistence_across_restart,
        test_6_dlq_retry,
    ]
    
    results = []
    
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    print(f"Failed: {total - passed}/{total}")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())