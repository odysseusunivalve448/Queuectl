"""
Utility functions for queuectl
Helper functions used across modules
"""
from datetime import datetime, timedelta
from typing import Optional


def calculate_backoff_delay(attempts: int, base: int = 2) -> int:
    """
    Calculate exponential backoff delay
    
    Args:
        attempts: Number of attempts made
        base: Base for exponential calculation
        
    Returns:
        Delay in seconds
    """
    return base ** attempts


def calculate_run_at(delay_seconds: int) -> str:
    """
    Calculate future timestamp for delayed job
    
    Args:
        delay_seconds: Delay in seconds
        
    Returns:
        ISO format timestamp string
    """
    run_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
    return run_at.isoformat()


def format_timestamp(timestamp: Optional[str]) -> str:
    """
    Format timestamp for display
    
    Args:
        timestamp: ISO format timestamp string
        
    Returns:
        Formatted timestamp or 'N/A'
    """
    if not timestamp:
        return 'N/A'
    
    try:
        dt = datetime.fromisoformat(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return timestamp


def truncate_string(s: str, max_length: int = 50) -> str:
    """
    Truncate string with ellipsis if too long
    
    Args:
        s: String to truncate
        max_length: Maximum length
        
    Returns:
        Truncated string
    """
    if not s:
        return ''
    
    if len(s) <= max_length:
        return s
    
    return s[:max_length-2] + '..'