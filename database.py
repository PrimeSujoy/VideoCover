# Don't Remove Credit Tg - @NexonBots
# Subscribe YouTube Channel For Amazing Bot https://youtube.com/@NexonBots
# Ask Doubt on telegram @NexonContactBot

"""
MongoDB Database Module for Video Cover Bot
Handles all database operations for user thumbnails
"""

import os
import logging
import time
from datetime import datetime
from pymongo import MongoClient

# Setup logging
logger = logging.getLogger(__name__)

# MongoDB Connection Setup
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "video_cover_bot")

try:
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = mongo_client[MONGODB_DATABASE]
    users_collection = db["users"]
    # Test connection
    mongo_client.server_info()
    logger.info("✅ MongoDB connected successfully")
    DB_AVAILABLE = True
except Exception as e:
    logger.warning(f"⚠️ MongoDB not available: {e}")
    logger.warning("⚠️ Bot will work with limited functionality (thumbnails won't persist)")
    DB_AVAILABLE = False
    users_collection = None


def register_user(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> dict:
    """Upsert a bot user without overwriting their existing bot data."""
    if not DB_AVAILABLE:
        logger.debug(f"Database not available, cannot register user {user_id}")
        return {"success": False, "is_new": False}

    try:
        now = datetime.now()
        result = users_collection.update_one(
            {"user_id": user_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "is_banned": False,
                    "joined_at": now,
                },
                "$set": {
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "last_active": now,
                },
            },
            upsert=True,
        )
        is_new = result.upserted_id is not None
        logger.info(
            "%s user %s",
            "Registered new" if is_new else "Updated existing",
            user_id,
        )
        return {"success": True, "is_new": is_new}
    except Exception as e:
        logger.error(f"❌ Error registering user {user_id}: {e}")
        return {"success": False, "is_new": False}


def save_thumbnail(user_id: int, photo_id: str) -> bool:
    """Save or update user's thumbnail to MongoDB"""
    if not DB_AVAILABLE:
        logger.debug(f"Database not available, skipping thumbnail save for user {user_id}")
        return False
    
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "photo_id": photo_id,
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )
        logger.info(f"✅ Thumbnail saved for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving thumbnail: {e}")
        return False


def get_thumbnail(user_id: int) -> str | None:
    """Retrieve user's thumbnail from MongoDB"""
    if not DB_AVAILABLE:
        logger.debug(f"Database not available, cannot get thumbnail for user {user_id}")
        return None
    
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        if user_record and "photo_id" in user_record:
            logger.info(f"✅ Retrieved thumbnail for user {user_id}")
            return user_record["photo_id"]
        logger.info(f"⚠️ No thumbnail found for user {user_id}")
        return None
    except Exception as e:
        logger.error(f"❌ Error retrieving thumbnail: {e}")
        return None


def delete_thumbnail(user_id: int) -> bool:
    """Delete user's thumbnail from MongoDB"""
    if not DB_AVAILABLE:
        logger.debug(f"Database not available, skipping thumbnail delete for user {user_id}")
        return False
    
    try:
        result = users_collection.update_one(
            {"user_id": user_id},
            {"$unset": {"photo_id": ""}}
        )
        if result.modified_count > 0:
            logger.info(f"✅ Thumbnail deleted for user {user_id}")
            return True
        logger.info(f"⚠️ No thumbnail to delete for user {user_id}")
        return False
    except Exception as e:
        logger.error(f"❌ Error deleting thumbnail: {e}")
        return False


def has_thumbnail(user_id: int) -> bool:
    """Check if user has a saved thumbnail"""
    if not DB_AVAILABLE:
        return False
    
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        has_thumb = user_record is not None and "photo_id" in user_record
        logger.debug(f"Thumbnail check for user {user_id}: {has_thumb}")
        return has_thumb
    except Exception as e:
        logger.error(f"❌ Error checking thumbnail: {e}")
        return False


"""═══════════════════ ADMIN FUNCTIONS ═══════════════════"""


def ban_user(user_id: int, reason: str = "No reason") -> bool:
    """Ban a user from using the bot"""
    if not DB_AVAILABLE:
        logger.debug(f"Database not available, skipping ban for user {user_id}")
        return False
    
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "is_banned": True,
                    "ban_reason": reason,
                    "banned_at": datetime.now()
                }
            },
            upsert=True
        )
        logger.info(f"🚫 User {user_id} banned. Reason: {reason}")
        return True
    except Exception as e:
        logger.error(f"❌ Error banning user {user_id}: {e}")
        return False


def unban_user(user_id: int) -> bool:
    """Unban a user"""
    if not DB_AVAILABLE:
        logger.debug(f"Database not available, skipping unban for user {user_id}")
        return False
    
    try:
        result = users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "is_banned": False,
                    "unbanned_at": datetime.now()
                }
            }
        )
        if result.modified_count > 0:
            logger.info(f"✅ User {user_id} unbanned")
            return True
        logger.info(f"⚠️ User {user_id} not found")
        return False
    except Exception as e:
        logger.error(f"❌ Error unbanning user {user_id}: {e}")
        return False


def is_user_banned(user_id: int) -> bool:
    """Check if user is banned"""
    if not DB_AVAILABLE:
        return False
    
    try:
        user_record = users_collection.find_one({"user_id": user_id})
        if user_record and user_record.get("is_banned", False):
            logger.debug(f"User {user_id} is banned")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Error checking ban status: {e}")
        return False


def get_total_users() -> int:
    """Get total number of users"""
    if not DB_AVAILABLE:
        return 0
    
    try:
        count = len(users_collection.distinct("user_id", {"user_id": {"$exists": True}}))
        logger.info(f"📊 Total users: {count}")
        return count
    except Exception as e:
        logger.error(f"❌ Error counting users: {e}")
        return 0


def get_banned_users_count() -> int:
    """Get total number of banned users"""
    if not DB_AVAILABLE:
        return 0
    
    try:
        count = users_collection.count_documents({"is_banned": True})
        logger.info(f"🚫 Total banned users: {count}")
        return count
    except Exception as e:
        logger.error(f"❌ Error counting banned users: {e}")
        return 0


def get_stats() -> dict:
    """Get bot statistics"""
    if not DB_AVAILABLE:
        return {
            "total_users": 0,
            "banned_users": 0,
            "users_with_thumbnail": 0
        }
    
    try:
        total = len(users_collection.distinct("user_id", {"user_id": {"$exists": True}}))
        banned = users_collection.count_documents({"is_banned": True})
        with_thumb = users_collection.count_documents({
            "user_id": {"$exists": True},
            "photo_id": {"$exists": True}
        })
        
        stats = {
            "total_users": total,
            "banned_users": banned,
            "users_with_thumbnail": with_thumb
        }
        logger.info(f"📊 Stats: {stats}")
        return stats
    except Exception as e:
        logger.error(f"❌ Error getting stats: {e}")
        return {
            "total_users": 0,
            "banned_users": 0,
            "users_with_thumbnail": 0
        }


def get_all_user_ids() -> list[int]:
    """Return unique registered Telegram user IDs for broadcasts."""
    if not DB_AVAILABLE:
        return []

    try:
        raw_user_ids = users_collection.distinct(
            "user_id", {"user_id": {"$exists": True}}
        )
        user_ids = []
        for user_id in raw_user_ids:
            try:
                normalized_id = int(user_id)
            except (TypeError, ValueError):
                logger.warning(f"Skipping invalid stored user ID: {user_id!r}")
                continue
            if normalized_id not in user_ids:
                user_ids.append(normalized_id)
        return user_ids
    except Exception as e:
        logger.error(f"❌ Error getting broadcast recipients: {e}")
        return []


def get_database_health() -> dict:
    """Return MongoDB availability and ping latency for the status command."""
    if not DB_AVAILABLE:
        return {"connected": False, "latency_ms": None}

    started_at = time.perf_counter()
    try:
        mongo_client.admin.command("ping")
        latency_ms = (time.perf_counter() - started_at) * 1000
        return {"connected": True, "latency_ms": latency_ms}
    except Exception as e:
        logger.warning(f"MongoDB health check failed: {e}")
        return {"connected": False, "latency_ms": None}


"""═══════════════════ LOGGING FUNCTIONS ═══════════════════"""


def create_log_entry(user_id: int, username: str, action: str, details: str = "") -> dict:
    """Create a formatted log entry"""
    from datetime import datetime
    
    log_entry = {
        "user_id": user_id,
        "username": f"@{username}" if username else "Unknown",
        "action": action,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }
    return log_entry


def format_log_message(user_id: int, username: str, action: str, details: str = "") -> str:
    """Format log message for Telegram channel"""
    from datetime import datetime
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username_str = f"@{username}" if username else "Unknown"
    
    log_msg = (
        f"📝 <b>{action}</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"📌 Username: {username_str}\n"
        f"⏰ Time: {now}\n"
    )
    
    if details:
        log_msg += f"📋 Details: {details}\n"
    
    return log_msg


def log_new_user(user_id: int, username: str, first_name: str) -> dict:
    """Build the only Telegram log event: a newly registered user."""
    action = "🆕 New User Registered"
    details = f"Name: {first_name}"
    logger.info(f"✅ {action} - {username} ({user_id})")
    return create_log_entry(user_id, username, action, details)


"""═══════════════════ CHANNEL FUNCTIONS (MULTI-CHANNEL) ═══════════════════"""


def _normalize_channel_id(channel_id) -> str | None:
    """Return one canonical string representation for Telegram channel IDs."""
    if channel_id is None:
        return None
    normalized = str(channel_id).strip()
    return normalized or None


def _normalized_channels(user_record: dict | None) -> list[str]:
    """Merge current and legacy channel fields into a unique string list."""
    if not user_record:
        return []

    raw_channels = user_record.get("channels", [])
    if not isinstance(raw_channels, list):
        raw_channels = [raw_channels]

    # Preserve a legacy single channel until the record is migrated.
    if user_record.get("channel_id") is not None:
        raw_channels.append(user_record["channel_id"])

    channels = []
    for raw_channel_id in raw_channels:
        channel_id = _normalize_channel_id(raw_channel_id)
        if channel_id and channel_id not in channels:
            channels.append(channel_id)
    return channels


def add_user_channel(user_id: int, channel_id: str) -> bool:
    """Add a channel to the user's MongoDB channel list."""
    if not DB_AVAILABLE:
        return False

    channel_id = _normalize_channel_id(channel_id)
    if not channel_id:
        return False

    try:
        user_record = users_collection.find_one({"user_id": user_id})
        channels = _normalized_channels(user_record)

        if channel_id in channels:
            return False  # Already exists

        channels.append(channel_id)
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "channels": channels,
                    "channels_updated_at": datetime.now()
                },
                "$unset": {"channel_id": ""}
            },
            upsert=True
        )
        logger.info(f"✅ Channel added for user {user_id}: {channel_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error adding channel for user {user_id}: {e}")
        return False


def remove_user_channel(user_id: int, channel_id: str) -> bool:
    """Remove a channel from both current and legacy MongoDB fields."""
    if not DB_AVAILABLE:
        return False

    channel_id = _normalize_channel_id(channel_id)
    if not channel_id:
        return False

    try:
        user_record = users_collection.find_one({"user_id": user_id})
        channels = _normalized_channels(user_record)

        if channel_id not in channels:
            return False

        channels = [saved_id for saved_id in channels if saved_id != channel_id]
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "channels": channels,
                    "channels_updated_at": datetime.now()
                },
                "$unset": {"channel_id": ""}
            }
        )
        logger.info(f"✅ Channel removed for user {user_id}: {channel_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error removing channel for user {user_id}: {e}")
        return False


def get_user_channels(user_id: int) -> list:
    """Get a user's channels and migrate legacy/mixed values to strings."""
    if not DB_AVAILABLE:
        return []

    try:
        user_record = users_collection.find_one({"user_id": user_id})
        channels = _normalized_channels(user_record)

        if user_record:
            stored_channels = user_record.get("channels", [])
            needs_migration = (
                "channel_id" in user_record
                or not isinstance(stored_channels, list)
                or stored_channels != channels
            )
            if needs_migration:
                users_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "channels": channels,
                            "channels_updated_at": datetime.now()
                        },
                        "$unset": {"channel_id": ""}
                    }
                )
                logger.info(f"✅ Migrated channel storage for user {user_id}")

        return channels
    except Exception as e:
        logger.error(f"❌ Error getting channels for user {user_id}: {e}")
        return []


def get_user_by_channel(channel_id: str) -> int | None:
    """Find which user owns a channel"""
    if not DB_AVAILABLE:
        return None

    channel_id = _normalize_channel_id(channel_id)
    if not channel_id:
        return None

    try:
        candidates = [channel_id]
        try:
            candidates.append(int(channel_id))
        except ValueError:
            pass

        user_record = users_collection.find_one({
            "$or": [
                {"channels": {"$in": candidates}},
                {"channel_id": {"$in": candidates}}
            ]
        })
        if user_record:
            return user_record["user_id"]
        return None
    except Exception as e:
        logger.error(f"❌ Error finding user for channel {channel_id}: {e}")
        return None


# Legacy functions for backward compatibility
def save_user_channel(user_id: int, channel_id: str) -> bool:
    return add_user_channel(user_id, channel_id)

def get_user_channel(user_id: int) -> str | None:
    channels = get_user_channels(user_id)
    return channels[0] if channels else None

def delete_user_channel(user_id: int) -> bool:
    if not DB_AVAILABLE:
        return False
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {"$unset": {"channels": "", "channel_id": ""}}
        )
        return True
    except:
        return False
