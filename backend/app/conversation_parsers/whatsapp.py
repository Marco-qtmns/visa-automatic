from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


@dataclass(frozen=True)
class ParsedMessage:
    sequence_number: int
    sender: str | None
    timestamp: datetime | None
    text: str


@dataclass(frozen=True)
class ParsedConversation:
    messages: list[ParsedMessage]
    warnings: list[dict[str, object]]


_IOS = re.compile(r"^\[(?P<date>[^,\]]+),\s*(?P<time>[^\]]+)\]\s*(?P<body>.*)$")
_ANDROID = re.compile(
    r"^(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm]\.?)?)\s*[-–]\s*(?P<body>.*)$"
)
_TIMESTAMPISH = re.compile(r"^(?:\[?\d{1,4}[./-]\d{1,2}[./-]\d{1,4})")


class WhatsAppConversationParser:
    """Parse common exported-text formats without performing semantic extraction."""

    _FORMATS = (
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M:%S", "%d/%m/%y %H:%M",
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M:%S", "%m/%d/%y %H:%M",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%d/%m/%Y %I:%M %p", "%d/%m/%y %I:%M %p", "%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M %p",
    )

    def parse(self, text: str) -> ParsedConversation:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
        messages: list[dict[str, object]] = []
        warnings: list[dict[str, object]] = []
        for line_number, line in enumerate(normalized.split("\n"), start=1):
            match = _IOS.match(line) or _ANDROID.match(line)
            if match:
                timestamp = self._timestamp(match.group("date"), match.group("time"))
                if timestamp is None:
                    warnings.append({"line": line_number, "message": "Timestamp could not be normalized"})
                sender, body = self._sender_and_body(match.group("body"))
                messages.append({"sender": sender, "timestamp": timestamp, "text": body})
            elif messages and not _TIMESTAMPISH.match(line):
                messages[-1]["text"] = f"{messages[-1]['text']}\n{line}".strip()
            elif line.strip():
                warnings.append({"line": line_number, "message": "Line did not match a supported WhatsApp header"})
                messages.append({"sender": None, "timestamp": None, "text": line.strip()})
        parsed = [
            ParsedMessage(index, item["sender"], item["timestamp"], str(item["text"]))
            for index, item in enumerate(messages, start=1)
            if str(item["text"]).strip()
        ]
        return ParsedConversation(parsed, warnings)

    @staticmethod
    def _sender_and_body(body: str) -> tuple[str | None, str]:
        if ": " not in body:
            return None, body.strip()
        sender, text = body.split(": ", 1)
        sender = sender.strip()
        return (sender[:255] or None), text.strip()

    def _timestamp(self, date_value: str, time_value: str) -> datetime | None:
        clean_time = time_value.replace("\u202f", " ").replace(".", "").upper().strip()
        combined = f"{date_value.strip()} {clean_time}"
        for format_value in self._FORMATS:
            try:
                return datetime.strptime(combined, format_value)
            except ValueError:
                continue
        return None
