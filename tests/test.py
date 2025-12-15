#!/usr/bin/env python3
"""
Tests for Telegram transcript exporter.

Uses MessageFactory from conftest.py to create test messages.
"""

import datetime
import sys
from datetime import UTC
from pathlib import Path

import pytest

# Add parent directory to path to import main module
sys.path.insert(0, str(Path(__file__).parent.parent))

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from main import (
    Author,
    Message,
    TranscriptBuilder,
    format_duration,
    format_file_size,
    generate_author_code,
)
from tests.conftest import MessageFactory


class TestGenerateAuthorCode:
    """Tests for author code generation."""

    def test_first_letter_code(self):
        """First letter should be used as code if available."""
        code = generate_author_code("Yaroslav", set())
        assert code == "Y"

    def test_first_letter_with_conflict(self):
        """When first letter is taken, use two letters."""
        code = generate_author_code("Yaroslav", {"Y"})
        assert code == "YA"

    def test_cyrillic_code(self):
        """Cyrillic names should work."""
        code = generate_author_code("Веталик", set())
        assert code == "В"  # noqa: RUF001

    def test_empty_name_fallback(self):
        """Empty/None name should fallback to Unknown."""
        code = generate_author_code("", set())
        assert code == "U"  # 'U' from 'Unknown' fallback

    def test_none_name_fallback(self):
        """None name should fallback to Unknown."""
        code = generate_author_code(None, set())
        assert code == "U"  # 'U' from 'Unknown' fallback

    def test_multiple_conflicts(self):
        """Handle multiple code conflicts."""
        code = generate_author_code("Test", {"T", "TE"})
        # Should try consonants or fallback to numbered
        assert code not in {"T", "TE"}

    def test_numbered_fallback(self):
        """When all simple options exhausted, use numbered code."""
        existing = {"T", "TE", "S"}
        code = generate_author_code("Test", existing)
        assert code not in existing


class TestFormatFileSize:
    """Tests for file size formatting."""

    def test_bytes(self):
        assert format_file_size(500) == "500B"

    def test_kilobytes(self):
        assert format_file_size(1536) == "1.5KB"

    def test_megabytes(self):
        assert format_file_size(2621440) == "2.5MB"

    def test_gigabytes(self):
        assert format_file_size(1610612736) == "1.5GB"

    def test_none(self):
        assert format_file_size(None) == ""


class TestFormatDuration:
    """Tests for duration formatting."""

    def test_seconds_only(self):
        assert format_duration(45) == "00:45"

    def test_minutes_and_seconds(self):
        assert format_duration(125) == "02:05"

    def test_none(self):
        assert format_duration(None) == ""


class TestAuthor:
    """Tests for Author class."""

    def test_format_line_with_username(self):
        author = Author(
            user_id=12345,
            display_name="Test User",
            username="testuser",
            is_channel=False,
        )
        author.code = "T"
        line = author.format_line()
        assert line == "  T=Test User (@testuser) (user12345)"

    def test_format_line_without_username(self):
        author = Author(
            user_id=12345,
            display_name="Test User",
            username=None,
            is_channel=False,
        )
        author.code = "T"
        line = author.format_line()
        assert line == "  T=Test User (none) (user12345)"

    def test_format_line_channel(self):
        author = Author(
            user_id=12345,
            display_name="Test Channel",
            username="testchannel",
            is_channel=True,
        )
        author.code = "T"
        line = author.format_line()
        assert line == "  T=Test Channel (@testchannel) (channel12345)"


class TestMessage:
    """Tests for Message class."""

    def test_message_creation(self):
        msg = Message(
            msg_id=1,
            author_id=12345,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Hello",
        )
        assert msg.msg_id == 1
        assert msg.author_id == 12345
        assert msg.text == "Hello"
        assert msg.reply_to_msg_id is None
        assert msg.forwarded_from_id is None

    def test_message_with_reply(self):
        msg = Message(
            msg_id=2,
            author_id=12345,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Reply",
            reply_to_msg_id=1,
        )
        assert msg.reply_to_msg_id == 1

    def test_message_with_forward(self):
        msg = Message(
            msg_id=3,
            author_id=12345,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Forwarded",
            forwarded_from_id=99999,
        )
        assert msg.forwarded_from_id == 99999


class TestTranscriptBuilder:
    """Tests for TranscriptBuilder class."""

    def test_build_basic_transcript(self):
        builder = TranscriptBuilder(
            chat_title="Test Chat",
            chat_id=12345,
        )

        # Add author
        author = Author(user_id=1, display_name="User One", username="userone")
        builder.add_author(author)

        # Add message
        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Hello world",
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "TG-TRANSCRIPT v1:" in transcript
        assert "CHAT: Test Chat (id=12345)" in transcript
        assert "AUTHORS:" in transcript
        assert "User One" in transcript
        assert "BODY:" in transcript
        assert "2025-01-01" in transcript
        assert "Hello world" in transcript

    def test_url_encoding(self):
        builder = TranscriptBuilder(
            chat_title="Test",
            chat_id=1,
            encode_links=True,
        )

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Check this out: https://example.com/test",
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "[L1]" in transcript
        assert "https://example.com/test" in transcript
        assert "LINKS:" in transcript

    def test_url_encoding_disabled(self):
        builder = TranscriptBuilder(
            chat_title="Test",
            chat_id=1,
            encode_links=False,
        )

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Check this out: https://example.com/test",
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "[L1]" not in transcript
        assert "https://example.com/test" in transcript

    def test_reply_formatting(self):
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        # Original message
        msg1 = Message(
            msg_id=100,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Original message",
        )
        builder.add_message(msg1)

        # Reply message
        msg2 = Message(
            msg_id=101,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 1, 0, tzinfo=UTC),
            text="Reply to original",
            reply_to_msg_id=100,
        )
        builder.add_message(msg2)

        transcript = builder.build()

        # Check reply indicator
        assert "↩100" in transcript
        # Original message should have #100 since it's referenced by a reply
        assert "#100" in transcript
        # Reply message should NOT have #101 since nothing references it
        assert "#101" not in transcript

    def test_msg_id_only_for_referenced_messages(self):
        """Message IDs should only appear for messages that are referenced by replies."""
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        # Message without any replies - should NOT have ID
        msg1 = Message(
            msg_id=100,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Not referenced",
        )
        builder.add_message(msg1)

        # Message that will be replied to - should have ID
        msg2 = Message(
            msg_id=200,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 1, 0, tzinfo=UTC),
            text="Will be replied to",
        )
        builder.add_message(msg2)

        # Reply to msg2
        msg3 = Message(
            msg_id=300,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 2, 0, tzinfo=UTC),
            text="This is a reply",
            reply_to_msg_id=200,
        )
        builder.add_message(msg3)

        # Another message without replies
        msg4 = Message(
            msg_id=400,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 3, 0, tzinfo=UTC),
            text="Also not referenced",
        )
        builder.add_message(msg4)

        transcript = builder.build()

        # Only msg2 (id=200) should have its ID shown
        assert "#200" in transcript
        # Other messages should NOT have their IDs shown
        assert "#100" not in transcript
        assert "#300" not in transcript
        assert "#400" not in transcript

    def test_forward_formatting(self):
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author1 = Author(user_id=1, display_name="User One")
        builder.add_author(author1)

        author2 = Author(user_id=2, display_name="Forwarded From", is_channel=True)
        builder.add_author(author2)

        msg = Message(
            msg_id=100,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Forwarded content",
            forwarded_from_id=2,
        )
        builder.add_message(msg)

        transcript = builder.build()

        # Check forward indicator
        assert "↪" in transcript

    def test_media_formatting(self):
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Here is a file",
            media=[{"type": "file", "filename": "document.pdf", "size": 1048576}],
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "📎(file:document.pdf 1.0MB)" in transcript

    def test_photo_media(self):
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="",
            media=[{"type": "photo", "filename": "photo.jpg"}],
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "📎(photo:photo.jpg)" in transcript

    def test_voice_media(self):
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="",
            media=[{"type": "voice", "filename": "voice.ogg", "duration": 15}],
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "📎(voice:voice.ogg 00:15)" in transcript

    def test_video_media(self):
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="",
            media=[{"type": "video", "filename": "video.mp4", "size": 10485760}],
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "📎(video:video.mp4 10.0MB)" in transcript

    def test_include_seconds(self):
        builder = TranscriptBuilder(
            chat_title="Test",
            chat_id=1,
            include_seconds=True,
        )

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 30, 45, tzinfo=UTC),
            text="Test",
        )
        builder.add_message(msg)

        transcript = builder.build()

        assert "12:30:45" in transcript

    def test_multiline_message(self):
        builder = TranscriptBuilder(chat_title="Test", chat_id=1)

        author = Author(user_id=1, display_name="User")
        builder.add_author(author)

        msg = Message(
            msg_id=1,
            author_id=1,
            timestamp=datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            text="Line one\nLine two\nLine three",
        )
        builder.add_message(msg)

        transcript = builder.build()

        # Check that continuation lines start with space
        lines = transcript.split("\n")
        body_started = False
        found_continuation = False
        for line in lines:
            if "BODY:" in line:
                body_started = True
            if body_started and line.startswith(" Line"):
                found_continuation = True
                break

        assert found_continuation, "Continuation lines should start with space"


class TestMessageFactory:
    """Tests for the MessageFactory helper."""

    def test_text_message(self, message_factory: MessageFactory):
        msg = message_factory.text("Hello world")
        assert msg.message == "Hello world"
        assert msg.out is True
        assert msg.fwd_from is None
        assert msg.reply_to is None

    def test_reply_message(self, message_factory: MessageFactory):
        original = message_factory.text("Original", msg_id=1000)
        reply = message_factory.reply("Reply text", reply_to_msg_id=1000)

        assert reply.reply_to is not None
        assert reply.reply_to.reply_to_msg_id == 1000

    def test_forward_message(self, message_factory: MessageFactory):
        fwd = message_factory.forward(
            message="Forwarded content",
            from_id=555666,
            from_name="Some Channel",
        )

        assert fwd.fwd_from is not None
        assert fwd.fwd_from.from_name == "Some Channel"

    def test_photo_message(self, message_factory: MessageFactory):
        msg = message_factory.photo("Check this photo")
        assert msg.media is not None
        assert isinstance(msg.media, MessageMediaPhoto)

    def test_video_message(self, message_factory: MessageFactory):
        msg = message_factory.video("Watch this", filename="clip.mp4")
        assert msg.media is not None
        assert isinstance(msg.media, MessageMediaDocument)

    def test_voice_message(self, message_factory: MessageFactory):
        msg = message_factory.voice(duration=30)
        assert msg.media is not None
        assert msg.message == ""

    def test_file_message(self, message_factory: MessageFactory):
        msg = message_factory.file("Here's the doc", filename="report.pdf")
        assert msg.media is not None

    def test_sticker_message(self, message_factory: MessageFactory):
        msg = message_factory.sticker(alt="👍")
        assert msg.media is not None
        assert msg.message == ""

    def test_message_timestamps(self, message_factory: MessageFactory):
        msg1 = message_factory.text("First", offset_seconds=0)
        msg2 = message_factory.text("Second", offset_seconds=60)

        assert msg2.date > msg1.date
        assert (msg2.date - msg1.date).seconds == 60

    def test_factory_with_custom_date(self, factory_with_date):
        factory = factory_with_date(year=2024, month=6, day=15, hour=10, minute=30)
        msg = factory.text("Test message")

        assert msg.date.year == 2024
        assert msg.date.month == 6
        assert msg.date.day == 15


class TestIntegrationWithFactory:
    """Integration tests using MessageFactory to create realistic test data."""

    def test_conversation_flow(self, factory_with_date):
        """Test a realistic conversation with multiple message types."""
        factory = factory_with_date(2025, 12, 10, 14, 0)

        # Create conversation
        msg1 = factory.text("Hey, did you see the news?", out=True, offset_seconds=0)
        msg2 = factory.text("No, what happened?", out=False, offset_seconds=30)
        msg3 = factory.forward(
            "Breaking: Important announcement",
            from_id=999,
            from_name="News Channel",
            offset_seconds=60,
        )
        msg4 = factory.reply(
            "Wow, that's crazy!",
            reply_to_msg_id=msg3.id,
            out=False,
            offset_seconds=90,
        )
        msg5 = factory.photo("Related image", out=True, offset_seconds=120)

        messages = factory.get_messages()
        assert len(messages) == 5

        # Verify message order and types
        assert messages[0].message == "Hey, did you see the news?"
        assert messages[2].fwd_from is not None
        assert messages[3].reply_to is not None
        assert messages[4].media is not None

    def test_media_conversation(self, message_factory: MessageFactory):
        """Test conversation with various media types."""
        message_factory.text("Sending some files")
        message_factory.file("Document", filename="report.pdf", size=1024000)
        message_factory.voice(duration=45)
        message_factory.video("Check this out", filename="demo.mp4", size=5000000)
        message_factory.photo("Screenshot")
        message_factory.sticker()

        messages = message_factory.get_messages()
        assert len(messages) == 6

        # Count media messages
        media_count = sum(1 for m in messages if m.media is not None)
        assert media_count == 5
