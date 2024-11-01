import datetime
import json
import random
import string
import time
import requests
from urllib.parse import quote
from PIL import Image

from app.db.userdata import SimilarArtistTable
from app.lib.colorlib import get_image_colors
from app.models.artist import Artist
from app.models.mix import Mix
from app.models.track import Track
from app.plugins import Plugin, plugin_method
from app.settings import Paths
from app.store.albums import AlbumStore
from app.store.artists import ArtistStore
from app.store.tracks import TrackStore
from app.utils.dates import get_date_range, get_duration_ago
from app.utils.mixes import balance_mix
from app.utils.remove_duplicates import remove_duplicates
from app.utils.stats import get_artists_in_period


class MixesPlugin(Plugin):
    MAX_TRACKS_TO_FETCH = 5
    TRACK_MIX_LENGTH = 50
    MIN_TRACK_MIX_LENGTH = 15

    MIN_DAY_LISTEN_DURATION = 3 * 60  # 3 minutes
    MIN_WEEK_LISTEN_DURATION = 10 * 60  # 10 minutes
    MIN_MONTH_LISTEN_DURATION = 20 * 60  # 20 minutes

    def __init__(self):
        super().__init__("mixes", "Mixes")
        self.server = "https://smcloud.mungaist.com"

        server_online = self.ping_server()
        self.set_active(server_online)

    def ping_server(self):
        try:
            requests.get(self.server, timeout=10)
        except requests.exceptions.ConnectionError:
            print("Failed to connect to the recommendation server")
            return False

        return True

    @plugin_method
    def get_track_mix(self, tracks: list[Track], with_help: bool = False):
        """
        Given a list of tracks, creates a mix by fetching data from the
        Swing Music Cloud recommendation server.

        The server returns a list of weak trackhashes. We use these to fetch
        the matching track data from our library database. Found tracks are
        then balanced and returned as the final mix tracklist.

        :param with_help: Whether to include the help flag in the query.
            The flag tells the server to find more data using other tracks from the same album.


        """
        queries = [
            {
                "query": f"{track.title} - {','.join(a['name'] for a in track.artists)}",
                "album": track.og_album,
                "with_help": with_help,
            }
            for track in tracks
        ]

        try:
            response = requests.post(f"{self.server}/radio", json=queries, timeout=10)
        except requests.exceptions.ConnectionError:
            print("Failed to connect to recommendation server")
            return []

        try:
            results = response.json()
        except json.JSONDecodeError:
            print("Failed to decode JSON response from recommendation server")
            return []

        # artisthashes = results["artists"]
        # albumhashes = results["albums"]
        trackhashes: list[str] = results["tracks"]

        trackmatches = TrackStore.get_flat_list()
        trackmatches = [t for t in trackmatches if t.weakhash in trackhashes]

        # filter out duplicates of the same weakhash
        # group by weakhash and pick the one with the highest bitrate
        grouped: dict[str, list[Track]] = {}
        for track in trackmatches:
            grouped.setdefault(track.weakhash, []).append(track)

        trackmatches = [
            max(group, key=lambda x: x.bitrate) for group in grouped.values()
        ]

        # sort by trackhash order
        trackmatches = sorted(trackmatches, key=lambda x: trackhashes.index(x.weakhash))

        if len(trackmatches) < self.TRACK_MIX_LENGTH:
            filler_tracks = self.fallback_create_artist_mix(
                artist=tracks[0].artists[0],
                similar_artists=results["artists"],
                similar_albums=results["albums"],
                omit_trackhashes={t.weakhash for t in trackmatches},
                limit=self.TRACK_MIX_LENGTH - len(trackmatches),
            )
            trackmatches.extend(filler_tracks)

        # try to balance the mix
        trackmatches = balance_mix(trackmatches)
        return trackmatches

    @plugin_method
    def get_artist_mix(self, artisthash: str):
        """
        Given an artisthash, creates an artist mix using the
        self.MAX_TRACKS_TO_FETCH most listened to tracks.
        """
        artist = ArtistStore.artistmap[artisthash]
        tracks = TrackStore.get_tracks_by_trackhashes(artist.trackhashes)

        tracks = sorted(tracks, key=lambda x: x.playduration, reverse=True)
        return self.get_track_mix(tracks[: self.MAX_TRACKS_TO_FETCH])

    @plugin_method
    def create_artist_mixes(self):
        mixes: list[Mix] = []
        indexed = set()

        today_start, today_end = get_date_range(duration="day")
        last_2_days_start = get_duration_ago("day", 2)
        last_7_days_start = get_duration_ago("week")
        last_1_month_start = get_duration_ago("month")

        artists = {
            "today": {
                "max": 3,
                "artists": get_artists_in_period(today_start, today_end),
                "created": 0,
            },
            "last_2_days": {
                "max": 2,
                "artists": get_artists_in_period(last_2_days_start, time.time()),
                "created": 0,
            },
            "last_7_days": {
                "max": 3,
                "artists": get_artists_in_period(last_7_days_start, time.time()),
                "created": 0,
            },
            "last_1_month": {
                "max": 2,
                "artists": get_artists_in_period(last_1_month_start, time.time()),
                "created": 0,
            },
        }

        for i, period in enumerate(artists.values()):
            # if previous period has less than its max
            # add the difference to this period's limit
            limit = period["max"]

            if i > 0:
                previous_period = artists[list(artists.keys())[i - 1]]
                if previous_period["created"] < previous_period["max"]:
                    limit += previous_period["max"] - previous_period["created"]

            for artist in period["artists"]:
                if period["created"] >= limit:
                    break

                if artist["artisthash"] in indexed:
                    continue

                mix = self.create_artist_mix(artist)

                if mix:
                    mixes.append(mix)
                    indexed.add(artist["artisthash"])
                    period["created"] += 1

        print(f"⭐⭐⭐⭐ Created {len(mixes)} mixes")
        return mixes

    def get_mix_description(self, tracks: list[Track], artishash: str):
        """
        Constructs a description for a mix by putting together the first n=4
        artists in the mix tracklist.
        """
        first_4_artists = []
        indexed = set()

        for track in tracks:
            if len(first_4_artists) < 4:
                if (
                    track.artists[0]["artisthash"] != artishash
                    and track.artists[0]["artisthash"] not in indexed
                ):
                    first_4_artists.append(track.artists[0])
                    indexed.add(track.artists[0]["artisthash"])

        if len(first_4_artists) == 4:
            return f"Featuring {', '.join(a['name'] for a in first_4_artists)} and more"

        if len(first_4_artists) > 0:
            return f"Featuring {', '.join(a['name'] for a in first_4_artists)}"

        return f"Featuring {tracks[0].artists[0]['name']}"

    def create_artist_mix(self, artist: dict[str, str]):
        """
        Given an artist dict, creates an artist mix.
        """
        _artist = ArtistStore.get_artist_by_hash(artist["artisthash"])

        if not _artist:
            return None

        mix_tracks = self.get_artist_mix(artist["artisthash"])

        if len(mix_tracks) < self.MIN_TRACK_MIX_LENGTH:
            return None

        # try downloading artist image
        mix_image = {"image": _artist.image, "color": _artist.color}
        downloaded_img_color = self.download_artist_image(_artist)

        if downloaded_img_color:
            mix_image["image"] = f"{_artist.artisthash}.jpg"
            mix_image["color"] = downloaded_img_color[0]

        return Mix(
            # the a prefix indicates that this is an artist mix
            id=f"a{artist['artisthash']}",
            title=artist["artist"] + " Radio",
            description=self.get_mix_description(mix_tracks, artist["artisthash"]),
            tracks=[t.trackhash for t in mix_tracks],
            extra={
                "type": "artist",
                "artisthash": artist["artisthash"],
                "image": mix_image,
            },
        )

    def download_artist_image(self, artist: Artist):
        try:
            res = requests.get(f"{self.server}/image?artist={artist.name}")
        except requests.exceptions.ConnectionError:
            return None

        if res.status_code == 200:
            # save to file
            with open(
                f"{Paths.get_md_mixes_img_path()}/{artist.artisthash}.jpg", "wb"
            ) as f:
                f.write(res.content)

            # resize to 256px width while maintaining aspect ratio
            img = Image.open(f"{Paths.get_md_mixes_img_path()}/{artist.artisthash}.jpg")
            aspect_ratio = img.width / img.height

            newwidth = 256
            newheight = int(256 / aspect_ratio)

            img = img.resize((newwidth, newheight), Image.LANCZOS)
            img.save(f"{Paths.get_sm_mixes_img_path()}/{artist.artisthash}.jpg")

            return get_image_colors(
                f"{Paths.get_sm_mixes_img_path()}/{artist.artisthash}.jpg"
            )

        return None

    def fallback_create_artist_mix(
        self,
        artist: dict[str, str],
        similar_albums: list[str],
        similar_artists: list[str],
        omit_trackhashes: set[str],
        limit: int,
    ):
        """
        Creates an artist mix by selecting random tracks from similar artists.

        This is used when:
        - The Swing Music recommendation server is down.
        - The artist has less than self.MIN_TRACK_MIX_LENGTH tracks from the cloud mix.
        - When we need to dilute the mix to balance the artist distribution.

        :param artist: The artist to create a mix for.
        :param similar_artists: A list of similar artists to select tracks from. If not provided, we try reading from the local database. When we exhaust the passed list, we also try reading from the local database.
        :param trackhashes: A set of trackhashes to omit from the new tracklist.
        :param limit: The maximum number of tracks to select.
        """

        mixtracks = []
        albummatches = (
            a
            for a in AlbumStore.albummap.values()
            if a.album.weakhash in similar_albums
        )

        for match in albummatches:
            if len(mixtracks) >= limit:
                print(f"Filled up to {limit} tracks with album tracks")
                return mixtracks

            albumtracks = [
                t
                for t in TrackStore.get_tracks_by_trackhashes(match.trackhashes)
                if t.weakhash not in omit_trackhashes
            ]

            if len(albumtracks) == 0:
                continue

            sample = random.sample(albumtracks, k=1)
            mixtracks.extend(sample)
            print(
                f"Supplement: album track {sample[0].title} from ALBUM: {match.album.og_title}"
            )

        artistmatches = (
            a
            for a in ArtistStore.artistmap.values()
            if a.artist.artisthash in similar_artists
        )

        for match in artistmatches:
            if len(mixtracks) >= limit:
                print(f"Filled up to {limit} tracks with artist tracks")
                return mixtracks

            artisttracks = [
                t
                for t in TrackStore.get_tracks_by_trackhashes(match.trackhashes)
                if t.weakhash not in omit_trackhashes
            ]

            if len(artisttracks) == 0:
                continue

            sample = random.sample(artisttracks, k=1)
            mixtracks.extend(sample)
            print(
                f"Supplement: track {sample[0].title} from ARTIST: {match.artist.name}"
            )

        return mixtracks

        # if len(similar_artists) == 0:
        #     local_similar_artists = SimilarArtistTable.get_by_hash(artist["artisthash"])

        #     if local_similar_artists:
        #         artists = [a.artisthash for a in local_similar_artists.similar_artists]

        # if len(artists) == 0:
        #     return []

        # CHECKPOINT: I'M TIRED AF AND I NEED TO SLEEP
        # The plan:
        # Figure out which artists we should skip for the new tracklist
        # these would be artists with a large number of tracks in the mix already

        # Since the artisthashes are ordered by similarity score, we iterate from the start
        # and go forward collecting tracks that aren't in the mix yet.
        #
