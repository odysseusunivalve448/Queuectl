"""
Worker process management for queuectl
Handles job execution, retry logic, and worker coordination
"""
import subprocess
import time
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional
from multiprocessing import Process, Manager
import uuid

from .storage import Storage
from .config import Config
from .models import Job, JobState


# Constants
MAX_OUTPUT_LEN = 2000
DEFAULT_TIMEOUT = 300


def _worker_process(worker_id, db_path, shutdown_event):
    """
    Worker process function (must be at module level for multiprocessing)
    This is called by WorkerManager in a separate process.
    
    Args:
        worker_id: Unique worker identifier
        db_path: Path to database
        shutdown_event: Shutdown event (shared between processes)
    """
    storage = Storage(db_path)
    config = Config(storage)
    
    worker = Worker(worker_id, storage, config, shutdown_event)
    worker.run()


class Worker:
    """Worker process that executes jobs from the queue"""
    
    def __init__(self, worker_id, storage, config, shutdown_event):
        """
        Initialize worker
        
        Args:
            worker_id: Unique worker identifier
            storage: Storage instance
            config: Config instance
            shutdown_event: Multiprocessing event for graceful shutdown
        """
        self.worker_id = worker_id
        self.storage = storage
        self.config = config
        self.shutdown_event = shutdown_event
        self.poll_interval = config.get('worker_poll_interval', 1)
    
    def run(self):
        """Main worker loop - poll for jobs and execute them"""
        print(f"[Worker {self.worker_id}] Started")
        
        while not self.shutdown_event.is_set():
            try:
                from pathlib import Path
                stop_file = Path.home() / ".queuectl" / "stop"
                if stop_file.exists():
                    print(f"[Worker {self.worker_id}] Stop file detected, shutting down")
                    self.shutdown_event.set()
                    break
  
                job_data = self.storage.claim_job(self.worker_id)
                
                if job_data:
                    job = Job.from_dict(job_data)
                    print(f"[Worker {self.worker_id}] Claimed job {job.id}")

                    self.execute_job(job)
                else:
                    time.sleep(self.poll_interval)
            
            except Exception as e:
                print(f"[Worker {self.worker_id}] Error in main loop: {e}")
                time.sleep(self.poll_interval)
        
        print(f"[Worker {self.worker_id}] Shutdown signal received, exiting")
    
    def execute_job(self, job):
        """
        Execute a job command
        
        Args:
            job: Job to execute
        """
        timeout = self.config.get('job_timeout', DEFAULT_TIMEOUT)
        
        try:
            print(f"[Worker {self.worker_id}] Executing: {job.command}")
            
            result = subprocess.run(
                job.command,
                shell=True,
                capture_output=True,
                timeout=timeout,
                text=True
            )

            stdout = result.stdout[:MAX_OUTPUT_LEN] if result.stdout else ""
            stderr = result.stderr[:MAX_OUTPUT_LEN] if result.stderr else ""

            if result.returncode == 0:
                self.mark_completed(job, stdout, stderr, result.returncode)
            else:
                self.handle_failure(job, stdout, stderr, result.returncode)
        
        except subprocess.TimeoutExpired:
            print(f"[Worker {self.worker_id}] Job {job.id} timed out after {timeout}s")
            self.handle_failure(
                job,
                "",
                f"Job exceeded timeout of {timeout} seconds",
                -1
            )
        
        except Exception as e:
            print(f"[Worker {self.worker_id}] Job {job.id} execution error: {e}")
            self.handle_failure(
                job,
                "",
                f"Execution error: {str(e)}",
                -1
            )
    
    def mark_completed(self, job, stdout, stderr, exit_code):
        """
        Mark job as completed successfully
        
        Args:
            job: Job that completed
            stdout: Standard output
            stderr: Standard error
            exit_code: Exit code
        """
        print(f"[Worker {self.worker_id}] Job {job.id} completed successfully")
        
        updates = {
            'state': JobState.COMPLETED,
            'stdout': stdout,
            'stderr': stderr,
            'exit_code': exit_code,
        }
        
        self.storage.update_job(job.id, updates)
    
    def handle_failure(self, job, stdout, stderr, exit_code):
        """
        Handle job failure with retry logic
        
        Args:
            job: Job that failed
            stdout: Standard output
            stderr: Standard error
            exit_code: Exit code
        """
        print(f"[Worker {self.worker_id}] Job {job.id} failed (attempt {job.attempts}/{job.max_retries})")
        
        updates = {
            'stdout': stdout,
            'stderr': stderr,
            'exit_code': exit_code,
        }

        if job.attempts >= job.max_retries:
            print(f"[Worker {self.worker_id}] Job {job.id} moved to DLQ after {job.attempts} attempts")
            updates['state'] = JobState.DEAD
        else:
            backoff_base = self.config.get('backoff_base', 2)
            delay = backoff_base ** job.attempts
            run_at = datetime.utcnow() + timedelta(seconds=delay)
            
            print(f"[Worker {self.worker_id}] Job {job.id} will retry in {delay}s")
            
            updates['state'] = JobState.PENDING
            updates['run_at'] = run_at.isoformat()
            updates['worker_id'] = None
            updates['locked_at'] = None
        
        self.storage.update_job(job.id, updates)


class WorkerManager:
    """Manages multiple worker processes"""
    
    def __init__(self, storage, config):
        """
        Initialize worker manager
        
        Args:
            storage: Storage instance
            config: Config instance
        """
        self.storage = storage
        self.config = config
        self.workers = []
        self.manager = Manager()
        self.shutdown_event = self.manager.Event()
    
    def start_workers(self, count):
        """
        Start multiple worker processes
        
        Args:
            count: Number of workers to start
        """
        print(f"Starting {count} worker(s)...")
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        for i in range(count):
            worker_id = f"worker-{uuid.uuid4().hex[:8]}"

            process = Process(
                target=_worker_process,
                args=(worker_id, self.storage.db_path, self.shutdown_event),
                name=worker_id
            )
            process.start()
            
            self.workers.append({
                'id': worker_id,
                'process': process
            })
        
        print(f"All workers started. Press Ctrl+C to stop.")

        try:
            for worker_info in self.workers:
                worker_info['process'].join()
        except KeyboardInterrupt:
            pass
        
        print("All workers stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print("\nShutdown signal received, stopping workers gracefully...")
        self.shutdown_event.set()
    
    def stop_workers(self):
        """Stop all running workers gracefully"""
        print("Requesting worker shutdown...")
        self.shutdown_event.set()

        for worker_info in self.workers:
            if worker_info['process'].is_alive():
                worker_info['process'].join(timeout=30)

                if worker_info['process'].is_alive():
                    print(f"Force terminating {worker_info['id']}")
                    worker_info['process'].terminate()
        
        self.workers.clear()
        print("All workers stopped")