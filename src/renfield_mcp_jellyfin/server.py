#!/usr/bin/env python3
"""
renfield-mcp-jellyfin — MCP server for Jellyfin media library.

Provides 13 specialized, LLM-friendly tools that map internally to exact
Jellyfin REST API endpoints.  Each tool returns compact JSON (~100-200 bytes
per item) so the LLM can reason efficiently.

Environment variables:
    JELLYFIN_URL      — Base URL (e.g. http://your-jellyfin-host:8096)
    JELLYFIN_API_KEY  — API key for authentication (query-param style)
    JELLYFIN_USER_ID  — User ID for library access
"""

import logging
import os
import sys

import httpx
from mcp.server.fastmcp import FastMCP

# MCP stdio servers must NEVER write to stdout — log to stderr only.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("renfield-mcp-jellyfin")

# --- Configuration from environment ---
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "").rstrip("/")
JELLYFIN_API_KEY = os.environ.get("JELLYFIN_API_KEY", "")
JELLYFIN_USER_ID = os.environ.get("JELLYFIN_USER_ID", "")

# --- Sort mapping: tool-level names → Jellyfin SortBy values ---
SORT_MAP = {
    "name": "SortName",
    "added": "DateCreated",
    "year": "PremiereDate",
    "rating": "CommunityRating",
    "random": "Random",
}


def _check_config() -> dict | None:
    """Return an error dict if configuration is missing, else None."""
    if not JELLYFIN_URL:
        return {"error": "JELLYFIN_URL not configured"}
    if not JELLYFIN_API_KEY:
        return {"error": "JELLYFIN_API_KEY not configured"}
    if not JELLYFIN_USER_ID:
        return {"error": "JELLYFIN_USER_ID not configured"}
    return None


async def _jellyfin_get(path: str, **params: str | int) -> dict:
    """GET a Jellyfin endpoint with api_key auth.  Returns parsed JSON."""
    url = f"{JELLYFIN_URL}{path}"
    params["api_key"] = JELLYFIN_API_KEY
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _format_duration(ticks: int | None) -> str | None:
    """Convert RunTimeTicks (100-ns units) to 'M:SS' string."""
    if not ticks:
        return None
    total_seconds = ticks // 10_000_000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _format_item(raw: dict, fields: list[str]) -> dict:
    """Extract only the requested fields from a verbose Jellyfin item.

    Supported field names and their source keys:
        id, name, artist, album_artist, album, year, genre, index,
        duration, overview, child_count, type, path, container,
        stream_url
    """
    extractors = {
        "id": lambda r: r.get("Id"),
        "name": lambda r: r.get("Name"),
        "artist": lambda r: (r.get("Artists") or [None])[0],
        "album_artist": lambda r: r.get("AlbumArtist"),
        "album": lambda r: r.get("Album"),
        "year": lambda r: r.get("ProductionYear"),
        "genre": lambda r: (r.get("Genres") or [None])[0],
        "index": lambda r: r.get("IndexNumber"),
        "duration": lambda r: _format_duration(r.get("RunTimeTicks")),
        "overview": lambda r: r.get("Overview"),
        "child_count": lambda r: r.get("ChildCount"),
        "type": lambda r: r.get("Type"),
        "path": lambda r: r.get("Path"),
        "container": lambda r: (r.get("MediaSources") or [{}])[0].get("Container"),
        "stream_url": lambda r: (r.get("MediaSources") or [{}])[0].get("Path"),
        "api_stream": lambda r: (
            f"{JELLYFIN_URL}/Audio/{r['Id']}/universal?api_key={JELLYFIN_API_KEY}"
            if r.get("Id") else None
        ),
    }
    result = {}
    for f in fields:
        if f in extractors:
            val = extractors[f](raw)
            if val is not None:
                result[f] = val
    return result


# --- MCP Server ---
mcp = FastMCP("renfield-jellyfin")


# ── Music tools (9) ──────────────────────────────────────────────────────────


@mcp.tool()
async def search_media(
    query: str,
    type: str = "Audio",
    limit: int = 20,
) -> dict:
    """Search the Jellyfin media library.

    Args:
        query: Search term (title, artist, album name)
        type: Item type — Audio, MusicAlbum, MusicArtist, Movie, or Series
        limit: Max results (1-50, default 20)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 50))
    data = await _jellyfin_get(
        "/Items",
        searchTerm=query,
        IncludeItemTypes=type,
        Recursive="true",
        Limit=limit,
        Fields="Genres,Artists,AlbumArtist,Album,ProductionYear,RunTimeTicks",
    )
    field_map = {
        "Audio": ["id", "name", "artist", "album", "year", "duration", "api_stream"],
        "MusicAlbum": ["id", "name", "album_artist", "year", "genre"],
        "MusicArtist": ["id", "name", "genre", "overview"],
        "Movie": ["id", "name", "year", "genre", "overview"],
        "Series": ["id", "name", "year", "genre", "overview"],
    }
    fields = field_map.get(type, ["id", "name", "type", "year"])
    items = [_format_item(it, fields) for it in data.get("Items", [])]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def list_albums(
    artist: str = "",
    genre: str = "",
    sort: str = "name",
    limit: int = 50,
) -> dict:
    """List music albums in the library.

    Args:
        artist: Filter by artist name (optional)
        genre: Filter by genre name (optional)
        sort: Sort order — name, added, year, or random (default: name)
        limit: Max results (1-100, default 50)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 100))
    params: dict[str, str | int] = {
        "IncludeItemTypes": "MusicAlbum",
        "Recursive": "true",
        "Limit": limit,
        "SortBy": SORT_MAP.get(sort, "SortName"),
        "SortOrder": "Descending" if sort in ("added", "year") else "Ascending",
        "Fields": "Genres,Artists,AlbumArtist,ProductionYear",
    }
    if artist:
        params["Artists"] = artist
    if genre:
        params["Genres"] = genre

    data = await _jellyfin_get(f"/Users/{JELLYFIN_USER_ID}/Items", **params)
    items = [
        _format_item(it, ["id", "name", "album_artist", "year", "genre"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def list_artists(limit: int = 50) -> dict:
    """List all music artists in the library.

    Args:
        limit: Max results (1-200, default 50)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 200))
    data = await _jellyfin_get(
        "/Artists",
        Limit=limit,
        Fields="Genres,Overview",
    )
    items = [
        _format_item(it, ["id", "name", "genre", "overview"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def get_album_tracks(album_id: str) -> dict:
    """Get all tracks of a specific album.

    Args:
        album_id: Jellyfin album ID
    """
    if err := _check_config():
        return err

    data = await _jellyfin_get(
        f"/Users/{JELLYFIN_USER_ID}/Items",
        ParentId=album_id,
        IncludeItemTypes="Audio",
        SortBy="IndexNumber",
        Fields="Artists,Album,RunTimeTicks",
    )
    items = [
        _format_item(it, ["id", "name", "index", "artist", "duration", "api_stream"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def get_artist_albums(artist_id: str) -> dict:
    """Get all albums by a specific artist.

    Args:
        artist_id: Jellyfin artist ID
    """
    if err := _check_config():
        return err

    data = await _jellyfin_get(
        f"/Users/{JELLYFIN_USER_ID}/Items",
        ArtistIds=artist_id,
        IncludeItemTypes="MusicAlbum",
        Recursive="true",
        SortBy="PremiereDate",
        SortOrder="Descending",
        Fields="Genres,ProductionYear",
    )
    items = [
        _format_item(it, ["id", "name", "year", "genre"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def list_genres() -> dict:
    """List all music genres in the library."""
    if err := _check_config():
        return err

    data = await _jellyfin_get("/MusicGenres", Limit=50)
    items = [{"id": it.get("Id"), "name": it.get("Name")} for it in data.get("Items", [])]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def get_recent(
    type: str = "MusicAlbum",
    limit: int = 20,
) -> dict:
    """Get recently added items.

    Args:
        type: Item type — MusicAlbum, Audio, Movie, Series (default: MusicAlbum)
        limit: Max results (1-50, default 20)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 50))
    # /Items/Latest returns a flat array (no TotalRecordCount wrapper)
    data = await _jellyfin_get(
        f"/Users/{JELLYFIN_USER_ID}/Items/Latest",
        IncludeItemTypes=type,
        Limit=limit,
        Fields="Genres,Artists,AlbumArtist,Album,ProductionYear",
    )
    # Latest endpoint returns a list directly
    raw_items = data if isinstance(data, list) else data.get("Items", [])
    field_map = {
        "Audio": ["id", "name", "artist", "album", "year"],
        "MusicAlbum": ["id", "name", "album_artist", "year", "genre"],
        "Movie": ["id", "name", "year", "genre"],
        "Series": ["id", "name", "year", "genre"],
    }
    fields = field_map.get(type, ["id", "name", "type", "year"])
    items = [_format_item(it, fields) for it in raw_items]
    return {"total": len(items), "items": items}


@mcp.tool()
async def get_favorites(limit: int = 50) -> dict:
    """Get favorite (hearted) items from the library.

    Args:
        limit: Max results (1-100, default 50)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 100))
    data = await _jellyfin_get(
        f"/Users/{JELLYFIN_USER_ID}/Items",
        IncludeItemTypes="Audio,MusicAlbum",
        Recursive="true",
        Filters="IsFavorite",
        Limit=limit,
        Fields="Genres,Artists,Album,ProductionYear,RunTimeTicks",
    )
    items = [
        _format_item(it, ["id", "name", "type", "artist", "album", "year", "duration"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def get_playlists(limit: int = 30) -> dict:
    """List all playlists in the library.

    Args:
        limit: Max results (1-100, default 30)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 100))
    data = await _jellyfin_get(
        f"/Users/{JELLYFIN_USER_ID}/Items",
        IncludeItemTypes="Playlist",
        Recursive="true",
        Limit=limit,
        Fields="ChildCount,Overview",
    )
    items = [
        _format_item(it, ["id", "name", "child_count", "overview"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


# ── Media tools (2) ──────────────────────────────────────────────────────────


@mcp.tool()
async def list_movies(
    genre: str = "",
    sort: str = "added",
    limit: int = 50,
) -> dict:
    """List movies in the library.

    Args:
        genre: Filter by genre name (optional)
        sort: Sort order — name, added, year, or rating (default: added)
        limit: Max results (1-100, default 50)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 100))
    params: dict[str, str | int] = {
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Limit": limit,
        "SortBy": SORT_MAP.get(sort, "DateCreated"),
        "SortOrder": "Descending" if sort in ("added", "year", "rating") else "Ascending",
        "Fields": "Genres,ProductionYear,Overview,CommunityRating",
    }
    if genre:
        params["Genres"] = genre

    data = await _jellyfin_get(f"/Users/{JELLYFIN_USER_ID}/Items", **params)
    items = [
        _format_item(it, ["id", "name", "year", "genre", "overview"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


@mcp.tool()
async def list_series(
    genre: str = "",
    sort: str = "added",
    limit: int = 50,
) -> dict:
    """List TV series in the library.

    Args:
        genre: Filter by genre name (optional)
        sort: Sort order — name, added, year, or rating (default: added)
        limit: Max results (1-100, default 50)
    """
    if err := _check_config():
        return err

    limit = max(1, min(limit, 100))
    params: dict[str, str | int] = {
        "IncludeItemTypes": "Series",
        "Recursive": "true",
        "Limit": limit,
        "SortBy": SORT_MAP.get(sort, "DateCreated"),
        "SortOrder": "Descending" if sort in ("added", "year", "rating") else "Ascending",
        "Fields": "Genres,ProductionYear,Overview,CommunityRating",
    }
    if genre:
        params["Genres"] = genre

    data = await _jellyfin_get(f"/Users/{JELLYFIN_USER_ID}/Items", **params)
    items = [
        _format_item(it, ["id", "name", "year", "genre", "overview"])
        for it in data.get("Items", [])
    ]
    return {"total": data.get("TotalRecordCount", 0), "items": items}


# ── Utility tools (2) ────────────────────────────────────────────────────────


@mcp.tool()
async def get_stream_url(item_id: str) -> dict:
    """Get the streaming URL and metadata for a media item.

    Args:
        item_id: Jellyfin item ID
    """
    if err := _check_config():
        return err

    data = await _jellyfin_get(
        f"/Users/{JELLYFIN_USER_ID}/Items/{item_id}",
        Fields="MediaSources,Path",
    )
    return _format_item(data, ["id", "name", "stream_url", "container", "api_stream"])


@mcp.tool()
async def library_stats() -> dict:
    """Get library statistics (counts of songs, albums, artists, movies, series, episodes)."""
    if err := _check_config():
        return err

    data = await _jellyfin_get("/Items/Counts")
    return {
        "songs": data.get("SongCount", 0),
        "albums": data.get("AlbumCount", 0),
        "artists": data.get("ArtistCount", 0),
        "movies": data.get("MovieCount", 0),
        "series": data.get("SeriesCount", 0),
        "episodes": data.get("EpisodeCount", 0),
    }


# --- Entry point ---

def main():
    """Entry point for console script and python -m."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
