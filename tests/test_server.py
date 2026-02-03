"""Tests for renfield-mcp-jellyfin MCP server."""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from renfield_mcp_jellyfin import server as jf


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_config(monkeypatch):
    """Ensure config env vars are set for every test."""
    monkeypatch.setattr(jf, "JELLYFIN_URL", "http://jellyfin.local:8096")
    monkeypatch.setattr(jf, "JELLYFIN_API_KEY", "test-api-key")
    monkeypatch.setattr(jf, "JELLYFIN_USER_ID", "test-user-id")


def _mock_response(data: dict | list) -> AsyncMock:
    """Create a mock httpx response with .json() and .raise_for_status()."""
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def _patch_get(return_data: dict | list):
    """Patch _jellyfin_get to return given data."""
    return patch.object(jf, "_jellyfin_get", new_callable=AsyncMock, return_value=return_data)


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

class TestCheckConfig:
    def test_all_set(self):
        assert jf._check_config() is None

    def test_missing_url(self, monkeypatch):
        monkeypatch.setattr(jf, "JELLYFIN_URL", "")
        err = jf._check_config()
        assert "JELLYFIN_URL" in err["error"]

    def test_missing_api_key(self, monkeypatch):
        monkeypatch.setattr(jf, "JELLYFIN_API_KEY", "")
        err = jf._check_config()
        assert "JELLYFIN_API_KEY" in err["error"]

    def test_missing_user_id(self, monkeypatch):
        monkeypatch.setattr(jf, "JELLYFIN_USER_ID", "")
        err = jf._check_config()
        assert "JELLYFIN_USER_ID" in err["error"]


class TestFormatDuration:
    def test_normal(self):
        # 5 minutes 30 seconds = 5*60+30 = 330 seconds = 330 * 10_000_000 ticks
        assert jf._format_duration(3_300_000_000) == "5:30"

    def test_zero_seconds(self):
        assert jf._format_duration(1_800_000_000) == "3:00"

    def test_none(self):
        assert jf._format_duration(None) is None

    def test_zero(self):
        assert jf._format_duration(0) is None


class TestFormatItem:
    def test_extracts_fields(self):
        raw = {
            "Id": "abc123",
            "Name": "Bohemian Rhapsody",
            "Artists": ["Queen"],
            "Album": "A Night at the Opera",
            "ProductionYear": 1975,
            "RunTimeTicks": 3_550_000_000,
        }
        result = jf._format_item(raw, ["id", "name", "artist", "album", "year", "duration"])
        assert result == {
            "id": "abc123",
            "name": "Bohemian Rhapsody",
            "artist": "Queen",
            "album": "A Night at the Opera",
            "year": 1975,
            "duration": "5:55",
        }

    def test_skips_none_values(self):
        raw = {"Id": "x", "Name": "Test"}
        result = jf._format_item(raw, ["id", "name", "artist", "album"])
        assert result == {"id": "x", "name": "Test"}

    def test_genre_extraction(self):
        raw = {"Id": "x", "Genres": ["Rock", "Classic Rock"]}
        result = jf._format_item(raw, ["id", "genre"])
        assert result == {"id": "x", "genre": "Rock"}

    def test_empty_artists_list(self):
        raw = {"Id": "x", "Artists": []}
        result = jf._format_item(raw, ["id", "artist"])
        assert result == {"id": "x"}

    def test_media_sources(self):
        raw = {
            "Id": "x",
            "MediaSources": [{"Path": "/music/song.flac", "Container": "flac"}],
        }
        result = jf._format_item(raw, ["id", "stream_url", "container"])
        assert result == {"id": "x", "stream_url": "/music/song.flac", "container": "flac"}


# ---------------------------------------------------------------------------
# Tool tests — Music (9)
# ---------------------------------------------------------------------------

class TestSearchMedia:
    async def test_audio_search(self):
        with _patch_get({
            "TotalRecordCount": 2,
            "Items": [
                {"Id": "1", "Name": "Song A", "Artists": ["Artist X"], "Album": "Album Y", "ProductionYear": 2020, "RunTimeTicks": 2_400_000_000},
                {"Id": "2", "Name": "Song B", "Artists": ["Artist Z"], "Album": "Album W", "ProductionYear": 2021, "RunTimeTicks": 1_800_000_000},
            ],
        }) as mock:
            result = await jf.search_media("test query")
            assert result["total"] == 2
            assert len(result["items"]) == 2
            assert result["items"][0]["name"] == "Song A"
            assert result["items"][0]["artist"] == "Artist X"
            assert "api_stream" in result["items"][0]
            assert "1" in result["items"][0]["api_stream"]
            mock.assert_called_once()

    async def test_album_search(self):
        with _patch_get({
            "TotalRecordCount": 1,
            "Items": [
                {"Id": "a1", "Name": "Dark Side", "AlbumArtist": "Pink Floyd", "ProductionYear": 1973, "Genres": ["Rock"]},
            ],
        }):
            result = await jf.search_media("dark side", type="MusicAlbum")
            assert result["items"][0]["name"] == "Dark Side"

    async def test_limit_clamped(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.search_media("x", limit=200)
            call_kwargs = mock.call_args
            assert call_kwargs.kwargs["Limit"] == 50

    async def test_missing_config(self, monkeypatch):
        monkeypatch.setattr(jf, "JELLYFIN_URL", "")
        result = await jf.search_media("test")
        assert "error" in result


class TestListAlbums:
    async def test_basic(self):
        with _patch_get({
            "TotalRecordCount": 1,
            "Items": [
                {"Id": "a1", "Name": "Album X", "AlbumArtist": "Artist Y", "ProductionYear": 2020, "Genres": ["Pop"]},
            ],
        }):
            result = await jf.list_albums()
            assert result["total"] == 1
            assert result["items"][0]["album_artist"] == "Artist Y"

    async def test_with_artist_filter(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_albums(artist="Queen")
            assert mock.call_args.kwargs["Artists"] == "Queen"

    async def test_with_genre_filter(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_albums(genre="Rock")
            assert mock.call_args.kwargs["Genres"] == "Rock"

    async def test_sort_by_year(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_albums(sort="year")
            assert mock.call_args.kwargs["SortBy"] == "PremiereDate"
            assert mock.call_args.kwargs["SortOrder"] == "Descending"

    async def test_sort_by_name_ascending(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_albums(sort="name")
            assert mock.call_args.kwargs["SortBy"] == "SortName"
            assert mock.call_args.kwargs["SortOrder"] == "Ascending"


class TestListArtists:
    async def test_basic(self):
        with _patch_get({
            "TotalRecordCount": 2,
            "Items": [
                {"Id": "ar1", "Name": "Queen", "Genres": ["Rock"]},
                {"Id": "ar2", "Name": "Mozart", "Genres": ["Classical"]},
            ],
        }):
            result = await jf.list_artists()
            assert result["total"] == 2
            assert result["items"][1]["name"] == "Mozart"

    async def test_limit_clamped(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_artists(limit=500)
            assert mock.call_args.kwargs["Limit"] == 200


class TestGetAlbumTracks:
    async def test_returns_tracks(self):
        with _patch_get({
            "TotalRecordCount": 3,
            "Items": [
                {"Id": "t1", "Name": "Track 1", "IndexNumber": 1, "Artists": ["Queen"], "RunTimeTicks": 2_100_000_000},
                {"Id": "t2", "Name": "Track 2", "IndexNumber": 2, "Artists": ["Queen"], "RunTimeTicks": 3_300_000_000},
                {"Id": "t3", "Name": "Track 3", "IndexNumber": 3, "Artists": ["Queen"], "RunTimeTicks": 1_500_000_000},
            ],
        }) as mock:
            result = await jf.get_album_tracks("album-id-123")
            assert result["total"] == 3
            assert result["items"][0]["index"] == 1
            assert result["items"][0]["duration"] == "3:30"
            assert "api_stream" in result["items"][0]
            assert "t1" in result["items"][0]["api_stream"]
            assert mock.call_args.kwargs["ParentId"] == "album-id-123"


class TestGetArtistAlbums:
    async def test_returns_albums(self):
        with _patch_get({
            "TotalRecordCount": 2,
            "Items": [
                {"Id": "a1", "Name": "Album A", "ProductionYear": 1980, "Genres": ["Rock"]},
                {"Id": "a2", "Name": "Album B", "ProductionYear": 1975, "Genres": ["Rock"]},
            ],
        }) as mock:
            result = await jf.get_artist_albums("artist-id-456")
            assert result["total"] == 2
            assert mock.call_args.kwargs["ArtistIds"] == "artist-id-456"


class TestListGenres:
    async def test_returns_genres(self):
        with _patch_get({
            "TotalRecordCount": 3,
            "Items": [
                {"Id": "g1", "Name": "Rock"},
                {"Id": "g2", "Name": "Jazz"},
                {"Id": "g3", "Name": "Classical"},
            ],
        }):
            result = await jf.list_genres()
            assert result["total"] == 3
            names = [g["name"] for g in result["items"]]
            assert "Rock" in names
            assert "Jazz" in names


class TestGetRecent:
    async def test_returns_list(self):
        """Latest endpoint returns a flat list, not {Items: [...]}."""
        with _patch_get([
            {"Id": "r1", "Name": "New Album", "AlbumArtist": "Band", "ProductionYear": 2025, "Genres": ["Pop"]},
            {"Id": "r2", "Name": "Another Album", "AlbumArtist": "Solo", "ProductionYear": 2024, "Genres": ["Rock"]},
        ]):
            result = await jf.get_recent()
            assert result["total"] == 2
            assert result["items"][0]["name"] == "New Album"

    async def test_audio_type(self):
        with _patch_get([
            {"Id": "s1", "Name": "Song", "Artists": ["X"], "Album": "Y", "ProductionYear": 2025},
        ]):
            result = await jf.get_recent(type="Audio")
            assert result["items"][0]["name"] == "Song"


class TestGetFavorites:
    async def test_returns_favorites(self):
        with _patch_get({
            "TotalRecordCount": 1,
            "Items": [
                {"Id": "f1", "Name": "Fav Song", "Type": "Audio", "Artists": ["Fav Artist"], "Album": "Fav Album", "ProductionYear": 2020, "RunTimeTicks": 2_400_000_000},
            ],
        }):
            result = await jf.get_favorites()
            assert result["total"] == 1
            assert result["items"][0]["name"] == "Fav Song"


class TestGetPlaylists:
    async def test_returns_playlists(self):
        with _patch_get({
            "TotalRecordCount": 2,
            "Items": [
                {"Id": "p1", "Name": "Chill Mix", "ChildCount": 15},
                {"Id": "p2", "Name": "Workout", "ChildCount": 30, "Overview": "Gym playlist"},
            ],
        }):
            result = await jf.get_playlists()
            assert result["total"] == 2
            assert result["items"][0]["child_count"] == 15
            assert result["items"][1]["overview"] == "Gym playlist"


# ---------------------------------------------------------------------------
# Tool tests — Media (2)
# ---------------------------------------------------------------------------

class TestListMovies:
    async def test_basic(self):
        with _patch_get({
            "TotalRecordCount": 1,
            "Items": [
                {"Id": "m1", "Name": "The Matrix", "ProductionYear": 1999, "Genres": ["Sci-Fi"], "Overview": "A hacker discovers reality is a simulation."},
            ],
        }):
            result = await jf.list_movies()
            assert result["total"] == 1
            assert result["items"][0]["name"] == "The Matrix"
            assert result["items"][0]["year"] == 1999

    async def test_genre_filter(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_movies(genre="Action")
            assert mock.call_args.kwargs["Genres"] == "Action"

    async def test_sort_by_rating(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_movies(sort="rating")
            assert mock.call_args.kwargs["SortBy"] == "CommunityRating"


class TestListSeries:
    async def test_basic(self):
        with _patch_get({
            "TotalRecordCount": 1,
            "Items": [
                {"Id": "s1", "Name": "Breaking Bad", "ProductionYear": 2008, "Genres": ["Drama"], "Overview": "A chemistry teacher turns to crime."},
            ],
        }):
            result = await jf.list_series()
            assert result["total"] == 1
            assert result["items"][0]["name"] == "Breaking Bad"

    async def test_genre_filter(self):
        with _patch_get({"TotalRecordCount": 0, "Items": []}) as mock:
            await jf.list_series(genre="Comedy")
            assert mock.call_args.kwargs["Genres"] == "Comedy"


# ---------------------------------------------------------------------------
# Tool tests — Utility (2)
# ---------------------------------------------------------------------------

class TestGetStreamUrl:
    async def test_returns_urls(self):
        with _patch_get({
            "Id": "item1",
            "Name": "Song X",
            "MediaSources": [{"Path": "/data/music/song.flac", "Container": "flac"}],
        }):
            result = await jf.get_stream_url("item1")
            assert result["name"] == "Song X"
            assert result["stream_url"] == "/data/music/song.flac"
            assert result["container"] == "flac"
            assert "api_stream" in result
            assert "item1" in result["api_stream"]


class TestLibraryStats:
    async def test_returns_counts(self):
        with _patch_get({
            "SongCount": 1234,
            "AlbumCount": 89,
            "ArtistCount": 45,
            "MovieCount": 67,
            "SeriesCount": 12,
            "EpisodeCount": 234,
        }):
            result = await jf.library_stats()
            assert result["songs"] == 1234
            assert result["albums"] == 89
            assert result["artists"] == 45
            assert result["movies"] == 67
            assert result["series"] == 12
            assert result["episodes"] == 234


# ---------------------------------------------------------------------------
# Response size tests
# ---------------------------------------------------------------------------

class TestResponseSize:
    def test_search_20_results_under_5kb(self):
        """20 compact search results must fit under 5KB."""
        items = []
        for i in range(20):
            items.append({
                "id": f"id-{i:04d}",
                "name": f"Song Title Number {i}",
                "artist": f"Artist Name {i}",
                "album": f"Album Name {i}",
                "year": 2020 + (i % 5),
                "duration": f"{3 + i % 4}:{(i * 7) % 60:02d}",
            })
        response = {"total": 20, "items": items}
        size = len(json.dumps(response).encode("utf-8"))
        assert size < 5120, f"Response is {size} bytes, exceeds 5KB"

    def test_library_stats_under_200_bytes(self):
        response = {
            "songs": 12345,
            "albums": 890,
            "artists": 456,
            "movies": 678,
            "series": 123,
            "episodes": 2345,
        }
        size = len(json.dumps(response).encode("utf-8"))
        assert size < 200, f"Stats response is {size} bytes, exceeds 200"
