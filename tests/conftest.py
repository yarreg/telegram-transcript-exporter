#!/usr/bin/env python3
"""
Pytest fixtures and message factory for Telegram transcript exporter tests.
"""

import datetime
from datetime import UTC
from typing import Any

import pytest
from telethon.tl.types import (
    Document,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeImageSize,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    InputStickerSetEmpty,
    Message,
    MessageFwdHeader,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageReplyHeader,
    PeerUser,
)


class MessageFactory:
    """Factory for creating Telethon Message objects for testing."""

    _id_counter = 100000
    _doc_id_counter = 1000000000000000000

    def __init__(
        self,
        peer_id: int = 987654321,
        base_date: datetime.datetime | None = None,
    ):
        self.peer_id = peer_id
        self.base_date = base_date or datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        self._messages: list[Message] = []

    def _next_id(self) -> int:
        MessageFactory._id_counter += 1
        return MessageFactory._id_counter

    def _next_doc_id(self) -> int:
        MessageFactory._doc_id_counter += 1
        return MessageFactory._doc_id_counter

    def _get_timestamp(self, offset_seconds: int = 0) -> datetime.datetime:
        return self.base_date + datetime.timedelta(seconds=offset_seconds)

    def _base_message_kwargs(self) -> dict[str, Any]:
        """Common kwargs for all message types."""
        return {
            "reply_markup": None,
            "entities": None,
            "views": None,
            "forwards": None,
            "replies": None,
            "edit_date": None,
            "post_author": None,
            "grouped_id": None,
            "restriction_reason": None,
            "ttl_period": None,
            "noforwards": False,
            "edit_hide": False,
            "from_scheduled": False,
            "legacy": False,
            "silent": False,
            "post": False,
            "pinned": False,
        }

    def text(
        self,
        message: str,
        out: bool = True,
        offset_seconds: int = 0,
        msg_id: int | None = None,
    ) -> Message:
        """Create a simple text message."""
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=msg_id or self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message=message,
            out=out,
            fwd_from=None,
            reply_to=None,
            via_bot_id=None,
            media=None,
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def reply(
        self,
        message: str,
        reply_to_msg_id: int,
        out: bool = True,
        offset_seconds: int = 0,
        reply_to_top_id: int | None = None,
    ) -> Message:
        """Create a reply message."""
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message=message,
            out=out,
            fwd_from=None,
            reply_to=MessageReplyHeader(
                reply_to_msg_id=reply_to_msg_id,
                reply_to_peer_id=None,
                reply_to_top_id=reply_to_top_id,
            ),
            via_bot_id=None,
            media=None,
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def forward(
        self,
        message: str,
        from_id: int,
        from_name: str,
        out: bool = False,
        offset_seconds: int = 0,
        fwd_date_offset: int = -60,
    ) -> Message:
        """Create a forwarded message."""
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message=message,
            out=out,
            fwd_from=MessageFwdHeader(
                from_id=PeerUser(from_id),
                date=self._get_timestamp(offset_seconds + fwd_date_offset),
                from_name=from_name,
            ),
            reply_to=None,
            via_bot_id=None,
            media=None,
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def photo(
        self,
        message: str = "",
        out: bool = True,
        offset_seconds: int = 0,
    ) -> Message:
        """Create a message with photo."""
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message=message,
            out=out,
            fwd_from=None,
            reply_to=None,
            via_bot_id=None,
            media=MessageMediaPhoto(photo=None),
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def _create_document(
        self,
        mime_type: str,
        size: int,
        attributes: list,
    ) -> Document:
        """Create a Document object."""
        return Document(
            id=self._next_doc_id(),
            access_hash=self._next_doc_id(),
            file_reference=b"fake_ref",
            date=self.base_date,
            mime_type=mime_type,
            size=size,
            dc_id=2,
            attributes=attributes,
        )

    def video(
        self,
        message: str = "",
        filename: str = "video.mp4",
        duration: int = 30,
        size: int = 1024000,
        out: bool = True,
        offset_seconds: int = 0,
    ) -> Message:
        """Create a message with video."""
        doc = self._create_document(
            mime_type="video/mp4",
            size=size,
            attributes=[
                DocumentAttributeVideo(
                    duration=duration,
                    w=1280,
                    h=720,
                    round_message=False,
                    supports_streaming=True,
                ),
                DocumentAttributeFilename(filename),
            ],
        )
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message=message,
            out=out,
            fwd_from=None,
            reply_to=None,
            via_bot_id=None,
            media=MessageMediaDocument(document=doc),
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def voice(
        self,
        duration: int = 15,
        out: bool = True,
        offset_seconds: int = 0,
    ) -> Message:
        """Create a voice message."""
        doc = self._create_document(
            mime_type="audio/ogg",
            size=256000,
            attributes=[
                DocumentAttributeAudio(
                    duration=duration,
                    voice=True,
                    title=None,
                    performer=None,
                    waveform=b"fake_waveform",
                )
            ],
        )
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message="",
            out=out,
            fwd_from=None,
            reply_to=None,
            via_bot_id=None,
            media=MessageMediaDocument(document=doc),
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def audio(
        self,
        message: str = "",
        filename: str = "song.mp3",
        title: str = "Test Song",
        performer: str = "Test Artist",
        duration: int = 180,
        size: int = 5120000,
        out: bool = True,
        offset_seconds: int = 0,
    ) -> Message:
        """Create an audio file message."""
        doc = self._create_document(
            mime_type="audio/mpeg",
            size=size,
            attributes=[
                DocumentAttributeAudio(
                    duration=duration,
                    voice=False,
                    title=title,
                    performer=performer,
                    waveform=None,
                ),
                DocumentAttributeFilename(filename),
            ],
        )
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message=message,
            out=out,
            fwd_from=None,
            reply_to=None,
            via_bot_id=None,
            media=MessageMediaDocument(document=doc),
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def file(
        self,
        message: str = "",
        filename: str = "document.pdf",
        size: int = 102400,
        out: bool = True,
        offset_seconds: int = 0,
    ) -> Message:
        """Create a file message."""
        doc = self._create_document(
            mime_type="application/pdf",
            size=size,
            attributes=[DocumentAttributeFilename(filename)],
        )
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message=message,
            out=out,
            fwd_from=None,
            reply_to=None,
            via_bot_id=None,
            media=MessageMediaDocument(document=doc),
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def sticker(
        self,
        alt: str = "😀",
        out: bool = True,
        offset_seconds: int = 0,
    ) -> Message:
        """Create a sticker message."""
        doc = self._create_document(
            mime_type="application/x-tgsticker",
            size=51200,
            attributes=[
                DocumentAttributeSticker(alt=alt, stickerset=InputStickerSetEmpty()),
                DocumentAttributeImageSize(w=512, h=512),
            ],
        )
        msg = Message(
            peer_id=PeerUser(self.peer_id),
            id=self._next_id(),
            date=self._get_timestamp(offset_seconds),
            message="",
            out=out,
            fwd_from=None,
            reply_to=None,
            via_bot_id=None,
            media=MessageMediaDocument(document=doc),
            **self._base_message_kwargs(),
        )
        self._messages.append(msg)
        return msg

    def get_messages(self) -> list[Message]:
        """Get all created messages."""
        return self._messages.copy()

    def clear(self) -> None:
        """Clear all created messages."""
        self._messages.clear()


@pytest.fixture
def message_factory() -> MessageFactory:
    """Provide a fresh MessageFactory instance for each test."""
    return MessageFactory()


@pytest.fixture
def factory_with_date():
    """Provide a factory function to create MessageFactory with custom date."""

    def _factory(
        year: int = 2025,
        month: int = 1,
        day: int = 1,
        hour: int = 12,
        minute: int = 0,
    ) -> MessageFactory:
        return MessageFactory(base_date=datetime.datetime(year, month, day, hour, minute, 0, tzinfo=UTC))

    return _factory
