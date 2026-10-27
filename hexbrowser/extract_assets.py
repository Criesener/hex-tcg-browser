"""Extract images from the HEX client's asset bundles into cache/art/<group>/.

Groups (each its own folder, so equal names in different bundles no longer
overwrite each other, as they did with HexTCG/tools/extract_art.py):
  cards      card art from AssetBundles/cardsets/*.harc
  portraits  champion/mercenary portraits (championsandmercenaries, *_mercenaries)
  icons      inventory icons from general/icons.ab (equipment, mercs, sleeves, packs, ...)
  sleeves    full sleeve images from general/DeckSleeves.harc
  ui         card-frame icons (threshold gems, resources) from the client's
             Resources/Data/*.assets, filtered by name (UI_TEXTURES)
  frame      the in-game card frame: every sprite of the NGUI atlases
             A_CardTemplate_{Frames,Elements,Icons} in resources.assets, plus
             layout.json with each sprite's box on the card (see extract_frame)

Files are written as <lowercase texture name>.webp plus a manifest.json
({name: [width, height, bundle]}). Equipment icons are DXT5 whose alpha
channel is a glow/edge mask rather than a cut-out; such textures are saved
without alpha.

Usage: python -m hexbrowser.extract_assets [--force] [group ...]
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import UnityPy
from PIL import ImageStat

from . import config

PORTRAIT_BUNDLES = ("championsandmercenaries.harc",)
UI_TEXTURES = r"u_threshold_qty_\w+_da|resource_(blood|diamond|ruby|sapphire|wild)|u_gameboard_resource_\w+"
NAME_FILTERS = {"ui": UI_TEXTURES}
KEEP_ALPHA = {"ui"}   # small cut-out icons: never apply the equipment alpha heuristic


def harc_entries(f):
    """A .harc is a text header ("HARC", then "offset,length,./name.ab" lines,
    CRLF) followed by UnityFS bundles; offsets start at the first bundle."""
    head = f.read(1 << 20)
    end = head.find(b"UnityFS")
    for line in head[:end].decode().split("\r\n")[1:]:
        if line:
            off, length, name = line.split(",", 2)
            yield end + int(off), int(length)


def bundle_envs(path):
    if path.endswith(".harc"):
        with open(path, "rb") as f:
            for off, length in list(harc_entries(f)):
                f.seek(off)
                yield UnityPy.load(f.read(length))
    else:
        yield UnityPy.load(path)


def save_texture(tex, path, keep_alpha=False):
    img = tex.image
    if img.mode not in ("RGB", "L", "RGBA"):
        img = img.convert("RGBA")
    if img.mode == "RGBA" and not keep_alpha:
        # Equipment icons carry a glow/edge mask in alpha (mean coverage <= ~62),
        # not a cut-out; every other icon kind averages 90+. Drop such masks.
        alpha = img.getchannel("A")
        if alpha.getextrema()[0] == 255 or ImageStat.Stat(alpha).mean[0] < 80:
            img = img.convert("RGB")
    # exact: keep RGB under transparent pixels instead of letting WebP discard it
    img.save(path, "WEBP", quality=85, method=4, exact=True)
    return img.size


def extract_bundle(path, tmp_dir, name_filter=None, keep_alpha=False):
    """Worker: write every Texture2D of one bundle file (whose name fully
    matches name_filter, if given) into tmp_dir."""
    os.makedirs(tmp_dir, exist_ok=True)
    wanted = re.compile(name_filter, re.I) if name_filter else None
    found, errors = {}, 0
    try:
        for env in bundle_envs(path):
            for obj in env.objects:
                if obj.type.name != "Texture2D":
                    continue
                if wanted and not wanted.fullmatch(obj.peek_name() or ""):
                    continue
                try:
                    tex = obj.read()
                    name = tex.m_Name.lower()
                    if not name or name in found:
                        continue
                    found[name] = save_texture(tex, os.path.join(tmp_dir, name + ".webp"), keep_alpha)
                except Exception:
                    errors += 1
    except Exception as e:
        print(f"  ! {os.path.basename(path)}: {e}", file=sys.stderr)
    return path, found, errors


def better(new, old):
    """Prefer square 512 card art over portraits and atlases of the same name."""
    def score(size):
        w, h = size
        return (w == h == 512, w == h, -abs(w - 512))
    return score(new) > score(old)


def groups():
    cardsets = config.CLIENT_ASSETS / "cardsets"
    general = config.CLIENT_ASSETS / "general"
    data = config.CLIENT_DATA
    harcs = sorted(p.name for p in cardsets.glob("*.harc"))
    portraits = [n for n in harcs if n in PORTRAIT_BUNDLES or "mercenaries" in n]
    return {
        "cards": [cardsets / n for n in harcs if n not in portraits],
        "portraits": [cardsets / n for n in portraits],
        "icons": [general / "icons.ab"],
        "sleeves": [general / "DeckSleeves.harc"],
        "ui": [data / "resources.assets", data / "sharedassets6.assets"],
        "frame": [],   # see extract_frame
    }


FRAME_ATLASES = ("A_CardTemplate_Frames", "A_CardTemplate_Elements", "A_CardTemplate_Icons")


def ngui_sprites(raw):
    """Sprites of a serialized NGUI UIAtlas (the build has no type trees).

    Layout after the MonoBehaviour header (GameObject, enabled, script, name)
    and the material PPtr: int count, then per UISpriteData a 4-aligned string
    name and 13 int32: x, y, width, height (pixels, top-left origin), border
    l/r/b/t, padding l/r/t/b, rotated (stored turned 90 degrees clockwise)."""
    p = 44
    count = struct.unpack_from("<i", raw, p)[0]
    p += 4
    out = {}
    for _ in range(count):
        n = struct.unpack_from("<i", raw, p)[0]
        name = raw[p + 4:p + 4 + n].decode()
        p = (p + 4 + n + 3) & ~3
        out[name] = struct.unpack_from("<13i", raw, p)
        p += 52
    return out


def extract_frame(out):
    """Write the card-frame sprites and layout.json.

    The padding of a sprite is the trimmed margin of the full card it was cut
    from, so (padding left, top) / (padding + size) is its box on the card,
    as fractions [left, top, width, height]. Sprites whose padding is empty
    (e.g. FactionRarity) are placed by the client's code; they get no box."""
    env = UnityPy.load(str(config.CLIENT_DATA / "resources.assets"))
    by_name = {}
    for obj in env.objects:
        if obj.type.name == "GameObject" and obj.peek_name() in FRAME_ATLASES:
            by_name[obj.peek_name()] = obj.read()
    textures = {o.peek_name(): o for o in env.objects
                if o.type.name == "Texture2D" and o.peek_name() in {a[2:] for a in FRAME_ATLASES}}
    manifest, layout = {}, {}
    for atlas in FRAME_ATLASES:
        go = by_name[atlas]
        raw = next(c.deref().get_raw_data() for c in go.m_Components
                   if c.deref().type.name == "MonoBehaviour")
        sheet = textures[atlas[2:]].read().image.convert("RGBA")
        for name, v in ngui_sprites(raw).items():
            x, y, w, h = v[:4]
            pad_l, pad_r, pad_t, pad_b, rotated = v[8:13]
            img = sheet.crop((x, y, x + (h if rotated else w), y + (w if rotated else h)))
            if rotated:
                img = img.rotate(90, expand=True)
            key = name.lower()
            img.save(out / f"{key}.webp", "WEBP", quality=90, method=4, exact=True)
            manifest[key] = [img.width, img.height, atlas]
            cw, ch = pad_l + w + pad_r, pad_t + h + pad_b
            if pad_l + pad_r + pad_t + pad_b:
                layout[key] = [round(pad_l / cw, 4), round(pad_t / ch, 4),
                               round(w / cw, 4), round(h / ch, 4)]
    with open(out / "layout.json", "w") as f:
        json.dump(layout, f, indent=0, sort_keys=True)
    return manifest


def run_group(name, paths, workers):
    out = config.ART / name
    tmp = config.ART / f".tmp-{name}"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    manifest, errors = {}, 0
    if name == "frame":
        paths = []
        manifest = extract_frame(out)
    with ProcessPoolExecutor(workers) as pool:
        jobs = [pool.submit(extract_bundle, str(p), str(tmp / p.name), NAME_FILTERS.get(name),
                            name in KEEP_ALPHA) for p in paths]
        results = {}
        for job in as_completed(jobs):
            path, found, err = job.result()
            results[path] = found
            errors += err
            print(f"  {name}: {os.path.basename(path)}: {len(found)} textures", flush=True)
    # resolve name collisions in a stable (alphabetical bundle) order
    for path in sorted(results):
        bundle = os.path.basename(path)
        for tex, size in results[path].items():
            if tex in manifest and not better(size, manifest[tex][:2]):
                continue
            os.replace(tmp / bundle / f"{tex}.webp", out / f"{tex}.webp")
            manifest[tex] = [size[0], size[1], bundle]
    shutil.rmtree(tmp, ignore_errors=True)
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=0, sort_keys=True)
    print(f"{name}: {len(manifest)} images, {errors} unreadable textures -> {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("groups", nargs="*", help="cards, portraits, icons, sleeves, ui, frame (default: all)")
    ap.add_argument("--force", action="store_true", help="re-extract groups that already exist")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args(argv)
    if not config.CLIENT_ASSETS.is_dir():
        sys.exit(f"client assets not found: {config.CLIENT_ASSETS} (set HEX_CLIENT_ASSETS)")
    all_groups = groups()
    for name in args.groups or all_groups:
        if (config.ART / name / "manifest.json").exists() and not args.force:
            print(f"{name}: already extracted (use --force)")
            continue
        run_group(name, all_groups[name], args.workers)


if __name__ == "__main__":
    main()
