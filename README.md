# renfield-mcp-jellyfin

MCP server for Jellyfin media library with specialized, LLM-friendly tools.

Part of the [Renfield](https://github.com/ebongard/renfield) digital assistant ecosystem.

## Features

- **13 tools** covering music, movies, series, and library management
- **Compact JSON responses** (~100-200 bytes per item) optimized for LLM context windows
- **Inline streaming URLs** — `search_media` (Audio) and `get_album_tracks` include `api_stream` URLs directly, so no extra `get_stream_url` call is needed
- **MCP stdio transport** — runs as a subprocess, no HTTP server required

## Tools (13)

### Music (9)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `search_media` | Search by title/artist/album | `query`, `type` (Audio, MusicAlbum, MusicArtist, Movie, Series), `limit` |
| `list_albums` | List albums with optional filters | `artist`, `genre`, `sort` (name, added, year, random), `limit` |
| `list_artists` | List all music artists | `limit` |
| `get_album_tracks` | Get all tracks of an album (with stream URLs) | `album_id` |
| `get_artist_albums` | Get all albums by an artist | `artist_id` |
| `list_genres` | List all music genres | — |
| `get_recent` | Recently added items | `type`, `limit` |
| `get_favorites` | Favorite (hearted) items | `limit` |
| `get_playlists` | List all playlists | `limit` |

### Media (2)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_movies` | List movies with optional genre filter | `genre`, `sort` (name, added, year, rating), `limit` |
| `list_series` | List TV series with optional genre filter | `genre`, `sort`, `limit` |

### Utility (2)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_stream_url` | Get streaming URL for a single item by ID | `item_id` |
| `library_stats` | Library statistics (songs, albums, artists, movies, series, episodes) | — |

## Response Format

All tools return compact JSON with only the fields relevant to the item type:

```json
// search_media(query="Bohemian", type="Audio")
{
  "total": 1,
  "items": [
    {
      "id": "abc123",
      "name": "Bohemian Rhapsody",
      "artist": "Queen",
      "album": "A Night at the Opera",
      "year": 1975,
      "duration": "5:55",
      "api_stream": "http://jellyfin:8096/Audio/abc123/universal?api_key=..."
    }
  ]
}
```

The `api_stream` URL is included inline for `Audio` items (in `search_media` and `get_album_tracks`), allowing direct playback without a separate `get_stream_url` call.

## Configuration

```bash
JELLYFIN_URL=http://your-jellyfin-host:8096
JELLYFIN_API_KEY=your_api_key
JELLYFIN_USER_ID=your_user_id
```

All three variables are required. The server returns an error dict if any are missing.

## Installation

```bash
pip install git+https://github.com/ebongard/renfield-mcp-jellyfin.git
```

## Usage

```bash
python -m renfield_mcp_jellyfin
```

### MCP Server Configuration (Renfield)

In `config/mcp_servers.yaml`:

```yaml
- name: jellyfin
  command: python
  args: ["-m", "renfield_mcp_jellyfin"]
  transport: stdio
  enabled: "${JELLYFIN_ENABLED:-false}"
```

## Development

```bash
git clone https://github.com/ebongard/renfield-mcp-jellyfin.git
cd renfield-mcp-jellyfin
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
