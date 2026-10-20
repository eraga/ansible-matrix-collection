"""Avatars named after their source, so "changed?" never depends on rendering.

An SVG source is rendered to PNG before upload, and the PNG differs from one
machine to the next (cairo and font versions): comparing rendered bytes or
sizes re-uploaded the same picture whenever the sync ran somewhere else. The
upload name carries a hash of the SOURCE bytes instead, and the check reads
only that name back.
"""
import hashlib
import mimetypes
import os
import re
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Optional
from urllib.parse import urlparse

import requests

FETCH_TIMEOUT = 30
SVG_RENDER_HEIGHT = 600
NAME_PATTERN = re.compile(r"^avatar-[0-9a-f]{16}(\.[A-Za-z0-9]+)?$")


@dataclass(frozen=True)
class Image:
    data: bytes
    mime: str
    name: str


def source_name(source: bytes, mime: str) -> str:
    ext = mimetypes.guess_extension(mime) or ""
    return "avatar-{}{}".format(hashlib.sha256(source).hexdigest()[:16], ext)


def is_source_named(name: Optional[str]) -> bool:
    return bool(name) and NAME_PATTERN.match(name) is not None


def _read_source(src: str) -> (bytes, Optional[str]):
    if src.startswith("http://") or src.startswith("https://"):
        r = requests.get(src, timeout=FETCH_TIMEOUT)
        r.raise_for_status()
        mime = (r.headers.get("Content-Type") or "").split(";")[0].strip() or None
        return r.content, mime or mimetypes.guess_type(urlparse(src).path)[0]
    with open(src, "rb") as f:
        return f.read(), mimetypes.guess_type(src)[0]


def _svg_to_png(svg: bytes) -> bytes:
    from cairosvg import svg2png

    # cairocffi cannot write to an in-memory stream on hardened macOS
    # (no write+execute memory for the callback); a file always works.
    with TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "avatar.png")
        svg2png(bytestring=svg, write_to=out, output_height=SVG_RENDER_HEIGHT)
        with open(out, "rb") as f:
            return f.read()


def load_image(src: str) -> Image:
    """Blocking: fetch or read the source and prepare what gets uploaded."""
    source, mime = _read_source(src)
    if not mime or not mime.startswith("image/"):
        raise ValueError("avatar {} is {}, not an image".format(src, mime))

    name = source_name(source, "image/png" if "svg" in mime else mime)
    if "svg" in mime:
        return Image(_svg_to_png(source), "image/png", name)
    return Image(source, mime, name)


async def avatar_to_set(api, src: Optional[str], current_mxc: Optional[str]) -> Optional[str]:
    """mxc URI to set as the new avatar, or None when the current one is it."""
    if src is None:
        return None

    image = await api.image(src)
    if current_mxc:
        current_name = await api.media_filename(current_mxc)
        if current_name == image.name:
            return None
        if current_name is not None and not is_source_named(current_name):
            # Uploaded before names carried the source hash. Identical bytes
            # mean it is this picture: keep it rather than post a change.
            if await api.download(current_mxc) == image.data:
                return None

    return await api.upload(image)
