"""Email formatting utilities.

Converts markdown-like text to HTML for email responses.
"""

from __future__ import annotations

import re

from .config import EmailConfig


def markdown_to_html(text: str) -> str:
    """Convert simple markdown to HTML.

    Handles **bold**, *italic*, `code`, ```code blocks```, and newlines.
    """
    if not text:
        return ""

    # Code blocks first (```...```)
    text = re.sub(
        r"```(\w*)\n?(.*?)```",
        r"<pre><code>\2</code></pre>",
        text,
        flags=re.DOTALL,
    )

    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)

    # Newlines to <br>
    text = text.replace("\n", "<br>\n")

    return text


def format_response(text: str, config: EmailConfig) -> str:
    """Wrap text in an HTML email template with agent footer."""
    html_body = markdown_to_html(text)
    agent_name = config.agent_name or "Amplifier"

    return (
        "<html><body>"
        f"<div>{html_body}</div>"
        f"<hr><p><small>Sent by {agent_name}</small></p>"
        "</body></html>"
    )


def split_message(text: str, max_length: int = 50000) -> list[str]:
    """Split long text into chunks at paragraph/line boundaries."""
    if not text:
        return [text]

    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Try to split at paragraph boundary
        split_pos = text.rfind("\n\n", 0, max_length)
        if split_pos == -1:
            # Try newline
            split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            # Force split at max_length
            split_pos = max_length

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")

    return chunks
