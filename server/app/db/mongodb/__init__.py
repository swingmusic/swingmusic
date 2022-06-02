"""
This module creates and initiliazes a MongoDB instance. It also contains the
`convert_one()` and `conver_many()` methods for converting MongoDB cursors to Python dicts.
"""


import json
import pymongo
from bson import json_util

from app.db import AlbumMethods


class Mongo:
    """
    The base class for all mongodb classes.
    """

    def __init__(self, database):
        mongo_uri = pymongo.MongoClient()
        self.db = mongo_uri[database]


class MongoAlbums(Mongo, AlbumMethods):
    def __init__(self):
        super(MongoAlbums, self).__init__("ALICE_ALBUMS")
        self.collection = self.db["ALL_ALBUMS"]


# ====================================================================== #
# cursor convertion methods


def convert_one(song):
    """
    Converts a single mongodb cursor to a json object.
    """
    json_song = json.dumps(song, default=json_util.default)
    loaded_song = json.loads(json_song)

    return loaded_song


def convert_many(array):
    """
    Converts a list of mongodb cursors to a list of json objects.
    """

    songs = []

    for song in array:
        json_song = json.dumps(song, default=json_util.default)
        loaded_song = json.loads(json_song)

        songs.append(loaded_song)

    return songs
