# Don't Remove Credit Tg - @NexonBots
# Subscribe YouTube Channel For Amazing Bot https://youtube.com/@NexonBots
# Ask Doubt on telegram @NexonContactBot

import os
import logging
import asyncio
import time
from html import escape
from io import BytesIO
from urllib.request import Request, urlopen
from collections import defaultdict
from telegram import InputMediaVideo, Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from config import config
import sys
from telegram.error import BadRequest, RetryAfter
import random
from health_server import start_health_server
from database import (
    register_user, save_thumbnail, get_thumbnail, delete_thumbnail, has_thumbnail,
    ban_user, unban_user, is_user_banned, get_total_users, get_banned_users_count, get_stats,
    get_all_user_ids, get_database_health,
    format_log_message, log_new_user,
    add_user_channel, remove_user_channel, get_user_channels, get_user_by_channel
)
from telegram import MessageEntity


"""═══════════════════ RATE LIMITER (30 MSG/SEC + SEQUENTIAL) ═══════════════════"""


class RateLimiter:
    """Global rate limiter - 30 messages per second with queue"""
    
    def __init__(self, max_per_second=30):
        self.max_per_second = max_per_second
        self.queue = asyncio.Queue()
        self.processing = False
        self.lock = asyncio.Lock()
        self.send_times = []
        self.min_interval = 1.0 / max_per_second  # Min time between sends
    
    async def add(self, func, *args, **kwargs):
        """Add a message to the queue"""
        event = asyncio.Event()
        await self.queue.put((func, args, kwargs, event))
        if not self.processing:
            asyncio.create_task(self._process_queue())
        await event.wait()  # Wait until actually sent
    
    async def _process_queue(self):
        """Process queue with 30/sec rate limit"""
        async with self.lock:
            self.processing = True
        
        while True:
            # Clean old timestamps (older than 1 sec)
            now = time.time()
            self.send_times = [t for t in self.send_times if now - t < 1.0]
            
            # If at limit (30/sec), wait
            if len(self.send_times) >= self.max_per_second:
                wait_time = 1.0 - (now - self.send_times[0])
                if wait_time > 0:
                    logger.info(f"⏳ Rate limit: waiting {wait_time:.2f}s (30/sec)")
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    self.send_times = [t for t in self.send_times if now - t < 1.0]
            
            # Check queue
            if self.queue.empty():
                break
            
            func, args, kwargs, event = await self.queue.get()
            try:
                await func(*args, **kwargs)
                self.send_times.append(time.time())
                logger.debug(f"✅ Sent via rate limiter ({len(self.send_times)}/sec)")
            except Exception as e:
                logger.error(f"Rate limiter error: {e}")
            finally:
                event.set()
            await asyncio.sleep(self.min_interval)
        
        async with self.lock:
            self.processing = False


class VideoDMQueue:
    """Per-user sequential video DM queue - videos come in order"""
    
    def __init__(self):
        self.queues = defaultdict(asyncio.Queue)
        self.processing = defaultdict(bool)
        self.locks = defaultdict(asyncio.Lock)
    
    async def add(self, user_id, func, *args, **kwargs):
        """Add video processing to user's queue"""
        event = asyncio.Event()
        await self.queues[user_id].put((func, args, kwargs, event))
        
        # Start processing only if not already running (uses lock to prevent race)
        async with self.locks[user_id]:
            if not self.processing[user_id]:
                asyncio.create_task(self._process_user(user_id))
        
        await event.wait()  # Wait until this video is done
    
    async def _process_user(self, user_id):
        """Process videos for one user sequentially - 1 per second per chat"""
        async with self.locks[user_id]:
            self.processing[user_id] = True
        
        while True:
            if self.queues[user_id].empty():
                break
            
            func, args, kwargs, event = await self.queues[user_id].get()
            try:
                await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Video queue error for user {user_id}: {e}")
            finally:
                event.set()
            # 1 msg/sec per chat (Telegram FAQ limit)
            await asyncio.sleep(1)
        
        async with self.locks[user_id]:
            self.processing[user_id] = False


# Global instances
rate_limiter = RateLimiter(max_per_second=30)
video_dm_queue = VideoDMQueue()


async def safe_send_message(context, chat_id, text, reply_markup=None, parse_mode="HTML"):
    """Send message through rate limiter"""
    await rate_limiter.add(
        context.bot.send_message,
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )


async def safe_send_photo(context, chat_id, photo, caption, reply_markup=None, parse_mode="HTML"):
    """Send photo through rate limiter"""
    await rate_limiter.add(
        context.bot.send_photo,
        chat_id=chat_id,
        photo=photo,
        caption=caption,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )

def bold_entities(text: str):
    """Return entities list to make full caption bold"""
    if not text:
        return None
    return [MessageEntity(type="bold", offset=0, length=len(text))]

# Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
# Avoid exposing the Telegram bot token in HTTP request URLs written by httpx.
logging.getLogger("httpx").setLevel(logging.WARNING)
BOT_STARTED_AT = time.time()
speedtest_lock = asyncio.Lock()

# Token from config or environment
TOKEN = getattr(config, "BOT_TOKEN", None) or os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN not set in config or environment (config.env).")
    raise SystemExit("BOT_TOKEN not set")

# Auto-detect bot username from token
BOT_USERNAME = None

def parse_owner_ids() -> tuple[int, ...]:
    """Parse space-separated owner IDs from OWNER_ID and OWNER_IDS."""
    raw_owner_ids = " ".join(
        value
        for value in (
            os.environ.get("OWNER_ID", ""),
            os.environ.get("OWNER_IDS", ""),
        )
        if value
    )
    parsed_owner_ids = []
    for raw_id in raw_owner_ids.replace(",", " ").split():
        try:
            owner_id = int(raw_id)
        except ValueError:
            logger.warning("Ignoring an invalid owner ID in configuration")
            continue
        if owner_id > 0 and owner_id not in parsed_owner_ids:
            parsed_owner_ids.append(owner_id)
    return tuple(parsed_owner_ids)


OWNER_ID_LIST = parse_owner_ids()
OWNER_IDS = frozenset(OWNER_ID_LIST)
# Primary owner is retained for links and other single-owner fallbacks.
OWNER_ID = OWNER_ID_LIST[0] if OWNER_ID_LIST else 0


def parse_force_sub_channels(raw_channels: str | None) -> tuple[int | str, ...]:
    """Parse space-separated numeric channel IDs or public usernames."""
    channels = []
    for raw_channel in (raw_channels or "").replace(",", " ").split():
        channel = raw_channel.strip()
        if not channel:
            continue
        try:
            parsed_channel = int(channel)
        except ValueError:
            parsed_channel = channel if channel.startswith("@") else f"@{channel}"
        if parsed_channel not in channels:
            channels.append(parsed_channel)
    return tuple(channels)


FORCE_SUB_CHANNEL_ID = os.environ.get("FORCE_SUB_CHANNEL_ID")
FORCE_SUB_CHANNEL_IDS = parse_force_sub_channels(FORCE_SUB_CHANNEL_ID)
FORCE_SUB_BANNER_URL = os.environ.get("FORCE_SUB_BANNER_URL")
HOME_MENU_BANNER_URL = os.environ.get("HOME_MENU_BANNER_URL")
OWNER_USERNAME = "NexonContactBot"
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")

# Fallback: collect images from ./ui/ and pick randomly when showing banner
FALLBACK_BANNER = None
UI_BANNERS = []
try:
    ui_dir = os.path.join(os.path.dirname(__file__), "ui")
    if os.path.isdir(ui_dir):
        UI_BANNERS = [os.path.join(ui_dir, f) for f in os.listdir(ui_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        if UI_BANNERS:
            FALLBACK_BANNER = UI_BANNERS[0]
except Exception:
    UI_BANNERS = []
    FALLBACK_BANNER = None

# Final banner env value (may be URL) or local fallback
FORCE_SUB_BANNER = FORCE_SUB_BANNER_URL or FALLBACK_BANNER

def get_force_banner():
    """Return a banner URL or local file path. Prefer env URL; else pick random local image."""
    if FORCE_SUB_BANNER_URL:
        return FORCE_SUB_BANNER_URL
    try:
        if UI_BANNERS:
            return random.choice(UI_BANNERS)
    except Exception:
        pass
    return FALLBACK_BANNER


# In-memory set of users who completed the verify step
verified_users = set()
# TTL cache for force-sub membership checks (user_id -> expiry_timestamp)
_force_sub_cache = {}

"""═════════════════ LOGGING HELPER ═════════════════"""
async def send_log(context: ContextTypes.DEFAULT_TYPE, log_message: str) -> bool:
    """Send a new-user registration log when a log channel is configured."""
    if not LOG_CHANNEL_ID:
        logger.debug("LOG_CHANNEL_ID not configured")
        return False
    
    try:
        await rate_limiter.add(
            context.bot.send_message,
            chat_id=LOG_CHANNEL_ID,
            text=log_message,
            parse_mode="HTML"
        )
        logger.debug(f"✅ Log queued for channel {LOG_CHANNEL_ID}")
        return True
    except Exception as e:
        logger.error(f"❌ Error queuing log: {e}")
        return False


async def register_verified_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Register a verified user and log only their first registration."""
    user = update.effective_user
    registration = register_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    if registration["is_new"]:
        username = user.username or "Unknown"
        first_name = user.first_name or "User"
        log_data = log_new_user(user.id, username, first_name)
        log_msg = format_log_message(
            user.id,
            username,
            log_data["action"],
            log_data.get("details", ""),
        )
        await send_log(context, log_msg)

    return registration


"""--------------------HELPER FUNCTIONS--------------------"""
async def send_or_edit(update: Update, text, reply_markup=None, force_banner=None):
    if update.callback_query:
        try:
            # If original message contains a photo, edit the caption instead
            msg = update.callback_query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            else:
                await msg.edit_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
        except BadRequest:
            pass
    else:
        if force_banner:
            # Support local file paths in addition to URLs
            try:
                if isinstance(force_banner, str) and os.path.isfile(force_banner):
                    photo = InputFile(force_banner)
                else:
                    photo = force_banner
            except Exception:
                photo = force_banner

            await update.message.reply_photo(
                photo=photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )


async def get_invite_link(bot, chat_id):
    """Create or return a chat invite link with rate-limit retry handling."""
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
        # Different objects may expose either 'invite_link' attribute or be a string
        return getattr(link_obj, "invite_link", link_obj)
    except RetryAfter as e:
        # python-telegram-bot RetryAfter provides `retry_after` in seconds
        secs = getattr(e, "retry_after", None) or 30
        logger.info(f"Rate limited while creating invite link: sleeping {secs}s")
        await asyncio.sleep(secs)
        return await get_invite_link(bot, chat_id)
    except Exception as e:
        logger.error(f"get_invite_link failed: {e}")
        return None

"""--------------------ADMIN CHECK-----------------"""

# Fancy text function removed - all text is now pre-converted to fancy font style

def is_admin(user_id: int) -> bool:
    """Check if user is bot owner or admin"""
    return user_id in OWNER_IDS


async def check_admin(update: Update) -> bool:
    """Check if user is admin and send error if not"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ")
        return False
    return True


async def check_admin_and_banned(update: Update, user_id_to_check: int = None) -> tuple[bool, str]:
    """Check if admin and if target user is banned"""
    admin = await check_admin(update)
    if not admin:
        return False, None
    
    if user_id_to_check and is_user_banned(user_id_to_check):
        return True, "banned"  # User is admin and target is banned
    return True, None


"""------------------FORCE-SUB CHECK-----------------"""

async def _legacy_check_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check if user has verified through force-sub AND is still a member.
    Verifies membership for cached users to ensure they haven't left the channel.
    """
    user_id = update.effective_user.id

    # Owner bypass
    if is_admin(user_id):
        return True

    # If no force-sub configured, allow access
    if not FORCE_SUB_CHANNEL_ID:
        return True

    # If user already verified through verify button, verify they're still a member
    if user_id in verified_users:
        # Check TTL cache first (5 min cache)
        now = time.time()
        if user_id in _force_sub_cache and _force_sub_cache[user_id] > now:
            logger.debug(f"🔍 User {user_id} verified from cache")
            return True
        
        logger.info(f"🔍 User {user_id} is cached - checking membership...")
        
        try:
            channel_id_str = str(FORCE_SUB_CHANNEL_ID).strip()
            
            # Parse channel ID
            try:
                if channel_id_str.startswith("-"):
                    channel_id = int(channel_id_str)
                else:
                    try:
                        channel_id = int(channel_id_str)
                    except ValueError:
                        channel_id = channel_id_str
            except Exception:
                channel_id = channel_id_str
            
            # Check current membership status
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            
            # If still a member, allow access and update cache
            if member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                logger.info(f"✅ User {user_id} is still a member - access granted")
                _force_sub_cache[user_id] = time.time() + 300  # 5 min TTL
                return True
            
            # If no longer a member, remove from cache and show join prompt
            logger.warning(f"⚠️ User {user_id} left the channel - removing from cache")
            verified_users.discard(user_id)
            
        except Exception as e:
            logger.warning(f"Could not verify membership for cached user {user_id}: {e}")
            # On error, remove from cache to be safe
            verified_users.discard(user_id)
    
    logger.info(f"🔒 User {user_id} not verified or left channel - showing join prompt")

    # User not verified - show join prompt
    try:
        channel_id_str = str(FORCE_SUB_CHANNEL_ID).strip()
        logger.info(f"📌 Channel config: {channel_id_str}")
        
        # Parse channel ID
        try:
            if channel_id_str.startswith("-"):
                channel_chat_id = int(channel_id_str)
            else:
                try:
                    channel_chat_id = int(channel_id_str)
                except ValueError:
                    channel_chat_id = channel_id_str
        except Exception as parse_err:
            logger.error(f"❌ Channel ID parse error: {parse_err}")
            channel_chat_id = channel_id_str

        # Get channel info
        try:
            logger.info(f"📍 Getting chat info for {channel_chat_id}")
            chat = await context.bot.get_chat(channel_chat_id)
            channel_name = chat.title or chat.username or "Channel"
            logger.info(f"✅ Got chat info: {channel_name}")
            
            # Get invite link
            invite_link = None
            if chat.username:
                invite_link = f"https://t.me/{chat.username}"
            elif hasattr(chat, 'invite_link') and chat.invite_link:
                invite_link = chat.invite_link
            
            # Try to create invite link if doesn't exist
            if not invite_link:
                try:
                    link_obj = await context.bot.create_chat_invite_link(
                        chat_id=channel_chat_id, 
                        member_limit=1
                    )
                    invite_link = link_obj.invite_link
                except Exception as link_error:
                    logger.warning(f"Could not create invite link: {link_error}")
                    # Fallback to direct channel link
                    if str(channel_chat_id).startswith('-100'):
                        invite_link = f"https://t.me/c/{str(channel_chat_id)[4:]}"
                    else:
                        invite_link = f"https://t.me/{channel_chat_id}"
            
        except Exception as e:
            logger.error(f"Could not get chat info: {e}")
            return True  # Fail open

        # Build keyboard
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url=invite_link)],
            [
                InlineKeyboardButton("✅ ᴠᴇʀɪꜰʏ", callback_data="check_fsub"),
                InlineKeyboardButton("✖️ ᴄʟᴏsᴇ", callback_data="close_banner")
            ]
        ])
        
        # Build prompt message
        prompt = (
            "🔒 ᴄʜᴀɴɴᴇʟ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ʀᴇqᴜɪʀᴇᴅ\n\n"
            f"→ ᴊᴏɪɴ ᴏᴜʀ ᴄᴏᴍᴍᴜɴɪᴛʏ ᴄʜᴀɴɴᴇʟ:\n\n"
            f"<b>📢 {channel_name}</b>\n\n"
            "→ ᴇxᴄʟᴜsɪᴠᴇ ᴜᴘᴅᴀᴛᴇs & ᴛɪᴘs\n\n"
            "👇 ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴠᴇʀɪꜰʏ 👇"
        )

        try:
            banner = FORCE_SUB_BANNER_URL
            
            if update.message:
                # Send with banner if available
                if banner:
                    try:
                        if isinstance(banner, str) and os.path.isfile(banner):
                            await update.message.reply_photo(
                                photo=InputFile(banner),
                                caption=prompt,
                                reply_markup=kb,
                                parse_mode="HTML"
                            )
                        else:
                            await update.message.reply_photo(
                                photo=banner,
                                caption=prompt,
                                reply_markup=kb,
                                parse_mode="HTML"
                            )
                    except Exception as banner_err:
                        logger.warning(f"Could not send banner, sending text instead: {banner_err}")
                        await update.message.reply_text(
                            prompt,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                else:
                    await update.message.reply_text(
                        prompt,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
            elif update.callback_query:
                # Edit message with banner
                if banner:
                    try:
                        await update.callback_query.message.edit_caption(
                            caption=prompt,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                    except Exception:
                        await update.callback_query.message.edit_text(
                            prompt,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                else:
                    await update.callback_query.message.edit_text(
                        prompt,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
            logger.info(f"🔒 Force-sub prompt shown to user {user_id} with banner")
        except Exception as e:
            logger.error(f"Failed to show prompt: {e}")
            return True

        return False

    except Exception as e:
        logger.error(f"Force-Sub Error: {e}", exc_info=True)
        return True  # Fail open


async def _get_missing_force_sub_channels(context, user_id: int) -> list[int | str]:
    """Return every configured channel the user has not joined."""
    missing_channels = []
    allowed_statuses = (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )

    for channel_id in FORCE_SUB_CHANNEL_IDS:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel_id,
                user_id=user_id,
            )
            if member.status not in allowed_statuses:
                missing_channels.append(channel_id)
        except Exception as e:
            logger.warning(
                "Could not check force-sub membership for channel %s: %s",
                channel_id,
                e,
            )
            missing_channels.append(channel_id)

    return missing_channels


async def _get_force_sub_channel_details(bot, channel_id: int | str) -> tuple[str, str | None]:
    """Resolve a force-sub channel's display name and join link."""
    fallback_name = str(channel_id)
    try:
        chat = await bot.get_chat(channel_id)
        channel_name = chat.title or chat.username or fallback_name

        if chat.username:
            return channel_name, f"https://t.me/{chat.username}"
        if getattr(chat, "invite_link", None):
            return channel_name, chat.invite_link

        invite = await bot.create_chat_invite_link(chat_id=channel_id)
        return channel_name, invite.invite_link
    except Exception as e:
        logger.warning(f"Could not resolve force-sub channel {channel_id}: {e}")
        if isinstance(channel_id, str) and channel_id.startswith("@"):
            return fallback_name, f"https://t.me/{channel_id[1:]}"
        return fallback_name, None


async def _show_force_sub_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    missing_channels: list[int | str],
) -> None:
    """Show join buttons for all missing channels without a verify button."""
    keyboard_rows = []
    channel_names = []

    for index, channel_id in enumerate(missing_channels, start=1):
        channel_name, invite_link = await _get_force_sub_channel_details(
            context.bot,
            channel_id,
        )
        channel_names.append(f"{index}. <b>{escape(channel_name)}</b>")
        if invite_link:
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"📢 Join {channel_name}"[:60],
                    url=invite_link,
                )
            ])

    keyboard_rows.append([
        InlineKeyboardButton("✖️ Close", callback_data="close_banner")
    ])
    keyboard = InlineKeyboardMarkup(keyboard_rows)
    prompt = (
        "🔒 <b>Channel Subscription Required</b>\n\n"
        "Please join all the channels below:\n\n"
        + "\n".join(channel_names)
        + "\n\n✅ After joining, send /start again.\n"
        "The bot will verify your membership automatically."
    )

    banner = FORCE_SUB_BANNER_URL
    if update.message:
        if banner:
            try:
                photo = InputFile(banner) if os.path.isfile(banner) else banner
                await update.message.reply_photo(
                    photo=photo,
                    caption=prompt,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                return
            except Exception as e:
                logger.warning(f"Could not send force-sub banner: {e}")
        await update.message.reply_text(
            prompt,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    if update.callback_query:
        message = update.callback_query.message
        try:
            if getattr(message, "photo", None):
                await message.edit_caption(
                    caption=prompt,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            else:
                await message.edit_text(
                    prompt,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
        except BadRequest:
            pass


async def check_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Automatically verify that the user joined every configured channel."""
    user_id = update.effective_user.id

    if is_admin(user_id) or not FORCE_SUB_CHANNEL_IDS:
        return True

    now = time.time()
    if _force_sub_cache.get(user_id, 0) > now:
        return True

    missing_channels = await _get_missing_force_sub_channels(context, user_id)
    if not missing_channels:
        verified_users.add(user_id)
        _force_sub_cache[user_id] = now + 300
        logger.info(
            "User %s automatically verified in all %s force-sub channels",
            user_id,
            len(FORCE_SUB_CHANNEL_IDS),
        )
        return True

    verified_users.discard(user_id)
    _force_sub_cache.pop(user_id, None)
    logger.info(
        "User %s is missing %s of %s force-sub channels",
        user_id,
        len(missing_channels),
        len(FORCE_SUB_CHANNEL_IDS),
    )
    await _show_force_sub_prompt(update, context, missing_channels)
    return False




async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback query with proper force-sub verification"""
    query = update.callback_query
    
    logger.info(f"🔵 CALLBACK | Data: {query.data}")
    
    if not query or not query.data:
        logger.error("❌ Invalid query!")
        return

    user_id = query.from_user.id
    logger.info(f"👤 User ID: {user_id} | Channel ID Config: {FORCE_SUB_CHANNEL_ID}")
    
    # Backward compatibility for verification buttons sent before this update.
    if query.data == "check_fsub":
        await query.answer("Checking all channel subscriptions...")
        if await check_force_sub(update, context):
            await register_verified_user(update, context)
            try:
                await query.message.delete()
            except Exception:
                pass
            await open_home(update, context)
        return

    # Disabled legacy single-channel verification path.
    if query.data == "_legacy_check_fsub":
        logger.info(f"🔍 Verify button clicked by user {user_id}")
        
        if not FORCE_SUB_CHANNEL_ID:
            logger.warning("⚠️ FORCE_SUB_CHANNEL_ID not configured")
            await query.answer("✅ Bot configured successfully!", show_alert=False)
            await register_verified_user(update, context)
            await open_home(update, context)
            return
        
        try:
            # Parse channel ID - make sure we handle it as string first
            channel_id_str = str(FORCE_SUB_CHANNEL_ID).strip()
            logger.info(f"📌 Channel ID string: {channel_id_str}")
            
            # Try to convert to int
            try:
                if channel_id_str.startswith("-"):
                    channel_id = int(channel_id_str)
                else:
                    # Try as int first, otherwise keep as string
                    try:
                        channel_id = int(channel_id_str)
                    except ValueError:
                        channel_id = channel_id_str
            except Exception as parse_error:
                logger.error(f"❌ Failed to parse channel ID: {parse_error}")
                channel_id = channel_id_str
            
            logger.info(f"🔎 Checking membership for user {user_id} in channel {channel_id}")
            
            # Direct membership check
            try:
                member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                logger.info(f"📊 Member status: {member.status}")
            except Exception as member_error:
                logger.error(f"❌ Error checking membership: {member_error}")
                await query.answer("❌ ᴄʜᴀɴɴᴇʟ ᴄʜᴇᴄᴋ ꜰᴀɪʟᴇᴅ! ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.", show_alert=True)
                return
            
            # Check if user is member
            if member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            ):
                verified_users.add(user_id)
                logger.info(f"✅ User {user_id} verified successfully with status {member.status}")

                # Register only after force-sub membership is successfully verified.
                await register_verified_user(update, context)
                
                # Show success alert
                await query.answer("✅ ᴄʜᴀɴɴᴇʟ ᴠᴇʀɪꜰɪᴇᴅ sᴜᴄᴄᴇssꜰᴜʟʟʏ!", show_alert=False)
                
                # Try to delete verification message
                try:
                    await query.message.delete()
                    logger.info(f"🗑️ Verification message deleted")
                except Exception as del_error:
                    logger.warning(f"Could not delete message: {del_error}")
                
                # Show home screen
                logger.info(f"🏠 Showing home screen for user {user_id}")
                await open_home(update, context)
                return
            
            # User not in channel yet
            logger.warning(f"⚠️ User {user_id} not a member. Status: {member.status}")
            await query.answer("❌ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀsᴛ!\n\nᴘʟᴇᴀsᴇ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ᴀɴᴅ ᴛʜᴇɴ ᴄʟɪᴄᴋ ᴠᴇʀɪꜰʏ.", show_alert=True)
            return
            
        except Exception as e:
            logger.error(f"❌ Verification error: {type(e).__name__}: {e}", exc_info=True)
            await query.answer("❌ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ꜰᴀɪʟᴇᴅ!\n\nᴘʟᴇᴀsᴇ ᴍᴀᴋᴇ sᴜʀᴇ ʏᴏᴜ ᴊᴏɪɴᴇᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀsᴛ.", show_alert=True)
            return
    
    # Handle close button
    if query.data == "close_banner":
        logger.info(f"❌ User {user_id} closed banner")
        try:

            await query.answer()
            await query.message.delete()
        except Exception as e:
            logger.error(f"Close error: {e}")
            try:
                await query.message.edit_text("Closed", parse_mode="HTML")
            except Exception:
                pass
        return
    
    # Handle admin callbacks
    if query.data == "admin_stats":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        stats = get_stats()
        text = (
            "📊 ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs\n\n"
            f"👥 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {stats['total_users']}\n"
            f"🚫 ʙᴀɴɴᴇᴅ ᴜsᴇʀs: {stats['banned_users']}\n"
            f"🖼 ᴡɪᴛʜ ᴛʜᴜᴍʙɴᴀɪʟ: {stats['users_with_thumbnail']}"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "admin_users":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        stats = get_stats()
        total_users = stats['total_users']
        banned_users = stats['banned_users']
        active_users = total_users - banned_users
        
        text = (
            "👥 ᴜsᴇʀ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ\n\n"
            f"📊 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {total_users}\n"
            f"✅ ᴀᴄᴛɪᴠᴇ ᴜsᴇʀs: {active_users}\n"
            f"🚫 ʙᴀɴɴᴇᴅ ᴜsᴇʀs: {banned_users}\n\n"
            f"📈 ʙᴀɴ ʀᴀᴛᴇ: {(banned_users/total_users*100):.1f}%" if total_users > 0 else "📈 ʙᴀɴ ʀᴀᴛᴇ: 0%"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "admin_status":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        try:
            import psutil
            import time
            cpu_percent = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            text = (
                "⏱️ ʙᴏᴛ sᴛᴀᴛᴜs\n\n"
                f"🟢 sᴛᴀᴛᴜs: ᴏɴʟɪɴᴇ\n\n"
                f"🖥 sʏsᴛᴇᴍ ʀᴇsᴏᴜʀᴄᴇs:\n"
                f"ᴄᴘᴜ: {cpu_percent}%\n"
                f"ʀᴀᴍ: {ram.percent}%"
            )
        except ImportError:
            text = "⏱️ <b>Bot Status</b>\n\n🟢 Status: <b>Online</b>"
        
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "admin_ban":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = "🚫 ʙᴀɴ ᴜsᴇʀ\n\nꜱᴇɴᴅ ᴜsᴇʀ ɪᴅ ᴛᴏ ʙᴀɴ ᴏʀ /ʙᴀɴ ᴜsᴇʀɪᴅ ʀᴇᴀsᴏɴ"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_unban":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = "✅ ᴜɴʙᴀɴ ᴜsᴇʀ\n\nꜱᴇɴᴅ ᴜsᴇʀ ɪᴅ ᴛᴏ ᴜɴʙᴀɴ ᴏʀ /ᴜɴʙᴀɴ ᴜsᴇʀɪᴅ"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_broadcast":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = "📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ\n\nꜱᴇɴᴅ ᴍᴇssᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀsᴛ ᴛᴏ ᴀʟʟ ᴜsᴇʀs"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_back")]
        ])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=back_kb, parse_mode="HTML")
        return
    
    if query.data == "admin_back":
        if not is_admin(user_id):
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        await query.answer()
        text = (
            "🛡️ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ\n\n"
            "<b>Management Options:</b>\n\n"
            "📊 <b>Statistics</b> – View user analytics\n"
            "⏱️ <b>Status</b> – Bot performance\n"
            "🚫 <b>Ban User</b> – Block users\n"
            "✅ <b>Unban</b> – Restore access"
        )
        admin_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 sᴛᴀᴛɪsᴛɪᴄs", callback_data="admin_stats"),
             InlineKeyboardButton("⏱️ sᴛᴀᴛᴜs", callback_data="admin_status")],
            [InlineKeyboardButton("🚫 ʙᴀɴ ᴜsᴇʀ", callback_data="admin_ban"),
             InlineKeyboardButton("✅ ᴜɴʙᴀɴ ᴜsᴇʀ", callback_data="admin_unban")],
            [InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", callback_data="admin_broadcast"),
             InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")],
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=admin_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception:
            pass
        return

    if query.data == "contact_owner":
        logger.info(f"📞 Contact owner for user {user_id}")
        try:
            await query.answer()
            if OWNER_USERNAME:
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"Contact owner: https://t.me/{OWNER_USERNAME}")
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text="Owner contact not configured.")
        except Exception as e:
            logger.error(f"Contact error: {e}")
        return

    # Handle channel remove buttons
    if query.data.startswith("rmch_") or query.data == "cancel":
        await remove_channel_callback(update, context)
        return
    
    # Handle add new channel
    if query.data == "add_new_channel":
        await query.answer()
        bot_username = get_bot_username()
        await query.message.edit_text(
            "➕ <b>Add New Channel</b>\n\n"
            "<b>STEP 1:</b> Add the bot to your channel as an administrator\n"
            "     (Enable the Edit Messages permission)\n\n"
            "<b>STEP 2:</b> Send the channel ID:\n"
            "     <code>/setchannel -100xxxxxxxxxx</code>",
            parse_mode="HTML"
        )
        return
    
    # Handle noop (do nothing)
    if query.data == "noop":
        await query.answer()
        return

    # Menu callbacks: show help/about/settings/developer inline
    if query.data.startswith("menu_"):
        key = query.data.split("menu_")[1]
        logger.info(f"📋 Menu callback: {key} for user {user_id}")
        await query.answer()
        
        # Handle back button - return to home menu
        if key == "back":
            bot_username = get_bot_username()
            text = (
                f"👋 <b>Hello {query.from_user.first_name}!</b>\n\n"
                "🎬 <b>Thumbnail Cover Bot</b>\n"
                "Automatically apply thumbnails to your videos!\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "⚡ <b>How It Works:</b>\n\n"
                "📸 <b>Step 1:</b> Send your thumbnail image\n"
                "   (The bot will save it)\n\n"
                "🎥 <b>Step 2:</b> Post a video in your channel\n"
                "   (The bot will apply the cover automatically!)\n\n"
                "━━━━━━━━━━━━━━━━━━━━━"
            )
            kb_rows = [
                [InlineKeyboardButton("➕ Add Bot To Channel", url=f"https://t.me/{bot_username}?startchannel=true")],
                [InlineKeyboardButton("📸 Thumbnail Set", callback_data="menu_settings"),
                 InlineKeyboardButton("📢 My Channels", callback_data="menu_mychannels")],
                [InlineKeyboardButton("❓ Help", callback_data="menu_help"),
                 InlineKeyboardButton("ℹ️ About", callback_data="menu_about")],
                [InlineKeyboardButton("👨‍💻 Developer", callback_data="menu_developer")]
            ]
            kb = InlineKeyboardMarkup(kb_rows)
            try:
                msg = query.message
                if getattr(msg, "photo", None):
                    await msg.edit_caption(text, reply_markup=kb, parse_mode="HTML")
                else:
                    await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logger.debug(f"Back button message edit error: {e}")
            return
        
        try:
            if key == "help":
                text = (
                    "ℹ️ ʜᴇʟᴘ ᴍᴇɴᴜ\n\n"
                    "<b>ʜᴏᴡ ᴛᴏ ᴜsᴇ:</b>\n\n"
                    "<b>1️⃣ ᴜᴘʟᴏᴀᴅ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n"
                    "   • sᴇɴᴅ ᴀɴʏ ᴘʜᴏᴛᴏ\n"
                    "   • ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ sᴀᴠᴇᴅ ᴛᴏ ᴘʀᴏꜰɪʟᴇ\n\n"
                    "<b>2️⃣ ᴀᴘᴘʟʏ ᴛᴏ ᴠɪᴅᴇᴏ</b>\n"
                    "   • sᴇɴᴅ ᴀ ᴠɪᴅᴇᴏ ꜰɪʟᴇ\n"
                    "   • ᴛʜᴜᴍʙɴᴀɪʟ ᴀᴘᴘʟɪᴇᴅ ɪɴsᴛᴀɴᴛʟʏ\n\n"
                    "<b>ᴀᴅᴅɪᴛɪᴏɴᴀʟ ᴄᴏᴍᴍᴀɴᴅs:</b>\n"
                    "/remove – ᴅᴇʟᴇᴛᴇ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ\n"
                    "/settings – ᴠɪᴇᴡ & ᴍᴀɴᴀɢᴇ sᴇᴛᴛɪɴɢs\n"
                    "/about – ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ ᴀʙᴏᴜᴛ ʙᴏᴛ"
                )
            elif key == "about":
                text = (
                    "🤖 ɪɴsᴛᴀɴᴛ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀ ʙᴏᴛ\n\n"
                    "<b>ᴘʀᴇᴍɪᴜᴍ ꜰᴇᴀᴛᴜʀᴇs:</b>\n\n"
                    "✅ <b>ᴏɴᴇ-ᴄʟɪᴄᴋ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n"
                    "   ᴜᴘʟᴏᴀᴅ ᴏɴᴄᴇ, ᴀᴘᴘʟʏ ᴛᴏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴠɪᴅᴇᴏs\n\n"
                    "✅ <b>ɪɴsᴛᴀɴᴛ ᴘʀᴏᴄᴇssɪɴɢ</b>\n"
                    "   ꜰᴀsᴛ ᴄᴏᴠᴇʀ ᴀᴘᴘʟɪᴄᴀᴛɪᴏɴ\n\n"
                    "✅ <b>sᴇᴄᴜʀᴇ & ᴘʀɪᴠᴀᴛᴇ</b>\n"
                    "   ʏᴏᴜʀ ᴅᴀᴛᴀ sᴛᴀʏs ᴇɴᴄʀʏᴘᴛᴇᴅ\n\n"
                    "<b>ᴛᴇᴄʜɴᴏʟᴏɢʏ:</b>\n"
                    "⚙️ ᴀᴅᴠᴀɴᴄᴇᴅ ᴘʏᴛʜᴏɴ ᴀᴘɪ\n"
                    "🔐 sᴇᴄᴜʀᴇ ᴛᴇʟᴇɢʀᴀᴍ ɪɴᴛᴇɢʀᴀᴛɪᴏɴ"
                )
            elif key == "settings":
                uid = query.from_user.id
                text = (
                    "⚙️ sᴇᴛᴛɪɴɢs\n\n"
                    "<b>ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴄᴏɴᴛᴇɴᴛ:</b>\n\n"
                    "🖼️ <b>ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ</b>\n"
                    "   • ᴠɪᴇᴡ ᴄᴜʀʀᴇɴᴛ ᴛʜᴜᴍʙɴᴀɪʟ\n"
                    "   • ᴅᴇʟᴇᴛᴇ & ᴜᴘʟᴏᴀᴅ ɴᴇᴡ\n\n"
                    "sᴇʟᴇᴄᴛ ᴏᴘᴛɪᴏɴ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:"
                )
                # Add settings submenus buttons
                settings_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🖼 ᴛʜᴜᴍʙɴᴀɪʟs", callback_data="submenu_thumbnails")],
                    [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")]
                ])
                try:
                    msg = query.message
                    if getattr(msg, "photo", None):
                        await msg.edit_caption(text, reply_markup=settings_kb, parse_mode="HTML")
                    else:
                        await msg.edit_text(text, reply_markup=settings_kb, parse_mode="HTML")
                except Exception as e:
                    logger.debug(f"Settings menu edit error: {e}")
                return
            elif key == "mychannels":
                uid = query.from_user.id
                channels = get_user_channels(uid)
                
                if not channels:
                    text = (
                        "📢 <b>My Channels</b>\n\n"
                        "⚠️ You have not added any channels yet!\n\n"
                        "📌 <b>Add a channel:</b>\n"
                        "1. Add the bot to your channel as an administrator\n"
                        "2. <code>/setchannel -100xxxxxxxxxx</code>"
                    )
                    ch_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add Channel", callback_data="add_new_channel")]
                    ])
                else:
                    text = f"📢 <b>Your Channels ({len(channels)})</b>\n\n"
                    buttons = []
                    for ch in channels:
                        try:
                            chat = await context.bot.get_chat(int(ch))
                            text += f"• <b>{chat.title}</b>\n  <code>{ch}</code>\n"
                            buttons.append([
                                InlineKeyboardButton(f"{chat.title}", callback_data="noop"),
                                InlineKeyboardButton("🗑️ Delete", callback_data=f"rmch_{ch}")
                            ])
                        except:
                            text += f"• <code>{ch}</code>\n"
                            buttons.append([
                                InlineKeyboardButton(f"{ch}", callback_data="noop"),
                                InlineKeyboardButton("🗑️ Delete", callback_data=f"rmch_{ch}")
                            ])
                    
                    buttons.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_new_channel")])
                    ch_kb = InlineKeyboardMarkup(buttons)
                
                try:
                    msg = query.message
                    if getattr(msg, "photo", None):
                        await msg.edit_caption(text, reply_markup=ch_kb, parse_mode="HTML")
                    else:
                        await msg.edit_text(text, reply_markup=ch_kb, parse_mode="HTML")
                except Exception as e:
                    logger.debug(f"MyChannels menu error: {e}")
                return
            elif key == "developer":
                dev_contact = f"https://t.me/{OWNER_USERNAME}" if OWNER_USERNAME else f"tg://user?id={OWNER_ID}"
                text = (
                    "👨‍💻 <b>ᴅᴇᴠᴇʟᴏᴘᴇʀ</b>\n\n"
                    f"ᴄᴏɴᴛᴀᴄᴛ: {dev_contact}\n"
                    "ɪꜰ ʏᴏᴜ ɴᴇᴇᴅ ʜᴇʟᴘ, ʀᴇᴀᴄʜ ᴏᴜᴛ ᴛᴏ ᴛʜᴇ ᴅᴇᴠᴇʟᴏᴘᴇʀ."
                )
            else:
                text = (
                    "ℹ️ <b>ɪɴꜰᴏ</b>\n\n"
                    "ɴᴏ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ ᴀᴠᴀɪʟᴀʙʟᴇ ꜰᴏʀ ᴛʜɪs ᴍᴇɴᴜ."
                )
            
            # Add back button to all menus (except settings which has its own)
            if key != "settings":
                back_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")]
                ])
                
                # Try to edit original message's caption/text first
                try:
                    msg = query.message
                    if getattr(msg, "photo", None):
                        await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
                    else:
                        await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
                except Exception as e:
                    logger.debug(f"Menu edit error: {e}")
                    await context.bot.send_message(chat_id=query.message.chat.id, text=text, reply_markup=back_kb, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Menu error: {e}", exc_info=True)
        return
    
    # Handle Thumbnails submenu
    if query.data == "submenu_thumbnails":
        await query.answer()
        uid = query.from_user.id
        thumb_status = "✅ sᴀᴠᴇᴅ" if has_thumbnail(uid) else "❌ ɴᴏᴛ sᴀᴠᴇᴅ"
        text = (
            "🖼️ <b>ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀɴᴀɢᴇʀ</b>\n\n"
            f"<b>ᴄᴜʀʀᴇɴᴛ sᴛᴀᴛᴜs:</b> {thumb_status}\n\n"
            "📚 <b>ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴄᴛɪᴏɴs:</b>\n\n"
            "💾 sᴀᴠᴇ ᴛʜᴜᴍʙɴᴀɪʟ\n"
            "ᴜᴘʟᴏᴀᴅ ᴀ ɴᴇᴡ ᴘʜᴏᴛᴏ ᴀs ʏᴏᴜʀ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀ\n\n"
            "👁️ sʜᴏᴡ ᴛʜᴜᴍʙɴᴀɪʟ\n"
            "ᴘʀᴇᴠɪᴇᴡ ʏᴏᴜʀ ᴄᴜʀʀᴇɴᴛʟʏ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ\n\n"
            "🗑️ ᴅᴇʟᴇᴛᴇ ᴛʜᴜᴍʙɴᴀɪʟ\n"
            "ʀᴇᴍᴏᴠᴇ ʏᴏᴜʀ sᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ"
        )
        thumb_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 sᴀᴠᴇ ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumb_save_info"),
             InlineKeyboardButton("👁️ sʜᴏᴡ ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumb_show")],
            [InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ ᴛʜᴜᴍʙɴᴀɪʟ", callback_data="thumb_delete"),
             InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_settings")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=thumb_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=thumb_kb, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"Thumbnails submenu edit error: {e}")
        return
    
    
    # Handle thumbnail operations
    if query.data == "thumb_save_info":
        await query.answer()
        text = (
            "💾 sᴀᴠᴇ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ\n\n"
            "📸 ʜᴏᴡ ɪᴛ ᴡᴏʀᴋs:\n\n"
            "<b>sᴛᴇᴘ 1️⃣:</b> sᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ\n"
            "→ ɢᴏ ʙᴀᴄᴋ ᴀɴᴅ sᴇɴᴅ ᴀɴʏ ᴘʜᴏᴛᴏ\n"
            "→ ᴛʜɪs ᴡɪʟʟ ʙᴇ ʏᴏᴜʀ ᴄᴏᴠᴇʀ\n\n"
            "<b>sᴛᴇᴘ 2️⃣:</b> ᴀᴜᴛᴏᴍᴀᴛɪᴄ sᴀᴠᴇ\n"
            "→ ᴛʜᴜᴍʙɴᴀɪʟ sᴀᴠᴇs ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ\n"
            "→ ʀᴇᴘʟᴀᴄᴇ ᴀɴʏᴛɪᴍᴇ\n\n"
            "<b>sᴛᴇᴘ 3️⃣:</b> ʀᴇᴀᴅʏ ᴛᴏ ᴜsᴇ\n"
            "→ sᴇɴᴅ ᴀɴʏ ᴠɪᴅᴇᴏ\n"
            "→ ᴄᴏᴠᴇʀ ᴀᴘᴘʟɪᴇs ɪɴsᴛᴀɴᴛʟʏ\n\n"
            "💡 ᴛɪᴘs:\n"
            "• ʜɪɢʜ-ʀᴇsᴏʟᴜᴛɪᴏɴ ɪᴍᴀɢᴇs\n"
            "• sqᴜᴀʀᴇ ꜰᴏʀᴍᴀᴛ 1:1\n"
            "• ᴍᴀx 5ᴍʙ ꜰɪʟᴇ\n\n"
            "📸 ʀᴇᴀᴅʏ? sᴇɴᴅ ʏᴏᴜʀ ᴘʜᴏᴛᴏ ɴᴏᴡ"
        )
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    if query.data == "thumb_show":
        await query.answer()
        photo_id = get_thumbnail(user_id)
        if photo_id:
            text = "👁️ ʏᴏᴜʀ ᴄᴜʀʀᴇɴᴛ ᴛʜᴜᴍʙɴᴀɪʟ\n\nᴛʜɪs ᴘʜᴏᴛᴏ ᴡɪʟʟ ʙᴇ ᴀᴘᴘʟɪᴇᴅ ᴛᴏ ʏᴏᴜʀ ᴠɪᴅᴇᴏs\nᴄʜᴀɴɢᴇ ɪᴛ ᴀɴʏᴛɪᴍᴇ ʙʏ ᴜᴘʟᴏᴀᴅɪɴɢ ᴀ ɴᴇᴡ ᴏɴᴇ"
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
            ])
            try:
                await query.message.delete()
            except Exception:
                pass
            try:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_id,
                    caption=text,
                    reply_markup=back_kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending thumbnail: {e}")
        else:
            text = "❌ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ sᴀᴠᴇᴅ ʏᴇᴛ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴏɴᴇ ɴᴏᴡ"
            back_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
            ])
            try:
                msg = query.message
                if getattr(msg, "photo", None):
                    await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
                else:
                    await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
            except Exception:
                pass
        return
    
    if query.data == "thumb_delete":
        await query.answer()
        if delete_thumbnail(user_id):
            text = "✅ ᴛʜᴜᴍʙɴᴀɪʟ ᴅᴇʟᴇᴛᴇᴅ\n\nʀᴇᴍᴏᴠᴇᴅ ꜰʀᴏᴍ sʏsᴛᴇᴍ. ᴜᴘʟᴏᴀᴅ ɴᴇᴡ ᴏɴᴇ ᴀɴʏᴛɪᴍᴇ"
        else:
            text = "⚠️ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ ꜰᴏᴜɴᴅ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴏɴᴇ"
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="submenu_thumbnails")]
        ])
        try:
            msg = query.message
            if getattr(msg, "photo", None):
                await msg.edit_caption(text, reply_markup=back_kb, parse_mode="HTML")
            else:
                await msg.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
        except Exception:
            pass
        return
    
    logger.warning(f"⚠️ Unknown callback: {query.data}")
    try:
        await query.answer("Unknown action", show_alert=False)
    except Exception:
        pass


"""---------------------- Menus--------------------- """

async def open_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = get_bot_username()
    first_name = "User"
    if update.callback_query:
        first_name = update.callback_query.from_user.first_name or "User"
    elif update.effective_user:
        first_name = update.effective_user.first_name or "User"
    
    text = (
        f"👋 <b>Hello {first_name}!</b>\n\n"
        "🎬 <b>Thumbnail Cover Bot</b>\n"
        "Automatically apply thumbnails to your videos!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ <b>How It Works:</b>\n\n"
        "📸 <b>Step 1:</b> Send your thumbnail image\n"
        "   (The bot will save it)\n\n"
        "🎥 <b>Step 2:</b> Post a video in your channel\n"
        "   (The bot will apply the cover automatically!)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✨ <b>Features:</b>\n"
        "• 🚀 Super fast processing\n"
        "• 📢 Multiple channels support\n"
        "• 🎨 High quality covers\n"
        "• 🔄 Auto apply on every video\n"
        "• 📊 24/7 Active\n\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Bot To Channel", url=f"https://t.me/{bot_username}?startchannel=true")],
        [
            InlineKeyboardButton("📸 Thumbnail Set", callback_data="menu_settings"),
            InlineKeyboardButton("📢 My Channels", callback_data="menu_mychannels")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
            InlineKeyboardButton("ℹ️ About", callback_data="menu_about")
        ],
        [InlineKeyboardButton("👨‍💻 Developer", callback_data="menu_developer")]
    ])

    if update.callback_query:
        msg = update.callback_query.message
        try:
            await msg.delete()
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=msg.chat.id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Error sending home: {e}")
    else:
        await update.message.reply_text(text=text, reply_markup=kb, parse_mode="HTML")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "User"

    if is_user_banned(user_id):
        return await update.message.reply_text(
            "🚫 <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>\n\n"
            "Your account is restricted.\n"
            "Contact @support for help.",
            parse_mode="HTML"
        )

    if not await check_force_sub(update, context):
        return

    # With force-sub enabled, this point is reached only after verification.
    await register_verified_user(update, context)
    
    bot_username = get_bot_username()
    
    welcome_text = (
        f"👋 <b>Hello {first_name}!</b>\n\n"
        "🎬 <b>Thumbnail Cover Bot</b>\n"
        "Automatically apply thumbnails to your videos!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ <b>How It Works:</b>\n\n"
        "📸 <b>Step 1:</b> Send your thumbnail image\n"
        "   (The bot will save it)\n\n"
        "🎥 <b>Step 2:</b> Post a video in your channel\n"
        "   (The bot will apply the cover automatically!)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✨ <b>Features:</b>\n"
        "• 🚀 Super fast processing\n"
        "• 📢 Multiple channels support\n"
        "• 🎨 High quality covers\n"
        "• 🔄 Auto apply on every video\n"
        "• 📊 24/7 Active\n\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Bot To Channel", url=f"https://t.me/{bot_username}?startchannel=true")],
        [
            InlineKeyboardButton("📸 Thumbnail Set", callback_data="menu_settings"),
            InlineKeyboardButton("📢 My Channels", callback_data="menu_mychannels")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
            InlineKeyboardButton("ℹ️ About", callback_data="menu_about")
        ],
        [InlineKeyboardButton("👨‍💻 Developer", callback_data="menu_developer")]
    ])
    
    if update.callback_query:
        msg = update.callback_query.message
        try:
            await msg.delete()
        except:
            pass
        await msg.chat.send_message(text=welcome_text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text=welcome_text, reply_markup=kb, parse_mode="HTML")
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    text = (
        "📖 ᴄᴏᴍᴘʟᴇᴛᴇ ɢᴜɪᴅᴇ\n\n"
        "<b>sᴛᴇᴘ-ʙʏ-sᴛᴇᴘ ɪɴsᴛʀᴜᴄᴛɪᴏɴs:</b>\n\n"
        "<b>1️⃣ ᴜᴘʟᴏᴀᴅ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ</b>\n"
        "   • sᴇɴᴅ ᴀ ʜɪɢʜ-qᴜᴀʟɪᴛʏ ᴘʜᴏᴛᴏ\n"
        "   • ɪᴛ sᴀᴠᴇs ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴀs ʏᴏᴜʀ ᴄᴏᴠᴇʀ\n\n"
        "<b>2️⃣ ᴀᴘᴘʟʏ ᴛᴏ ᴠɪᴅᴇᴏs</b>\n"
        "   • sᴇɴᴅ ᴀɴʏ ᴠɪᴅᴇᴏ ꜰɪʟᴇ\n"
        "   • ᴄᴏᴠᴇʀ ᴀᴘᴘʟɪᴇs ɪɴsᴛᴀɴᴛʟʏ\n\n"
        "<b>3️⃣ ᴅᴏᴡɴʟᴏᴀᴅ & sʜᴀʀᴇ</b>\n"
        "   • ʏᴏᴜʀ ᴠɪᴅᴇᴏ ᴡɪᴛʜ ᴄᴏᴠᴇʀ ɪs ʀᴇᴀᴅʏ\n"
        "   • ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴᴅ sʜᴀʀᴇ ᴀɴʏᴡʜᴇʀᴇ\n\n"
        "<b>💡 ᴘʀᴏ ᴛɪᴘs:</b>\n"
        "✓ ʜɪɢʜ-qᴜᴀʟɪᴛʏ ᴘʜᴏᴛᴏs ᴡᴏʀᴋ ʙᴇsᴛ\n"
        "✓ ᴜᴘᴅᴀᴛᴇ ᴛʜᴜᴍʙɴᴀɪʟ ᴀɴʏᴛɪᴍᴇ\n"
        "✓ ʀᴇᴍᴏᴠᴇ ᴏʟᴅ ᴄᴏᴠᴇʀs ꜰʀᴏᴍ sᴇᴛᴛɪɴɢs\n\n"
        "📞 ɴᴇᴇᴅ ʜᴇʟᴘ? ᴄᴏɴᴛᴀᴄᴛ: /about"
    )
    banner = HOME_MENU_BANNER_URL
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(photo=InputFile(banner), caption=text, parse_mode="HTML")
            else:
                await update.message.reply_photo(photo=banner, caption=text, parse_mode="HTML")
            return
        except Exception:
            pass
    await update.message.reply_text(text, parse_mode="HTML")
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    text = (
        "🤖 ᴀʙᴏᴜᴛ ᴛʜɪs ʙᴏᴛ\n\n"
        "<b>ᴘʀᴏꜰᴇssɪᴏɴᴀʟ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀ ᴛᴏᴏʟ</b>\n\n"
        "<b>ᴅᴇsᴄʀɪᴘᴛɪᴏɴ:</b>\n"
        "ᴀᴘᴘʟʏ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟs ᴛᴏ ʏᴏᴜʀ ᴠɪᴅᴇᴏs ɪɴsᴛᴀɴᴛʟʏ\n\n"
        "<b>ᴘʀᴇᴍɪᴜᴍ ꜰᴇᴀᴛᴜʀᴇs:</b>\n"
        "✅ ʟɪɢʜᴛɴɪɴɢ-ꜰᴀsᴛ ᴘʀᴏᴄᴇssɪɴɢ\n"
        "✅ ʜɪɢʜ-qᴜᴀʟɪᴛʏ ᴛʜᴜᴍʙɴᴀɪʟ sᴛᴏʀᴀɢᴇ\n"
        "✅ ᴘʀᴏꜰᴇssɪᴏɴᴀʟ ᴠɪᴅᴇᴏ ᴄᴏᴠᴇʀs\n"
        "✅ sɪᴍᴘʟᴇ ɪɴᴛᴇʀꜰᴀᴄᴇ\n"
        "✅ ɪɴsᴛᴀɴᴛ ʀᴇsᴜʟᴛs\n\n"
        "<b>ᴛᴇᴄʜɴᴏʟᴏɢʏ sᴛᴀᴄᴋ:</b>\n"
        "⚙️ ᴀᴅᴠᴀɴᴄᴇᴅ ᴘʏᴛʜᴏɴ ᴀᴘɪ\n"
        "<b>sᴜᴘᴘᴏʀᴛ & ᴄᴏɴᴛᴀᴄᴛ:</b>\n"
        f"👨‍💻 ᴅᴇᴠᴇʟᴏᴘᴇʀ: @{OWNER_USERNAME or 'sᴜᴘᴘᴏʀᴛ'}\n"
        "📧 ꜰᴏʀ ʜᴇʟᴘ: /about → ᴅᴇᴠᴇʟᴏᴘᴇʀ\n\n"
        "ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ! 🎬"
    )
    banner = HOME_MENU_BANNER_URL
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(photo=InputFile(banner), caption=text, parse_mode="HTML")
            else:
                await update.message.reply_photo(photo=banner, caption=text, parse_mode="HTML")
            return
        except Exception:
            pass
    await update.message.reply_text(text, parse_mode="HTML")
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    user_id = update.message.from_user.id
    # Show thumbnail status
    thumb_status = "✅ sᴀᴠᴇᴅ & ʀᴇᴀᴅʏ" if has_thumbnail(user_id) else "❌ ɴᴏᴛ sᴀᴠᴇᴅ ʏᴇᴛ"
    
    text = (
        "⚙️ ʏᴏᴜʀ sᴇᴛᴛɪɴɢs\n\n"
        "<b>ᴀᴄᴄᴏᴜɴᴛ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ:</b>\n"
        f"👤 ᴜsᴇʀ ɪᴅ: <code>{user_id}</code>\n\n"
        "<b>ᴛʜᴜᴍʙɴᴀɪʟ sᴛᴀᴛᴜs:</b>\n"
        f"{thumb_status}\n\n"
        "<b>ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ᴏᴘᴛɪᴏɴs:</b>\n"
        "🖼️ ᴠɪᴇᴡ ᴀɴᴅ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟs"
    )
    settings_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 ᴛʜᴜᴍʙɴᴀɪʟs", callback_data="submenu_thumbnails")],
        [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")]
    ])
    banner = HOME_MENU_BANNER_URL
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(photo=InputFile(banner), caption=text, reply_markup=settings_kb, parse_mode="HTML")
            else:
                await update.message.reply_photo(photo=banner, caption=text, reply_markup=settings_kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await update.message.reply_text(text, reply_markup=settings_kb, parse_mode="HTML")



async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    user_id = update.message.from_user.id
    
    if delete_thumbnail(user_id):
        return await update.message.reply_text("✅ ᴛʜᴜᴍʙɴᴀɪʟ ʀᴇᴍᴏᴠᴇᴅ\n\nᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssꜰᴜʟʟʏ. ᴜᴘʟᴏᴀᴅ ᴀ ɴᴇᴡ ᴏɴᴇ ᴀɴʏᴛɪᴍᴇ!", reply_to_message_id=update.message.message_id, parse_mode="HTML")
    await update.message.reply_text("⚠️ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴛᴏ ʀᴇᴍᴏᴠᴇ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ꜰɪʀsᴛ!", reply_to_message_id=update.message.message_id, parse_mode="HTML")


"""═══════════════════ CHANNEL SETUP COMMANDS (MULTI-CHANNEL) ═══════════════════"""


def get_bot_username():
    """Get bot username - auto detected from token"""
    return BOT_USERNAME or "bot"


async def setchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add channel - /setchannel -100xxxxxxxxxx"""
    if not await check_force_sub(update, context):
        return
    
    user_id = update.effective_user.id
    args = context.args
    
    if not args:
        text = (
            "📢 <b>ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ</b>\n\n"
            "<b>STEP 1:</b> Add the bot to your channel as an administrator\n"
            "     (Enable the Edit Messages permission)\n\n"
            "<b>STEP 2:</b> Send the channel ID:\n"
            "     <code>/setchannel -100xxxxxxxxxx</code>\n\n"
            "📌 <b>Only channel IDs are supported</b>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Bot To Channel", url=f"https://t.me/{get_bot_username()}?startchannel=true")]
        ])
        return await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    
    channel_id = args[0].strip()
    
    if not (channel_id.startswith("-100") and channel_id.lstrip("-").isdigit()):
        return await update.message.reply_text(
            "❌ <b>ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ</b>\n\n"
            "📌 The channel ID must use this format:\n"
            "<code>-1001234567890</code>",
            parse_mode="HTML"
        )
    
    try:
        chat = await context.bot.get_chat(int(channel_id))
        
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if bot_member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return await update.message.reply_text(
                f"❌ The bot is not an administrator in <b>{chat.title}</b>\n\n"
                "📌 Add the bot as an administrator and enable the Edit Messages permission",
                parse_mode="HTML"
            )
        
        if not bot_member.can_edit_messages:
            return await update.message.reply_text(
                f"❌ The bot does not have the Edit Messages permission in <b>{chat.title}</b>\n\n"
                "📌 Enable the Edit Messages permission for the bot",
                parse_mode="HTML"
            )
        
        if add_user_channel(user_id, channel_id):
            channels = get_user_channels(user_id)
            text = (
                f"✅ <b>{chat.title}</b> has been added!\n\n"
                f"📊 <b>Total Channels:</b> {len(channels)}\n\n"
                "📌 <b>What to do next:</b>\n"
                "1. Send an image to this bot—it will be saved automatically as your thumbnail\n"
                "2. Post a video in the channel—the cover will be applied automatically!"
            )
        else:
            text = "⚠️ This channel has already been added!"
        
        await update.message.reply_text(text, parse_mode="HTML")
        
    except Exception as e:
        if "not found" in str(e).lower():
            await update.message.reply_text(
                "❌ <b>ᴄʜᴀɴɴᴇʟ ɴᴏᴛ ꜰᴏᴜɴᴅ</b>\n\n"
                "📌 Please check that:\n"
                "• The bot has been added to the channel\n"
                "• The channel ID is correct",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(f"❌ Error: <code>{str(e)[:100]}</code>", parse_mode="HTML")


async def removechannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove channel - /removechannel"""
    if not await check_force_sub(update, context):
        return
    
    user_id = update.effective_user.id
    channels = get_user_channels(user_id)
    
    if not channels:
        return await update.message.reply_text(
            "⚠️ You have not added any channels!\n\n"
            "📌 Add one first using /setchannel",
            parse_mode="HTML"
        )
    
    if context.args:
        channel_id = context.args[0].strip()
        if remove_user_channel(user_id, channel_id):
            remaining = get_user_channels(user_id)
            await update.message.reply_text(
                f"✅ Channel <code>{channel_id}</code> has been removed!\n\n"
                f"📊 <b>Remaining:</b> {len(remaining)} channels",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ Channel not found!", parse_mode="HTML")
        return
    
    # Show buttons for each channel
    buttons = []
    for ch in channels:
        try:
            chat = await context.bot.get_chat(int(ch))
            buttons.append([InlineKeyboardButton(f"🗑️ {chat.title}", callback_data=f"rmch_{ch}")])
        except:
            buttons.append([InlineKeyboardButton(f"🗑️ {ch}", callback_data=f"rmch_{ch}")])
    
    buttons.append([InlineKeyboardButton("✖️ Cancel", callback_data="cancel")])
    
    await update.message.reply_text(
        "🗑️ <b>Which channel would you like to remove?</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )


async def mychannels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all channels - /mychannels"""
    if not await check_force_sub(update, context):
        return
    
    user_id = update.effective_user.id
    channels = get_user_channels(user_id)
    
    if not channels:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Channel", callback_data="add_new_channel")]
        ])
        return await update.message.reply_text(
            "📢 <b>YOUR CHANNELS</b>\n\n"
            "⚠️ You have not added any channels yet!\n\n"
            "📌 <b>Add a channel:</b>\n"
            "1. Add the bot to your channel as an administrator\n"
            "2. <code>/setchannel -100xxxxxxxxxx</code>\n\n"
            "or use the button below 👇",
            reply_markup=kb,
            parse_mode="HTML"
        )
    
    text = f"📢 <b>YOUR CHANNELS ({len(channels)})</b>\n\n"
    buttons = []
    bot_username = get_bot_username()
    
    for i, ch in enumerate(channels, 1):
        try:
            chat = await context.bot.get_chat(int(ch))
            text += f"{i}. <b>{chat.title}</b>\n   <code>{ch}</code>\n\n"
            buttons.append([
                InlineKeyboardButton(f"{chat.title}", callback_data="noop"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"rmch_{ch}")
            ])
        except:
            text += f"{i}. <code>{ch}</code>\n\n"
            buttons.append([
                InlineKeyboardButton(f"{ch}", callback_data="noop"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"rmch_{ch}")
            ])
    
    buttons.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_new_channel")])
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel action"""
    await update.callback_query.message.delete()


async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel remove button"""
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "cancel":
        await query.answer("Cancelled")
        try:
            await query.message.delete()
        except Exception:
            pass
        return
    
    if query.data == "add_channel":
        await query.answer()
        bot_username = get_bot_username()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Bot To Channel", url=f"https://t.me/{bot_username}?startchannel=true")]
        ])
        await query.message.edit_text(
            "➕ <b>Add a Channel</b>\n\n"
            "<b>STEP 1:</b> Tap the button above\n"
            "<b>STEP 2:</b> Make the bot an administrator (enable Edit Messages)\n"
            "<b>STEP 3:</b> Send the channel ID:\n"
            "<code>/setchannel -100xxxxxxxxxx</code>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return
    
    if query.data.startswith("rmch_"):
        channel_id = query.data.removeprefix("rmch_").strip()
        if remove_user_channel(user_id, channel_id):
            remaining = get_user_channels(user_id)
            await query.answer(f"✅ Removed! {len(remaining)} channels left", show_alert=True)
            # Delete old message and show updated list
            try:
                await query.message.delete()
            except:
                pass
            # Send updated channels list
            bot_username = get_bot_username()
            if remaining:
                text = f"📢 <b>Your Channels ({len(remaining)})</b>\n\n"
                buttons = []
                for ch in remaining:
                    try:
                        chat = await context.bot.get_chat(int(ch))
                        text += f"• <b>{chat.title}</b>\n  <code>{ch}</code>\n"
                        buttons.append([
                            InlineKeyboardButton(f"{chat.title}", callback_data="noop"),
                            InlineKeyboardButton("🗑️ Delete", callback_data=f"rmch_{ch}")
                        ])
                    except:
                        text += f"• <code>{ch}</code>\n"
                        buttons.append([
                            InlineKeyboardButton(f"{ch}", callback_data="noop"),
                            InlineKeyboardButton("🗑️ Delete", callback_data=f"rmch_{ch}")
                        ])
                buttons.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_new_channel")])
                kb = InlineKeyboardMarkup(buttons)
            else:
                text = (
                    "📢 <b>My Channels</b>\n\n"
                    "⚠️ All channels have been removed!\n\n"
                    "📌 Add a new channel:"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add Channel", callback_data="add_new_channel")]
                ])
            
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        else:
            await query.answer("⚠️ This channel was already removed or was not saved for your account.", show_alert=True)


"""═══════════════════ CHANNEL POST HANDLER (GUARANTEED QUEUE) ═══════════════════"""


class GuaranteedCoverQueue:
    """Ensures EVERY video gets cover - per-channel 3sec + global 30/sec"""
    
    def __init__(self):
        self.queues = defaultdict(list)
        self.processing = defaultdict(bool)
        self.locks = defaultdict(asyncio.Lock)
        self.last_edit = {}
    
    async def add(self, channel_id, message_id, video_file_id, caption, caption_entities, cover, context):
        item = {
            "channel_id": channel_id,
            "message_id": message_id,
            "video_file_id": video_file_id,
            "caption": caption,
            "caption_entities": caption_entities,
            "cover": cover,
            "context": context,
            "attempt": 0,
            "max_attempts": 10
        }
        self.queues[channel_id].append(item)
        logger.info(f"📥 Queued: ch={channel_id} msg={message_id} (queue: {len(self.queues[channel_id])})")
        
        # Use lock to prevent race condition
        async with self.locks[channel_id]:
            if not self.processing[channel_id]:
                asyncio.create_task(self._process(channel_id))
    
    async def _wait_channel_rate(self, channel_id):
        """Wait 3 seconds between edits per channel"""
        async with self.locks[channel_id]:
            now = time.time()
            last = self.last_edit.get(channel_id, 0)
            wait = max(0, 3.0 - (now - last))
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_edit[channel_id] = time.time()
    
    async def _process(self, channel_id):
        async with self.locks[channel_id]:
            self.processing[channel_id] = True
        
        while True:
            if not self.queues[channel_id]:
                break
            
            item = self.queues[channel_id].pop(0)
            item["attempt"] += 1
            
            try:
                # Per-channel 3 second rate limit
                await self._wait_channel_rate(channel_id)
                
                # Global rate limit via rate_limiter (30/sec)
                media = InputMediaVideo(
                    media=item["video_file_id"],
                    caption=item["caption"],
                    caption_entities=item["caption_entities"],
                    supports_streaming=True,
                    cover=item["cover"]
                )
                
                await rate_limiter.add(
                    item["context"].bot.edit_message_media,
                    chat_id=int(item["channel_id"]),
                    message_id=item["message_id"],
                    media=media
                )
                logger.info(f"✅ Cover: ch={channel_id} msg={item['message_id']} | Left: {len(self.queues[channel_id])}")
                    
            except Exception as e:
                err = str(e).lower()
                if "429" in err or "flood" in err:
                    wait = 35
                    try:
                        if "retry after" in err:
                            wait = int(err.split("retry after")[1].strip().split()[0]) + 2
                    except:
                        pass
                    logger.warning(f"⚠️ Flood ch={channel_id}, retry in {wait}s (attempt {item['attempt']})")
                    self.queues[channel_id].insert(0, item)  # Put back at front
                    await asyncio.sleep(wait)
                elif "message to edit not found" in err or "not modified" in err:
                    logger.debug(f"⏭️ Skip msg={item['message_id']} (not found)")
                else:
                    if item["attempt"] < item["max_attempts"]:
                        self.queues[channel_id].append(item)  # Re-queue at end
                        await asyncio.sleep(2)
                    else:
                        logger.error(f"❌ GAVE UP msg={item['message_id']}: {e}")
        
        async with self.locks[channel_id]:
            self.processing[channel_id] = False
        logger.info(f"🏁 Queue done: ch={channel_id}")

queue = GuaranteedCoverQueue()


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video posts - GUARANTEED cover on every video"""
    channel_post = update.channel_post or update.edited_channel_post
    if not channel_post or not channel_post.video:
        return

    channel_id = str(channel_post.chat.id)
    message_id = channel_post.message_id

    owner_user_id = get_user_by_channel(channel_id)
    if not owner_user_id:
        return

    cover = get_thumbnail(owner_user_id)
    if not cover:
        return

    await queue.add(
        channel_id=channel_id,
        message_id=message_id,
        video_file_id=channel_post.video.file_id,
        caption=channel_post.caption or "",
        caption_entities=channel_post.caption_entities,
        cover=cover,
        context=context
    )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_sub(update, context):
        return
    user_id = update.message.from_user.id
    photo_id = update.message.photo[-1].file_id
    
    # Check if replacing
    old_thumbnail = get_thumbnail(user_id)
    is_replace = old_thumbnail is not None
    
    save_thumbnail(user_id, photo_id)
    logger.info(f"✅ Thumbnail saved to MongoDB for user {user_id}")
    
    action_text = "ᴜᴘᴅᴀᴛᴇᴅ" if is_replace else "sᴀᴠᴇᴅ"
    await update.message.reply_text("✅ ᴛʜᴜᴍʙɴᴀɪʟ " + action_text + "\n\nʀᴇᴀᴅʏ! sᴇɴᴅ ᴀɴʏ ᴠɪᴅᴇᴏ ᴛᴏ ᴀᴘᴘʟʏ ᴄᴏᴠᴇʀ", reply_to_message_id=update.message.message_id, parse_mode="HTML")

async def _process_video(update: Update, context: ContextTypes.DEFAULT_TYPE, msg):
    """Process video and send back with cover (used by video_dm_queue)"""
    user_id = update.message.from_user.id
    cover = get_thumbnail(user_id)
    video = update.message.video.file_id
    original_caption = update.message.caption or ""
    caption_entities = bold_entities(original_caption)
    
    media = InputMediaVideo(media=video, caption=original_caption, caption_entities=caption_entities, supports_streaming=True, cover=cover)
    
    await context.bot.edit_message_media(chat_id=update.effective_chat.id, message_id=msg.message_id, media=media)
    
    logger.debug(f"✅ Video processed for user {user_id}")


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video - sequential per user via video_dm_queue"""
    if not await check_force_sub(update, context):
        return
    user_id = update.message.from_user.id
    cover = get_thumbnail(user_id)
    if not cover:
        return await update.message.reply_text("❌ ɴᴏ ᴛʜᴜᴍʙɴᴀɪʟ ꜰᴏᴜɴᴅ\n\nꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ꜰɪʀsᴛ ᴛᴏ sᴀᴠᴇ ᴛʜᴜᴍʙɴᴀɪʟ", reply_to_message_id=update.message.message_id, parse_mode="HTML")
    
    # Send processing message
    msg = await update.message.reply_text("⏳ ᴘʀᴏᴄᴇssɪɴɢ ᴠɪᴅᴇᴏ\n\nᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...", reply_to_message_id=update.message.message_id, parse_mode="HTML")
    
    # Add to user's sequential queue - videos come in order
    await video_dm_queue.add(user_id, _process_video, update, context, msg)


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart the running bot process without modifying repository files."""
    if not await check_admin(update):
        return

    msg = await update.message.reply_text(
        "🔄 <b>Restarting bot...</b>\n\n"
        "Please wait a few seconds.",
        parse_mode="HTML",
    )
    try:
        logger.info("Owner requested a bot process restart")
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        logger.error(f"Bot restart failed: {e}", exc_info=True)
        await msg.edit_text(
            "❌ <b>Restart failed.</b>\n\n"
            "Check the deployment logs for details.",
            parse_mode="HTML",
        )


"""═══════════════════ ADMIN COMMANDS ═══════════════════"""

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin control panel"""
    if not await check_admin(update):
        return
    
    text = (
        "🛡️ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ\n\n"
        "👑 <b>ᴡᴇʟᴄᴏᴍᴇ ᴀᴅᴍɪɴ</b>\n\n"
        "<b>ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ᴛᴏᴏʟs ᴀᴠᴀɪʟᴀʙʟᴇ:</b>\n\n"
        "📊 <b>sᴛᴀᴛɪsᴛɪᴄs</b> – ᴜsᴇʀ ᴀɴᴀʟʏᴛɪᴄs\n"
        "⏱️ <b>sᴛᴀᴛᴜs</b> – ʙᴏᴛ ᴘᴇʀꜰᴏʀᴍᴀɴᴄᴇ\n"
        "👥 <b>ᴜsᴇʀs</b> – ᴛᴏᴛᴀʟ ᴜsᴇʀs ᴄᴏᴜɴᴛ\n"
        "🚫 <b>ʙᴀɴ ᴜsᴇʀ</b> – ʙʟᴏᴄᴋ ᴜsᴇʀs\n"
        "✅ <b>ᴜɴʙᴀɴ ᴜsᴇʀ</b> – ʀᴇsᴛᴏʀᴇ ᴀᴄᴄᴇss\n"
        "📢 <b>ʙʀᴏᴀᴅᴄᴀsᴛ</b> – sᴇɴᴅ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛs\n\n"
        "sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ:"
    )
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 sᴛᴀᴛɪsᴛɪᴄs", callback_data="admin_stats"),
         InlineKeyboardButton("⏱️ sᴛᴀᴛᴜs", callback_data="admin_status")],
        [InlineKeyboardButton("👥 ᴜsᴇʀs", callback_data="admin_users"),
         InlineKeyboardButton("🚫 ʙᴀɴ ᴜsᴇʀ", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ ᴜɴʙᴀɴ ᴜsᴇʀ", callback_data="admin_unban"),
         InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data="menu_back")],
    ])
    
    # Get home menu banner
    banner = HOME_MENU_BANNER_URL
    
    if banner:
        try:
            if isinstance(banner, str) and os.path.isfile(banner):
                await update.message.reply_photo(
                    photo=InputFile(banner),
                    caption=text,
                    reply_markup=admin_kb,
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_photo(
                    photo=banner,
                    caption=text,
                    reply_markup=admin_kb,
                    parse_mode="HTML"
                )
            return
        except Exception as e:
            logger.warning(f"Could not send admin menu banner: {e}")
    
    await update.message.reply_text(text, reply_markup=admin_kb, parse_mode="HTML")


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user - usage: /ban user_id reason"""
    if not await check_admin(update):
        return
    
    args = update.message.text.split(None, 2)
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ ᴜsᴀɢᴇ: /ʙᴀɴ <ᴜsᴇʀ_ɪᴅ> [ʀᴇᴀsᴏɴ]\n"
            "📌 ᴇxᴀᴍᴘʟᴇ: /ʙᴀɴ 123456789 sᴘᴀᴍ"
        )
    
    try:
        user_id = int(args[1])
        reason = args[2] if len(args) > 2 else "No reason"
        
        if ban_user(user_id, reason):
            await update.message.reply_text(
                "✅ ᴜsᴇʀ " + str(user_id) + " ʙᴀɴɴᴇᴅ\n"
                f"📌 ʀᴇᴀsᴏɴ: {reason}",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ʙᴀɴ ᴜsᴇʀ")
    except ValueError:
        await update.message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜsᴇʀ ɪᴅ")
    except Exception as e:
        await update.message.reply_text("❌ ᴇʀʀᴏʀ: " + str(e))


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban a user - usage: /unban user_id"""
    if not await check_admin(update):
        return
    
    args = update.message.text.split()
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ ᴜsᴀɢᴇ: /ᴜɴʙᴀɴ <ᴜsᴇʀ_ɪᴅ>\n"
            "📌 ᴇxᴀᴍᴘʟᴇ: /ᴜɴʙᴀɴ 123456789"
        )
    
    try:
        user_id = int(args[1])
        if unban_user(user_id):
            await update.message.reply_text("✅ ᴜsᴇʀ " + str(user_id) + " ᴜɴʙᴀɴɴᴇᴅ")
        else:
            await update.message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ᴜɴʙᴀɴ ᴜsᴇʀ")
    except ValueError:
        await update.message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜsᴇʀ ɪᴅ")
    except Exception as e:
        await update.message.reply_text("❌ ᴇʀʀᴏʀ: " + str(e))


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    if not await check_admin(update):
        return
    
    stats = get_stats()
    text = (
        "📊 ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs\n\n"
        f"👥 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {stats['total_users']}\n"
        f"🚫 ʙᴀɴɴᴇᴅ ᴜsᴇʀs: {stats['banned_users']}\n"
        f"🖼 ᴜsᴇʀs ᴡɪᴛʜ ᴛʜᴜᴍʙɴᴀɪʟ: {stats['users_with_thumbnail']}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show advanced bot, hosting, and database health statistics."""
    if not await check_admin(update):
        return

    status_message = await update.message.reply_text("⏳ Collecting system statistics...")

    try:
        import platform
        import psutil
        import telegram

        ping_started_at = time.perf_counter()
        await status_message.edit_text("⏳ Measuring Telegram and server health...")
        telegram_ping_ms = (time.perf_counter() - ping_started_at) * 1000

        # Run blocking system and database probes outside the bot event loop.
        cpu_percent, database_health = await asyncio.gather(
            asyncio.to_thread(psutil.cpu_percent, 0.5),
            asyncio.to_thread(get_database_health),
        )

        process = psutil.Process(os.getpid())
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        logical_cores = psutil.cpu_count(logical=True) or 0
        physical_cores = psutil.cpu_count(logical=False) or logical_cores
        process_memory = process.memory_info().rss

        bot_uptime = max(0, int(time.time() - BOT_STARTED_AT))
        server_uptime = max(0, int(time.time() - psutil.boot_time()))

        def format_duration(total_seconds: int) -> str:
            days, remainder = divmod(total_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{days}d {hours:02d}h {minutes:02d}m {seconds:02d}s"

        def format_size(size_bytes: int) -> str:
            size = float(size_bytes)
            for unit in ("B", "KB", "MB", "GB", "TB"):
                if size < 1024 or unit == "TB":
                    return f"{size:.2f} {unit}"
                size /= 1024
            return "0 B"

        def progress_bar(percentage: float, length: int = 10) -> str:
            safe_percentage = max(0.0, min(100.0, percentage))
            filled = round(safe_percentage / 100 * length)
            return "█" * filled + "░" * (length - filled)

        database_text = "🔴 Disconnected"
        if database_health["connected"]:
            database_text = (
                f"🟢 Connected ({database_health['latency_ms']:.1f} ms)"
            )

        text = (
            "⏱️ <b>Advanced Bot Status</b>\n\n"
            "🟢 <b>Status:</b> Online\n"
            f"📡 <b>Telegram API:</b> {telegram_ping_ms:.1f} ms\n"
            f"🗄️ <b>MongoDB:</b> {database_text}\n\n"
            "⌛ <b>Uptime</b>\n"
            f"├ <b>Bot:</b> {format_duration(bot_uptime)}\n"
            f"└ <b>Server:</b> {format_duration(server_uptime)}\n\n"
            "🖥️ <b>CPU</b>\n"
            f"├ <code>{progress_bar(cpu_percent)}</code> {cpu_percent:.1f}%\n"
            f"└ <b>Cores:</b> {physical_cores} physical / {logical_cores} logical\n\n"
            "🧠 <b>RAM</b>\n"
            f"├ <code>{progress_bar(ram.percent)}</code> {ram.percent:.1f}%\n"
            f"├ <b>Used:</b> {format_size(ram.used)}\n"
            f"├ <b>Available:</b> {format_size(ram.available)}\n"
            f"└ <b>Total:</b> {format_size(ram.total)}\n\n"
            "💾 <b>Disk</b>\n"
            f"├ <code>{progress_bar(disk.percent)}</code> {disk.percent:.1f}%\n"
            f"├ <b>Used:</b> {format_size(disk.used)}\n"
            f"├ <b>Free:</b> {format_size(disk.free)}\n"
            f"└ <b>Total:</b> {format_size(disk.total)}\n\n"
            "⚙️ <b>Runtime</b>\n"
            f"├ <b>Bot memory:</b> {format_size(process_memory)}\n"
            f"├ <b>Python:</b> {platform.python_version()}\n"
            f"└ <b>PTB:</b> {telegram.__version__}"
        )
        await status_message.edit_text(text, parse_mode="HTML")
    except ImportError:
        text = (
            "⏱️ <b>Bot Status</b>\n\n"
            "🟢 <b>Status:</b> Online\n\n"
            "⚠️ Install <code>psutil</code> to view system resource usage."
        )
        await status_message.edit_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Status command failed: {e}", exc_info=True)
        await status_message.edit_text("❌ Failed to collect system statistics.")


def _format_speed(bits_per_second: float) -> str:
    """Convert speedtest bits/second to a readable bytes/second value."""
    size = float(bits_per_second or 0) / 8
    for unit in ("B/s", "KB/s", "MB/s", "GB/s", "TB/s"):
        if size < 1024 or unit == "TB/s":
            return f"{size:.2f} {unit}"
        size /= 1024
    return "0 B/s"


def _format_transfer_size(size_bytes: int) -> str:
    """Format transferred bytes using binary units."""
    size = float(size_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return "0 B"


def _safe_speedtest_value(value, fallback: str = "Unknown") -> str:
    """Escape external speedtest metadata before using Telegram HTML."""
    if value is None or value == "":
        return fallback
    return escape(str(value))


def _download_speedtest_image(image_url: str) -> BytesIO:
    """Download the shared result image before uploading it to Telegram."""
    request = Request(
        image_url,
        headers={"User-Agent": "Mozilla/5.0 VideoCoverBot/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        image_data = response.read(10 * 1024 * 1024 + 1)

    if not image_data:
        raise ValueError("Speed test image response was empty")
    if len(image_data) > 10 * 1024 * 1024:
        raise ValueError("Speed test image exceeded 10 MB")

    image = BytesIO(image_data)
    image.name = "speedtest.png"
    image.seek(0)
    return image


async def speedtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run an owner-only Ookla-compatible server speed test."""
    if not await check_admin(update):
        return

    if speedtest_lock.locked():
        return await update.message.reply_text(
            "⚠️ A speed test is already running. Please wait for it to finish."
        )

    progress = await update.message.reply_text(
        "🚀 <b>Speed Test Started</b>\n\n"
        "🔎 Selecting the best server...",
        parse_mode="HTML",
    )

    async with speedtest_lock:
        try:
            from speedtest import Speedtest

            test = await asyncio.to_thread(Speedtest, secure=True)
            await asyncio.to_thread(test.get_best_server)

            await progress.edit_text(
                "🚀 <b>Speed Test Running</b>\n\n"
                "⬇️ Measuring download speed...",
                parse_mode="HTML",
            )
            await asyncio.to_thread(test.download)

            await progress.edit_text(
                "🚀 <b>Speed Test Running</b>\n\n"
                "⬆️ Measuring upload speed...",
                parse_mode="HTML",
            )
            await asyncio.to_thread(test.upload)

            share_url = None
            try:
                await progress.edit_text(
                    "🚀 <b>Speed Test Complete</b>\n\n"
                    "🖼️ Generating the result image...",
                    parse_mode="HTML",
                )
                share_url = await asyncio.to_thread(test.results.share)
            except Exception as share_error:
                logger.warning(f"Could not generate speed test image: {share_error}")

            result = test.results.dict()
            share_url = share_url or result.get("share")

            server = result.get("server") or {}
            client = result.get("client") or {}
            server_country = ", ".join(
                item for item in (
                    _safe_speedtest_value(server.get("country"), ""),
                    _safe_speedtest_value(server.get("cc"), ""),
                )
                if item
            ) or "Unknown"

            text = (
                "╭─《 🚀 <b>SPEEDTEST INFO</b> 》\n"
                f"├ <b>Upload:</b> <code>{_format_speed(result.get('upload', 0))}</code>\n"
                f"├ <b>Download:</b> <code>{_format_speed(result.get('download', 0))}</code>\n"
                f"├ <b>Ping:</b> <code>{float(result.get('ping') or 0):.3f} ms</code>\n"
                f"├ <b>Time:</b> <code>{_safe_speedtest_value(result.get('timestamp'))}</code>\n"
                f"├ <b>Data Sent:</b> <code>{_format_transfer_size(result.get('bytes_sent', 0))}</code>\n"
                f"╰ <b>Data Received:</b> <code>{_format_transfer_size(result.get('bytes_received', 0))}</code>\n\n"
                "╭─《 🌐 <b>SPEEDTEST SERVER</b> 》\n"
                f"├ <b>Name:</b> <code>{_safe_speedtest_value(server.get('name'))}</code>\n"
                f"├ <b>Country:</b> <code>{server_country}</code>\n"
                f"├ <b>Sponsor:</b> <code>{_safe_speedtest_value(server.get('sponsor'))}</code>\n"
                f"├ <b>Latency:</b> <code>{_safe_speedtest_value(server.get('latency'))} ms</code>\n"
                f"├ <b>Latitude:</b> <code>{_safe_speedtest_value(server.get('lat'))}</code>\n"
                f"╰ <b>Longitude:</b> <code>{_safe_speedtest_value(server.get('lon'))}</code>\n\n"
                "╭─《 👤 <b>CLIENT DETAILS</b> 》\n"
                f"├ <b>IP Address:</b> <code>{_safe_speedtest_value(client.get('ip'))}</code>\n"
                f"├ <b>Latitude:</b> <code>{_safe_speedtest_value(client.get('lat'))}</code>\n"
                f"├ <b>Longitude:</b> <code>{_safe_speedtest_value(client.get('lon'))}</code>\n"
                f"├ <b>Country:</b> <code>{_safe_speedtest_value(client.get('country'))}</code>\n"
                f"├ <b>ISP:</b> <code>{_safe_speedtest_value(client.get('isp'))}</code>\n"
                f"├ <b>ISP Rating:</b> <code>{_safe_speedtest_value(client.get('isprating'))}</code>\n"
                "╰ <b>Powered by Nexon Bots</b>"
            )

            if share_url:
                try:
                    speedtest_image = await asyncio.to_thread(
                        _download_speedtest_image,
                        share_url,
                    )
                    await update.message.reply_photo(
                        photo=InputFile(speedtest_image, filename="speedtest.png"),
                        caption=text,
                        parse_mode="HTML",
                        read_timeout=60,
                        write_timeout=60,
                        connect_timeout=30,
                    )
                    await progress.delete()
                except Exception as photo_error:
                    logger.warning(f"Could not send speed test image: {photo_error}")
                    await progress.edit_text(text, parse_mode="HTML")
            else:
                await progress.edit_text(text, parse_mode="HTML")
        except ImportError:
            await progress.edit_text(
                "❌ <b>Speed test dependency is missing.</b>\n\n"
                "Install <code>speedtest-cli</code> and restart the bot.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Speed test failed: {e}", exc_info=True)
            await progress.edit_text(
                "❌ <b>Speed test failed.</b>\n\n"
                "The test server may be unavailable. Please try again later.",
                parse_mode="HTML",
            )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users - usage: /broadcast <message>"""
    if not await check_admin(update):
        return
    
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ ᴜsᴀɢᴇ: /ʙʀᴏᴀᴅᴄᴀsᴛ <ᴍᴇssᴀɢᴇ>\n\n"
            "📌 ᴇxᴀᴍᴘʟᴇ: /ʙʀᴏᴀᴅᴄᴀsᴛ ʜᴇʟʟᴏ ᴇᴠᴇʀʏᴏɴᴇ!\\n\\n"
            "💡 ᴛɪᴘs:\\n"
            "• ᴍᴇssᴀɢᴇ sᴇɴᴛ ᴛᴏ ᴀʟʟ ᴜsᴇʀs\\n"
            "• ʜᴛᴍʟ ꜰᴏʀᴍᴀᴛᴛɪɴɢ sᴜᴘᴘᴏʀᴛᴇᴅ\\n"
            "• ᴇᴍᴏᴊɪs ᴡᴏʀᴋ ɢʀᴇᴀᴛ ᴛᴏᴏ",
            parse_mode="HTML"
        )
    
    message_text = args[1]
    
    # Show confirmation
    confirm_text = (
        "📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏɴꜰɪʀᴍᴀᴛɪᴏɴ\n\n"
        f"📝 ᴍᴇssᴀɢᴇ:\\n"
        f"{message_text}\n\n"
        f"👥 ᴛᴏᴛᴀʟ ᴜsᴇʀs: {get_total_users()}\n\n"
        "⚠️ ᴘʀᴏᴄᴇssɪɴɢ... sᴇɴᴅɪɴɢ ɴᴏᴡ"
    )
    msg = await update.message.reply_text(confirm_text, parse_mode="HTML")
    
    try:
        # Get every unique user registered through /start.
        user_ids = get_all_user_ids()
        
        if not user_ids:
            await msg.edit_text(
                "❌ ɴᴏ ᴜsᴇʀs ꜰᴏᴜɴᴅ\n\n"
                "💭 ᴅᴀᴛᴀʙᴀsᴇ ɪs ᴇᴍᴘᴛʏ",
                parse_mode="HTML"
            )
            return
        
        # Send message to all users via rate limiter
        sent = 0
        failed = 0
        
        for user_id in user_ids:
            try:
                await rate_limiter.add(
                    context.bot.send_message,
                    chat_id=user_id,
                    text=f"📢 <b>Announcement from Admin</b>\n\n{message_text}",
                    parse_mode="HTML"
                )
                sent += 1
            except Exception as e:
                logger.warning(f"Could not send broadcast to user {user_id}: {e}")
                failed += 1
        
        # Show final status
        result_text = (
            "✅ ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ\n\n"
            f"📤 sᴇɴᴛ: {sent}\n"
            f"❌ ꜰᴀɪʟᴇᴅ: {failed}\n"
            f"👥 ᴛᴏᴛᴀʟ: {sent + failed}\n\n"
            f"📊 sᴜᴄᴄᴇss: {(sent/(sent+failed)*100):.1f}%" if (sent + failed) > 0 else "📊 sᴜᴄᴄᴇss: 0%"
        )
        
        await msg.edit_text(result_text, parse_mode="HTML")
        
    except Exception as e:
        await msg.edit_text(
            f"❌ ʙʀᴏᴀᴅᴄᴀsᴛ ꜰᴀɪʟᴇᴅ\\n\\n"
            f"ᴇʀʀᴏʀ: {str(e)[:100]}\\n\\n"
            "ᴄʜᴇᴄᴋ ʟᴏɢs ꜰᴏʀ ᴅᴇᴛᴀɪʟs.",
            parse_mode="HTML"
        )
        logger.error(f"Broadcast error: {e}", exc_info=True)



async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages - guide users"""
    if not await check_force_sub(update, context):
        return
    
    # Send helpful guidance
    await update.message.reply_text(
        "🤔 <b>I did not understand that!</b>\n\n"
        "📌 <b>Use one of these commands:</b>\n"
        "/start - Start the bot\n"
        "/help - View help\n"
        "/settings - Manage your thumbnail\n"
        "/setchannel - Add a channel\n"
        "/mychannels - View your channels\n\n"
        "💡 <b>Tip:</b> Send an image to save it as your thumbnail!",
        parse_mode="HTML"
    )


"""-----------CALLBAck Hnadlers--------"""


def main() -> None:
    global BOT_USERNAME

    start_health_server()
    app = Application.builder().token(TOKEN).build()

    # Global error handler
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log all errors"""
        logger.error(f"🔴 ERROR: {context.error}", exc_info=context.error)

    app.add_error_handler(error_handler)
    
    # Setup bot commands on startup
    async def setup_commands(app: Application) -> None:
        """Setup bot commands menu"""
        global BOT_USERNAME
        from telegram import BotCommand
        
        # Auto-detect bot username
        try:
            me = await app.bot.get_me()
            BOT_USERNAME = me.username
            logger.info(f"🤖 Bot username: @{BOT_USERNAME}")
        except Exception as e:
            logger.error(f"❌ Error getting bot info: {e}")
        
        commands = [
            BotCommand("start", "🏠 Start bot"),
            BotCommand("help", "ℹ️ How to use bot"),
            BotCommand("about", "🤖 About bot"),
            BotCommand("settings", "⚙️ Bot settings"),
            BotCommand("remove", "🗑️ Remove thumbnail"),
            BotCommand("setchannel", "➕ Add channel"),
            BotCommand("removechannel", "🗑️ Remove channel"),
            BotCommand("mychannels", "📢 My channels"),
            BotCommand("admin", "🛡️ Admin panel"),
            BotCommand("ban", "🚫 Ban user"),
            BotCommand("unban", "✅ Unban user"),
            BotCommand("stats", "📊 Bot statistics"),
            BotCommand("status", "⏱️ Bot status"),
            BotCommand("speedtest", "🚀 Server speed test"),
            BotCommand("restart", "🔄 Restart bot"),
            BotCommand("broadcast", "📢 Broadcast message"),
        ]
        
        try:
            await app.bot.set_my_commands(commands)
            logger.info("✅ Bot commands configured successfully")
        except Exception as e:
            logger.error(f"❌ Error setting bot commands: {e}")
    
    # Register post_init callback to setup commands
    app.post_init = setup_commands

    # Command handlers (MUST be registered FIRST before text handler)
    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("help", help_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("about", about, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("settings", settings, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("remove", remover, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("restart", restart, filters=filters.ChatType.PRIVATE))
    
    # Admin commands
    app.add_handler(CommandHandler("admin", admin_menu, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("ban", ban_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("unban", unban_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("stats", stats_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("status", status_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("speedtest", speedtest_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd, filters=filters.ChatType.PRIVATE))
    
    # Channel setup commands
    app.add_handler(CommandHandler("setchannel", setchannel_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("removechannel", removechannel_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("mychannels", mychannels_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("mychannel", mychannels_cmd, filters=filters.ChatType.PRIVATE))  # Alias

    # Photo and video handlers (private chats only via filters)
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, video_handler))
    
    # Channel post handler (for auto-applying cover in channels)
    app.add_handler(MessageHandler(filters.VIDEO & (filters.ChatType.CHANNEL), channel_post_handler))
    
    # Text handler for dump channel ID capture (MUST be LAST - only non-command text)
    # Add filter to exclude commands (messages starting with /)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text_handler))
    
    # Register callback handler (handles all callbacks)
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("✅ All handlers registered")
    logger.info("Bot starting (polling)")
    app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
            "channel_post",
            "edited_channel_post",
        ],
        close_loop=False,
    )


if __name__ == "__main__":
    main()
