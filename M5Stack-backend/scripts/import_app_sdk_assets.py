"""One-time, offline import of pinned licensed art into the canonical FIRE SDK.

Inputs are downloaded source artifacts in ignored workspace/sdk-sources.
Runtime, CI and header generation never need network or these build dependencies.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from PIL import Image, ImageDraw, ImageFont
import resvg_py

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "workspace/sdk-sources"
OUT = ROOT / "fire_backend/data/app_sdk"


def write_json(name, data):
    (OUT / name).write_bytes((json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def rgb565(rgb):
    r, g, b = rgb[:3]
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def encode_image(image):
    image = image.convert("RGBA")
    palette, indices, colors = [0], [], {}
    for pixel in image.getdata():
        if pixel[3] < 128:
            indices.append(0)
            continue
        value = rgb565(pixel)
        if value not in colors:
            colors[value] = len(palette)
            palette.append(value)
        indices.append(colors[value])
    if len(palette) > 256:
        raise ValueError("Asset needs quantization before import")
    runs = bytearray()
    for value in indices:
        if runs and runs[-1] == value and runs[-2] < 255:
            runs[-2] += 1
        else:
            runs.extend((1, value))
    return {"width": image.width, "height": image.height, "palette": palette,
            "runs_b64": base64.b64encode(runs).decode(),
            "pixel_sha256": hashlib.sha256(bytes(indices)).hexdigest()}


def game_description(pack, number, filename):
    # Hand-reviewed useful semantic IDs supplement stable source tile IDs.
    dungeon = {29: "fire-brazier", 65: "tombstone", 67: "stool", 75: "bookcase",
               84: "wizard", 85: "adventurer", 86: "rogue", 87: "warrior",
               88: "archer", 89: "chest-closed", 90: "chest-open", 96: "knight",
               102: "shield", 103: "dagger", 104: "sword", 105: "axe",
               106: "short-sword", 108: "slime", 109: "goblin", 110: "demon",
               111: "beast", 112: "elf", 113: "potion-dark", 114: "potion-green",
               115: "potion-red", 116: "potion-blue", 117: "hammer", 121: "skeleton",
               122: "spider", 123: "bat", 124: "rat", 125: "torch", 130: "bow", 131: "arrow"}
    platform = {24: "green-alien-idle", 25: "green-alien-walk", 26: "blue-alien-idle",
                27: "blue-alien-walk", 28: "pink-alien-idle", 29: "pink-alien-walk",
                30: "yellow-alien-idle", 31: "yellow-alien-walk", 32: "saw",
                33: "orange-alien-idle", 34: "orange-alien-walk", 35: "block-question",
                37: "goal-medal", 38: "goal-medal-glow", 39: "red-button",
                40: "red-button-pressed", 41: "red-button-low", 46: "robot-idle",
                47: "robot-walk", 60: "block-bright", 63: "lava-left", 78: "key",
                95: "heart-full", 96: "heart-half", 97: "heart-empty", 118: "gem",
                119: "spikes", 122: "ladder", 136: "sign-blank", 137: "sign-left",
                138: "sign-right", 162: "flag", 163: "flag-wave", 179: "mushroom",
                202: "coin", 203: "coin-edge", 204: "cloud-large", 208: "star"}
    town = {3: "tree-orange", 4: "tree-pine", 5: "tree-round", 29: "mushrooms",
            43: "stone-path", 55: "window", 56: "wagon", 83: "sign", 85: "door",
            104: "water-well", 105: "key", 106: "log", 107: "barrel"}
    aliases = {"tiny-dungeon": dungeon, "pixel-platformer": platform, "tiny-town": town}
    alias = aliases[pack].get(number)
    category = "terrain"
    if pack == "tiny-dungeon":
        category = "character" if 84 <= number <= 88 or 96 <= number <= 101 or 108 <= number <= 112 or 120 <= number <= 124 else "item" if number >= 102 else "dungeon"
    elif pack == "pixel-platformer":
        category = "character" if 24 <= number <= 50 else "interface" if number >= 209 else "platform"
    description = (alias or filename.rsplit("/", 1)[-1].removesuffix(".png").replace("_", " ")).replace("-", " ")
    return alias, category, description


def import_assets():
    entries = []
    for icon in json.loads((SOURCES / "icons-selected.json").read_text()):
        name = icon["id"].removeprefix("icon.")
        raw = (SOURCES / "lucide" / (name + ".svg")).read_text(encoding="utf8")
        png = resvg_py.svg_to_bytes(svg_string=raw.replace('stroke="currentColor"', 'stroke="#ffffff"'),
                                    width=24, height=24, skip_system_fonts=True)
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        # Native tinting is binary coverage; simulator uses the exact same mask.
        pixels = [(255, 255, 255, 255 if a >= 96 else 0) for _, _, _, a in im.getdata()]
        im.putdata(pixels)
        entries.append({**icon, **encode_image(im), "kind": "icon", "tintable": True,
                        "style": "outline", "description": name.replace("-", " "), "license": "ISC+MIT"})
    for pack in ("tiny-dungeon", "tiny-town", "pixel-platformer"):
        names = json.loads((SOURCES / (pack + "-files.json")).read_text())
        with zipfile.ZipFile(SOURCES / (pack + ".zip")) as z:
            for number, name in enumerate(names):
                image = Image.open(io.BytesIO(z.read(name))).convert("RGBA")
                if image.width > 64 or image.height > 64:
                    raise ValueError("Oversized source tile")
                alias, category, description = game_description(pack, number, name)
                entries.append({"id": pack + "." + str(number).zfill(3), **encode_image(image),
                                "alias": alias, "kind": "sprite", "category": category,
                                "style": "pixel", "description": description, "license": "CC0-1.0",
                                "tintable": False, "source_pack": pack, "source_path": name,
                                "source_sha256": hashlib.sha256(z.read(name)).hexdigest()})
            license_name = next(n for n in z.namelist() if "license" in n.lower() and not n.endswith("/"))
            (OUT / "licenses" / (pack + ".txt")).write_bytes(z.read(license_name))
    # Hand-selected, reviewed vehicles/projectiles complement the adventure sets.
    selected = {(0,38):"ufo",(0,43):"car-front",(0,44):"car-side",(0,45):"truck-side",
                (0,46):"car-top",(0,47):"wheel",(1,43):"car-front-alt",(1,44):"car-side-alt",
                (1,45):"truck-side-alt",(1,46):"bus-top",(1,47):"engine",
                (2,41):"bomb",(2,42):"projectile",(3,41):"coin",(4,43):"medkit",
                (5,38):"bow",(5,40):"arrow",(5,43):"pickaxe",(6,40):"sword",
                (6,43):"potion",(7,41):"hammer",(8,38):"axe",(8,39):"spear"}
    with zipfile.ZipFile(SOURCES / "1-bit-pack.zip") as z:
        sheet = Image.open(io.BytesIO(z.read("Tilesheet/colored-transparent_packed.png"))).convert("RGBA")
        for (row,col), alias in selected.items():
            image = sheet.crop((col*16,row*16,(col+1)*16,(row+1)*16))
            entries.append({"id":"one-bit."+alias,**encode_image(image),"alias":alias,
                            "kind":"sprite","category":"vehicle" if row<2 else "item",
                            "style":"pixel-monochrome","description":alias.replace("-"," "),
                            "license":"CC0-1.0","tintable":True,"source_pack":"1-bit-pack",
                            "source_path":"Tilesheet/colored-transparent_packed.png",
                            "source_rect":[col*16,row*16,16,16]})
        (OUT / "licenses/1-bit-pack.txt").write_bytes(z.read("License.txt"))
    entries.sort(key=lambda item: item["id"])
    write_json("assets.json", {"schema": 1, "encoding": "palette-rle-u8-count-index", "transparent_index": 0,
                               "assets": entries,
                               "animations": {"alien.walk": {"frames": ["pixel-platformer.024", "pixel-platformer.025"], "fps": 6},
                                              "coin.spin": {"frames": ["pixel-platformer.202", "pixel-platformer.203"], "fps": 8},
                                              "flag.wave": {"frames": ["pixel-platformer.162", "pixel-platformer.163"], "fps": 5}}})
    (OUT / "licenses/lucide.txt").write_bytes((SOURCES / "lucide-LICENSE.txt").read_bytes())
    return len(entries)


def import_fonts():
    codepoints = list(range(32, 127)) + sorted(set(map(ord, "æøåÆØÅ°×−")))
    fonts = {}
    configs = {"ui12": ("atkinson-AtkinsonHyperlegible-Regular.ttf", 12),
               "ui12b": ("atkinson-AtkinsonHyperlegible-Bold.ttf", 12),
               "ui16": ("atkinson-AtkinsonHyperlegible-Regular.ttf", 16),
               "title20": ("atkinson-AtkinsonHyperlegible-Bold.ttf", 20),
               "digits28": ("atkinson-AtkinsonHyperlegible-Bold.ttf", 28),
               "pixel8": ("pixel-PressStart2P-Regular.ttf", 8)}
    for name, (source, size) in configs.items():
        font = ImageFont.truetype(str(SOURCES / source), size)
        ascent, descent = font.getmetrics()
        glyphs = {}
        for cp in codepoints:
            ch = chr(cp); x0, y0, x1, y1 = font.getbbox(ch, anchor="ls")
            width, height = max(0, x1 - x0), max(0, y1 - y0)
            assert width <= 32 and height <= 32
            mask = Image.new("L", (max(1, width), max(1, height)))
            ImageDraw.Draw(mask).text((-x0, -y0), ch, font=font, fill=255, anchor="ls")
            rows = [sum((1 << (width - 1 - x)) for x in range(width) if mask.getpixel((x, y)) >= 96)
                    for y in range(height)]
            glyphs[str(cp)] = {"width": width, "height": height, "advance": round(font.getlength(ch)),
                               "x_offset": x0, "y_offset": ascent + y0, "rows": rows}
        fonts[name] = {"line_height": ascent + descent, "ascent": ascent, "descent": descent,
                       "license": "OFL-1.1", "glyphs": glyphs}
    legacy = ROOT.parent / "M5Stack-device/.pio/libdeps/m5stack-fire-ble/M5GFX/src/lgfx/Fonts/glcdfont.h"
    raw = legacy.read_text(encoding="utf8")
    data = bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", raw.split("font[] PROGMEM =", 1)[1]))
    glyphs = {}
    for cp in range(32, 127):
        cols = data[cp * 5:cp * 5 + 5]
        glyphs[str(cp)] = {"width": 5, "height": 8, "advance": 6, "x_offset": 0, "y_offset": 0,
                           "rows": [sum((1 << (4 - x)) for x, col in enumerate(cols) if col & (1 << y)) for y in range(8)]}
    fonts["legacy6x8"] = {"line_height": 8, "ascent": 7, "descent": 1, "license": "BSD-3-Clause", "glyphs": glyphs}
    (OUT / "licenses/legacy-font.txt").write_text(raw.split("*/", 1)[0].removeprefix("/*").strip() + "\n", encoding="utf8")
    for kind in ("atkinson", "pixel"):
        (OUT / "licenses" / (kind + "-OFL.txt")).write_bytes((SOURCES / (kind + "-OFL.txt")).read_bytes())
    write_json("fonts.json", {"schema": 1, "row_encoding": "uint32-msb-left-within-width", "fallback_codepoint": 63, "fonts": fonts})
    return len(fonts)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True); (OUT / "licenses").mkdir(exist_ok=True)
    count = import_assets(); font_count = import_fonts()
    write_json("sources.json", json.loads((SOURCES / "sources.json").read_text()))
    print(f"Imported {count} assets and {font_count} shared bitmap fonts")
