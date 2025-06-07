# fantasyfb/utils/cache.py
"""
Data caching system for the fantasy football package.
"""

import pickle
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional, Union
import logging
import hashlib

logger = logging.getLogger(__name__)


class DataCache:
    """
    Simple file-based caching system for fantasy football data.
    
    Supports different cache durations for different types of data:
    - Player data: 6 hours (changes throughout the day)
    - League settings: 1 week (rarely changes during season)
    - NFL schedule: 1 day (updated daily)
    - Injury data: 1 hour (changes frequently)
    """
    
    def __init__(self, cache_dir: str = "cache"):
        """
        Initialize cache system.
        
        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Create subdirectories for different data types
        (self.cache_dir / "players").mkdir(exist_ok=True)
        (self.cache_dir / "leagues").mkdir(exist_ok=True)
        (self.cache_dir / "nfl").mkdir(exist_ok=True)
        (self.cache_dir / "stats").mkdir(exist_ok=True)
    
    def get_cached_data(self, key: str, max_age_hours: int = 24) -> Optional[Any]:
        """
        Retrieve cached data if it exists and is fresh enough.
        
        Args:
            key: Cache key
            max_age_hours: Maximum age in hours for cache to be valid
            
        Returns:
            Cached data if available and fresh, None otherwise
        """
        cache_file = self._get_cache_file(key)
        
        if not cache_file.exists():
            return None
        
        # Check file age
        mod_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mod_time > timedelta(hours=max_age_hours):
            logger.debug(f"Cache expired for key: {key}")
            return None
        
        try:
            # Try to load the data
            if cache_file.suffix == '.pkl':
                with open(cache_file, 'rb') as f:
                    data = pickle.load(f)
            elif cache_file.suffix == '.json':
                with open(cache_file, 'r') as f:
                    data = json.load(f)
            elif cache_file.suffix == '.csv':
                data = pd.read_csv(cache_file)
            else:
                logger.warning(f"Unknown cache file format: {cache_file}")
                return None
            
            logger.debug(f"Cache hit for key: {key}")
            return data
            
        except Exception as e:
            logger.warning(f"Failed to load cache for key {key}: {e}")
            # Remove corrupted cache file
            cache_file.unlink(missing_ok=True)
            return None
    
    def save_data(self, key: str, data: Any, format: str = "auto") -> bool:
        """
        Save data to cache.
        
        Args:
            key: Cache key
            data: Data to cache
            format: Format to save in (auto, pickle, json, csv)
            
        Returns:
            True if save successful, False otherwise
        """
        try:
            cache_file = self._get_cache_file(key, format)
            
            # Ensure parent directory exists
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            if format == "auto":
                format = self._auto_detect_format(data)
            
            if format == "pickle":
                with open(cache_file.with_suffix('.pkl'), 'wb') as f:
                    pickle.dump(data, f)
            elif format == "json":
                with open(cache_file.with_suffix('.json'), 'w') as f:
                    json.dump(data, f)
            elif format == "csv":
                if isinstance(data, pd.DataFrame):
                    data.to_csv(cache_file.with_suffix('.csv'), index=False)
                else:
                    raise ValueError("CSV format requires pandas DataFrame")
            else:
                raise ValueError(f"Unknown format: {format}")
            
            logger.debug(f"Cached data for key: {key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cache data for key {key}: {e}")
            return False
    
    def invalidate(self, key: str) -> bool:
        """
        Remove cached data for a specific key.
        
        Args:
            key: Cache key to invalidate
            
        Returns:
            True if file was removed, False if it didn't exist
        """
        cache_file = self._get_cache_file(key)
        
        # Try different extensions
        for ext in ['.pkl', '.json', '.csv']:
            file_path = cache_file.with_suffix(ext)
            if file_path.exists():
                file_path.unlink()
                logger.debug(f"Invalidated cache for key: {key}")
                return True
        
        return False
    
    def clear_all(self) -> int:
        """
        Clear all cached data.
        
        Returns:
            Number of files removed
        """
        files_removed = 0
        
        for cache_file in self.cache_dir.rglob("*"):
            if cache_file.is_file():
                cache_file.unlink()
                files_removed += 1
        
        logger.info(f"Cleared {files_removed} cache files")
        return files_removed
    
    def clear_expired(self, max_age_hours: int = 168) -> int:
        """
        Clear cache files older than specified age.
        
        Args:
            max_age_hours: Maximum age in hours
            
        Returns:
            Number of files removed
        """
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        files_removed = 0
        
        for cache_file in self.cache_dir.rglob("*"):
            if cache_file.is_file():
                mod_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                if mod_time < cutoff_time:
                    cache_file.unlink()
                    files_removed += 1
        
        logger.info(f"Cleared {files_removed} expired cache files")
        return files_removed
    
    def get_cache_info(self) -> dict:
        """
        Get information about the cache.
        
        Returns:
            Dictionary with cache statistics
        """
        total_files = 0
        total_size = 0
        oldest_file = None
        newest_file = None
        
        for cache_file in self.cache_dir.rglob("*"):
            if cache_file.is_file():
                total_files += 1
                total_size += cache_file.stat().st_size
                
                mod_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                if oldest_file is None or mod_time < oldest_file:
                    oldest_file = mod_time
                if newest_file is None or mod_time > newest_file:
                    newest_file = mod_time
        
        return {
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "oldest_file": oldest_file,
            "newest_file": newest_file,
            "cache_dir": str(self.cache_dir)
        }
    
    def _get_cache_file(self, key: str, format: str = None) -> Path:
        """
        Get cache file path for a given key.
        
        Args:
            key: Cache key
            format: File format (affects extension)
            
        Returns:
            Path to cache file
        """
        # Hash the key to avoid filesystem issues with special characters
        key_hash = hashlib.md5(key.encode()).hexdigest()
        
        # Determine subdirectory based on key prefix
        if key.startswith(("players_", "roster_", "injury_")):
            subdir = "players"
        elif key.startswith(("league_", "settings_", "schedule_fantasy")):
            subdir = "leagues"
        elif key.startswith(("nfl_", "schedule_nfl")):
            subdir = "nfl"
        elif key.startswith(("stats_", "war_", "rates_")):
            subdir = "stats"
        else:
            subdir = ""
        
        # Create filename with original key (truncated) and hash
        safe_key = "".join(c for c in key if c.isalnum() or c in "._-")[:50]
        filename = f"{safe_key}_{key_hash}"
        
        return self.cache_dir / subdir / filename
    
    def _auto_detect_format(self, data: Any) -> str:
        """Auto-detect the best format for the given data type."""
        if isinstance(data, pd.DataFrame):
            return "csv"
        elif isinstance(data, (dict, list)) and self._is_json_serializable(data):
            return "json"
        else:
            return "pickle"
    
    def _is_json_serializable(self, obj: Any) -> bool:
        """Check if object can be serialized to JSON."""
        try:
            json.dumps(obj)
            return True
        except (TypeError, ValueError):
            return False


# Convenience decorators for caching function results
def cached_result(cache_key_func, max_age_hours: int = 24):
    """
    Decorator to cache function results.
    
    Args:
        cache_key_func: Function that takes the same arguments and returns a cache key
        max_age_hours: Maximum age for cached results
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache = DataCache()
            cache_key = cache_key_func(*args, **kwargs)
            
            # Try to get cached result
            result = cache.get_cached_data(cache_key, max_age_hours)
            if result is not None:
                return result
            
            # Compute and cache result
            result = func(*args, **kwargs)
            cache.save_data(cache_key, result)
            return result
        
        return wrapper
    return decorator


# Example usage:
def player_cache_key(league_id: str, season: int, week: int) -> str:
    return f"players_{league_id}_{season}_{week}"

@cached_result(player_cache_key, max_age_hours=6)
def get_player_data(league_id: str, season: int, week: int):
    """Example cached function."""
    # This would be cached for 6 hours
    pass
