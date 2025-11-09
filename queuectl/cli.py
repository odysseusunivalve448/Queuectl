"""
CLI interface for queuectl
Provides command-line interface for all queue operations
"""
import click
import json
import sys
from pathlib import Path
from typing import Optional

from .storage import Storage
from .config import Config
from .queue import Queue
from .worker import WorkerManager
from .models import JobState


# Initialize storage, config, and queue (lazy loaded)
_storage = None
_config = None
_queue = None


def get_storage() -> Storage:
    """Get or create storage instance"""
    global _storage
    if _storage is None:
        _storage = Storage()
    return _storage


def get_config() -> Config:
    """Get or create config instance"""
    global _config
    if _config is None:
        _config = Config(get_storage())
    return _config


def get_queue() -> Queue:
    """Get or create queue instance"""
    global _queue
    if _queue is None:
        _queue = Queue(get_storage(), get_config())
    return _queue


@click.group()
def cli():
    """queuectl - A CLI-based background job queue system"""
    pass


@cli.command()
@click.argument('job_json')
def enqueue(job_json):
    """
    Enqueue a new job
    
    Example: queuectl enqueue '{"id":"job1","command":"sleep 2"}'
    """
    try:
        job_data = json.loads(job_json)
        
        queue = get_queue()
        job = queue.enqueue(job_data)
        
        if job:
            click.echo(f"✓ Job enqueued successfully")
            click.echo(f"  ID: {job.id}")
            click.echo(f"  Command: {job.command}")
            click.echo(f"  State: {job.state}")
        else:
            click.echo(f"✗ Failed to enqueue job (ID may already exist)", err=True)
            sys.exit(1)
    
    except json.JSONDecodeError as e:
        click.echo(f"✗ Invalid JSON: {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cli.group()
def worker():
    """Worker management commands"""
    pass


@worker.command()
@click.option('--count', default=1, help='Number of workers to start')
def start(count):
    """
    Start worker processes
    
    Example: queuectl worker start --count 3
    """
    storage = get_storage()
    config = get_config()
    
    manager = WorkerManager(storage, config)
    manager.start_workers(count)


@worker.command()
def stop():
    """
    Stop running workers
    
    Note: This command works best when workers are running in foreground mode.
    For background workers, use system commands like 'kill' with PID.
    """
    stop_file = Path.home() / ".queuectl" / "stop"
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.touch()
    
    click.echo("✓ Stop signal sent to workers")
    click.echo("  Workers will finish their current jobs and then exit")

    import time
    time.sleep(2)
    if stop_file.exists():
        stop_file.unlink()


@cli.command()
def status():
    """
    Show queue status
    
    Example: queuectl status
    """
    queue = get_queue()
    status_info = queue.get_status()
    
    click.echo("=" * 50)
    click.echo("QUEUE STATUS")
    click.echo("=" * 50)

    jobs = status_info['jobs']
    click.echo(f"\nJobs:")
    click.echo(f"  Pending:    {jobs['pending']:>5}")
    click.echo(f"  Processing: {jobs['processing']:>5}")
    click.echo(f"  Completed:  {jobs['completed']:>5}")
    click.echo(f"  Failed:     {jobs['failed']:>5}")
    click.echo(f"  Dead (DLQ): {jobs['dead']:>5}")
    click.echo(f"  {'-' * 20}")
    click.echo(f"  Total:      {status_info['total_jobs']:>5}")

    click.echo(f"\nActive Workers: {status_info['active_workers']}")

    config = get_config()
    all_config = config.get_all()
    click.echo(f"\nConfiguration:")
    for key, value in sorted(all_config.items()):
        click.echo(f"  {key}: {value}")
    
    click.echo("=" * 50)


@cli.command()
@click.option('--state', type=click.Choice(['pending', 'processing', 'completed', 'failed', 'dead']), 
              help='Filter by job state')
@click.option('--limit', default=20, help='Maximum number of jobs to display')
def list(state, limit):
    """
    List jobs
    
    Example: queuectl list --state pending
    """
    queue = get_queue()
    jobs = queue.list_jobs(state)
    
    if not jobs:
        click.echo(f"No jobs found" + (f" with state '{state}'" if state else ""))
        return

    jobs = jobs[:limit]
    
    click.echo("=" * 100)
    click.echo(f"{'ID':<20} {'STATE':<12} {'COMMAND':<30} {'ATTEMPTS':<10} {'CREATED':<20}")
    click.echo("=" * 100)
    
    for job in jobs:
        job_id = job.id[:18] + '..' if len(job.id) > 20 else job.id
        command = job.command[:28] + '..' if len(job.command) > 30 else job.command
        created = job.created_at[:19] if job.created_at else 'N/A'
        
        click.echo(f"{job_id:<20} {job.state:<12} {command:<30} {job.attempts:<10} {created:<20}")
    
    if len(jobs) == limit:
        click.echo(f"\n(Showing first {limit} jobs, use --limit to see more)")
    
    click.echo("=" * 100)


@cli.group()
def dlq():
    """Dead Letter Queue management"""
    pass


@dlq.command('list')
@click.option('--limit', default=20, help='Maximum number of jobs to display')
def dlq_list(limit):
    """
    List jobs in Dead Letter Queue
    
    Example: queuectl dlq list
    """
    queue = get_queue()
    jobs = queue.list_dlq()
    
    if not jobs:
        click.echo("Dead Letter Queue is empty")
        return
    
    jobs = jobs[:limit]
    
    click.echo("=" * 120)
    click.echo(f"{'ID':<20} {'COMMAND':<30} {'ATTEMPTS':<10} {'EXIT CODE':<12} {'ERROR':<40}")
    click.echo("=" * 120)
    
    for job in jobs:
        job_id = job.id[:18] + '..' if len(job.id) > 20 else job.id
        command = job.command[:28] + '..' if len(job.command) > 30 else job.command
        exit_code = str(job.exit_code) if job.exit_code is not None else 'N/A'
        error = (job.stderr[:38] + '..') if job.stderr and len(job.stderr) > 40 else (job.stderr or 'N/A')
        
        click.echo(f"{job_id:<20} {command:<30} {job.attempts:<10} {exit_code:<12} {error:<40}")
    
    if len(jobs) == limit:
        click.echo(f"\n(Showing first {limit} jobs, use --limit to see more)")
    
    click.echo("=" * 120)


@dlq.command('retry')
@click.argument('job_id')
def dlq_retry(job_id):
    """
    Retry a job from Dead Letter Queue
    
    Example: queuectl dlq retry job1
    """
    queue = get_queue()
    success = queue.retry_job(job_id)
    
    if success:
        click.echo(f"✓ Job {job_id} moved from DLQ to pending queue")
    else:
        click.echo(f"✗ Failed to retry job {job_id} (job not found or not in DLQ)", err=True)
        sys.exit(1)


@cli.group()
def config():
    """Configuration management"""
    pass


@config.command('set')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """
    Set configuration value
    
    Example: queuectl config set max-retries 5
    """
    key = key.replace('-', '_')
    
    cfg = get_config()
    
    if not cfg.is_valid_key(key):
        click.echo(f"✗ Invalid configuration key: {key}", err=True)
        click.echo(f"  Valid keys: {', '.join(sorted(cfg.VALID_KEYS))}")
        sys.exit(1)

    try:
        if '.' in value:
            value = float(value)
        else:
            value = int(value)
    except ValueError:
        pass
    
    cfg.set(key, value)
    click.echo(f"✓ Configuration updated: {key} = {value}")


@config.command('get')
@click.argument('key')
def config_get(key):
    """
    Get configuration value
    
    Example: queuectl config get max-retries
    """
    key = key.replace('-', '_')
    
    cfg = get_config()
    value = cfg.get(key)
    
    if value is not None:
        click.echo(f"{key}: {value}")
    else:
        click.echo(f"✗ Configuration key not found: {key}", err=True)
        sys.exit(1)


@config.command('list')
def config_list():
    """
    List all configuration values
    
    Example: queuectl config list
    """
    cfg = get_config()
    all_config = cfg.get_all()
    
    click.echo("Configuration:")
    click.echo("=" * 50)
    for key, value in sorted(all_config.items()):
        click.echo(f"  {key:<25} {value}")
    click.echo("=" * 50)


if __name__ == '__main__':
    cli()