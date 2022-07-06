"""
This library contains all the functions related to the search functionality.
"""
from typing import List

from app import api
from app import helpers
from app import models
from app.lib import albumslib
from rapidfuzz import fuzz
from rapidfuzz import process

ratio = fuzz.ratio
wratio = fuzz.WRatio


class Cutoff:
    """
    Holds all the default cutoff values.
    """

    tracks: int = 80
    albums: int = 80
    artists: int = 80
    playlists: int = 80


class Limit:
    """
    Holds all the default limit values.
    """

    tracks: int = 50
    albums: int = 50
    artists: int = 50
    playlists: int = 50


class SearchTracks:
    def __init__(self, tracks: List[models.Track], query: str) -> None:
        self.query = query
        self.tracks = tracks

    def __call__(self) -> List[models.Track]:
        """
        Gets all songs with a given title.
        """

        tracks = [track.title for track in self.tracks]
        results = process.extract(
            self.query,
            tracks,
            scorer=fuzz.WRatio,
            score_cutoff=Cutoff.tracks,
            limit=Limit.tracks,
        )

        return [self.tracks[i[2]] for i in results]


class SearchArtists:
    def __init__(self, artists: set[str], query: str) -> None:
        self.query = query
        self.artists = artists

    def __call__(self) -> list:
        """
        Gets all artists with a given name.
        """

        results = process.extract(
            self.query,
            self.artists,
            scorer=fuzz.WRatio,
            score_cutoff=Cutoff.artists,
            limit=Limit.artists,
        )

        f_artists = []
        for artist in results:
            aa = {
                "name": artist[0],
                "image": helpers.create_safe_name(artist[0]) + ".webp",
            }
            f_artists.append(aa)

        return f_artists


class SearchAlbums:
    def __init__(self, albums: List[models.Album], query: str) -> None:
        self.query = query
        self.albums = albums

    def __call__(self) -> List[models.Album]:
        """
        Gets all albums with a given title.
        """

        albums = [a.title.lower() for a in self.albums]

        results = process.extract(
            self.query,
            albums,
            scorer=fuzz.WRatio,
            score_cutoff=Cutoff.albums,
            limit=Limit.albums,
        )

        return [self.albums[i[2]] for i in results]

        # get all artists that matched the query
        # for get all albums from the artists
        # get all albums that matched the query
        # return [**artist_albums **albums]

        # recheck next and previous artist on play next or add to playlist


class SearchPlaylists:
    def __init__(self, playlists: List[models.Playlist], query: str) -> None:
        self.playlists = playlists
        self.query = query

    def __call__(self) -> List[models.Playlist]:
        playlists = [p.name for p in self.playlists]
        results = process.extract(
            self.query,
            playlists,
            scorer=fuzz.WRatio,
            score_cutoff=Cutoff.playlists,
            limit=Limit.playlists,
        )

        return [self.playlists[i[2]] for i in results]
