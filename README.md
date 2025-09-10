# Spotify Plus MCP Server

MCP server for Spotify control.

## Features

- Playback control (play, pause, skip, volume)
- Search (tracks, albums, artists, playlists)
- Queue management
- Playlist management with pagination support
  - Fetch specific pages of playlist tracks using offset
  - Export complete playlists (all tracks) to JSON
- Enhanced metadata from Last.fm and MusicBrainz
- Similar artist discovery

## Setup

### 1. Get Spotify Credentials

1. Create app at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Set redirect URI: `http://127.0.0.1:8888/callback`
3. Save Client ID and Secret

### 2. Install

```bash
git clone https://github.com/omniwaifu/spotify-plus-mcp.git
cd spotify-plus-mcp

# Create .env
echo "SPOTIFY_CLIENT_ID=your_client_id" > .env
echo "SPOTIFY_CLIENT_SECRET=your_client_secret" >> .env
echo "SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback" >> .env

# Authenticate (one-time)
python auth.py
```

Tokens saved to `~/.spotify-mcp/spotify-config.json`.

### 3. Configure MCP

Add to config:

```json
{
  "mcpServers": {
    "spotify": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/spotify-plus-mcp",
        "run",
        "spotify-plus-mcp"
      ],
      "env": {
        "LASTFM_API_KEY": "optional_api_key"
      }
    }
  }
}
```

## Requirements

- Spotify Premium
- Python 3.12+
- uv

## Playlist Export

The MCP now supports full playlist export with pagination:

### Get specific page of tracks
```
action: get_tracks
playlist_id: <playlist_id>
limit: 50
offset: 100  # Start from track 101
```

### Export complete playlist
```
action: get_all_tracks
playlist_id: <playlist_id>
```

This returns all tracks regardless of playlist size, handling pagination automatically.

## Troubleshooting

- **No active device**: Open Spotify on any device
- **Auth failed**: Run `python auth.py`
- **Permission denied**: Need Spotify Premium

## License

MIT