"""HW6 Part 1 - PyMongo database connection.

One MongoClient is shared by the whole app (PyMongo keeps its own
connection pool). init_collection() also installs a MongoDB-side
$jsonSchema validator, so bad documents are refused by the database
itself, not only by Pydantic.
"""
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import CollectionInvalid

from .config import (MONGO_URI, MONGO_DB_NAME, NOTICES_COLLECTION,
                     MESSAGES_COLLECTION, SUMMARIES_COLLECTION, EPISODES_COLLECTION)
from .schemas import STATUS_VALUES, CATEGORY_VALUES

_client = None

# Database-level rules (mirror the Pydantic schema in schemas.py).
NOTICE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["product", "status", "category", "recall_date",
                     "createdAt", "updatedAt"],
        "properties": {
            "product": {"bsonType": "string", "minLength": 1, "maxLength": 100,
                        "description": "required short text, max 100 chars"},
            "description": {"bsonType": ["string", "null"],
                            "description": "optional longer description"},
            "status": {"enum": STATUS_VALUES,
                       "description": "recall status, default 'announced'"},
            "category": {"enum": CATEGORY_VALUES,
                         "description": "fixed set of recall categories"},
            "recall_date": {"bsonType": "date",
                            "description": "required date the recall was issued"},
            "createdAt": {"bsonType": "date"},
            "updatedAt": {"bsonType": "date"},
        },
    }
}


def get_client() -> MongoClient:
    global _client
    if _client is None:
        # Short timeout so a stopped MongoDB fails fast with a clear error.
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    return _client


def get_db():
    return get_client()[MONGO_DB_NAME]


def get_notices_collection():
    return get_db()[NOTICES_COLLECTION]


def _create_or_update(name, validator):
    db = get_db()
    try:
        db.create_collection(name, validator=validator)
    except CollectionInvalid:
        db.command("collMod", name, validator=validator)


def init_collection():
    """Create the collection with its validator (or update the validator
    if the collection already exists). Safe to call on every startup."""
    _create_or_update(NOTICES_COLLECTION, NOTICE_VALIDATOR)


# --- HW6 Part 2: chat memory collections ----------------------------------
MESSAGES_VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["user_id", "session_id", "role", "content", "created_at"],
    "properties": {
        "user_id": {"bsonType": "string", "minLength": 1},
        "session_id": {"bsonType": "string", "minLength": 1},
        "role": {"enum": ["user", "assistant"]},
        "content": {"bsonType": "string"},
        "created_at": {"bsonType": "date"},
    },
}}

SUMMARIES_VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["user_id", "session_id", "scope", "text", "created_at"],
    "properties": {
        "user_id": {"bsonType": "string", "minLength": 1},
        # null for the lifetime (scope='user') summary
        "session_id": {"bsonType": ["string", "null"]},
        "scope": {"enum": ["session", "user"]},
        "text": {"bsonType": "string"},
        "created_at": {"bsonType": "date"},
    },
}}

EPISODES_VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["user_id", "session_id", "fact", "importance", "embedding", "created_at"],
    "properties": {
        "user_id": {"bsonType": "string", "minLength": 1},
        "session_id": {"bsonType": "string"},
        "fact": {"bsonType": "string", "minLength": 1, "maxLength": 200},
        "importance": {"bsonType": ["double", "int"], "minimum": 0, "maximum": 1},
        "embedding": {"bsonType": "array", "items": {"bsonType": "double"}},
        "created_at": {"bsonType": "date"},
    },
}}


def get_messages_collection():
    return get_db()[MESSAGES_COLLECTION]


def get_summaries_collection():
    return get_db()[SUMMARIES_COLLECTION]


def get_episodes_collection():
    return get_db()[EPISODES_COLLECTION]


def init_memory_collections():
    """Create messages / summaries / episodes with validators and the
    indexes the memory queries use. Leaves recall_notices untouched."""
    _create_or_update(MESSAGES_COLLECTION, MESSAGES_VALIDATOR)
    _create_or_update(SUMMARIES_COLLECTION, SUMMARIES_VALIDATOR)
    _create_or_update(EPISODES_COLLECTION, EPISODES_VALIDATOR)
    get_messages_collection().create_index(
        [("user_id", ASCENDING), ("session_id", ASCENDING), ("created_at", ASCENDING)])
    get_summaries_collection().create_index(
        [("user_id", ASCENDING), ("scope", ASCENDING), ("created_at", DESCENDING)])
    get_episodes_collection().create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)])
