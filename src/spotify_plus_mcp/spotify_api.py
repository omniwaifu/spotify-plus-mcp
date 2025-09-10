import logging
import os
import json
import requests
import base64
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from urllib.parse import urlencode, parse_qs, urlparse

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

from . import utils

load_dotenv()

# Config file location
CONFIG_DIR = Path.home() / ".spotify-plus-mcp"
CONFIG_FILE = CONFIG_DIR / "spotify-config.json"

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# Normalize the redirect URI to meet Spotify's requirements
if REDIRECT_URI:
    REDIRECT_URI = utils.normalize_redirect_uri(REDIRECT_URI)

SCOPES = [
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-read-currently-playing",  # spotify connect
    "app-remote-control",
    "streaming",  # playback
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    # playlists
    "user-read-playback-position",
    "user-top-read",
    "user-read-recently-played",  # listening history
    "user-library-modify",
    "user-library-read",  # library
]


class Client:
    def __init__(self, logger: logging.Logger):
        """Initialize Spotify client with necessary permissions"""
        self.logger = logger
        self.config = self._load_config()
        self.sp = None
        self.username = None
        self._init_spotify_client()

    def _load_config(self) -> Dict:
        """Load configuration from file or create default."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.logger.info(f"Loaded config from {CONFIG_FILE}")
                    return config
            except Exception as e:
                self.logger.error(f"Error loading config: {e}")
        
        # Create default config
        config = {
            "client_id": CLIENT_ID or "",
            "client_secret": CLIENT_SECRET or "",
            "redirect_uri": REDIRECT_URI or "http://127.0.0.1:8888/callback",
            "access_token": None,
            "refresh_token": None,
            "expires_at": None
        }
        self._save_config(config)
        return config
    
    def _save_config(self, config: Dict = None):
        """Save configuration to file."""
        if config is None:
            config = self.config
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            self.logger.info(f"Saved config to {CONFIG_FILE}")
        except Exception as e:
            self.logger.error(f"Error saving config: {e}")
    
    def _init_spotify_client(self):
        """Initialize Spotify client with stored or new tokens."""
        scope = "user-library-read,user-read-playback-state,user-modify-playback-state,user-read-currently-playing,playlist-read-private,playlist-read-collaborative,playlist-modify-private,playlist-modify-public"
        
        # Check if we have stored tokens
        if self.config.get("access_token") and not self._is_token_expired():
            # Use stored access token directly
            self.sp = spotipy.Spotify(auth=self.config["access_token"])
            self.logger.info("Using stored access token")
        elif self.config.get("refresh_token"):
            # Try to refresh the token
            if self._refresh_token():
                self.sp = spotipy.Spotify(auth=self.config["access_token"])
                self.logger.info("Refreshed and using new access token")
            else:
                # Fall back to OAuth flow
                self._init_oauth_client(scope)
        else:
            # No tokens, use OAuth flow
            self._init_oauth_client(scope)
    
    def _init_oauth_client(self, scope: str):
        """Initialize client with OAuth flow."""
        try:
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    scope=scope,
                    client_id=self.config.get("client_id") or CLIENT_ID,
                    client_secret=self.config.get("client_secret") or CLIENT_SECRET,
                    redirect_uri=self.config.get("redirect_uri") or REDIRECT_URI,
                )
            )
            self.auth_manager: SpotifyOAuth = self.sp.auth_manager
            self.cache_handler: CacheFileHandler = self.auth_manager.cache_handler
        except Exception as e:
            self.logger.error(f"Failed to initialize Spotify client: {str(e)}")
            raise
    
    def _is_token_expired(self) -> bool:
        """Check if the stored access token has expired."""
        expires_at = self.config.get("expires_at")
        if not expires_at:
            return True
        try:
            expiry_time = datetime.fromisoformat(expires_at)
            return datetime.now() >= expiry_time
        except:
            return True
    
    def _refresh_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        refresh_token = self.config.get("refresh_token")
        if not refresh_token:
            return False
        
        client_id = self.config.get("client_id") or CLIENT_ID
        client_secret = self.config.get("client_secret") or CLIENT_SECRET
        
        if not client_id or not client_secret:
            return False
        
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
        
        try:
            response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
            
            if response.status_code != 200:
                self.logger.error(f"Token refresh failed: {response.text}")
                return False
            
            token_info = response.json()
            
            # Update stored tokens
            self.config["access_token"] = token_info["access_token"]
            if "refresh_token" in token_info:
                self.config["refresh_token"] = token_info["refresh_token"]
            
            # Calculate expiration time
            expires_in = token_info.get("expires_in", 3600)
            expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
            self.config["expires_at"] = expires_at.isoformat()
            
            self._save_config()
            self.logger.info("Successfully refreshed access token")
            return True
            
        except Exception as e:
            self.logger.error(f"Error refreshing token: {e}")
            return False

    @utils.validate
    def set_username(self, device=None):
        # Ensure we have a valid client before making API calls
        if not self.sp or self._is_token_expired():
            if self.config.get("refresh_token"):
                self._refresh_token()
                self._init_spotify_client()
        self.username = self.sp.current_user()["display_name"]

    @utils.validate
    def search(self, query: str, qtype: str = "track", limit=10, device=None):
        """
        Searches based of query term.
        - query: query term
        - qtype: the types of items to return. One or more of 'artist', 'album',  'track', 'playlist'.
                 If multiple types are desired, pass in a comma separated string; e.g. 'track,album'
        - limit: max # items to return
        """
        if self.username is None:
            self.set_username()
        results = self.sp.search(q=query, limit=limit, type=qtype)
        if not results:
            raise ValueError("No search results found.")
        return utils.parse_search_results(results, qtype, self.username)

    def recommendations(
        self, artists: Optional[List] = None, tracks: Optional[List] = None, limit=20
    ):
        # doesnt work
        recs = self.sp.recommendations(
            seed_artists=artists, seed_tracks=tracks, limit=limit
        )
        return recs

    def get_info(self, item_uri: str) -> dict:
        """
        Returns more info about item.
        - item_uri: uri. Looks like 'spotify:track:xxxxxx', 'spotify:album:xxxxxx', etc.
        """
        _, qtype, item_id = item_uri.split(":")
        match qtype:
            case "track":
                return utils.parse_track(self.sp.track(item_id), detailed=True)
            case "album":
                album_info = utils.parse_album(self.sp.album(item_id), detailed=True)
                return album_info
            case "artist":
                artist_info = utils.parse_artist(self.sp.artist(item_id), detailed=True)
                albums = self.sp.artist_albums(item_id)
                top_tracks = self.sp.artist_top_tracks(item_id)["tracks"]
                albums_and_tracks = {"albums": albums, "tracks": {"items": top_tracks}}
                parsed_info = utils.parse_search_results(
                    albums_and_tracks, qtype="album,track"
                )
                artist_info["top_tracks"] = parsed_info["tracks"]
                artist_info["albums"] = parsed_info["albums"]

                return artist_info
            case "playlist":
                if self.username is None:
                    self.set_username()
                playlist = self.sp.playlist(item_id)
                self.logger.info(f"playlist info is {playlist}")
                playlist_info = utils.parse_playlist(
                    playlist, self.username, detailed=True
                )

                return playlist_info

        raise ValueError(f"Unknown qtype {qtype}")

    def get_current_track(self) -> Optional[Dict]:
        """Get information about the currently playing track"""
        try:
            # current_playback vs current_user_playing_track?
            current = self.sp.current_user_playing_track()
            if not current:
                self.logger.info("No playback session found")
                return None
            if current.get("currently_playing_type") != "track":
                self.logger.info("Current playback is not a track")
                return None

            track_info = utils.parse_track(current["item"])
            if "is_playing" in current:
                track_info["is_playing"] = current["is_playing"]

            self.logger.info(
                f"Current track: {track_info.get('name', 'Unknown')} by {track_info.get('artist', 'Unknown')}"
            )
            return track_info
        except Exception as e:
            self.logger.error("Error getting current track info.")
            raise

    @utils.validate
    def start_playback(self, spotify_uri=None, device=None):
        """
        Starts spotify playback of uri. If spotify_uri is omitted, resumes current playback.
        - spotify_uri: ID of resource to play, or None. Typically looks like 'spotify:track:xxxxxx' or 'spotify:album:xxxxxx'.
        """
        try:
            self.logger.info(
                f"Starting playback for spotify_uri: {spotify_uri} on {device}"
            )
            if not spotify_uri:
                if self.is_track_playing():
                    self.logger.info(
                        "No track_id provided and playback already active."
                    )
                    return
                if not self.get_current_track():
                    raise ValueError(
                        "No track_id provided and no current playback to resume."
                    )

            if spotify_uri is not None:
                if spotify_uri.startswith("spotify:track:"):
                    uris = [spotify_uri]
                    context_uri = None
                else:
                    uris = None
                    context_uri = spotify_uri
            else:
                uris = None
                context_uri = None

            device_id = device.get("id") if device else None

            self.logger.info(
                f"Starting playback of on {device}: context_uri={context_uri}, uris={uris}"
            )
            result = self.sp.start_playback(
                uris=uris, context_uri=context_uri, device_id=device_id
            )
            self.logger.info(f"Playback result: {result}")
            return result
        except Exception as e:
            self.logger.error(f"Error starting playback: {str(e)}.")
            raise

    @utils.validate
    def pause_playback(self, device=None):
        """Pauses playback."""
        playback = self.sp.current_playback()
        if playback and playback.get("is_playing"):
            self.sp.pause_playback(device.get("id") if device else None)

    @utils.validate
    def add_to_queue(self, track_id: str, device=None):
        """
        Adds track to queue.
        - track_id: ID of track to play.
        """
        self.sp.add_to_queue(track_id, device.get("id") if device else None)

    @utils.validate
    def get_queue(self, device=None):
        """Returns the current queue of tracks."""
        queue_info = self.sp.queue()
        queue_info["currently_playing"] = self.get_current_track()

        queue_info["queue"] = [
            utils.parse_track(track) for track in queue_info.pop("queue")
        ]

        return queue_info

    def get_liked_songs(self):
        # todo
        results = self.sp.current_user_saved_tracks()
        for idx, item in enumerate(results["items"]):
            track = item["track"]
            print(idx, track["artists"][0]["name"], " – ", track["name"])

    def is_track_playing(self) -> bool:
        """Returns if a track is actively playing."""
        curr_track = self.get_current_track()
        if not curr_track:
            return False
        if curr_track.get("is_playing"):
            return True
        return False

    def get_current_user_playlists(self, limit=50) -> List[Dict]:
        """
        Get current user's playlists.
        - limit: Max number of playlists to return.
        """
        playlists = self.sp.current_user_playlists()
        if not playlists:
            raise ValueError("No playlists found.")
        return [
            utils.parse_playlist(playlist, self.username)
            for playlist in playlists["items"]
        ]

    @utils.ensure_username
    def get_playlist_tracks(self, playlist_id: str, limit=50, offset=0) -> List[Dict]:
        """
        Get tracks from a playlist.
        - playlist_id: ID of the playlist to get tracks from.
        - limit: Max number of tracks to return.
        - offset: The index of the first track to return.
        """
        tracks = self.sp.playlist_tracks(playlist_id, limit=limit, offset=offset)
        if not tracks:
            raise ValueError("No tracks found.")
        return utils.parse_tracks(tracks["items"])
    
    @utils.ensure_username
    def get_all_playlist_tracks(self, playlist_id: str) -> Dict:
        """
        Get ALL tracks from a playlist, handling pagination automatically.
        Returns a dictionary with playlist info and all tracks.
        - playlist_id: ID of the playlist to get tracks from.
        """
        try:
            # Get playlist info
            playlist = self.sp.playlist(playlist_id, fields="name,description,owner,tracks.total")
            if not playlist:
                raise ValueError("No playlist found.")
            
            all_tracks = []
            limit = 100  # Max allowed by Spotify API
            offset = 0
            total = playlist["tracks"]["total"]
            
            self.logger.info(f"Fetching all {total} tracks from playlist {playlist.get('name', playlist_id)}")
            
            # Fetch all tracks using pagination
            max_retries = 3
            while offset < total:
                retry_count = 0
                tracks_batch = None
                
                while retry_count < max_retries:
                    try:
                        tracks_batch = self.sp.playlist_tracks(playlist_id, limit=limit, offset=offset)
                        break
                    except Exception as e:
                        retry_count += 1
                        self.logger.error(f"Error fetching tracks (attempt {retry_count}/{max_retries}): {e}")
                        if retry_count >= max_retries:
                            self.logger.error(f"Failed to fetch tracks at offset {offset} after {max_retries} attempts")
                            # Return partial results rather than failing completely
                            return {
                                "playlist_id": playlist_id,
                                "name": playlist.get("name", "Unknown"),
                                "description": playlist.get("description", ""),
                                "owner": playlist.get("owner", {}).get("display_name", "Unknown"),
                                "total_tracks": total,
                                "tracks": all_tracks,
                                "warning": f"Only fetched {len(all_tracks)} of {total} tracks due to API errors"
                            }
                        # Wait a bit before retrying (exponential backoff)
                        time.sleep(2 ** retry_count)
                
                if tracks_batch and tracks_batch.get("items"):
                    parsed_tracks = utils.parse_tracks(tracks_batch["items"])
                    all_tracks.extend(parsed_tracks)
                    offset += limit
                    self.logger.info(f"Fetched {min(offset, total)}/{total} tracks")
                else:
                    self.logger.warning(f"No tracks returned at offset {offset}, stopping pagination")
                    break
            
            return {
                "playlist_id": playlist_id,
                "name": playlist.get("name", "Unknown"),
                "description": playlist.get("description", ""),
                "owner": playlist.get("owner", {}).get("display_name", "Unknown"),
                "total_tracks": total,
                "tracks": all_tracks
            }
        except Exception as e:
            self.logger.error(f"Error fetching playlist tracks: {e}")
            raise

    @utils.ensure_username
    def add_tracks_to_playlist(
        self, playlist_id: str, track_ids: List[str], position: Optional[int] = None
    ):
        """
        Add tracks to a playlist.
        - playlist_id: ID of the playlist to modify.
        - track_ids: List of track IDs to add.
        - position: Position to insert the tracks at (optional).
        """
        if not playlist_id:
            raise ValueError("No playlist ID provided.")
        if not track_ids:
            raise ValueError("No track IDs provided.")

        try:
            response = self.sp.playlist_add_items(
                playlist_id, track_ids, position=position
            )
            self.logger.info(
                f"Response from adding tracks: {track_ids} to playlist {playlist_id}: {response}"
            )
        except Exception as e:
            self.logger.error(f"Error adding tracks to playlist: {str(e)}")

    @utils.ensure_username
    def remove_tracks_from_playlist(self, playlist_id: str, track_ids: List[str]):
        """
        Remove tracks from a playlist.
        - playlist_id: ID of the playlist to modify.
        - track_ids: List of track IDs to remove.
        """
        if not playlist_id:
            raise ValueError("No playlist ID provided.")
        if not track_ids:
            raise ValueError("No track IDs provided.")

        try:
            response = self.sp.playlist_remove_all_occurrences_of_items(
                playlist_id, track_ids
            )
            self.logger.info(
                f"Response from removing tracks: {track_ids} from playlist {playlist_id}: {response}"
            )
        except Exception as e:
            self.logger.error(f"Error removing tracks from playlist: {str(e)}")

    @utils.ensure_username
    def change_playlist_details(
        self,
        playlist_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        """
        Change playlist details.
        - playlist_id: ID of the playlist to modify.
        - name: New name for the playlist.
        - public: Whether the playlist should be public.
        - description: New description for the playlist.
        """
        if not playlist_id:
            raise ValueError("No playlist ID provided.")

        try:
            response = self.sp.playlist_change_details(
                playlist_id, name=name, description=description
            )
            self.logger.info(f"Response from changing playlist details: {response}")
        except Exception as e:
            self.logger.error(f"Error changing playlist details: {str(e)}")

    def get_devices(self) -> dict:
        return self.sp.devices()["devices"]

    def is_active_device(self):
        return any([device.get("is_active") for device in self.get_devices()])

    def _get_candidate_device(self):
        devices = self.get_devices()
        if not devices:
            raise ConnectionError("No active device. Is Spotify open?")
        for device in devices:
            if device.get("is_active"):
                return device
        self.logger.info(f"No active device, assigning {devices[0]['name']}.")
        return devices[0]

    def auth_ok(self) -> bool:
        """Check if we have valid authentication."""
        try:
            # First check our stored tokens
            if self.config.get("access_token"):
                if not self._is_token_expired():
                    self.logger.info("Auth check result: valid stored token")
                    return True
                elif self.config.get("refresh_token"):
                    # Try to refresh
                    if self._refresh_token():
                        self.logger.info("Auth check result: token refreshed")
                        return True
            
            # Fall back to checking OAuth cache
            if hasattr(self, 'cache_handler'):
                token = self.cache_handler.get_cached_token()
                if token is not None and not self.auth_manager.is_token_expired(token):
                    self.logger.info("Auth check result: valid OAuth token")
                    return True
            
            self.logger.info("Auth check result: no valid tokens")
            return False
        except Exception as e:
            self.logger.error(f"Error checking auth status: {str(e)}")
            return False

    def auth_refresh(self):
        self.auth_manager.validate_token(self.cache_handler.get_cached_token())

    def skip_track(self, n=1):
        # todo: Better error handling
        for _ in range(n):
            self.sp.next_track()

    def previous_track(self):
        self.sp.previous_track()

    def seek_to_position(self, position_ms):
        self.sp.seek_track(position_ms=position_ms)

    def set_volume(self, volume_percent):
        self.sp.volume(volume_percent)

    def get_auth_url(self) -> str:
        """Get the authorization URL for user to visit and authorize the app."""
        try:
            auth_url = self.auth_manager.get_authorize_url()
            self.logger.info(f"Generated auth URL: {auth_url}")
            return f"Please visit this URL to authorize the application:\n{auth_url}"
        except Exception as e:
            self.logger.error(f"Error generating auth URL: {str(e)}")
            raise

    def exchange_code(self, code: str) -> str:
        """Exchange authorization code for access token."""
        try:
            # Extract the authorization code from the callback URL if needed
            if code.startswith("http"):
                parsed_url = urlparse(code)
                query_params = parse_qs(parsed_url.query)
                if "code" in query_params:
                    code = query_params["code"][0]
                else:
                    raise ValueError("No authorization code found in the provided URL")

            client_id = self.config.get("client_id") or CLIENT_ID
            client_secret = self.config.get("client_secret") or CLIENT_SECRET
            redirect_uri = self.config.get("redirect_uri") or REDIRECT_URI
            
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
                "redirect_uri": redirect_uri
            }
            
            response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
            
            if response.status_code != 200:
                self.logger.error(f"Token exchange failed: {response.text}")
                raise Exception(f"Failed to exchange code: {response.text}")
            
            token_info = response.json()
            
            # Store tokens in config
            self.config["access_token"] = token_info["access_token"]
            self.config["refresh_token"] = token_info.get("refresh_token")
            
            # Calculate expiration time
            expires_in = token_info.get("expires_in", 3600)
            expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
            self.config["expires_at"] = expires_at.isoformat()
            
            self._save_config()
            
            # Reinitialize the client with new tokens
            self._init_spotify_client()
            
            self.logger.info("Successfully exchanged code for access token")
            return "Successfully authenticated! You can now use Spotify commands."
            
        except Exception as e:
            self.logger.error(f"Error exchanging authorization code: {str(e)}")
            raise

    def check_auth(self) -> str:
        """Check current authentication status."""
        try:
            if self.auth_ok():
                # Make sure we have a valid client
                if not self.sp:
                    self._init_spotify_client()
                user_info = self.sp.current_user()
                username = user_info.get("display_name", user_info.get("id", "Unknown"))
                return f"Authenticated as: {username}"
            else:
                return "Not authenticated. Use get_auth_url to start the authentication process."
        except Exception as e:
            self.logger.error(f"Error checking auth status: {str(e)}")
            return f"Error checking authentication: {str(e)}"
