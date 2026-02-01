# renfield-mcp-jellyfin

MCP server for Jellyfin media library with specialized, LLM-friendly tools.

Part of the [Renfield](https://github.com/ebongard/renfield) digital assistant ecosystem.

## Tools (13)

### Music (9)

| Tool | Description |
|------|-------------|
| `search_media` | Search by title/artist/album (Audio, MusicAlbum, MusicArtist, Movie, Series) |
| `list_albums` | List albums with optional artist/genre filter and sort |
| `list_artists` | List all music artists |
| `get_album_tracks` | Get all tracks of an album |
| `get_artist_albums` | Get all albums by an artist |
| `list_genres` | List all music genres |
| `get_recent` | Recently added items |
| `get_favorites` | Favorite (hearted) items |
| `get_playlists` | List all playlists |

### Media (2)

| Tool | Description |
|------|-------------|
| `list_movies` | List movies with optional genre filter and sort |
| `list_series` | List TV series with optional genre filter and sort |

### Utility (2)

| Tool | Description |
|------|-------------|
| `get_stream_url` | Get streaming URL for a media item |
| `library_stats` | Library statistics (songs, albums, artists, movies, series, episodes) |

## Configuration

```bash
JELLYFIN_URL=http://your-jellyfin-host:8096
JELLYFIN_API_KEY=your_api_key
JELLYFIN_USER_ID=your_user_id
```

## Installation

```bash
pip install git+https://github.com/ebongard/renfield-mcp-jellyfin.git
```

## Usage

```bash
python -m renfield_mcp_jellyfin
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
