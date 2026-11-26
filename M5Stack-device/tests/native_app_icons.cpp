#include "fire_app_icons.h"
#include "fire_ui.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>

struct IconSurface {
  std::array<uint16_t, 320*240> pixels{};
  void fillRect(int x,int y,int w,int h,uint16_t color) {
    assert(x>=0 && y>=0 && x+w<=320 && y+h<=240);
    for (int r=y;r<y+h;++r) for (int c=x;c<x+w;++c) pixels[r*320+c]=color;
  }
  uint16_t readPixel(int x,int y) {return pixels[y*320+x];}
};
int main() {
  struct Case {const char* name;const char* icon;};
  const Case cases[]={{"Luna-stoppeklokke","timer"},{"Kalkulator","calculator"},
    {"Prikkjakt","crosshair"},{"AI Oppdrag GC test","crosshair"},{"Vær","cloud-sun"},
    {"STRØM","zap"},{"Måledata kontroll","activity"},{"Vibrasjonsanalyse","activity"},
    {"Bluetooth lys","lightbulb"},{"Loggbok","file-text"},{"Slange spill","gamepad-2"}};
  for (const auto& c:cases) {
    assert(!std::strcmp(fire_app_icons::select(c.name)+5,c.icon));
  }
  assert(!std::strcmp(fire_app_icons::select("Stopwatch","icon.house"),"icon.house"));
  char declared[]="icon.house";
  const char* retained=fire_app_icons::select("Unknown",declared);declared[5]='x';
  assert(!std::strcmp(retained,"icon.house")); // Cached pointer owns no temporary manifest string.
  assert(!std::strcmp(fire_app_icons::select("Unknown","../../file"),"icon.code"));
  char longName[1100];std::memset(longName,'x',sizeof(longName)-1);longName[sizeof(longName)-1]=0;
  assert(!std::strcmp(fire_app_icons::select(longName),"icon.code"));
  for (const char* id:fire_app_icons::ids) {
    assert(fire_app_icons::valid(id));
    static IconSurface surface;
    surface.pixels.fill(0);
    FireUI::icon(surface,id,20,20,0xffff,24);
    unsigned lit=0;for (auto px:surface.pixels) lit+=px!=0;
    assert(lit>20 && lit<24*24);
  }
  std::puts("PASS shared app icons, Nordic fallback and actual AA rendering");
}
