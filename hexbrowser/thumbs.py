"""On-demand thumbnails for extracted art (cache/thumbs/<group>/<name>.webp)."""
import re

from PIL import Image

from . import config

THUMB = 256
GROUPS = ("cards", "portraits", "icons", "sleeves", "ui", "frame")
_NAME = re.compile(r"^[a-z0-9_\-]+$")


def source_path(group, name):
    """Path of an extracted image, or None for unknown groups or names."""
    if group not in GROUPS or not _NAME.match(name):
        return None
    path = config.ART / group / f"{name}.webp"
    return path if path.is_file() else None


def thumb_path(group, name):
    src = source_path(group, name)
    if src is None:
        return None
    dst = config.CACHE / "thumbs" / group / f"{name}.webp"
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        if max(img.size) <= THUMB:
            return src
        img.thumbnail((THUMB, THUMB))
        tmp = dst.with_suffix(".tmp")
        img.save(tmp, "WEBP", quality=80, method=4, exact=True)
        tmp.replace(dst)
    return dst
