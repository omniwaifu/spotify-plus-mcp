#!/usr/bin/env python3
"""Standalone authentication script for Spotify MCP."""

import sys
import json
import time
import threading
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import requests
import base64
from datetime import datetime, timedelta
import secrets
import os
from dotenv import load_dotenv

# Config file location
CONFIG_DIR = Path.home() / ".spotify-plus-mcp"
CONFIG_FILE = CONFIG_DIR / "spotify-config.json"

# Load environment variables
load_dotenv()

class AuthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""
    
    def do_GET(self):
        """Handle GET request from Spotify callback."""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/callback':
            params = parse_qs(parsed_path.query)
            
            if 'error' in params:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Authentication Failed</h1><p>Error: ' + 
                                params['error'][0].encode() + 
                                b'</p><p>Please close this window and try again.</p></body></html>')
                self.server.auth_code = None
                self.server.error = params['error'][0]
            elif 'code' in params:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Authentication Successful!</h1>' +
                               b'<p>You can now close this window and return to the application.</p></body></html>')
                self.server.auth_code = params['code'][0]
                self.server.error = None
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Authentication Failed</h1>' +
                               b'<p>No authorization code received.</p></body></html>')
                self.server.auth_code = None
                self.server.error = "No code received"
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress request logging."""
        pass


def load_config():
    """Load or create configuration."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    
    # Create default config from environment variables
    config = {
        "client_id": os.getenv("SPOTIFY_CLIENT_ID", ""),
        "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
        "access_token": None,
        "refresh_token": None,
        "expires_at": None
    }
    
    save_config(config)
    return config


def save_config(config):
    """Save configuration to file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"✓ Configuration saved to {CONFIG_FILE}")


def exchange_code_for_token(code, config):
    """Exchange authorization code for access and refresh tokens."""
    auth_str = f"{config['client_id']}:{config['client_secret']}"
    auth_bytes = auth_str.encode('ascii')
    auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config['redirect_uri']
    }
    
    response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
    
    if response.status_code != 200:
        raise Exception(f"Failed to exchange code: {response.text}")
    
    return response.json()


def run_auth_server(port=8888):
    """Run the authorization flow."""
    config = load_config()
    
    # Check if credentials are configured
    if not config.get('client_id') or not config.get('client_secret'):
        print("Error: Spotify credentials not configured.")
        print("\nPlease set the following environment variables or add them to the config file:")
        print("  - SPOTIFY_CLIENT_ID")
        print("  - SPOTIFY_CLIENT_SECRET")
        print(f"\nConfig file location: {CONFIG_FILE}")
        return False
    
    # Generate state for security
    state = secrets.token_urlsafe(16)
    
    # Build authorization URL
    scopes = [
        "user-read-currently-playing",
        "user-read-playback-state",
        "user-modify-playback-state",
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
        "user-library-read"
    ]
    
    params = {
        "client_id": config['client_id'],
        "response_type": "code",
        "redirect_uri": config['redirect_uri'],
        "scope": " ".join(scopes),
        "state": state,
        "show_dialog": "false"
    }
    
    auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"
    
    # Start HTTP server
    server = HTTPServer(('127.0.0.1', port), AuthHandler)
    server.auth_code = None
    server.error = None
    server.timeout = 120  # 2 minute timeout
    
    print(f"Starting authentication server on port {port}...")
    print(f"Opening browser for Spotify authorization...")
    
    # Open browser
    if not webbrowser.open(auth_url):
        print(f"\nFailed to open browser automatically.")
        print(f"Please visit this URL to authorize:")
        print(f"\n{auth_url}\n")
    
    # Wait for callback
    print("Waiting for authorization callback...")
    
    start_time = time.time()
    while server.auth_code is None and server.error is None:
        server.handle_request()
        if time.time() - start_time > 120:
            print("Error: Authentication timeout (2 minutes)")
            return False
    
    if server.error:
        print(f"Error: Authentication failed - {server.error}")
        return False
    
    if not server.auth_code:
        print("Error: No authorization code received")
        return False
    
    print("✓ Authorization code received")
    
    # Exchange code for tokens
    try:
        print("Exchanging code for access token...")
        token_info = exchange_code_for_token(server.auth_code, config)
        
        # Update config with tokens
        config['access_token'] = token_info['access_token']
        config['refresh_token'] = token_info.get('refresh_token')
        
        # Calculate expiration time
        expires_in = token_info.get('expires_in', 3600)
        expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
        config['expires_at'] = expires_at.isoformat()
        
        save_config(config)
        
        print("✓ Authentication successful!")
        print(f"✓ Tokens saved to {CONFIG_FILE}")
        print("\nYou can now use the Spotify MCP server!")
        return True
        
    except Exception as e:
        print(f"Error exchanging code for token: {e}")
        return False


def main():
    """Main entry point for the auth script."""
    success = run_auth_server()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()