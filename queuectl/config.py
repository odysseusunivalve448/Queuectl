"""
Configuration management for queuectl
Handles getting and setting configuration values
"""
from typing import Any, Dict
from .storage import Storage


class Config:
    """Configuration manager"""

    DEFAULTS = {
        'max_retries': 3,
        'backoff_base': 2,
        'job_timeout': 300,
        'worker_poll_interval': 1,
    }

    VALID_KEYS = set(DEFAULTS.keys())
    
    def __init__(self, storage: Storage):
        """Initialize config manager with storage"""
        self.storage = storage
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        if default is None:
            default = self.DEFAULTS.get(key)
        
        return self.storage.get_config(key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """
        Set configuration value
        
        Args:
            key: Configuration key
            value: Value to set
            
        Returns:
            True if successful
        """
        return self.storage.set_config(key, value)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values"""
        return self.storage.list_config()
    
    def is_valid_key(self, key: str) -> bool:
        """Check if configuration key is valid"""
        return key in self.VALID_KEYS
    
    def reset_to_defaults(self):
        """Reset all configuration to defaults"""
        for key, value in self.DEFAULTS.items():
            self.set(key, value)