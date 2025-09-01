"""Tests for external metadata client functionality."""

import pytest
import logging
from unittest.mock import Mock, patch, MagicMock
from src.spotify_mcp.external_metadata import ExternalMetadataClient, RateLimiter


class TestRateLimiter:
    """Test the thread-safe rate limiter."""
    
    def test_rate_limiter_initialization(self):
        """Test rate limiter initializes correctly."""
        limiter = RateLimiter(rate_limit=1.0)
        assert limiter._rate_limit == 1.0
        assert limiter._last_request == 0.0
        assert limiter._lock is not None
    
    @patch('time.time')
    @patch('time.sleep')
    def test_rate_limiter_waits_when_needed(self, mock_sleep, mock_time):
        """Test rate limiter sleeps when requests are too frequent."""
        # Mock time progression
        mock_time.side_effect = [0.0, 0.5, 0.5]  # First call, check time, set time
        
        limiter = RateLimiter(rate_limit=1.0)
        limiter._last_request = 0.0
        limiter.wait_if_needed()
        
        # Should sleep for 0.5 seconds (1.0 - 0.5)
        mock_sleep.assert_called_once_with(0.5)
    
    @patch('time.time')
    @patch('time.sleep')
    def test_rate_limiter_no_wait_when_not_needed(self, mock_sleep, mock_time):
        """Test rate limiter doesn't sleep when enough time has passed."""
        # Mock time progression
        mock_time.side_effect = [0.0, 2.0, 2.0]  # First call, check time, set time
        
        limiter = RateLimiter(rate_limit=1.0)
        limiter._last_request = 0.0
        limiter.wait_if_needed()
        
        # Should not sleep since 2.0 > 1.0
        mock_sleep.assert_not_called()


class TestExternalMetadataClient:
    """Test the external metadata client."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger for testing."""
        return Mock(spec=logging.Logger)
    
    @pytest.fixture
    def client(self, mock_logger):
        """Create an ExternalMetadataClient for testing."""
        return ExternalMetadataClient(mock_logger)
    
    def test_client_initialization(self, mock_logger):
        """Test client initializes correctly."""
        client = ExternalMetadataClient(mock_logger)
        assert client.logger == mock_logger
        assert client.session is not None
        assert 'spotify-mcp' in client.session.headers['User-Agent']
    
    def test_get_similar_artists_no_api_key(self, client):
        """Test get_similar_artists returns empty list when no API key."""
        with patch('src.spotify_mcp.external_metadata.LASTFM_API_KEY', None):
            result = client.get_similar_artists("Test Artist")
            assert result == []
    
    @patch('src.spotify_mcp.external_metadata.LASTFM_API_KEY', 'test_key')
    def test_get_similar_artists_success(self, client):
        """Test successful similar artists retrieval."""
        mock_response_data = {
            'similarartists': {
                'artist': [
                    {
                        'name': 'Similar Artist 1',
                        'match': '0.85',
                        'url': 'http://example.com',
                        'image': [{'#text': 'image_url'}]
                    }
                ]
            }
        }
        
        with patch.object(client.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            result = client.get_similar_artists("Test Artist", limit=5)
            
            assert len(result) == 1
            assert result[0]['name'] == 'Similar Artist 1'
            assert result[0]['match_score'] == 0.85
            assert result[0]['image'] == 'image_url'
    
    @patch('src.spotify_mcp.external_metadata.LASTFM_API_KEY', 'test_key')
    def test_get_similar_artists_empty_image_list(self, client):
        """Test similar artists with empty image list doesn't crash."""
        mock_response_data = {
            'similarartists': {
                'artist': [
                    {
                        'name': 'Similar Artist 1',
                        'match': '0.85',
                        'url': 'http://example.com',
                        'image': []  # Empty image list
                    }
                ]
            }
        }
        
        with patch.object(client.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            result = client.get_similar_artists("Test Artist")
            
            assert len(result) == 1
            assert result[0]['image'] is None  # Should be None, not crash
    
    def test_get_similar_artists_api_error(self, client):
        """Test similar artists handles API errors gracefully."""
        with patch('src.spotify_mcp.external_metadata.LASTFM_API_KEY', 'test_key'):
            with patch.object(client.session, 'get') as mock_get:
                mock_get.side_effect = Exception("API Error")
                
                result = client.get_similar_artists("Test Artist")
                
                assert result == []
                client.logger.error.assert_called_once()
    
    def test_musicbrainz_rate_limiting(self, client):
        """Test MusicBrainz rate limiting is called."""
        with patch.object(client, '_respect_musicbrainz_rate_limit') as mock_rate_limit:
            with patch.object(client.session, 'get') as mock_get:
                mock_response = Mock()
                mock_response.json.return_value = {'recordings': []}
                mock_response.raise_for_status.return_value = None
                mock_get.return_value = mock_response
                
                client._get_musicbrainz_track_info("Artist", "Track")
                
                mock_rate_limit.assert_called_once()
    
    def test_enhanced_track_info_error_handling(self, client):
        """Test enhanced track info handles errors gracefully."""
        with patch.object(client, '_get_lastfm_track_info') as mock_lastfm:
            with patch.object(client, '_get_musicbrainz_track_info') as mock_mb:
                mock_lastfm.side_effect = Exception("Last.fm error")
                mock_mb.side_effect = Exception("MusicBrainz error")
                
                result = client.get_enhanced_track_info("Artist", "Track")
                
                assert result['artist'] == "Artist"
                assert result['track'] == "Track"
                assert result['lastfm_data'] is None
                assert result['musicbrainz_data'] is None
                
                # Should log errors
                assert client.logger.error.call_count == 2