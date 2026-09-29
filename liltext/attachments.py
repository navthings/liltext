from __future__ import annotations

import base64
from pathlib import Path

from .messages import Attachment

IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic", "image/heif"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}


def image_b64(attachments: tuple[Attachment, ...]) -> str | None:
    for attachment in attachments:
        path = attachment.path
        mime = (attachment.mime_type or "").lower()
        if not (mime.startswith("image/") or path.suffix.lower() in IMAGE_EXTS):
            continue
        try:
            data = path.read_bytes()
        except (OSError, PermissionError):
            continue
        if not data:
            continue
        return base64.b64encode(data).decode("ascii")
    return None
