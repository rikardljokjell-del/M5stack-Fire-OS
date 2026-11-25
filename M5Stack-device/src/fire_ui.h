#pragma once
#include "fire_app_bitmap.h"
#include "fire_app_sdk_data.h"
#include <cstring>

// Small shared OS/Home drawing vocabulary. It reuses the existing flash fonts
// and icons, draws directly into the OS canvas, and owns no heap or framebuffer.
namespace FireUI {
constexpr uint16_t rgb(unsigned r, unsigned g, unsigned b) {
  return uint16_t(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}
inline constexpr uint16_t Bg = rgb(9, 15, 25);
inline constexpr uint16_t Panel = rgb(20, 29, 44);
inline constexpr uint16_t Raised = rgb(29, 41, 59);
inline constexpr uint16_t Selected = rgb(22, 49, 64);
inline constexpr uint16_t Border = rgb(43, 58, 77);
inline constexpr uint16_t Text = rgb(241, 246, 252);
inline constexpr uint16_t Muted = rgb(158, 177, 199);
inline constexpr uint16_t Accent = rgb(69, 216, 217);
inline constexpr uint16_t Blue = rgb(110, 177, 255);
inline constexpr uint16_t Green = rgb(111, 222, 162);
inline constexpr uint16_t Amber = rgb(255, 195, 105);
inline constexpr uint16_t Red = rgb(255, 126, 145);
inline constexpr uint16_t Purple = rgb(185, 158, 255);

inline const FireSdkData::Font& font(const char* id) {
  const auto* found = fire_app_bitmap::find(FireSdkData::kFonts, FireSdkData::kFontCount, id);
  return found ? *found : FireSdkData::kFonts[4];  // canonical ui12
}
inline int width(const char* value, const char* id = "ui12") {
  if (!value) return 0;
  int w = 0, h = 0;
  return fire_app_bitmap::measure(font(id), value, std::strlen(value), w, h) ? w : 10000;
}
template<class Surface>
void text(Surface& c, int x, int y, const char* value, uint16_t color = Text,
          const char* id = "ui12", int maxWidth = 300, int align = 0) {
  if (!value || maxWidth < 1) return;
  // Clip on a whole UTF-8 codepoint and glyph advance, never half a glyph.
  char clipped[81] = {};
  size_t used = 0, offset = 0;
  int advance = 0;
  const size_t length = std::strlen(value);
  const auto& f = font(id);
  while (offset < length && used < 80) {
    const size_t start = offset;
    uint32_t cp = 0;
    if (!fire_app_bitmap::codepoint(value, length, offset, cp) || offset > 80) break;
    const auto* g = fire_app_bitmap::glyph(f, cp);
    if (!g || advance + g->advance > maxWidth) break;
    std::memcpy(clipped + used, value + start, offset - start);
    used += offset - start;
    advance += g->advance;
  }
  fire_app_bitmap::text(c, f, x, y, clipped, used, color, align, maxWidth);
}
template<class Surface>
void panel(Surface& c, int x, int y, int w, int h, bool selected = false,
           uint16_t accent = Accent) {
  fire_app_graphics::roundRect(c, x, y, w, h, 10, selected ? Selected : Panel, true);
  fire_app_graphics::roundRect(c, x, y, w, h, 10, selected ? accent : Border, false);
}
template<class Surface>
void icon(Surface& c, const char* id, int x, int y, uint16_t color = Text, int size = 24) {
  const auto* a = fire_app_bitmap::find(FireSdkData::kAssets, FireSdkData::kAssetCount, id);
  if (!a || a->width != 24 || a->height != 24 || size < 8 || size > 64) return;
  struct Target {
    Surface& c; int x, y, size;
    void fillRect(int sx, int sy, int w, int h, uint16_t ink) {
      const int left = sx * size / 24, top = sy * size / 24;
      const int right = (sx + w) * size / 24, bottom = (sy + h) * size / 24;
      if (right > left && bottom > top) c.fillRect(x + left, y + top, right - left, bottom - top, ink);
    }
  } target{c, x, y, size};
  fire_app_bitmap::asset(target, *a, 0, 0, 1, color, false, false);
}
template<class Surface>
void pill(Surface& c, int x, int y, int w, const char* label, uint16_t color = Accent) {
  fire_app_graphics::roundRect(c, x, y, w, 20, 9, Raised, true);
  text(c, x + 5, y + 2, label, color, "ui12b", w - 10, 1);
}
template<class Surface>
void footer(Surface& c, const char* left, const char* middle, const char* right) {
  c.fillRect(0, 216, 320, 24, Bg);
  c.fillRect(10, 216, 300, 1, Border);
  if (left && *left) {
    text(c, 10, 220, "A", Accent, "ui12b", 12);
    text(c, 25, 220, left, Muted, "ui12", 76);
  }
  if (middle && *middle) {
    fire_app_graphics::roundRect(c, 105, 219, 110, 20, 7, Selected, true);
    text(c, 113, 221, "B", Accent, "ui12b", 12);
    text(c, 127, 221, middle, Text, "ui12b", 80, 1);
  }
  if (right && *right) {
    text(c, 222, 220, right, Muted, "ui12", 72, 2);
    text(c, 302, 220, "C", Accent, "ui12b", 12);
  }
}
template<class Surface>
void tile(Surface& c, int x, int y, int w, int h, const char* label,
          const char* iconId, uint16_t color, bool selected) {
  panel(c, x, y, w, h, selected, color);
  fire_app_graphics::roundRect(c, x + 10, y + 8, 34, 32, 8, Raised, true);
  icon(c, iconId, x + 15, y + 12, color, 24);
  if (selected) icon(c, "icon.circle-check", x + w - 25, y + 10, color, 15);
  const char* labelFont = width(label, "ui16") <= w - 24 ? "ui16" : "ui12b";
  text(c, x + 12, y + h - 26, label, Text, labelFont, w - 24);
}
template<class Surface>
void menuRow(Surface& c, int y, const char* label, const char* value,
             bool selected, const char* iconId = nullptr) {
  fire_app_graphics::roundRect(c, 10, y, 300, 25, 7, selected ? Selected : Panel, true);
  if (selected) c.fillRect(10, y + 7, 3, 11, Accent);
  const int x = iconId ? 42 : 20;
  if (iconId) icon(c, iconId, 18, y + 3, selected ? Accent : Muted, 19);
  const bool hasValue = value && *value;
  text(c, x, y + 5, label, Text, "ui12", hasValue ? 155 : 268 - (x - 20));
  if (hasValue) text(c, 199, y + 5, value, selected ? Accent : Muted, "ui12", 100, 2);
}
template<class Surface>
void homeHeader(Surface& c, const char* title, const char* section,
                const char* connection, uint16_t connectionColor, bool camper = false) {
  c.fillRect(0, 0, 320, 240, Bg);
  icon(c, camper ? "icon.caravan" : "icon.house", 12, 8, Accent, 24);
  text(c, 46, 8, title, Text, "ui16", 147);
  pill(c, 200, 9, 110, connection, connectionColor);
  text(c, 12, 36, section, Muted, "pixel8", 290);
  c.fillRect(12, 49, 296, 1, Border);
}
template<class Surface>
void homeCard(Surface& c, int slot, bool large, const char* name,
              const char* reading, const char* detail, const char* iconId,
              uint16_t color, bool selected, bool available, bool favorite = false) {
  const int x = large ? 10 : 10 + (slot % 2) * 155;
  const int y = large ? 56 : 56 + (slot / 2) * 73;
  const int w = large ? 300 : 145, h = large ? 137 : 68;
  panel(c, x, y, w, h, selected, Accent);
  text(c, x + 12, y + 8, name, Text, large ? "ui16" : "ui12", w - (large ? 70 : 46));
  icon(c, iconId, x + w - (large ? 56 : 31), y + (large ? 18 : 9),
       available ? color : Muted, large ? 40 : 20);
  const bool numeric = reading && ((*reading >= '0' && *reading <= '9') || *reading == '-');
  const char* readingFont = large && available && numeric ? "digits28" : "title20";
  if (width(reading, readingFont) > w - (large ? 38 : 24)) readingFont = large ? "title20" : "ui16";
  if (width(reading, readingFont) > w - 24) readingFont = "ui12b";
  text(c, x + (large ? 16 : 12), y + (large ? 48 : 27), reading,
       available ? color : Muted, readingFont, w - (large ? 38 : 24));
  text(c, x + (large ? 16 : 12), y + h - (large ? 27 : 13), detail,
       available ? Muted : Amber, large ? "ui12" : "pixel8", w - (favorite ? 42 : 24));
  if (favorite) icon(c, "icon.star", x + w - 26, y + h - (large ? 22 : 15), Amber, 10);
}
}  // namespace FireUI
