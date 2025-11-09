# Architecture Documentation

## System Overview

queuectl is a production-grade job queue system with the following key components:

## Core Components

### 1. Storage Layer (`storage.py`)

**Purpose**: Persistent data layer using SQLite

**Key Responsibilities**:
- Database initialization and schema management
- Atomic job claiming (preventing race conditions)
- CRUD operations for jobs and configuration
- Transaction management

**Critical Methods**:
```python
claim_job(worker_id) -> Dict
```
- Uses atomic SQL UPDATE with WHERE subquery
- Prevents duplicate job execution
- Includes safety timeout for crashed workers
- Returns None if no jobs available

**Database Schema**:
```sql
jobs (
    id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    worker_id TEXT,
    locked_at TIMESTAMP,
    run_at TIMESTAMP,
    stdout TEXT,
    stderr TEXT,
    exit_code INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)

config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
```

### 2. Queue Manager (`queue.py`)

**Purpose**: High-level job queue operations

**Key Responsibilities**:
- Job enqueueing with validation
- Job listing and filtering
- Status reporting
- Dead Letter Queue management
- Job scheduling

**Key Features**:
- Auto-generates job IDs if not provided
- Applies default config values
- Handles job retry from DLQ

### 3. Worker System (`worker.py`)

**Purpose**: Job execution and lifecycle management

**Components**:

#### Worker Class
- Single worker process
- Polls queue for jobs
- Executes commands via subprocess
- Handles success/failure/timeout

#### WorkerManager Class
- Manages multiple worker processes
- Coordinates graceful shutdown
- Signal handling (SIGINT, SIGTERM)

**Worker Loop**:
```
1. Check shutdown signal
2. Check for stop file
3. Claim job from queue (atomic)
4. Execute job command
5. Handle outcome (success/retry/DLQ)
6. Repeat
```

**Job Execution Flow**:
```python
subprocess.run(
    command,
    shell=True,          # For compound commands
    capture_output=True, # Capture stdout/stderr
    timeout=300,         # Prevent hangs
    text=True           # String output
)
```

### 4. Configuration (`config.py`)

**Purpose**: Runtime configuration management

**Configurable Parameters**:
- `max_retries`: Maximum retry attempts (default: 3)
- `backoff_base`: Exponential backoff base (default: 2)
- `job_timeout`: Job execution timeout in seconds (default: 300)
- `worker_poll_interval`: Polling interval (default: 1)

### 5. Data Models (`models.py`)

**Purpose**: Data structure definitions

**Job Model**:
- Dataclass for type safety
- Conversion methods (to_dict, from_dict)
- Validation helpers

**JobState Constants**:
- PENDING, PROCESSING, COMPLETED, FAILED, DEAD
- State transition validation

### 6. CLI Interface (`cli.py`)

**Purpose**: User-facing command-line interface

**Command Groups**:
- Main commands: enqueue, status, list
- Worker commands: start, stop
- DLQ commands: list, retry
- Config commands: set, get, list

**Built with Click**:
- Intuitive command structure
- Built-in help text
- Argument validation

## Critical Design Patterns

### 1. Preventing Race Conditions

**Problem**: Multiple workers might claim the same job

**Solution**: Atomic SQL UPDATE with WHERE subquery

```sql
UPDATE jobs 
SET state='processing', worker_id=?, locked_at=CURRENT_TIMESTAMP
WHERE id IN (
    SELECT id FROM jobs
    WHERE state='pending'
    AND (run_at IS NULL OR run_at <= CURRENT_TIMESTAMP)
    ORDER BY created_at ASC
    LIMIT 1
)
```

**Why it works**:
- Single atomic operation
- Only one worker succeeds
- Database handles concurrency

### 2. Exponential Backoff

**Formula**: `delay = base ^ attempts`

**Implementation**:
```python
backoff_delay = config.get('backoff_base', 2) ** job.attempts
run_at = now + timedelta(seconds=backoff_delay)
```

**Example** (base=2):
- Attempt 1: 2¹ = 2 seconds
- Attempt 2: 2² = 4 seconds
- Attempt 3: 2³ = 8 seconds

**Benefits**:
- Reduces system load
- Gives temporary issues time to resolve
- Configurable via `backoff_base`

### 3. Safety Timeout

**Problem**: Worker crashes while processing job

**Solution**: Auto-recovery after 5 minutes

```sql
WHERE (state='pending' 
    OR (state='processing' AND locked_at < datetime('now', '-5 minutes')))
```

**How it works**:
- Jobs stuck in processing state > 5 minutes
- Become available for claiming again
- Prevents jobs from being permanently stuck

### 4. Graceful Shutdown

**Mechanism**: Signal handling + shared Event

```python
shutdown_event = multiprocessing.Event()

def signal_handler(signum, frame):
    shutdown_event.set()

while not shutdown_event.is_set():
    # Process jobs
```

**Benefits**:
- Workers finish current job
- No abrupt termination
- Clean state in database

## Data Flow

### Enqueue Flow
```
User → CLI → Queue → Storage → SQLite
                              ↓
                         (Job created in 'pending')
```

### Execution Flow
```
Worker → claim_job() → Atomic UPDATE → Job acquired
   ↓
Execute subprocess
   ↓
Exit code = 0? → Yes → Mark completed
              → No  → Check retries
                      ↓
                 Retries left? → Yes → Schedule retry (exponential backoff)
                               → No  → Move to DLQ (dead state)
```

### Status Query Flow
```
User → CLI → Queue → Storage → Aggregate stats
                              ↓
                         Count by state
                         Count active workers
                              ↓
                         Display summary
```

## Concurrency Model

**Process-based concurrency**:
- Each worker = separate process
- Isolation via multiprocessing
- No GIL issues
- Independent memory space

**Coordination**:
- Database-level locking (SQLite)
- Atomic operations (SQL)
- Shared Event for shutdown signal

## Error Handling Strategy

### Job Execution Errors

1. **Subprocess timeout**: Move to retry/DLQ
2. **Command not found**: Move to retry/DLQ
3. **Non-zero exit code**: Move to retry/DLQ
4. **Python exception**: Log and move to retry/DLQ

### System Errors

1. **Database errors**: Retry operation, log error
2. **Worker crashes**: Safety timeout recovers jobs
3. **Invalid input**: Validate early, return error to user

## Performance Considerations

### Optimizations

1. **Database Indexes**:
   - `idx_jobs_state` for filtering
   - `idx_jobs_run_at` for delayed jobs
   - `idx_jobs_locked_at` for safety timeout

2. **Efficient Polling**:
   - Configurable poll interval
   - Single query to claim job
   - No busy waiting

3. **Output Truncation**:
   - Limit stdout/stderr to 2000 chars
   - Prevents database bloat
   - Documented trade-off

### Scalability Limits

**Current design**:
- Single machine only
- SQLite concurrency limits (~100 concurrent writers)
- File-based storage

**For production scale**:
- Would need distributed queue (Redis, RabbitMQ)
- Separate job store (PostgreSQL)
- Multiple queue servers

## Security Considerations

### shell=True Trade-off

**Risk**: Shell injection attacks

**Mitigation**:
- Commands only from trusted CLI
- No external API
- Documented assumption

**Future**: Could add command validation/sanitization

### Data Privacy

**Current**: All job data stored in clear text

**Considerations**:
- stdout/stderr may contain sensitive data
- Truncation helps limit exposure
- Single-user system assumption

## Testing Strategy

### Unit Tests
- Individual component testing
- Mock external dependencies

### Integration Tests
- End-to-end workflows
- Multiple workers coordination
- Retry and DLQ behavior

### Test Scenarios
1. Basic success flow
2. Retry with backoff
3. Concurrent worker execution
4. Error handling
5. Persistence verification

## Future Enhancements

### Short-term
- Job priority queues
- Job dependencies
- Better logging

### Long-term
- Distributed architecture
- Web dashboard
- Job history/audit log
- Metrics and monitoring
- API endpoints

## Code Organization

```
queuectl/
├── storage.py      # Data layer
├── models.py       # Data structures
├── config.py       # Configuration
├── queue.py        # Queue operations
├── worker.py       # Execution engine
├── cli.py          # User interface
└── utils.py        # Helpers
```

**Principle**: Clear separation of concerns
- Each module has single responsibility
- Minimal coupling between modules
- Easy to test and extend