#pragma once
#include "fire_app_graphics.h"
#include "fire_ui_aa_data.h"

// OS-only coverage rendering into the existing canvas. No blur, scaling of
// finished text, framebuffer, decoded image cache, heap or floating point.
namespace fire_ui_aa {
inline uint16_t blend(uint16_t fg, uint16_t bg, unsigned alpha) {
  if (!alpha) return bg;
  if (alpha >= 15) return fg;
  const auto channel = [&](unsigned shift, unsigned mask) {
    return ((((fg >> shift) & mask) * alpha + ((bg >> shift) & mask) * (15 - alpha) + 7) / 15);
  };
  return uint16_t((channel(11, 31) << 11) | (channel(5, 63) << 5) | channel(0, 31));
}
inline uint16_t composite(uint16_t fill, uint16_t border, uint16_t bg,
                          unsigned fillAlpha, unsigned borderAlpha) {
  const unsigned backgroundAlpha = 15 - fillAlpha - borderAlpha;
  const auto channel = [&](unsigned shift, unsigned mask) {
    return ((((fill >> shift) & mask) * fillAlpha + ((border >> shift) & mask) * borderAlpha +
             ((bg >> shift) & mask) * backgroundAlpha + 7) / 15);
  };
  return uint16_t((channel(11, 31) << 11) | (channel(5, 63) << 5) | channel(0, 31));
}
template<class Surface>
void span(Surface& c, int x, int y, int count, uint16_t color, unsigned alpha,
          const fire_app_graphics::Rect& clip) {
  if (!alpha || y < clip.y || y >= clip.y + clip.h) return;
  const int a = x < clip.x ? clip.x : x;
  const int end = x + count < clip.x + clip.w ? x + count : clip.x + clip.w;
  if (a >= end) return;
  if (alpha == 15) { c.fillRect(a, y, end - a, 1, color); return; }
  int start = a;
  uint16_t previous = blend(color, c.readPixel(a, y), alpha);
  for (int px = a + 1; px < end; ++px) {
    const uint16_t next = blend(color, c.readPixel(px, y), alpha);
    if (next != previous) { c.fillRect(start, y, px - start, 1, previous); start = px; previous = next; }
  }
  c.fillRect(start, y, end - start, 1, previous);
}
template<class Surface>
bool mask(Surface& c, const FireUiAaData::Mask& m, int x, int y, uint16_t color,
          const fire_app_graphics::Rect& clip) {
  const unsigned total = unsigned(m.width) * m.height;
  if (!total) return m.bytes == 0;
  if (!m.runs || m.width > 64 || m.height > 64) return false;
  unsigned pixel = 0;
  for (unsigned i = 0; i < m.bytes; ++i) {
    unsigned remaining = unsigned(m.runs[i] >> 4) + 1;
    const unsigned alpha = m.runs[i] & 15;
    if (pixel + remaining > total) return false;
    if (!alpha) { pixel += remaining; continue; }
    while (remaining) {
      const unsigned row = pixel / m.width, col = pixel % m.width;
      const unsigned amount = remaining < m.width - col ? remaining : m.width - col;
      span(c, x + int(col), y + int(row), int(amount), color, alpha, clip);
      pixel += amount; remaining -= amount;
    }
  }
  return pixel == total;
}
inline unsigned corner(int radius, int x, int y) {
  if (radius < 1 || radius > 16 || x < 0 || y < 0 || x >= radius || y >= radius) return 0;
  return FireUiAaData::kCorners[FireUiAaData::kCornerOffsets[radius] + y * radius + x];
}
template<class Surface>
void cornerPaint(Surface& c, int x, int y, int radius, bool right, bool bottom,
                  uint16_t fill, uint16_t border, bool filled, bool outlined) {
  for (int row = 0; row < radius; ++row) {
    const int py = y + row;
    if (py < 0 || py >= 240) continue;
    int start = -1;
    uint16_t previous = 0;
    const auto flush = [&](int end) { if (start >= 0) c.fillRect(x + start, py, end - start, 1, previous); };
    for (int col = 0; col < radius; ++col) {
      const int px = x + col;
      const int mx = right ? radius - 1 - col : col, my = bottom ? radius - 1 - row : row;
      const unsigned outer = corner(radius, mx, my);
      const unsigned inner = outlined ? corner(radius - 1, mx - 1, my - 1) : outer;
      const unsigned a = filled ? inner : 0, b = outlined ? outer - inner : 0;
      if (px < 0 || px >= 320 || !(a + b)) { flush(col); start = -1; continue; }
      const uint16_t bg = a + b == 15 ? 0 : c.readPixel(px, py);
      const uint16_t next = composite(fill, border, bg, a, b);
      if (start < 0) { start = col; previous = next; }
      else if (next != previous) { flush(col); start = col; previous = next; }
    }
    flush(radius);
  }
}
template<class Surface>
void rounded(Surface& c, int x, int y, int w, int h, int radius,
              uint16_t fill, uint16_t border, bool filled, bool outlined) {
  if (w < 1 || h < 1 || (!filled && !outlined)) return;
  int r = radius < 0 ? 0 : radius > 16 ? 16 : radius;
  if (r > w / 2) r = w / 2;
  if (r > h / 2) r = h / 2;
  const auto rect = [&](int a, int b, int rw, int rh, uint16_t ink) {
    const auto clip = fire_app_graphics::clippedRect(a, b, rw, rh);
    if (clip.w && clip.h) c.fillRect(clip.x, clip.y, clip.w, clip.h, ink);
  };
  if (!r) {
    if (filled) rect(x, y, w, h, fill);
    if (outlined) { rect(x, y, w, 1, border); rect(x, y + h - 1, w, 1, border); rect(x, y, 1, h, border); rect(x + w - 1, y, 1, h, border); }
    return;
  }
  const int inset = outlined ? 1 : 0;
  if (filled) {
    rect(x + r, y + inset, w - 2*r, h - 2*inset, fill);
    rect(x + inset, y + r, r - inset, h - 2*r, fill);
    rect(x + w - r, y + r, r - inset, h - 2*r, fill);
  }
  if (outlined) {
    rect(x + r, y, w - 2*r, 1, border); rect(x + r, y + h - 1, w - 2*r, 1, border);
    rect(x, y + r, 1, h - 2*r, border); rect(x + w - 1, y + r, 1, h - 2*r, border);
  }
  cornerPaint(c, x, y, r, false, false, fill, border, filled, outlined);
  cornerPaint(c, x + w - r, y, r, true, false, fill, border, filled, outlined);
  cornerPaint(c, x, y + h - r, r, false, true, fill, border, filled, outlined);
  cornerPaint(c, x + w - r, y + h - r, r, true, true, fill, border, filled, outlined);
}
}  // namespace fire_ui_aa
