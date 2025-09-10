import asyncio
import base64
import os
import logging
import sys
from enum import Enum
import json
from typing import List, Optional, Tuple
from datetime import datetime
from pathlib import Path

import mcp.types as types
from mcp.server import NotificationOptions, Server  # , stdio_server
import mcp.server.stdio
from pydantic import BaseModel, Field, AnyUrl
from spotipy import SpotifyException

from . import spotify_api
from .utils import normalize_redirect_uri
from .external_metadata import ExternalMetadataClient

# Configuration constants
EXTERNAL_API_CALL_LIMIT = int(os.getenv("EXTERNAL_API_CALL_LIMIT", "3"))  # Limit external API calls per search


def setup_logger():
    class Logger:
        def info(self, message):
            print(f"[INFO] {message}", file=sys.stderr)

        def error(self, message):
            print(f"[ERROR] {message}", file=sys.stderr)

    return Logger()


logger = setup_logger()
# Normalize the redirect URI to meet Spotify's requirements
if spotify_api.REDIRECT_URI:
    spotify_api.REDIRECT_URI = normalize_redirect_uri(spotify_api.REDIRECT_URI)
spotify_client = spotify_api.Client(logger)
external_metadata_client = ExternalMetadataClient(logger)

server = Server("spotify-mcp")


# options =
class ToolModel(BaseModel):
    @classmethod
    def as_tool(cls):
        return types.Tool(
            name="Spotify" + cls.__name__,
            description=cls.__doc__,
            inputSchema=cls.model_json_schema(),
        )


class Playback(ToolModel):
    """Manages the current playback with the following actions:
    - get: Get information about user's current track.
    - start: Starts playing new item or resumes current playback if called with no uri.
    - pause: Pauses current playback.
    - skip: Skips current track.
    """

    action: str = Field(
        description="Action to perform: 'get', 'start', 'pause' or 'skip'."
    )
    spotify_uri: Optional[str] = Field(
        default=None,
        description="Spotify uri of item to play for 'start' action. "
        + "If omitted, resumes current playback.",
    )
    num_skips: Optional[int] = Field(
        default=1, description="Number of tracks to skip for `skip` action."
    )


class Queue(ToolModel):
    """Manage the playback queue - get the queue or add tracks."""

    action: str = Field(description="Action to perform: 'add' or 'get'.")
    track_id: Optional[str] = Field(
        default=None, description="Track ID to add to queue (required for add action)"
    )


class GetInfo(ToolModel):
    """Get detailed information about a Spotify item (track, album, artist, or playlist)."""

    item_uri: str = Field(
        description="URI of the item to get information about. "
        + "If 'playlist' or 'album', returns its tracks. "
        + "If 'artist', returns albums and top tracks."
    )


class Search(ToolModel):
    """Search for tracks, albums, artists, or playlists on Spotify."""

    query: str = Field(description="query term")
    qtype: Optional[str] = Field(
        default="track",
        description="Type of items to search for (track, album, artist, playlist, "
        + "or comma-separated combination)",
    )
    limit: Optional[int] = Field(
        default=10, description="Maximum number of items to return"
    )


class Playlist(ToolModel):
    """Manage Spotify playlists.
    - get: Get a list of user's playlists.
    - get_tracks: Get tracks in a specific playlist (supports pagination with offset).
    - get_all_tracks: Get ALL tracks from a playlist (auto-pagination, useful for export).
    - add_tracks: Add tracks to a specific playlist.
    - remove_tracks: Remove tracks from a specific playlist.
    - change_details: Change details of a specific playlist.
    """

    action: str = Field(
        description="Action to perform: 'get', 'get_tracks', 'get_all_tracks', 'add_tracks', 'remove_tracks', 'change_details'."
    )
    playlist_id: Optional[str] = Field(
        default=None, description="ID of the playlist to manage."
    )
    track_ids: Optional[List[str]] = Field(
        default=None, description="List of track IDs to add/remove."
    )
    name: Optional[str] = Field(default=None, description="New name for the playlist.")
    description: Optional[str] = Field(
        default=None, description="New description for the playlist."
    )
    limit: Optional[int] = Field(
        default=50, description="Max number of tracks to return (for get_tracks action)."
    )
    offset: Optional[int] = Field(
        default=0, description="The index of the first track to return (for get_tracks action, useful for pagination)."
    )


class Authentication(ToolModel):
    """Check Spotify authentication status.
    Note: To authenticate, run 'python auth.py' or 'spotify-mcp-auth' from the command line.
    """

    action: str = Field(
        description="Action to perform: 'check_auth' to verify authentication status."
    )


class EnhancedSearch(ToolModel):
    """Enhanced search that combines Spotify data with external metadata sources (Last.fm, MusicBrainz).
    Provides richer information including similar artists, genre tags, detailed music relationships, and community data.
    """

    query: str = Field(description="Search query term")
    search_type: str = Field(
        default="track",
        description="Type of search: 'track', 'artist', or 'album'"
    )
    include_similar: Optional[bool] = Field(
        default=True,
        description="Include similar artists from Last.fm (for artist searches)"
    )
    limit: Optional[int] = Field(
        default=5, 
        description="Maximum number of results to return"
    )


class SimilarArtists(ToolModel):
    """Get similar artists based on Last.fm collaborative filtering data."""
    
    artist: str = Field(description="Artist name to find similar artists for")
    limit: Optional[int] = Field(
        default=10,
        description="Maximum number of similar artists to return"
    )


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    return []


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    return []


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    logger.info("Listing available tools")
    # await server.request_context.session.send_notification("are you recieving this notification?")
    tools = [
        Playback.as_tool(),
        Search.as_tool(),
        Queue.as_tool(),
        GetInfo.as_tool(),
        Playlist.as_tool(),
        Authentication.as_tool(),
        EnhancedSearch.as_tool(),
        SimilarArtists.as_tool(),
    ]
    logger.info(f"Available tools: {[tool.name for tool in tools]}")
    return tools


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    assert name[:7] == "Spotify", f"Unknown tool: {name}"
    try:
        match name[7:]:
            case "Playback":
                action = arguments.get("action")
                match action:
                    case "get":
                        logger.info("Attempting to get current track")
                        curr_track = spotify_client.get_current_track()
                        if curr_track:
                            logger.info(
                                f"Current track retrieved: {curr_track.get('name', 'Unknown')}"
                            )
                            return [
                                types.TextContent(
                                    type="text", text=json.dumps(curr_track, indent=2)
                                )
                            ]
                        logger.info("No track currently playing")
                        return [
                            types.TextContent(type="text", text="No track playing.")
                        ]
                    case "start":
                        logger.info(f"Starting playback with arguments: {arguments}")
                        spotify_client.start_playback(
                            spotify_uri=arguments.get("spotify_uri")
                        )
                        logger.info("Playback started successfully")
                        return [
                            types.TextContent(type="text", text="Playback starting.")
                        ]
                    case "pause":
                        logger.info("Attempting to pause playback")
                        spotify_client.pause_playback()
                        logger.info("Playback paused successfully")
                        return [types.TextContent(type="text", text="Playback paused.")]
                    case "skip":
                        num_skips = int(arguments.get("num_skips", 1))
                        logger.info(f"Skipping {num_skips} tracks.")
                        spotify_client.skip_track(n=num_skips)
                        return [
                            types.TextContent(
                                type="text", text="Skipped to next track."
                            )
                        ]

            case "Search":
                logger.info(f"Performing search with arguments: {arguments}")
                search_results = spotify_client.search(
                    query=arguments.get("query", ""),
                    qtype=arguments.get("qtype", "track"),
                    limit=arguments.get("limit", 10),
                )
                logger.info("Search completed successfully.")
                return [
                    types.TextContent(
                        type="text", text=json.dumps(search_results, indent=2)
                    )
                ]

            case "Queue":
                logger.info(f"Queue operation with arguments: {arguments}")
                action = arguments.get("action")

                match action:
                    case "add":
                        track_id = arguments.get("track_id")
                        if not track_id:
                            logger.error("track_id is required for add to queue.")
                            return [
                                types.TextContent(
                                    type="text",
                                    text="track_id is required for add action",
                                )
                            ]
                        spotify_client.add_to_queue(track_id)
                        return [
                            types.TextContent(
                                type="text", text=f"Track added to queue."
                            )
                        ]

                    case "get":
                        queue = spotify_client.get_queue()
                        return [
                            types.TextContent(
                                type="text", text=json.dumps(queue, indent=2)
                            )
                        ]

                    case _:
                        return [
                            types.TextContent(
                                type="text",
                                text=f"Unknown queue action: {action}. Supported actions are: add, remove, and get.",
                            )
                        ]

            case "GetInfo":
                logger.info(f"Getting item info with arguments: {arguments}")
                item_info = spotify_client.get_info(item_uri=arguments.get("item_uri"))
                return [
                    types.TextContent(type="text", text=json.dumps(item_info, indent=2))
                ]

            case "Playlist":
                logger.info(f"Playlist operation with arguments: {arguments}")
                action = arguments.get("action")
                match action:
                    case "get":
                        logger.info(
                            f"Getting current user's playlists with arguments: {arguments}"
                        )
                        playlists = spotify_client.get_current_user_playlists()
                        return [
                            types.TextContent(
                                type="text", text=json.dumps(playlists, indent=2)
                            )
                        ]
                    case "get_tracks":
                        logger.info(
                            f"Getting tracks in playlist with arguments: {arguments}"
                        )
                        if not arguments.get("playlist_id"):
                            logger.error(
                                "playlist_id is required for get_tracks action."
                            )
                            return [
                                types.TextContent(
                                    type="text",
                                    text="playlist_id is required for get_tracks action.",
                                )
                            ]
                        tracks = spotify_client.get_playlist_tracks(
                            playlist_id=arguments.get("playlist_id"),
                            limit=arguments.get("limit", 50),
                            offset=arguments.get("offset", 0)
                        )
                        return [
                            types.TextContent(
                                type="text", text=json.dumps(tracks, indent=2)
                            )
                        ]
                    case "get_all_tracks":
                        logger.info(
                            f"Getting ALL tracks from playlist with arguments: {arguments}"
                        )
                        if not arguments.get("playlist_id"):
                            logger.error(
                                "playlist_id is required for get_all_tracks action."
                            )
                            return [
                                types.TextContent(
                                    type="text",
                                    text="playlist_id is required for get_all_tracks action.",
                                )
                            ]
                        playlist_data = spotify_client.get_all_playlist_tracks(
                            playlist_id=arguments.get("playlist_id")
                        )
                        return [
                            types.TextContent(
                                type="text", text=json.dumps(playlist_data, indent=2)
                            )
                        ]
                    case "add_tracks":
                        logger.info(
                            f"Adding tracks to playlist with arguments: {arguments}"
                        )
                        track_ids = arguments.get("track_ids")
                        if isinstance(track_ids, str):
                            try:
                                track_ids = json.loads(
                                    track_ids
                                )  # Convert JSON string to Python list
                            except json.JSONDecodeError:
                                logger.error(
                                    "track_ids must be a list or a valid JSON array."
                                )
                                return [
                                    types.TextContent(
                                        type="text",
                                        text="Error: track_ids must be a list or a valid JSON array.",
                                    )
                                ]

                        spotify_client.add_tracks_to_playlist(
                            playlist_id=arguments.get("playlist_id"),
                            track_ids=track_ids,
                        )
                        return [
                            types.TextContent(
                                type="text", text="Tracks added to playlist."
                            )
                        ]
                    case "remove_tracks":
                        logger.info(
                            f"Removing tracks from playlist with arguments: {arguments}"
                        )
                        track_ids = arguments.get("track_ids")
                        if isinstance(track_ids, str):
                            try:
                                track_ids = json.loads(
                                    track_ids
                                )  # Convert JSON string to Python list
                            except json.JSONDecodeError:
                                logger.error(
                                    "track_ids must be a list or a valid JSON array."
                                )
                                return [
                                    types.TextContent(
                                        type="text",
                                        text="Error: track_ids must be a list or a valid JSON array.",
                                    )
                                ]

                        spotify_client.remove_tracks_from_playlist(
                            playlist_id=arguments.get("playlist_id"),
                            track_ids=track_ids,
                        )
                        return [
                            types.TextContent(
                                type="text", text="Tracks removed from playlist."
                            )
                        ]

                    case "change_details":
                        logger.info(
                            f"Changing playlist details with arguments: {arguments}"
                        )
                        if not arguments.get("playlist_id"):
                            logger.error(
                                "playlist_id is required for change_details action."
                            )
                            return [
                                types.TextContent(
                                    type="text",
                                    text="playlist_id is required for change_details action.",
                                )
                            ]
                        if not arguments.get("name") and not arguments.get(
                            "description"
                        ):
                            logger.error(
                                "At least one of name, description or public is required."
                            )
                            return [
                                types.TextContent(
                                    type="text",
                                    text="At least one of name, description, public, or collaborative is required.",
                                )
                            ]

                        spotify_client.change_playlist_details(
                            playlist_id=arguments.get("playlist_id"),
                            name=arguments.get("name"),
                            description=arguments.get("description"),
                        )
                        return [
                            types.TextContent(
                                type="text", text="Playlist details changed."
                            )
                        ]

                    case _:
                        return [
                            types.TextContent(
                                type="text",
                                text=f"Unknown playlist action: {action}. "
                                "Supported actions are: get, get_tracks, get_all_tracks, add_tracks, remove_tracks, change_details.",
                            )
                        ]
            case "Authentication":
                logger.info(f"Authentication operation with arguments: {arguments}")
                action = arguments.get("action")
                match action:
                    case "check_auth":
                        logger.info("Checking authentication status")
                        status = spotify_client.check_auth()
                        return [
                            types.TextContent(
                                type="text", text=f"Authentication status: {status}"
                            )
                        ]
                    case _:
                        return [
                            types.TextContent(
                                type="text",
                                text=f"Unknown authentication action: {action}. Only 'check_auth' is supported. To authenticate, run 'python auth.py' from the command line.",
                            )
                        ]
            
            case "EnhancedSearch":
                logger.info(f"Enhanced search with arguments: {arguments}")
                query = arguments.get("query", "")
                search_type = arguments.get("search_type", "track")
                include_similar = arguments.get("include_similar", True)
                limit = arguments.get("limit", 5)
                
                # First, get Spotify search results
                spotify_results = spotify_client.search(
                    query=query,
                    qtype=search_type,
                    limit=limit
                )
                
                enhanced_results = {
                    "query": query,
                    "search_type": search_type,
                    "spotify_results": spotify_results,
                    "external_metadata": []
                }
                
                # Enhance each result with external metadata
                if search_type == "track" and spotify_results.get("tracks"):
                    for track in spotify_results["tracks"][:EXTERNAL_API_CALL_LIMIT]:
                        try:
                            enhanced_info = external_metadata_client.get_enhanced_track_info(
                                track.get("artist", ""), track.get("name", "")
                            )
                            enhanced_results["external_metadata"].append(enhanced_info)
                        except Exception as e:
                            logger.error(f"Error enhancing track metadata: {e}")
                
                elif search_type == "artist" and spotify_results.get("artists"):
                    for artist in spotify_results["artists"][:EXTERNAL_API_CALL_LIMIT]:
                        try:
                            enhanced_info = external_metadata_client.get_enhanced_artist_info(
                                artist.get("name", "")
                            )
                            # Add similar artists if requested
                            if include_similar:
                                enhanced_info["similar_artists"] = external_metadata_client.get_similar_artists(
                                    artist.get("name", ""), limit=5
                                )
                            enhanced_results["external_metadata"].append(enhanced_info)
                        except Exception as e:
                            logger.error(f"Error enhancing artist metadata: {e}")
                
                return [
                    types.TextContent(
                        type="text", text=json.dumps(enhanced_results, indent=2)
                    )
                ]
            
            case "SimilarArtists":
                logger.info(f"Getting similar artists with arguments: {arguments}")
                artist = arguments.get("artist", "")
                limit = arguments.get("limit", 10)
                
                if not artist:
                    return [
                        types.TextContent(
                            type="text", text="Artist name is required for similar artists search"
                        )
                    ]
                
                similar_artists = external_metadata_client.get_similar_artists(artist, limit)
                
                result = {
                    "artist": artist,
                    "similar_artists": similar_artists,
                    "count": len(similar_artists)
                }
                
                return [
                    types.TextContent(
                        type="text", text=json.dumps(result, indent=2)
                    )
                ]
            
            case _:
                error_msg = f"Unknown tool: {name}"
                logger.error(error_msg)
                return [types.TextContent(type="text", text=error_msg)]
    except SpotifyException as se:
        error_msg = f"Spotify Client error occurred: {str(se)}"
        logger.error(error_msg)
        return [
            types.TextContent(
                type="text",
                text=f"An error occurred with the Spotify Client: {str(se)}",
            )
        ]
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return [types.TextContent(type="text", text=error_msg)]


async def main():
    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error occurred: {str(e)}")
        raise
