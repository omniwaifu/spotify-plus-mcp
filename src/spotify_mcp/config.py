"""Configuration management for Spotify MCP with persistent token storage."""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging

# Get the directory where the package is installed
PACKAGE_DIR = Path(__file__).parent
# Look for config file in user's home directory
CONFIG_DIR = Path.home() / ".spotify-plus-mcp"
CONFIG_FILE = CONFIG_DIR / "spotify-config.json"

logger = logging.getLogger(__name__)


class SpotifyConfig:
    """Manages Spotify configuration and persistent token storage."""
    
    def __init__(self):
        self.config_file = CONFIG_FILE
        self.config_dir = CONFIG_DIR
        self._config = None
        self._ensure_config_dir()
        
    def _ensure_config_dir(self):
        """Ensure the configuration directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
    def load(self) -> Dict[str, Any]:
        """Load configuration from file or create default."""
        if self._config is not None:
            return self._config
            
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self._config = json.load(f)
                    logger.info(f"Loaded config from {self.config_file}")
                    return self._config
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                
        # Create default config
        self._config = self._create_default_config()
        self.save()
        return self._config
        
    def _create_default_config(self) -> Dict[str, Any]:
        """Create default configuration."""
        return {
            "client_id": os.getenv("SPOTIFY_CLIENT_ID", ""),
            "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET", ""),
            "redirect_uri": os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            "access_token": None,
            "refresh_token": None,
            "expires_at": None,
            "scopes": [
                "user-read-currently-playing",
                "user-read-playback-state",
                "app-remote-control",
                "streaming",
                "playlist-read-private",
                "playlist-read-collaborative",
                "playlist-modify-private",
                "playlist-modify-public",
                "user-read-playback-position",
                "user-top-read",
                "user-read-recently-played",
                "user-library-modify",
                "user-library-read",
                "user-modify-playback-state"
            ]
        }
        
    def save(self):
        """Save current configuration to file."""
        if self._config is None:
            return
            
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self._config, f, indent=2)
            logger.info(f"Saved config to {self.config_file}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            
    def get(self, key: str, default=None):
        """Get configuration value."""
        if self._config is None:
            self.load()
        return self._config.get(key, default)
        
    def set(self, key: str, value):
        """Set configuration value and save."""
        if self._config is None:
            self.load()
        self._config[key] = value
        self.save()
        
    def update_tokens(self, access_token: str, refresh_token: str = None, expires_in: int = 3600):
        """Update access and refresh tokens with expiration time."""
        if self._config is None:
            self.load()
            
        self._config["access_token"] = access_token
        if refresh_token:
            self._config["refresh_token"] = refresh_token
            
        # Calculate expiration time (slightly before actual expiration for safety)
        expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
        self._config["expires_at"] = expires_at.isoformat()
        
        self.save()
        logger.info("Updated tokens in configuration")
        
    def is_token_expired(self) -> bool:
        """Check if the access token has expired."""
        if self._config is None:
            self.load()
            
        expires_at = self._config.get("expires_at")
        if not expires_at:
            return True
            
        try:
            expiry_time = datetime.fromisoformat(expires_at)
            return datetime.now() >= expiry_time
        except Exception:
            return True
            
    def has_tokens(self) -> bool:
        """Check if we have stored tokens."""
        if self._config is None:
            self.load()
        return bool(self._config.get("access_token") and self._config.get("refresh_token"))
        
    def clear_tokens(self):
        """Clear stored tokens."""
        if self._config is None:
            self.load()
        self._config["access_token"] = None
        self._config["refresh_token"] = None
        self._config["expires_at"] = None
        self.save()
        
    def is_configured(self) -> bool:
        """Check if the basic configuration is present."""
        if self._config is None:
            self.load()
        return bool(self._config.get("client_id") and self._config.get("client_secret"))