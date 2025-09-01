"""Authentication manager with persistent token storage and automatic refresh."""

import logging
import time
from typing import Optional, Dict, Any
from urllib.parse import urlencode, parse_qs, urlparse
import requests
import base64

from .config import SpotifyConfig


class SpotifyAuthManager:
    """Manages Spotify OAuth authentication with persistent storage."""
    
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    AUTH_URL = "https://accounts.spotify.com/authorize"
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.config = SpotifyConfig()
        self.config.load()
        
    def get_auth_url(self) -> str:
        """Generate the authorization URL for user to visit."""
        params = {
            "client_id": self.config.get("client_id"),
            "response_type": "code",
            "redirect_uri": self.config.get("redirect_uri"),
            "scope": " ".join(self.config.get("scopes", [])),
            "show_dialog": "false"
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"
        
    def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        # Extract code if full URL is provided
        if code.startswith("http"):
            parsed_url = urlparse(code)
            query_params = parse_qs(parsed_url.query)
            if "code" in query_params:
                code = query_params["code"][0]
            else:
                raise ValueError("No authorization code found in the provided URL")
                
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")
        
        # Prepare the request
        auth_str = f"{client_id}:{client_secret}"
        auth_bytes = auth_str.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.get("redirect_uri")
        }
        
        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        
        if response.status_code != 200:
            self.logger.error(f"Token exchange failed: {response.text}")
            raise Exception(f"Failed to exchange code: {response.text}")
            
        token_info = response.json()
        
        # Store tokens in config
        self.config.update_tokens(
            access_token=token_info["access_token"],
            refresh_token=token_info.get("refresh_token"),
            expires_in=token_info.get("expires_in", 3600)
        )
        
        self.logger.info("Successfully exchanged code for tokens")
        return token_info
        
    def refresh_access_token(self) -> Optional[str]:
        """Refresh the access token using the refresh token."""
        refresh_token = self.config.get("refresh_token")
        if not refresh_token:
            self.logger.error("No refresh token available")
            return None
            
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")
        
        # Prepare the request
        auth_str = f"{client_id}:{client_secret}"
        auth_bytes = auth_str.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        
        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        
        if response.status_code != 200:
            self.logger.error(f"Token refresh failed: {response.text}")
            return None
            
        token_info = response.json()
        
        # Update stored tokens
        self.config.update_tokens(
            access_token=token_info["access_token"],
            refresh_token=token_info.get("refresh_token", refresh_token),  # Keep old refresh token if not provided
            expires_in=token_info.get("expires_in", 3600)
        )
        
        self.logger.info("Successfully refreshed access token")
        return token_info["access_token"]
        
    def get_valid_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if necessary."""
        if not self.config.has_tokens():
            self.logger.info("No tokens available, authentication required")
            return None
            
        if self.config.is_token_expired():
            self.logger.info("Token expired, refreshing...")
            return self.refresh_access_token()
            
        return self.config.get("access_token")
        
    def is_authenticated(self) -> bool:
        """Check if we have valid authentication."""
        return self.get_valid_token() is not None
        
    def clear_tokens(self):
        """Clear all stored tokens."""
        self.config.clear_tokens()
        self.logger.info("Cleared all stored tokens")