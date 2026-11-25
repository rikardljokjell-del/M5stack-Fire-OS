"""Bounded 320x240 RGB565 raster output from the trusted Lua simulator.

No application code, file names or Python callbacks are accepted by this module.
Native timing and exact native primitive rasterization are not established here.
SDK fonts/assets are read from the one canonical, packaged data/app_sdk library.
"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import io
import json
import base64
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 320, 240
MAX_PNG_BYTES = 240000
SDK_DATA = Path(__file__).parent / 'data' / 'app_sdk'


def rgb565(value):
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError('Invalid RGB565 color')
    r, g, b = value >> 11, (value >> 5) & 63, value & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def integer(value, low=-4096, high=4096):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid bounded raster coordinate')
    return value


def fonts():
    from .app_sdk import data_fingerprint
    return _fonts(data_fingerprint())


@lru_cache(maxsize=2)
def _fonts(fingerprint):
    path = SDK_DATA / 'fonts.json'
    if not path.exists():
        return {}
    if path.stat().st_size > 8388608:
        raise ValueError('SDK font data exceeds bound')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or not isinstance(data.get('fonts'), dict):
        raise ValueError('Invalid canonical SDK font data')
    return data['fonts']


def text_size(text,font_id):
    font=fonts().get(font_id)
    if font is None:raise ValueError('Unknown canonical SDK font')
    fallback=font['glyphs']['63']
    return sum(font['glyphs'].get(str(ord(c)),fallback)['advance'] for c in text),font['line_height']


def asset_image(asset_id,tint=-1):
    from .app_sdk import data_fingerprint
    return _asset_image(data_fingerprint(),asset_id,tint)


@lru_cache(maxsize=128)
def _asset_image(fingerprint,asset_id,tint):
    from .app_sdk import assets
    asset=assets().get(asset_id)
    if asset is None:raise ValueError('Unknown canonical SDK asset ID')
    if not asset.get('tintable'):tint=-1
    width,height=asset['width'],asset['height']
    if not 1<=width<=128 or not 1<=height<=128:raise ValueError('Invalid canonical asset dimensions')
    palette=asset['palette'];raw=base64.b64decode(asset['runs_b64'],validate=True)
    if len(raw)%2 or len(raw)>width*height*2:raise ValueError('Invalid bounded asset RLE')
    pixels=[]
    for offset in range(0,len(raw),2):
        count,index=raw[offset:offset+2]
        if not count or index>=len(palette) or len(pixels)+count>width*height:raise ValueError('Invalid canonical asset run')
        rgb=rgb565(tint if tint!=-1 else palette[index])
        pixels.extend([(*rgb,0 if index==0 else 255)]*count)
    if len(pixels)!=width*height:raise ValueError('Incomplete canonical asset RLE')
    image=Image.new('RGBA',(width,height));image.putdata(pixels)
    return image


@dataclass
class RenderedFrame:
    png: bytes
    pixel_sha256: str
    png_sha256: str
    metrics: dict


class RasterRenderer:
    """One software framebuffer; a new black frame for every captured update."""
    def __init__(self):
        self.image = Image.new('RGB', (WIDTH, HEIGHT), (0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)
        self.font_exact = True
        self.sdk_text_used = False
        self.legacy_text_used = False
        self.text_boxes = []

    def bitmap_text(self, x, y, text, color, font_id, background=None,clip=None):
        font = fonts().get(font_id)
        if font is None:
            raise ValueError('Requested canonical font is unavailable')
        cursor = x
        glyphs = font['glyphs']
        height = integer(font['line_height'], 1, 64)
        for char in text:
            glyph = glyphs.get(str(ord(char)), glyphs.get('63'))
            if not glyph:
                raise ValueError('SDK font has no fallback glyph')
            width = integer(glyph['width'], 0, 32)
            gh = integer(glyph['height'], 0, 64)
            advance = integer(glyph['advance'], 0, 64)
            gx = cursor + integer(glyph.get('x_offset', 0), -64, 64)
            gy = y + integer(glyph.get('y_offset', 0), -64, 64)
            rows = glyph['rows']
            if len(rows) != gh:
                raise ValueError('Invalid canonical glyph rows')
            if background is not None and advance:
                self.draw.rectangle((cursor, y, cursor + advance - 1, y + height - 1), fill=background)
            for row, bits in enumerate(rows):
                integer(bits, 0, 4294967295)
                for col in range(width):
                    px, py = gx + col, gy + row
                    if (bits & (1 << (width - 1 - col)) and 0 <= px < WIDTH and 0 <= py < HEIGHT
                            and (clip is None or clip[0]<=px<clip[2] and clip[1]<=py<clip[3])):
                        self.image.putpixel((px, py), color)
            cursor += advance
        self.text_boxes.append({'x': x, 'y': y, 'width': cursor - x, 'height': height})
        return cursor - x

    def legacy_text(self, x, y, text, color):
        # The reference bytes are shared, but historical M5 font settings and
        # Unicode handling have not established exact native legacy parity.
        self.legacy_text_used = True
        if 'legacy6x8' in fonts():
            return self.bitmap_text(x, y, text, color, 'legacy6x8', (0, 0, 0))
        # Existing hardware font bytes are not yet part of the old API contract.
        # A bundled Pillow glyph fallback is explicitly reported as approximate;
        # no system font lookup or claim of physical/exact font parity is made.
        self.font_exact = False
        fallback = ImageFont.load_default(size=8)
        for index, char in enumerate(text):
            mask = Image.new('1', (8, 12))
            ImageDraw.Draw(mask).text((0, -1), char if ord(char) < 128 else '?', fill=1, font=fallback)
            mask = mask.crop((0, 0, 6, 8))
            px = x + index * 6
            self.draw.rectangle((px, y, px + 5, y + 7), fill=(0, 0, 0))
            self.image.paste(color, (px, y), mask)
        self.text_boxes.append({'x': x, 'y': y, 'width': len(text) * 6, 'height': 8})

    def command(self, op):
        if not isinstance(op, list) or not op or not isinstance(op[0], str):
            raise ValueError('Invalid visual command')
        name, a = op[0], op[1:]
        counts = {'clear': 1, 'pixel': 3, 'line': 5, 'rect': 5, 'fill_rect': 5,
                  'circle': 4, 'fill_circle': 4, 'text': 4, 'grid': 8,
                  'text_style':7,'asset':7,'round_rect':7,'triangle':8,'polyline':3,
                  'polygon':3,'gradient_rect':7,'arc':7}
        if name not in counts or len(a) != counts[name]:
            raise ValueError('Unsupported or malformed visual command')
        if name == 'clear':
            self.draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill=rgb565(a[0]))
        elif name == 'pixel':
            x, y = integer(a[0]), integer(a[1])
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                self.image.putpixel((x, y), rgb565(a[2]))
        elif name == 'line':
            self.draw.line(tuple(integer(v) for v in a[:4]), fill=rgb565(a[4]))
        elif name in {'rect', 'fill_rect'}:
            x, y = integer(a[0]), integer(a[1])
            w, h = integer(a[2], 1, WIDTH), integer(a[3], 1, HEIGHT)
            self.draw.rectangle((x, y, x + w - 1, y + h - 1),
                                **{'fill' if name == 'fill_rect' else 'outline': rgb565(a[4])})
        elif name in {'circle', 'fill_circle'}:
            x, y, radius = integer(a[0]), integer(a[1]), integer(a[2], 0, 320)
            self.draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                              **{'fill' if name == 'fill_circle' else 'outline': rgb565(a[3])})
        elif name == 'text':
            if not isinstance(a[2], str) or len(a[2].encode('utf-8')) > 80:
                raise ValueError('Invalid bounded legacy text')
            self.legacy_text(integer(a[0]), integer(a[1]), a[2], rgb565(a[3]))
        elif name == 'grid':
            x, y = integer(a[0]), integer(a[1])
            cw, ch = integer(a[2], 1, 32), integer(a[3], 1, 32)
            cols, rows = integer(a[4], 1, 32), integer(a[5], 1, 32)
            cells, palette = a[6:]
            if (not isinstance(cells, list) or cols * rows > 384 or len(cells) != cols * rows
                    or not isinstance(palette, list) or not 1 <= len(palette) <= 16):
                raise ValueError('Invalid bounded raster grid')
            colors = [rgb565(c) for c in palette]
            for i, cell in enumerate(cells):
                c = colors[integer(cell, 0, len(colors) - 1)]
                px, py = x + (i % cols) * cw, y + (i // cols) * ch
                self.draw.rectangle((px, py, px + cw - 1, py + ch - 1), fill=c)
        elif name=='text_style':
            self.sdk_text_used = True
            x,y=integer(a[0],-1024,1024),integer(a[1],-1024,1024)
            text,color,font_id,align,width=a[2],rgb565(a[3]),a[4],a[5],integer(a[6],1,1024)
            if not isinstance(text,str) or len(text.encode('utf-8'))>80 or '\0' in text:raise ValueError('Invalid SDK text')
            tw,th=text_size(text,font_id)
            if align not in {'left','center','right'}:raise ValueError('Invalid SDK text alignment')
            start=x+(width-tw)//2 if align=='center' else x+width-tw if align=='right' else x
            self.bitmap_text(start,y,text,color,font_id,clip=(x,y,x+width,y+th))
            self.text_boxes[-1].update(box_x=x,box_width=width,clipped=tw>width,font=font_id)
        elif name=='asset':
            x,y=integer(a[0],-1024,1024),integer(a[1],-1024,1024)
            scale=integer(a[3],1,4);tint=integer(a[4],-1,65535)
            if type(a[5]) is not bool or type(a[6]) is not bool:raise ValueError('Invalid SDK asset flip')
            image=asset_image(a[2],tint)
            if a[5]:image=image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            if a[6]:image=image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            if scale!=1:image=image.resize((image.width*scale,image.height*scale),Image.Resampling.NEAREST)
            self.image.paste(image,(x,y),image)
        elif name=='round_rect':
            x,y=integer(a[0],-1024,1024),integer(a[1],-1024,1024)
            w,h=integer(a[2],1,1024),integer(a[3],1,1024);radius=integer(a[4],0,min(160,w//2,h//2))
            if type(a[6]) is not bool:raise ValueError('Invalid SDK fill')
            self.draw.rounded_rectangle((x,y,x+w-1,y+h-1),radius=radius,
                                        **{'fill' if a[6] else 'outline':rgb565(a[5])})
        elif name in {'triangle','polygon','polyline'}:
            values=a[:6] if name=='triangle' else a[0]
            color=rgb565(a[6] if name=='triangle' else a[1]);filled=a[7] if name=='triangle' else a[2]
            if (not isinstance(values,list) or len(values)%2 or len(values)<4 or len(values)>128
                    or type(filled) is not bool):raise ValueError('Invalid SDK polygon capture')
            points=[(integer(values[i],-1024,1024),integer(values[i+1],-1024,1024)) for i in range(0,len(values),2)]
            if name!='polyline' and filled:
                for py in range(max(0,min(p[1] for p in points)),min(HEIGHT,max(p[1] for p in points))):
                    center=py+.5;crossings=[]
                    for first,second in zip(points,points[1:]+points[:1]):
                        if min(first[1],second[1])<=center<max(first[1],second[1]):
                            crossings.append(first[0]+(center-first[1])*(second[0]-first[0])/(second[1]-first[1]))
                    crossings.sort()
                    for left,right in zip(crossings[::2],crossings[1::2]):
                        lo,hi=max(0,math.ceil(left-.5)),min(WIDTH-1,math.ceil(right-.5)-1)
                        if lo<=hi:self.draw.line((lo,py,hi,py),fill=color)
            else:self.draw.line(points+([points[0]] if name!='polyline' or filled else []),fill=color)
        elif name=='gradient_rect':
            x,y=integer(a[0],-1024,1024),integer(a[1],-1024,1024)
            w,h=integer(a[2],1,1024),integer(a[3],1,1024);rgb565(a[4]);rgb565(a[5])
            if type(a[6]) is not bool:raise ValueError('Invalid gradient direction')
            vertical=a[6];dimension=h if vertical else w;span=dimension-1
            low=max(0,-y if vertical else -x);high=min(dimension,HEIGHT-y if vertical else WIDTH-x)
            for at in range(low,high):
                if span:
                    channels=[((((a[4]>>shift)&mask)*(span-at)+((a[5]>>shift)&mask)*at+span//2)//span) for shift,mask in ((11,31),(5,63),(0,31))]
                    c=(channels[0]<<11)|(channels[1]<<5)|channels[2]
                else:c=a[4]
                bounds=(x,y+at,x+w-1,y+at) if vertical else (x+at,y,x+at,y+h-1)
                self.draw.line(bounds,fill=rgb565(c))
        elif name=='arc':
            x,y=integer(a[0],-1024,1024),integer(a[1],-1024,1024);radius=integer(a[2],1,160)
            start,end=integer(a[3],0,360),integer(a[4],0,360);color=rgb565(a[5]);thick=integer(a[6],1,radius)
            if end<start:raise ValueError('Invalid arc sweep')
            def lround(v):return math.floor(v+.5) if v>=0 else math.ceil(v-.5)
            for r in range(radius-thick+1,radius+1):
                angles=list(range(start,end,3))+([end] if end>start else [])
                points=[(x+lround(math.cos(math.radians(angle))*r),y+lround(math.sin(math.radians(angle))*r)) for angle in angles]
                if len(points)>1:self.draw.line(points,fill=color)

    def render(self, frame):
        ops = frame.get('ops')
        if not isinstance(ops, list) or len(ops) > 64 or len(json.dumps(ops)) > 24000:
            raise ValueError('Visual frame exceeds bound')
        for op in ops:
            self.command(op)
        raw = self.image.tobytes()
        target = io.BytesIO()
        self.image.save(target, format='PNG', compress_level=6)
        png = target.getvalue()
        if len(png) > MAX_PNG_BYTES:
            raise ValueError('Rendered PNG exceeds bound')
        histogram = self.image.getcolors(WIDTH * HEIGHT) or []
        metrics = {'width': WIDTH, 'height': HEIGHT, 'draw_commands': len(ops),
                   'unique_colors': len(histogram), 'content_bbox': self.image.getbbox(),
                   'font_data_exact': self.font_exact, 'native_raster_exact': False,
                   'legacy_font_settings_verified': False if self.legacy_text_used else None,
                   'font_mode': ('mixed' if self.sdk_text_used and self.legacy_text_used else
                                 'shared_sdk' if self.sdk_text_used else
                                 'legacy_reference' if self.legacy_text_used else 'none'),
                   'text_boxes': self.text_boxes, 'physical_verified': False}
        return RenderedFrame(png, hashlib.sha256(raw).hexdigest(), hashlib.sha256(png).hexdigest(), metrics)


def render_frame(frame):
    return RasterRenderer().render(frame)
