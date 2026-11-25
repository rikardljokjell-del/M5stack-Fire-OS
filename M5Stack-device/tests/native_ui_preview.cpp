#include "fire_ui.h"
#include <array>
#include <cstdio>
#include <cassert>
#include <cstring>
struct Surface {
 std::array<uint16_t,320*240> pixels{}; unsigned calls=0;
 void fillRect(int x,int y,int w,int h,uint16_t color) {
  assert(x>=0 && y>=0 && w>=0 && h>=0 && x+w<=320 && y+h<=240);++calls;
  for(int row=y;row<y+h;++row) for(int col=x;col<x+w;++col) pixels[row*320+col]=color;
 }
 uint16_t readPixel(int x,int y) { assert(x>=0 && y>=0 && x<320 && y<240); return pixels[y*320+x]; }
 void save(const char* name) {
  FILE* f=std::fopen(name,"wb");assert(f);std::fprintf(f,"P6\n320 240\n255\n");
  for(auto color:pixels) {unsigned char rgb[]={static_cast<unsigned char>(((color>>11)&31)*255/31),static_cast<unsigned char>(((color>>5)&63)*255/63),static_cast<unsigned char>((color&31)*255/31)};std::fwrite(rgb,1,3,f);}std::fclose(f);
  std::printf("%s %u draw spans\n",name,calls);assert(calls<10000);
 }
};
int main(){using namespace FireUI;static Surface c;
 c.fillRect(0,0,320,240,Bg);text(c,12,8,"FIRE OS",Text,"ui16",148);pill(c,231,9,79,"19:45",Muted);text(c,12,36,"APPENE DINE",Muted,"pixel8",250);
 const char* labels[]={"AI Developer","Apps","Home","Settings"};const char* icons[]={"icon.bot","icon.layout-grid","icon.house","icon.settings"};uint16_t colors[]={Purple,Blue,Green,Muted};
 for(int i=0;i<4;++i)tile(c,12+(i%2)*152,56+(i/2)*77,144,70,labels[i],icons[i],colors[i],i==2);
 text(c,12,204,"1 / 3",Muted,"pixel8",296,1);footer(c,"Forrige","Åpne","Neste");c.save("main.ppm");
 c.calls=0;homeHeader(c,"Home","OVERSIKT","Lokalt",Green);
 homeCard(c,0,false,"Lys i stuen","På","Lys","icon.lightbulb",Amber,true,true);
 homeCard(c,1,false,"Gulvvarme","22.5 °C","Mål 23","icon.thermometer",Green,false,true);
 homeCard(c,2,false,"Innetemperatur","21.8 °C","Måleverdi","icon.activity",Blue,false,true);
 homeCard(c,3,false,"God natt","Klar","Kjør i meny","icon.sparkles",Purple,false,true);
 text(c,12,199,"Tilkoblet",Muted,"ui12",296);footer(c,"Forrige","Åpne","Neste");c.save("home.ppm");
 c.calls=0;homeHeader(c,"Camper","OVERSIKT","Utdatert",Amber,true);
 homeCard(c,0,true,"Bodelsbatteri","Utdatert","Venter på ferske data","icon.activity",Blue,true,false);
 text(c,12,199,"Venter på ferske data",Amber,"ui12",296);footer(c,"Forrige","Åpne","Neste");c.save("home-stale.ppm");
 c.calls=0;homeHeader(c,"Home","INNSTILLINGER","Lokalt",Green);
 const char* row[]={"Profil","Forbindelse","Visning","Favoritter","Oppsett på mobil","Tilbake"};const char* val[]={"Home","Auto","Fire kort","Alle kort","Åpne",""};const char* ico[]={"icon.house","icon.wifi","icon.layout-grid","icon.star","icon.sliders-horizontal","icon.arrow-left"};
 for(int i=0;i<6;++i) { menuRow(c,54+i*26,row[i],val[i],i==2,ico[i]); }
 footer(c,"Forrige","Velg","Neste");c.save("home-settings.ppm");
 c.calls=0;homeHeader(c,"Home","STYRING","Lokalt",Green);panel(c,10,56,300,96);icon(c,"icon.thermometer",263,71,Green,30);text(c,24,65,"Gulvvarme bad",Text,"ui16",230);text(c,24,93,"22.5 °C",Green,"title20",226);text(c,24,130,"Mål 23 / Auto",Muted,"ui12",272);panel(c,10,160,300,34,true,Amber);icon(c,"icon.circle-check",20,167,Amber,20);text(c,50,170,"Måltemperatur / 23 °C",Amber,"ui12b",229);text(c,12,199,"B bekrefter handlingen",Amber,"ui12",296);footer(c,"Tilbake","Bekreft","Avbryt");c.save("home-confirm.ppm");
 c.calls=0;homeHeader(c,"Home","OVERSIKT","Oppsett",Amber);panel(c,10,56,300,137);icon(c,"icon.house",24,72,Accent,36);text(c,76,76,"Koble til hjemmet",Text,"ui16",223);text(c,24,124,"Velg hva FIRE kan styre i Home Assistant.",Muted,"ui12",270);text(c,24,155,"B åpner innstillinger",Accent,"ui12b",270);footer(c,"Forrige","Oppsett","Neste");c.save("home-empty.ppm");
 return 0;
}
