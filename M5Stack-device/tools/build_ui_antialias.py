"""Build OS-only 4-bit coverage tables; normal generation/check needs no imaging dependencies.

One-time import: --import-sources ../M5Stack-backend/workspace/sdk-sources
The App SDK's data, metrics and contract are never rewritten by this tool.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ui/fire_ui_aa.json"
HEADER = ROOT / "src/fire_ui_aa_data.h"
SIZES = (10, 12, 14, 15, 16, 18, 19, 20, 24, 28, 30, 32, 36, 40)


def encode(values):
    result = bytearray()
    for value in values:
        assert 0 <= value <= 15
        if result and result[-1] & 15 == value and result[-1] >> 4 < 15:
            result[-1] += 16
        else:
            result.append(value)
    return base64.b64encode(result).decode("ascii")


def decode(value, pixels):
    raw = base64.b64decode(value, validate=True)
    assert sum((b >> 4) + 1 for b in raw) == pixels
    return raw


def import_sources(source: Path):
    from PIL import Image, ImageDraw, ImageFont
    import resvg_py
    sdk = ROOT.parent / "M5Stack-backend/fire_backend/data/app_sdk"
    pinned = json.loads((sdk / "sources.json").read_text(encoding="utf-8"))
    canonical = json.loads((sdk / "fonts.json").read_text(encoding="utf-8"))["fonts"]
    fonts = {}
    configs = {"ui12": ("Regular", 12), "ui12b": ("Bold", 12), "ui16": ("Regular", 16),
               "title20": ("Bold", 20), "digits28": ("Bold", 28), "small10": ("Regular", 10)}
    sources = {}
    for name, (weight, size) in sorted(configs.items()):
        filename = f"atkinson-AtkinsonHyperlegible-{weight}.ttf"
        path = source / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == pinned[filename]["sha256"]
        sources[filename] = digest
        font = ImageFont.truetype(str(path), size)
        ascent, descent = font.getmetrics()
        glyphs = {}
        for cp in sorted(map(int, canonical["ui12"]["glyphs"])):
            char = chr(cp)
            x0, y0, x1, y1 = font.getbbox(char, anchor="ls")
            w, h = x1 - x0, y1 - y0
            assert 0 <= w <= 32 and 0 <= h <= 36
            mask = Image.new("L", (max(1, w), max(1, h)))
            ImageDraw.Draw(mask).text((-x0, -y0), char, font=font, fill=255, anchor="ls")
            glyph = {"width": w, "height": h, "advance": round(font.getlength(char)),
                     "x_offset": x0, "y_offset": ascent + y0,
                     "coverage": encode((v * 15 + 127) // 255 for v in list(mask.getdata())[:w*h])}
            if name != "small10":
                assert all(glyph[k] == canonical[name]["glyphs"][str(cp)][k]
                           for k in ("width", "height", "advance", "x_offset", "y_offset"))
            glyphs[str(cp)] = glyph
        if name != "small10":
            assert ascent + descent == canonical[name]["line_height"]
        fonts[name] = {"line_height": ascent + descent, "ascent": ascent, "descent": descent, "glyphs": glyphs}
    ids = set()
    for name in ("fire_ui.h", "fire_os.cpp", "fire_home.cpp"):
        ids.update(re.findall(r'"(icon\.[a-z0-9-]+)"', (ROOT / "src" / name).read_text(encoding="utf-8")))
    # Compact status symbols share the same coverage renderer.
    ids.update("icon." + name for name in ("battery-full", "battery-medium", "battery-low", "battery-charging", "wifi-off", "bot"))
    icons = []
    for id_ in sorted(ids):
        path = source / "lucide" / (id_[5:] + ".svg")
        raw = path.read_text(encoding="utf-8")
        sources["lucide/" + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for size in SIZES:
            png = resvg_py.svg_to_bytes(svg_string=raw.replace('stroke="currentColor"', 'stroke="#ffffff"'),
                                        width=size, height=size, skip_system_fonts=True)
            alpha = Image.open(io.BytesIO(png)).convert("RGBA").getchannel("A")
            icons.append({"id": id_, "size": size, "coverage": encode((v * 15 + 127) // 255 for v in alpha.getdata())})
    corners = {}
    for radius in range(1, 17):
        values = []
        for y in range(radius):
            for x in range(radius):
                hits = sum((16*x + 2*sx + 1 - 16*radius)**2 + (16*y + 2*sy + 1 - 16*radius)**2
                           <= (16*radius)**2 for sy in range(8) for sx in range(8))
                values.append((hits * 15 + 32) // 64)
        corners[str(radius)] = values
    value = {"schema": 1, "encoding": "rle4-count-minus-one-high-alpha-low", "alpha_bits": 4,
             "fonts": fonts, "icons": icons, "corners": corners, "sources": sources,
             "licenses": "Existing App SDK Atkinson OFL-1.1 and Lucide ISC/Feather notices apply; preserved in release bundles.",
             "lucide_source_commit": "164efbaf879fb29f55d88047efd49fc7725f53ab"}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_bytes((json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode())


def generate(value):
    assert value["schema"] == 1 and value["alpha_bits"] == 4
    lines = ['// Generated by tools/build_ui_antialias.py; OS/Home only, not App SDK data.',
             '// Coverage from pinned Atkinson/Lucide sources; original release notices retained.',
             '#pragma once', '#include <cstdint>', '#include <cstddef>', 'namespace FireUiAaData {',
             'struct Mask { uint8_t width,height; const uint8_t* runs; uint16_t bytes; };',
             'struct Glyph { uint32_t codepoint; uint8_t width,height,advance; int8_t xOffset,yOffset; Mask mask; };',
             'struct Font { const char* id; uint8_t lineHeight,ascent,descent; const Glyph* glyphs; uint16_t glyphCount; };',
             'struct Icon { const char* id; uint8_t size; Mask mask; };']
    def array(name, raw):
        lines.append(f'inline constexpr uint8_t {name}[] = {{' + (','.join(map(str, raw)) if raw else '0') + '};')
    font_entries = []
    for i, (name, font) in enumerate(sorted(value["fonts"].items())):
        entries = []
        for j, (cp, g) in enumerate(sorted(font["glyphs"].items(), key=lambda x: int(x[0]))):
            raw = decode(g["coverage"], g["width"] * g["height"])
            array(f'g{i}_{j}', raw)
            entries.append(f'{{{cp},{g["width"]},{g["height"]},{g["advance"]},{g["x_offset"]},{g["y_offset"]},'
                           f'{{{g["width"]},{g["height"]},g{i}_{j},{len(raw)}}}}}')
        lines.append(f'inline constexpr Glyph glyphs{i}[] = {{' + ','.join(entries) + '};')
        font_entries.append('{' + json.dumps(name) + f',{font["line_height"]},{font["ascent"]},{font["descent"]},glyphs{i},{len(entries)}}}')
    lines.append('inline constexpr Font kFonts[] = {' + ','.join(font_entries) + '};')
    entries = []
    for i, icon in enumerate(value["icons"]):
        size = icon["size"]; raw = decode(icon["coverage"], size * size)
        array(f'i{i}', raw)
        entries.append('{' + json.dumps(icon["id"]) + f',{size},{{{size},{size},i{i},{len(raw)}}}}}')
    lines.append('inline constexpr Icon kIcons[] = {' + ','.join(entries) + '};')
    all_corners, offsets = [], [0]
    for radius in range(1, 17):
        offsets.append(len(all_corners)); all_corners += value["corners"][str(radius)]
    array('kCorners', all_corners)
    lines.append('inline constexpr uint16_t kCornerOffsets[] = {' + ','.join(map(str, offsets)) + '};')
    lines.append('inline constexpr size_t kFontCount = sizeof(kFonts)/sizeof(kFonts[0]);')
    lines.append('inline constexpr size_t kIconCount = sizeof(kIcons)/sizeof(kIcons[0]);')
    lines.append('} // namespace FireUiAaData')
    return ('\n'.join(lines) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-sources', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.import_sources:
        import_sources(args.import_sources)
    value = json.loads(DATA.read_text(encoding='utf-8'))
    result = generate(value)
    if args.check:
        if not HEADER.exists() or HEADER.read_bytes() != result:
            raise SystemExit('OS-only antialias data/header drift')
    else:
        HEADER.write_bytes(result)
    print(f'OS-only coverage tables verified: {len(value["fonts"])} fonts, {len(value["icons"])} exact-size icons')


if __name__ == '__main__':
    main()
