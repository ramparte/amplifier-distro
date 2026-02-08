"""Format Amplifier output for Slack messages.

Handles:
- Markdown to Slack mrkdwn conversion
- Long message splitting (Slack has ~4000 char limit)
- Block Kit message formatting for rich UI elements
"""

from __future__ import annotations

import re
from typing import Any


class SlackFormatter:
    """Converts Amplifier output to Slack-compatible formats."""

    @staticmethod
    def markdown_to_slack(text: str) -> str:
        """Convert standard Markdown to Slack mrkdwn format.

        Key differences:
        - Bold: **text** -> *text*
        - Italic: *text* or _text_ -> _text_
        - Strikethrough: ~~text~~ -> ~text~
        - Code blocks: ```lang\\n...``` -> ```\\n...``` (lang stripped)
        - Links: [text](url) -> <url|text>
        - Headers: # text -> *text* (bold, no header support in Slack)
        """
        if not text:
            return ""

        result = text

        # Convert code blocks first (preserve contents)
        # Remove language hints from fenced code blocks
        result = re.sub(r"```\w*\n", "```\n", result)

        # Convert links: [text](url) -> <url|text>
        result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", result)

        # Convert headers: # text -> *text*
        result = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", result, flags=re.MULTILINE)

        # Convert bold: **text** -> *text* (must come before italic)
        result = re.sub(r"\*\*(.+?)\*\*", r"*\1*", result)

        # Convert strikethrough: ~~text~~ -> ~text~
        result = re.sub(r"~~(.+?)~~", r"~\1~", result)

        # Bullet lists: - item -> • item (Slack renders these better)
        result = re.sub(r"^(\s*)[-*]\s+", r"\1• ", result, flags=re.MULTILINE)

        return result

    @staticmethod
    def split_message(text: str, max_length: int = 3900) -> list[str]:
        """Split a long message into chunks respecting Slack's limit.

        Tries to split at paragraph boundaries first, then line boundaries,
        then hard-splits as last resort. Preserves code blocks.
        """
        if len(text) <= max_length:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break

            # Try to split at paragraph boundary
            split_point = remaining.rfind("\n\n", 0, max_length)

            # Fall back to line boundary
            if split_point < max_length // 2:
                split_point = remaining.rfind("\n", 0, max_length)

            # Hard split as last resort
            if split_point < max_length // 4:
                split_point = max_length

            chunks.append(remaining[:split_point].rstrip())
            remaining = remaining[split_point:].lstrip("\n")

        return chunks

    @staticmethod
    def format_response(text: str, max_length: int = 3900) -> list[str]:
        """Format an Amplifier response for Slack.

        Converts markdown, splits long messages, returns list of
        message texts ready to send.
        """
        converted = SlackFormatter.markdown_to_slack(text)
        return SlackFormatter.split_message(converted, max_length)

    @staticmethod
    def format_session_list(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format a session list as Slack Block Kit blocks.

        Returns a list of Block Kit blocks for rich display.
        """
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Amplifier Sessions"},
            }
        ]

        if not sessions:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "_No sessions found._"},
                }
            )
            return blocks

        for session in sessions:
            session_id = session.get("session_id", "unknown")
            short_id = session_id[:8]
            project = session.get("project", "unknown")
            date = session.get("date_str", "")
            name = session.get("name", "")
            desc = session.get("description", "")

            label = f"*{name}*\n" if name else ""
            label += f"`{short_id}` | {project}"
            if date:
                label += f" | {date}"
            if desc:
                label += f"\n{desc}"

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": label},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Connect"},
                        "value": session_id,
                        "action_id": f"connect_session_{short_id}",
                    },
                }
            )

        return blocks

    @staticmethod
    def format_error(error: str) -> list[dict[str, Any]]:
        """Format an error as Slack Block Kit blocks."""
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *Error*\n{error}",
                },
            }
        ]

    @staticmethod
    def format_status(
        session_id: str,
        project: str = "",
        description: str = "",
        is_active: bool = True,
    ) -> list[dict[str, Any]]:
        """Format session status as Slack Block Kit blocks."""
        status_emoji = ":large_green_circle:" if is_active else ":white_circle:"
        status_text = "Active" if is_active else "Inactive"

        text = f"{status_emoji} *Session Status: {status_text}*\n"
        text += f"ID: `{session_id[:8]}`\n"
        if project:
            text += f"Project: {project}\n"
        if description:
            text += f"Description: {description}\n"

        return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    @staticmethod
    def format_help() -> list[dict[str, Any]]:
        """Format help text as Slack Block Kit blocks."""
        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Amplifier Slack Bridge"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Commands* (mention @amp or use in a session thread):\n\n"
                        "• `list` - List recent Amplifier sessions\n"
                        "• `projects` - List known projects\n"
                        "• `new [description]` - Start a new session\n"
                        "• `connect <session_id>` - Connect to an existing session\n"
                        "• `status` - Show current session status\n"
                        "• `breakout` - Move session to its own channel\n"
                        "• `end` - End the current session\n"
                        "• `help` - Show this help\n"
                        "\n"
                        "*How it works:*\n"
                        "• Messages in this channel create threads per session\n"
                        "• Reply in a thread to continue that session\n"
                        "• Use `breakout` to promote a thread to its own channel\n"
                    ),
                },
            },
        ]
