#!/usr/bin/env python3
"""
Telegram Transcript Exporter

Export a Telegram private chat / group / channel via Telethon or from a Telegram Desktop
JSON export into a compact, token-efficient transcript format for LLM analysis.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetForumTopicsRequest
from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
    User,
)

# Load environment variables from .env file
load_dotenv()

# URL regex pattern
URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")

# Format version
TRANSCRIPT_VERSION = "v1"
TRANSCRIPT_HEADER = (
    f"TG-TRANSCRIPT {TRANSCRIPT_VERSION}: "
    "Format: CHAT line, AUTHORS section (CODE=Name), LINKS section ([L#]=url), "
    "BODY with date headers (YYYY-MM-DD), turns as [HH:MM][#MSGID] CODE[OP][REF]:text. "
    "OP: ↩=reply, ↪=forward. Media: 📎(type:name details)."
)


def generate_author_code(name: str | None, existing_codes: set[str]) -> str:
    """Generate a short unique code for an author."""
    if not name:
        name = "Unknown"

    # Try first letter uppercase
    code = name[0].upper()
    if code.isalpha() and code not in existing_codes:
        return code

    # Try first two letters
    if len(name) >= 2:
        code = name[:2].upper()
        if code not in existing_codes:
            return code

    # Try consonants
    consonants = "".join(c for c in name.upper() if c in "BCDFGHJKLMNPQRSTVWXYZ")
    if consonants and consonants[0] not in existing_codes:
        return consonants[0]

    # Fallback: first letter + number
    base = name[0].upper() if name[0].isalpha() else "U"
    i = 1
    while f"{base}{i}" in existing_codes:
        i += 1
    return f"{base}{i}"


def format_file_size(size_bytes: int | None) -> str:
    """Format file size in human-readable format."""
    if size_bytes is None:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def format_duration(seconds: int | None) -> str:
    """Format duration in MM:SS format."""
    if seconds is None:
        return ""
    mins, secs = divmod(int(seconds), 60)
    return f"{mins:02d}:{secs:02d}"


class Author:
    """Represents a message author."""

    def __init__(
        self,
        user_id: int | str,
        display_name: str,
        username: str | None = None,
        is_channel: bool = False,
    ):
        self.user_id = user_id
        self.display_name = display_name
        self.username = username
        self.is_channel = is_channel
        self.code: str = ""

    def format_line(self) -> str:
        """Format author for the AUTHORS section."""
        username_part = f"@{self.username}" if self.username else "none"
        id_prefix = "channel" if self.is_channel else "user"
        return f"  {self.code}={self.display_name} ({username_part}) ({id_prefix}{self.user_id})"


class Message:
    """Represents a chat message."""

    def __init__(
        self,
        msg_id: int,
        author_id: int | str,
        timestamp: datetime,
        text: str,
        reply_to_msg_id: int | None = None,
        forwarded_from_id: int | str | None = None,
        media: list[dict] | None = None,
    ):
        self.msg_id = msg_id
        self.author_id = author_id
        self.timestamp = timestamp
        self.text = text or ""
        self.reply_to_msg_id = reply_to_msg_id
        self.forwarded_from_id = forwarded_from_id
        self.media = media or []


class TranscriptBuilder:
    """Builds the transcript output."""

    def __init__(
        self,
        chat_title: str,
        chat_id: int | str,
        include_seconds: bool = False,
        merge_window_seconds: int = 0,
        encode_links: bool = True,
    ):
        self.chat_title = chat_title
        self.chat_id = chat_id
        self.include_seconds = include_seconds
        self.merge_window_seconds = merge_window_seconds
        self.encode_links = encode_links

        self.authors: dict[int | str, Author] = {}
        self.messages: list[Message] = []
        self.links: OrderedDict[str, str] = OrderedDict()
        self._link_counter = 0

    def add_author(self, author: Author) -> None:
        """Add an author to the transcript."""
        if author.user_id not in self.authors:
            existing_codes = {a.code for a in self.authors.values()}
            author.code = generate_author_code(author.display_name, existing_codes)
            self.authors[author.user_id] = author

    def add_message(self, message: Message) -> None:
        """Add a message to the transcript."""
        self.messages.append(message)

    def _get_link_code(self, url: str) -> str:
        """Get or create a link code for a URL."""
        if url not in self.links:
            self._link_counter += 1
            self.links[url] = f"L{self._link_counter}"
        return self.links[url]

    def _encode_text(self, text: str) -> str:
        """Encode URLs in text with link codes."""
        if not self.encode_links:
            return text

        def replace_url(match: re.Match) -> str:
            url = match.group(0)
            code = self._get_link_code(url)
            return f"[{code}]"

        return URL_PATTERN.sub(replace_url, text)

    def _format_media(self, media: dict) -> str:
        """Format media attachment."""
        media_type = media.get("type", "file")
        filename = media.get("filename", "unknown")
        size = media.get("size")
        duration = media.get("duration")

        if media_type == "photo":
            return f"📎(photo:{filename})"
        if media_type == "voice":
            dur_str = f" {format_duration(duration)}" if duration else ""
            return f"📎(voice:{filename}{dur_str})"
        if media_type == "video":
            size_str = f" {format_file_size(size)}" if size else ""
            return f"📎(video:{filename}{size_str})"
        # file
        size_str = f" {format_file_size(size)}" if size else ""
        return f"📎(file:{filename}{size_str})"

    def _format_time(self, dt: datetime) -> str:
        """Format timestamp."""
        if self.include_seconds:
            return dt.strftime("%H:%M:%S")
        return dt.strftime("%H:%M")

    def build(self) -> str:
        """Build the complete transcript."""
        lines: list[str] = []

        # Header
        lines.append(TRANSCRIPT_HEADER)
        lines.append("")

        # Chat info
        lines.append(f"CHAT: {self.chat_title} (id={self.chat_id})")
        lines.append("")

        # Sort messages by timestamp
        self.messages.sort(key=lambda m: (m.timestamp, m.msg_id))

        # Collect message IDs that are referenced by replies
        referenced_msg_ids: set[int] = set()
        for msg in self.messages:
            if msg.reply_to_msg_id is not None:
                referenced_msg_ids.add(msg.reply_to_msg_id)

        # First pass: encode all text to collect links
        encoded_messages: list[tuple[Message, str]] = []
        for msg in self.messages:
            text = self._encode_text(msg.text)
            # Add media
            for media in msg.media:
                media_str = self._format_media(media)
                text = f"{text} {media_str}" if text else media_str
            encoded_messages.append((msg, text))

        # Authors section
        lines.append("AUTHORS:")
        for author in self.authors.values():
            lines.append(author.format_line())
        lines.append("")

        # Links section
        lines.append("LINKS:")
        if self.links:
            for url, code in self.links.items():
                lines.append(f"  {code}={url}")
        lines.append("")

        # Body
        lines.append("BODY:")
        current_date: str | None = None
        last_author_id: int | str | None = None
        last_timestamp: datetime | None = None
        merge_buffer: list[str] = []

        def flush_merge_buffer() -> None:
            nonlocal merge_buffer
            if merge_buffer:
                for buffered_line in merge_buffer:
                    lines.append(buffered_line)
                merge_buffer = []

        for msg, text in encoded_messages:
            msg_date = msg.timestamp.strftime("%Y-%m-%d")

            # Check if we need a new date header
            if msg_date != current_date:
                flush_merge_buffer()
                if current_date is not None:
                    lines.append("")
                lines.append(msg_date)
                current_date = msg_date
                last_author_id = None
                last_timestamp = None

            author = self.authors.get(msg.author_id)
            author_code = author.code if author else "?"

            # Determine operation type
            op = ""
            ref = ""
            if msg.forwarded_from_id is not None:
                fwd_author = self.authors.get(msg.forwarded_from_id)
                fwd_code = fwd_author.code if fwd_author else "?"
                op = "↪"
                ref = fwd_code
            elif msg.reply_to_msg_id is not None:
                op = "↩"
                ref = str(msg.reply_to_msg_id)

            # Check if we should merge with previous message
            can_merge = (
                self.merge_window_seconds > 0
                and last_author_id == msg.author_id
                and last_timestamp is not None
                and (msg.timestamp - last_timestamp).total_seconds() <= self.merge_window_seconds
                and not op  # Don't merge replies/forwards
            )

            # Format multiline text
            text_lines = text.split("\n") if text else [""]

            if can_merge:
                # Add to merge buffer as continuation
                for i, line in enumerate(text_lines):
                    if i == 0 and not merge_buffer:
                        # This shouldn't happen but handle it
                        merge_buffer.append(f" {line}")
                    else:
                        merge_buffer.append(f" {line}")
            else:
                flush_merge_buffer()

                # Format the message line
                time_str = self._format_time(msg.timestamp)
                # Show msg_id only if this message is referenced by a reply
                msg_id_str = f"#{msg.msg_id}" if msg.msg_id in referenced_msg_ids else ""

                # Build the turn line
                first_line = text_lines[0]
                if op:
                    turn_line = f"{time_str}{msg_id_str} {author_code}{op}{ref}:{first_line}"
                else:
                    turn_line = f"{time_str}{msg_id_str} {author_code}:{first_line}"

                lines.append(turn_line)

                # Additional lines
                for additional_line in text_lines[1:]:
                    lines.append(f" {additional_line}")

            last_author_id = msg.author_id
            last_timestamp = msg.timestamp

        flush_merge_buffer()

        return "\n".join(lines)


# =============================================================================
# JSON Import (Telegram Desktop Export)
# =============================================================================


def parse_json_export(
    json_path: Path,
    max_messages: int | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> TranscriptBuilder:
    """Parse a Telegram Desktop JSON export."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    chat_name = data.get("name", "Unknown Chat")
    chat_id = data.get("id", 0)

    builder = TranscriptBuilder(chat_title=chat_name, chat_id=chat_id)

    messages_data = data.get("messages", [])

    for msg_data in messages_data:
        # Skip service messages
        if msg_data.get("type") != "message":
            continue

        msg_id = msg_data.get("id", 0)

        # Parse timestamp
        date_str = msg_data.get("date", "")
        try:
            timestamp = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
        except (ValueError, AttributeError):
            timestamp = datetime.now(UTC)

        # Apply date filters
        if from_date and timestamp < from_date:
            continue
        if to_date and timestamp > to_date:
            continue

        # Get author info
        from_name = msg_data.get("from", "Unknown")
        from_id = msg_data.get("from_id", from_name)

        # Handle different from_id formats
        if isinstance(from_id, str):
            if from_id.startswith("user"):
                from_id = int(from_id[4:])
            elif from_id.startswith("channel"):
                from_id = f"ch_{from_id[7:]}"

        # Add author
        author = Author(
            user_id=from_id,
            display_name=from_name,
            username=None,  # Not available in JSON export
            is_channel=isinstance(from_id, str) and str(from_id).startswith("ch_"),
        )
        builder.add_author(author)

        # Parse text content
        text_data = msg_data.get("text", "")
        if isinstance(text_data, list):
            # Rich text format
            text_parts = []
            for part in text_data:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    text_parts.append(part.get("text", ""))
            text = "".join(text_parts)
        else:
            text = str(text_data)

        # Handle reply
        reply_to_msg_id = msg_data.get("reply_to_message_id")

        # Handle forward
        forwarded_from_id = None
        if "forwarded_from" in msg_data:
            fwd_from = msg_data.get("forwarded_from", "")
            forwarded_from_id = f"fwd_{hash(fwd_from) % 100000}"
            # Add forwarded author
            fwd_author = Author(
                user_id=forwarded_from_id,
                display_name=fwd_from,
                is_channel=True,
            )
            builder.add_author(fwd_author)

        # Handle media
        media: list[dict] = []
        if "photo" in msg_data:
            media.append(
                {
                    "type": "photo",
                    "filename": msg_data.get("photo", "photo.jpg").split("/")[-1],
                }
            )
        if "file" in msg_data:
            file_path = msg_data.get("file", "")
            filename = file_path.split("/")[-1] if file_path else "file"
            media_type = msg_data.get("media_type", "")

            if media_type == "voice_message":
                media.append(
                    {
                        "type": "voice",
                        "filename": filename,
                        "duration": msg_data.get("duration_seconds"),
                    }
                )
            elif media_type == "video_file":
                media.append(
                    {
                        "type": "video",
                        "filename": filename,
                        "size": msg_data.get("file_size"),
                    }
                )
            else:
                media.append(
                    {
                        "type": "file",
                        "filename": filename,
                        "size": msg_data.get("file_size"),
                    }
                )

        message = Message(
            msg_id=msg_id,
            author_id=from_id,
            timestamp=timestamp,
            text=text,
            reply_to_msg_id=reply_to_msg_id,
            forwarded_from_id=forwarded_from_id,
            media=media,
        )
        builder.add_message(message)

    # Apply max_messages limit (keep latest N messages)
    if max_messages and len(builder.messages) > max_messages:
        builder.messages = builder.messages[-max_messages:]

    return builder


# =============================================================================
# Telethon Direct Export
# =============================================================================


async def get_forum_topics(client, entity: Channel) -> dict[int, str]:
    """Get forum topics for a channel.
    
    Args:
        client: Telegram client
        entity: Channel entity (must be a forum)
    
    Returns:
        Dictionary mapping topic_id to topic_title
    """
    forum_topics = {}
    try:
        # Get forum topics using official API
        result = await client(GetForumTopicsRequest(
            peer=entity,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100
        ))
        
        # Process forum topics from result
        if hasattr(result, 'topics'):
            for topic in result.topics:
                # Topics are ForumTopic objects with id and title
                if hasattr(topic, 'id') and hasattr(topic, 'title'):
                    forum_topics[topic.id] = topic.title
    except Exception:
        # Silently skip forums where we can't get topics
        pass
    
    return forum_topics


async def search_dialogs(client, query: str) -> None:
    """Search dialogs and print matching results."""
    print(f"Searching for dialogs matching: {query}")
    print("-" * 60)

    query_lower = query.lower()
    found = 0

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        title = dialog.title or dialog.name or ""
        username = getattr(entity, "username", None)

        # Check if query matches dialog title/username
        dialog_matches = (
            query_lower in title.lower()
            or (username and query_lower in username.lower())
        )

        # Check if entity is a forum
        is_forum = (
            isinstance(entity, Channel)
            and not entity.broadcast
            and getattr(entity, "forum", False)
        )

        # For forums, find matching topics
        forum_topics = {}
        matching_topic_ids: set[int] = set()
        if is_forum:
            forum_topics = await get_forum_topics(client, entity)
            matching_topic_ids = {
                tid for tid, t_title in forum_topics.items()
                if query_lower in t_title.lower()
            }

        # Skip if nothing matches
        if not dialog_matches and not matching_topic_ids:
            continue

        found += 1

        # Determine entity type
        if isinstance(entity, User):
            entity_type = "User"
        elif isinstance(entity, Chat):
            entity_type = "Group"
        elif isinstance(entity, Channel):
            if entity.broadcast:
                entity_type = "Channel"
            elif is_forum:
                entity_type = "Forum"
            else:
                entity_type = "Supergroup"
        else:
            entity_type = "Unknown"

        username_str = f"@{username}" if username else ""
        print(f"  [{entity_type}] {title} {username_str} (id={dialog.id})")

        # If it's a forum with topics, list them
        if is_forum and forum_topics:
            print("    Topics:")
            # Show all topics if dialog matches, otherwise only matching topics
            topics_to_show = forum_topics if dialog_matches else {
                tid: forum_topics[tid] for tid in matching_topic_ids
            }
            for topic_id, topic_title in topics_to_show.items():
                print(f"      - {topic_title} (topic_id={topic_id})")

    print("-" * 60)
    print(f"Found {found} matching dialog(s)")
    if found > 0:
        print("\nUse one of the above as --target (id, @username, or title)")


def parse_target_string(target: str) -> tuple[str, int | None]:
    """Parse target string and extract topic_id if present.
    
    Supports format: target/topic_id
    Examples: -1001875939239/40264, @username/12345
    
    Returns:
        tuple: (base_target, topic_id or None)
    """
    if "/" in target:
        parts = target.rsplit("/", 1)
        if len(parts) == 2:
            base_target, topic_str = parts
            try:
                topic_id = int(topic_str)
                return base_target, topic_id
            except ValueError:
                pass
    return target, None


async def resolve_target(client, target: str):
    """Resolve target string to a Telegram entity."""
    # Try as numeric ID
    try:
        entity_id = int(target)
        return await client.get_entity(entity_id)
    except (ValueError, Exception):
        pass

    # Try as username or link
    if target.startswith("@") or target.startswith("t.me/") or target.startswith("https://t.me/"):
        try:
            return await client.get_entity(target)
        except Exception:
            pass

    # Try as dialog title
    async for dialog in client.iter_dialogs():
        title = dialog.title or dialog.name or ""
        if title.lower() == target.lower():
            return dialog.entity

    raise ValueError(f"Could not resolve target: {target}")


async def export_from_telethon(
    client,
    target: str,
    include_seconds: bool = False,
    merge_window_seconds: int = 0,
    encode_links: bool = True,
    max_messages: int | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    topic_id: int | None = None,
) -> TranscriptBuilder:
    """Export chat from Telegram using Telethon."""
    entity = await resolve_target(client, target)

    # Get chat info
    if isinstance(entity, User):
        chat_title = f"{entity.first_name or ''} {entity.last_name or ''}".strip() or "Private Chat"
        chat_id = entity.id
    elif isinstance(entity, (Chat, Channel)):
        chat_title = entity.title or "Chat"
        chat_id = entity.id
    else:
        chat_title = "Chat"
        chat_id = getattr(entity, "id", 0)

    builder = TranscriptBuilder(
        chat_title=chat_title,
        chat_id=chat_id,
        include_seconds=include_seconds,
        merge_window_seconds=merge_window_seconds,
        encode_links=encode_links,
    )

    print(f"Exporting chat: {chat_title} (id={chat_id})")
    print("Fetching messages...")

    msg_count = 0
    exported_count = 0

    # Optimize iteration based on filters
    # If only max_messages without date filters, we can use limit and get latest messages directly
    # If we have date filters, we need to iterate and filter
    use_reverse = from_date is not None  # Need chronological order if filtering by from_date

    iter_kwargs: dict = {"reverse": use_reverse}

    # Use offset_date if to_date is specified (messages before this date)
    if to_date:
        iter_kwargs["offset_date"] = to_date

    # Add topic filter if specified (for forum groups)
    if topic_id:
        iter_kwargs["reply_to"] = topic_id

    # If no date filters and only max_messages, use limit directly for efficiency
    if max_messages and not from_date and not to_date:
        iter_kwargs["limit"] = max_messages
        iter_kwargs["reverse"] = False  # Get latest messages first

    async for msg in client.iter_messages(entity, **iter_kwargs):
        msg_count += 1
        if msg_count % 500 == 0:
            print(f"  Processed {msg_count} messages...")

        # Get timestamp early for filtering
        timestamp = msg.date
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        # Apply date filters
        if from_date and timestamp < from_date:
            continue
        if to_date and timestamp > to_date:
            continue

        # Skip empty service messages
        if msg.action and not msg.text:
            continue

        # Get sender info
        sender = await msg.get_sender()
        if sender is None:
            continue

        if isinstance(sender, User):
            display_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "Unknown"
            username = sender.username
            is_channel = False
            sender_id = sender.id
        elif isinstance(sender, Channel):
            display_name = sender.title or "Channel"
            username = sender.username
            is_channel = True
            sender_id = sender.id
        else:
            display_name = getattr(sender, "title", "Unknown")
            username = getattr(sender, "username", None)
            is_channel = True
            sender_id = getattr(sender, "id", 0)

        author = Author(
            user_id=sender_id,
            display_name=display_name,
            username=username,
            is_channel=is_channel,
        )
        builder.add_author(author)

        # Handle forward
        forwarded_from_id = None
        if msg.forward:
            fwd_sender = msg.forward.sender
            fwd_chat = msg.forward.chat
            fwd_entity = fwd_sender or fwd_chat

            if fwd_entity:
                if isinstance(fwd_entity, User):
                    fwd_name = f"{fwd_entity.first_name or ''} {fwd_entity.last_name or ''}".strip()
                    fwd_username = fwd_entity.username
                    fwd_is_channel = False
                else:
                    fwd_name = getattr(fwd_entity, "title", "Unknown")
                    fwd_username = getattr(fwd_entity, "username", None)
                    fwd_is_channel = True

                forwarded_from_id = fwd_entity.id
                fwd_author = Author(
                    user_id=forwarded_from_id,
                    display_name=fwd_name,
                    username=fwd_username,
                    is_channel=fwd_is_channel,
                )
                builder.add_author(fwd_author)

        # Handle reply
        reply_to_msg_id = msg.reply_to_msg_id if msg.reply_to else None

        # Handle media
        media: list[dict] = []
        if msg.media:
            if isinstance(msg.media, MessageMediaPhoto):
                media.append(
                    {
                        "type": "photo",
                        "filename": f"photo_{msg.id}.jpg",
                    }
                )
            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.media.document
                if doc:
                    filename = "file"
                    duration = None
                    is_voice = False
                    is_video = False

                    for attr in doc.attributes:
                        if isinstance(attr, DocumentAttributeFilename):
                            filename = attr.file_name
                        elif isinstance(attr, DocumentAttributeAudio):
                            duration = attr.duration
                            is_voice = attr.voice
                        elif isinstance(attr, DocumentAttributeVideo):
                            is_video = True

                    if is_voice:
                        media.append(
                            {
                                "type": "voice",
                                "filename": filename,
                                "duration": duration,
                            }
                        )
                    elif is_video:
                        media.append(
                            {
                                "type": "video",
                                "filename": filename,
                                "size": doc.size,
                            }
                        )
                    else:
                        media.append(
                            {
                                "type": "file",
                                "filename": filename,
                                "size": doc.size,
                            }
                        )

        # timestamp already parsed above for filtering

        message = Message(
            msg_id=msg.id,
            author_id=sender_id,
            timestamp=timestamp,
            text=msg.text or "",
            reply_to_msg_id=reply_to_msg_id,
            forwarded_from_id=forwarded_from_id,
            media=media,
        )
        builder.add_message(message)
        exported_count += 1

    # Apply max_messages limit (keep latest N messages)
    if max_messages and len(builder.messages) > max_messages:
        builder.messages = builder.messages[-max_messages:]

    print(f"Total messages processed: {msg_count}, exported: {len(builder.messages)}")
    return builder


async def async_main(args: argparse.Namespace) -> int:
    """Async main function."""
    # Get credentials
    api_id = args.api_id or os.getenv("TELEGRAM_API_ID")
    api_hash = args.api_hash or os.getenv("TELEGRAM_API_HASH")
    session_name = args.session or os.getenv("TELEGRAM_SESSION_NAME", "tg_session")
    session_string = os.getenv("TELEGRAM_SESSION_STRING")

    if not api_id or not api_hash:
        print(
            "Error: API credentials required. Set TELEGRAM_API_ID and TELEGRAM_API_HASH or use --api-id and --api-hash"
        )
        return 1

    api_id = int(api_id)

    # Create client
    session = StringSession(session_string) if session_string else session_name

    client = TelegramClient(session, api_id, api_hash)

    await client.start()

    try:
        if args.search:
            await search_dialogs(client, args.search)
            return 0

        if not args.target:
            print("Error: --target is required when not using --search")
            return 1

        # Parse target string to extract topic_id if present
        base_target, topic_id = parse_target_string(args.target)

        # Parse date filters
        from_date = None
        to_date = None
        if args.from_date:
            from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.to_date:
            # Set to end of day for inclusive filtering
            to_date = datetime.strptime(args.to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)

        builder = await export_from_telethon(
            client,
            base_target,
            include_seconds=args.include_seconds,
            merge_window_seconds=args.merge_window_seconds,
            encode_links=not args.no_link_encoding,
            max_messages=args.max_messages,
            from_date=from_date,
            to_date=to_date,
            topic_id=topic_id,
        )

        # Write output
        transcript = builder.build()
        output_path = Path(args.output)
        output_path.write_text(transcript, encoding="utf-8")
        print(f"Transcript written to: {output_path}")

    finally:
        await client.disconnect()

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export Telegram chats to a compact transcript format for LLM analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Input modes
    input_group = parser.add_argument_group("Input Options")
    input_group.add_argument(
        "--input-json",
        type=str,
        help="Path to Telegram Desktop export JSON file (result.json)",
    )

    # Telethon credentials
    telethon_group = parser.add_argument_group("Telethon Options")
    telethon_group.add_argument(
        "--api-id",
        type=int,
        help="Telegram API ID (or set TELEGRAM_API_ID env var)",
    )
    telethon_group.add_argument(
        "--api-hash",
        type=str,
        help="Telegram API hash (or set TELEGRAM_API_HASH env var)",
    )
    telethon_group.add_argument(
        "--session",
        type=str,
        help="Session name (or set TELEGRAM_SESSION_NAME env var, default: tg_session)",
    )
    telethon_group.add_argument(
        "--target",
        type=str,
        help="Target chat: @username, t.me/... link, numeric ID, or dialog title. For forum topics use: target/topic_id (e.g., -1001875939239/40264)",
    )
    telethon_group.add_argument(
        "--search",
        type=str,
        help="Search dialogs by query and print results",
    )

    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--output",
        "-o",
        type=str,
        default="./tg_transcript.txt",
        help="Output file path (default: ./tg_transcript.txt)",
    )

    # Format options
    format_group = parser.add_argument_group("Format Options")
    format_group.add_argument(
        "--include-seconds",
        action="store_true",
        help="Include seconds in timestamps (HH:MM:SS instead of HH:MM)",
    )
    format_group.add_argument(
        "--merge-window-seconds",
        type=int,
        default=300,
        help="Merge consecutive messages from same author within this time window in seconds (default: 300, 0 to disable)",
    )
    format_group.add_argument(
        "--no-link-encoding",
        action="store_true",
        help="Disable URL encoding (keep URLs inline instead of [L#] codes)",
    )

    # Filter options
    filter_group = parser.add_argument_group("Filter Options")
    filter_group.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Export only the latest N messages (default: all messages)",
    )
    filter_group.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Export messages starting from this date inclusive (YYYY-MM-DD)",
    )
    filter_group.add_argument(
        "--to-date",
        type=str,
        default=None,
        help="Export messages up to this date inclusive (YYYY-MM-DD)",
    )

    args = parser.parse_args()

    # Validate input mode
    if args.input_json:
        # JSON import mode
        json_path = Path(args.input_json)
        if not json_path.exists():
            print(f"Error: JSON file not found: {json_path}")
            return 1

        # Parse date filters
        from_date = None
        to_date = None
        if args.from_date:
            from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.to_date:
            # Set to end of day for inclusive filtering
            to_date = datetime.strptime(args.to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)

        print(f"Parsing JSON export: {json_path}")
        builder = parse_json_export(
            json_path,
            max_messages=args.max_messages,
            from_date=from_date,
            to_date=to_date,
        )
        builder.include_seconds = args.include_seconds
        builder.merge_window_seconds = args.merge_window_seconds
        builder.encode_links = not args.no_link_encoding

        transcript = builder.build()
        output_path = Path(args.output)
        output_path.write_text(transcript, encoding="utf-8")
        print(f"Transcript written to: {output_path}")
        return 0

    # Telethon mode
    if not args.search and not args.target:
        # Check if credentials are available
        api_id = args.api_id or os.getenv("TELEGRAM_API_ID")
        api_hash = args.api_hash or os.getenv("TELEGRAM_API_HASH")

        if not api_id or not api_hash:
            parser.print_help()
            print("\nError: Either --input-json or Telethon credentials with --target/--search required")
            return 1

    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
