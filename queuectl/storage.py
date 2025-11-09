"""
Database storage layer for queuectl
Handles SQLite operations for jobs and configuration
"""
import sqlite3
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime


class Storage:
    """SQLite storage manager for jobs and configuration"""
    
    def __init__(self, db_path: str = None):
        """Initialize storage with database path"""
        if db_path is None:
            base_dir = Path.home() / ".queuectl"
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(base_dir / "queuectl.db")
        
        self.db_path = db_path
        self.conn = None
        self._initialize_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn
    
    def _initialize_db(self):
        """Create tables if they don't exist"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Create jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_run_at ON jobs(run_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_locked_at ON jobs(locked_at)")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        default_config = [
            ('max_retries', '3'),
            ('backoff_base', '2'),
            ('job_timeout', '300'),
            ('worker_poll_interval', '1'),
        ]
        
        for key, value in default_config:
            cursor.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                (key, value)
            )
        
        conn.commit()
    
    def create_job(self, job_data: Dict[str, Any]) -> bool:
        """Insert a new job into the database"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO jobs (
                    id, command, state, attempts, max_retries,
                    run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data['id'],
                job_data['command'],
                job_data.get('state', 'pending'),
                job_data.get('attempts', 0),
                job_data.get('max_retries', 3),
                job_data.get('run_at'),
                job_data.get('created_at', datetime.utcnow().isoformat()),
                job_data.get('updated_at', datetime.utcnow().isoformat())
            ))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a job by ID"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def claim_job(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically claim a pending job for processing
        Includes safety timeout for crashed workers
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Atomic update with safety timeout check
        cursor.execute("""
            UPDATE jobs 
            SET state = 'processing',
                worker_id = ?,
                locked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                attempts = attempts + 1
            WHERE id IN (
                SELECT id FROM jobs
                WHERE (
                    state = 'pending'
                    OR (state = 'processing' AND locked_at < datetime('now', '-5 minutes'))
                )
                AND (run_at IS NULL OR run_at <= CURRENT_TIMESTAMP)
                ORDER BY created_at ASC
                LIMIT 1
            )
        """, (worker_id,))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            # Get the claimed job
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE worker_id = ? AND state = 'processing'
                ORDER BY updated_at DESC
                LIMIT 1
            """, (worker_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
        
        return None
    
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """Update job fields"""
        conn = self._get_connection()
        cursor = conn.cursor()

        updates['updated_at'] = datetime.utcnow().isoformat()

        fields = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [job_id]
        
        cursor.execute(f"UPDATE jobs SET {fields} WHERE id = ?", values)
        conn.commit()
        
        return cursor.rowcount > 0
    
    def list_jobs(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all jobs, optionally filtered by state"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if state:
            cursor.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC",
                (state,)
            )
        else:
            cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_job_stats(self) -> Dict[str, int]:
        """Get count of jobs by state"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT state, COUNT(*) as count
            FROM jobs
            GROUP BY state
        """)
        
        stats = {row['state']: row['count'] for row in cursor.fetchall()}
        
        # Ensure all states are present
        for state in ['pending', 'processing', 'completed', 'failed', 'dead']:
            if state not in stats:
                stats[state] = 0
        
        return stats
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        
        if row:
            value = row['value']
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return value
        
        return default
    
    def set_config(self, key: str, value: Any) -> bool:
        """Set configuration value"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO config (key, value)
            VALUES (?, ?)
        """, (key, str(value)))
        
        conn.commit()
        return True
    
    def list_config(self) -> Dict[str, Any]:
        """List all configuration values"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT key, value FROM config")
        
        config = {}
        for row in cursor.fetchall():
            value = row['value']
            try:
                config[row['key']] = int(value)
            except ValueError:
                try:
                    config[row['key']] = float(value)
                except ValueError:
                    config[row['key']] = value
        
        return config
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None