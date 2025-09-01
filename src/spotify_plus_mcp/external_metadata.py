"""
External metadata sources for enhanced music discovery.
Integrates with Last.fm and MusicBrainz APIs to provide additional music metadata.
"""

import logging
import os
import time
import threading
from typing import Dict, List, Optional, Any
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()

LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
LASTFM_BASE_URL = "https://ws.audioscrobbler.com/2.0/"
MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2/"

# Rate limiting for MusicBrainz (1 request per second)
MUSICBRAINZ_RATE_LIMIT = 1.0

class RateLimiter:
    """Thread-safe rate limiter for MusicBrainz API."""
    
    def __init__(self, rate_limit: float = MUSICBRAINZ_RATE_LIMIT):
        self._rate_limit = rate_limit
        self._last_request = 0.0
        self._lock = threading.Lock()
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        with self._lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request
            
            if time_since_last < self._rate_limit:
                sleep_time = self._rate_limit - time_since_last
                time.sleep(sleep_time)
            
            self._last_request = time.time()

_musicbrainz_rate_limiter = RateLimiter()


class ExternalMetadataClient:
    """Client for fetching metadata from external sources like Last.fm and MusicBrainz."""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'spotify-mcp/1.0 (https://github.com/omniwaifu/spotify-mcp)'
        })
    
    def get_enhanced_track_info(self, artist: str, track: str) -> Dict[str, Any]:
        """Get enhanced track information from multiple sources."""
        enhanced_info = {
            'artist': artist,
            'track': track,
            'lastfm_data': None,
            'musicbrainz_data': None
        }
        
        # Get Last.fm data
        if LASTFM_API_KEY:
            try:
                enhanced_info['lastfm_data'] = self._get_lastfm_track_info(artist, track)
            except Exception as e:
                self.logger.error(f"Error fetching Last.fm track info: {e}")
        
        # Get MusicBrainz data
        try:
            enhanced_info['musicbrainz_data'] = self._get_musicbrainz_track_info(artist, track)
        except Exception as e:
            self.logger.error(f"Error fetching MusicBrainz track info: {e}")
        
        return enhanced_info
    
    def get_enhanced_artist_info(self, artist: str) -> Dict[str, Any]:
        """Get enhanced artist information from multiple sources."""
        enhanced_info = {
            'artist': artist,
            'lastfm_data': None,
            'musicbrainz_data': None
        }
        
        # Get Last.fm data
        if LASTFM_API_KEY:
            try:
                enhanced_info['lastfm_data'] = self._get_lastfm_artist_info(artist)
            except Exception as e:
                self.logger.error(f"Error fetching Last.fm artist info: {e}")
        
        # Get MusicBrainz data  
        try:
            enhanced_info['musicbrainz_data'] = self._get_musicbrainz_artist_info(artist)
        except Exception as e:
            self.logger.error(f"Error fetching MusicBrainz artist info: {e}")
        
        return enhanced_info
    
    def get_similar_artists(self, artist: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get similar artists from Last.fm."""
        if not LASTFM_API_KEY:
            self.logger.warning("Last.fm API key not configured, cannot get similar artists")
            return []
        
        try:
            params = {
                'method': 'artist.getsimilar',
                'artist': artist,
                'api_key': LASTFM_API_KEY,
                'format': 'json',
                'limit': limit
            }
            
            response = self.session.get(LASTFM_BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'similarartists' in data and 'artist' in data['similarartists']:
                similar = []
                for similar_artist in data['similarartists']['artist']:
                    similar.append({
                        'name': similar_artist.get('name'),
                        'match_score': float(similar_artist.get('match', 0)),
                        'url': similar_artist.get('url'),
                        'image': similar_artist.get('image', [{}])[-1].get('#text') if similar_artist.get('image') and len(similar_artist['image']) > 0 else None
                    })
                return similar
            
            return []
        except Exception as e:
            self.logger.error(f"Error getting similar artists: {e}")
            return []
    
    def _get_lastfm_track_info(self, artist: str, track: str) -> Optional[Dict[str, Any]]:
        """Get track information from Last.fm."""
        params = {
            'method': 'track.getinfo',
            'api_key': LASTFM_API_KEY,
            'artist': artist,
            'track': track,
            'format': 'json'
        }
        
        response = self.session.get(LASTFM_BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'track' in data:
            track_data = data['track']
            return {
                'name': track_data.get('name'),
                'artist': track_data.get('artist', {}).get('name'),
                'album': track_data.get('album', {}).get('title'),
                'duration': track_data.get('duration'),
                'listeners': int(track_data.get('listeners', 0)),
                'playcount': int(track_data.get('playcount', 0)),
                'tags': [tag['name'] for tag in track_data.get('toptags', {}).get('tag', [])],
                'url': track_data.get('url'),
                'wiki': track_data.get('wiki', {}).get('summary')
            }
        
        return None
    
    def _get_lastfm_artist_info(self, artist: str) -> Optional[Dict[str, Any]]:
        """Get artist information from Last.fm."""
        params = {
            'method': 'artist.getinfo',
            'api_key': LASTFM_API_KEY,
            'artist': artist,
            'format': 'json'
        }
        
        response = self.session.get(LASTFM_BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'artist' in data:
            artist_data = data['artist']
            return {
                'name': artist_data.get('name'),
                'listeners': int(artist_data.get('stats', {}).get('listeners', 0)),
                'playcount': int(artist_data.get('stats', {}).get('playcount', 0)),
                'tags': [tag['name'] for tag in artist_data.get('tags', {}).get('tag', [])],
                'url': artist_data.get('url'),
                'bio': artist_data.get('bio', {}).get('summary'),
                'image': artist_data.get('image', [{}])[-1].get('#text') if artist_data.get('image') and len(artist_data['image']) > 0 else None
            }
        
        return None
    
    def _get_musicbrainz_track_info(self, artist: str, track: str) -> Optional[Dict[str, Any]]:
        """Get track information from MusicBrainz."""
        self._respect_musicbrainz_rate_limit()
        
        # Search for recordings
        query = f'recording:"{track}" AND artist:"{artist}"'
        params = {
            'query': query,
            'fmt': 'json',
            'limit': 5
        }
        
        response = self.session.get(f"{MUSICBRAINZ_BASE_URL}recording", params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get('recordings'):
            recording = data['recordings'][0]  # Take the first match
            return {
                'id': recording.get('id'),
                'title': recording.get('title'),
                'length': recording.get('length'),
                'disambiguation': recording.get('disambiguation'),
                'artist_credits': [
                    {
                        'name': credit.get('name'),
                        'artist_id': credit.get('artist', {}).get('id')
                    }
                    for credit in recording.get('artist-credit', [])
                    if isinstance(credit, dict)
                ],
                'releases': [
                    {
                        'id': release.get('id'),
                        'title': release.get('title'),
                        'date': release.get('date')
                    }
                    for release in recording.get('releases', [])
                ],
                'score': recording.get('score')
            }
        
        return None
    
    def _get_musicbrainz_artist_info(self, artist: str) -> Optional[Dict[str, Any]]:
        """Get artist information from MusicBrainz."""
        self._respect_musicbrainz_rate_limit()
        
        # Search for artists
        params = {
            'query': f'artist:"{artist}"',
            'fmt': 'json',
            'limit': 5
        }
        
        response = self.session.get(f"{MUSICBRAINZ_BASE_URL}artist", params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get('artists'):
            artist_data = data['artists'][0]  # Take the first match
            return {
                'id': artist_data.get('id'),
                'name': artist_data.get('name'),
                'sort_name': artist_data.get('sort-name'),
                'type': artist_data.get('type'),
                'gender': artist_data.get('gender'),
                'country': artist_data.get('country'),
                'disambiguation': artist_data.get('disambiguation'),
                'begin_area': artist_data.get('begin-area', {}).get('name'),
                'life_span': {
                    'begin': artist_data.get('life-span', {}).get('begin'),
                    'end': artist_data.get('life-span', {}).get('end'),
                    'ended': artist_data.get('life-span', {}).get('ended')
                },
                'score': artist_data.get('score')
            }
        
        return None
    
    def _respect_musicbrainz_rate_limit(self):
        """Ensure we don't exceed MusicBrainz rate limits (1 request per second)."""
        _musicbrainz_rate_limiter.wait_if_needed()