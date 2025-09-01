# Spotify Plus MCP Server

A Model Context Protocol (MCP) server that connects Claude to Spotify, allowing you to control your music directly from conversations.

## Features

- **Playback Control**: Play, pause, skip tracks, and control volume
- **Music Discovery**: Search for tracks, albums, artists, and playlists
- **Enhanced Search**: Combines Spotify data with external metadata from Last.fm and MusicBrainz
- **Similar Artists**: Find similar artists using Last.fm's collaborative filtering
- **Rich Metadata**: Genre tags, artist biographies, detailed music relationships, and community data
- **Queue Management**: Add tracks to your queue and view what's coming up
- **Playlist Management**: Create, modify, and manage your playlists
- **Music Information**: Get detailed info about any track, album, or artist
- **Smart Authentication**: Automatic token management - authenticate once, use forever

## Quick Start

### 1. Get Spotify API Credentials

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Set the redirect URI to: `http://127.0.0.1:8888/callback`
4. Note your **Client ID** and **Client Secret**

### 1.5. Optional: Get Last.fm API Key (for Enhanced Features)

For enhanced music discovery features:
1. Go to [Last.fm API account creation](https://www.last.fm/api/account/create)
2. Create an API account
3. Note your **API Key**

*Note: Enhanced features will work without Last.fm API key, but with limited external metadata.*

### 2. Install and Authenticate

```bash
git clone https://github.com/omniwaifu/spotify-plus-mcp.git
cd spotify-plus-mcp

# Create a .env file with your credentials
echo "SPOTIFY_CLIENT_ID=your_client_id_here" > .env
echo "SPOTIFY_CLIENT_SECRET=your_client_secret_here" >> .env
echo "SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback" >> .env

# Run one-time authentication
python auth.py
# This will open your browser - log in and authorize the app
```

Authentication tokens are saved to `~/.spotify-mcp/spotify-config.json` and automatically refresh.

### 3. Configure Claude Desktop

Add this to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

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
        "LASTFM_API_KEY": "your_lastfm_api_key_here"  // Optional, for enhanced features
      }
    }
  }
}
```

**Note:** Spotify credentials are no longer needed in the MCP config - they're stored securely after running `auth.py`.

### 4. Start Using Spotify

1. **Restart Claude Desktop**
2. **Start using Spotify commands!**

The authentication from step 2 persists across sessions - no need to re-authenticate.

## Example Conversations

```
You: "Play some jazz music"
Claude: [Searches for jazz, starts playing]

You: "What's currently playing?"
Claude: [Shows current track info]

You: "Find me artists similar to Radiohead"
Claude: [Uses Last.fm data to find similar artists with match scores]

You: "Do an enhanced search for 'Bohemian Rhapsody'"
Claude: [Combines Spotify data with Last.fm genre tags, MusicBrainz metadata, and additional context]

You: "Add this to my favorites playlist"
Claude: [Adds current track to specified playlist]

You: "Skip to the next song"
Claude: [Skips track]
```

## Requirements

- **Spotify Premium** (required for playback control)
- **Python 3.12+**
- **uv** package manager
- **Claude Desktop**

## Development & Testing

```bash
# Check authentication status
python -c "from src.spotify_mcp.spotify_api import Client; c = Client(print); print(c.check_auth())"

# Re-authenticate if needed
python auth.py
```

## Debugging

### Common Issues

**"No active device"**: Open Spotify on any device (phone, computer, etc.)

**"Authentication failed"**: Run `python auth.py` from the command line to re-authenticate

**"Permission denied"**: Make sure you have Spotify Premium

### Logs

- **macOS**: `~/Library/Logs/Claude/`
- **Windows**: Check Claude Desktop logs
- **Debug mode**: Use MCP Inspector:
  ```bash
  npx @modelcontextprotocol/inspector uv --directory /path/to/spotify-mcp run spotify-mcp
  ```

## Available Commands

The server automatically handles all Spotify operations through natural conversation. You can:

- Control playback (play, pause, skip, volume)
- Search for any music content
- **Enhanced search** with external metadata (Last.fm + MusicBrainz)
- **Find similar artists** using collaborative filtering
- Manage your queue
- Work with playlists
- Get information about tracks/artists/albums
- Check what's currently playing

### New Enhanced Features

- **Enhanced Search**: Combines Spotify results with genre tags, artist biographies, and detailed music relationships
- **Similar Artists**: Find artists similar to your favorites using Last.fm's collaborative filtering data
- **Rich Metadata**: Additional context including community tags, listening statistics, and music database information

## Privacy & Security

- **Tokens are stored in** `~/.spotify-mcp/spotify-config.json` and refreshed automatically
- **No data is stored** beyond what's needed for authentication
- **Standard OAuth2 flow** - same as any Spotify app
- **Revoke access anytime** in your Spotify account settings

## Contributing

PRs welcome! This project is actively maintained.

## License

MIT License - see LICENSE file for details

---

**Need help?** Open an issue on GitHub or check the troubleshooting section above.
