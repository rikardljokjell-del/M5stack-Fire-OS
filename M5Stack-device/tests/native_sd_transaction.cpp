#include "fire_sd_transaction.h"
#include <assert.h>
#include <stdio.h>
#include <map>
#include <string>

struct Writer {
  unsigned calls = 0;
  bool shortWrite = false;
  size_t write(const unsigned char*, size_t n) {
    ++calls; if (shortWrite) { errno = EIO; return n - 1; } return n;
  }
};
struct Hash {
  unsigned calls = 0; int error = 0;
  int update(const unsigned char*, size_t) { ++calls; return error; }
};
struct Fs {
  std::map<std::string, std::string> files;
  int renames = 0, failAt = 0;
  bool exists(const char* p) { return files.count(p) != 0; }
  bool rename(const char* a, const char* b) {
    if (++renames == failAt || !exists(a) || exists(b)) return false;
    files[b] = files[a]; files.erase(a); return true;
  }
};

int main() {
  const unsigned char bytes[] = {0,1,2,3};
  Writer writer; Hash hash;
  writer.shortWrite = true;
  auto shortResult = fireWriteSdBlock(writer, hash, bytes, sizeof(bytes));
  assert(!shortResult.ok(sizeof(bytes)) && shortResult.written == 3 && shortResult.writeError == EIO);
  assert(writer.calls == 1 && hash.calls == 0);
  writer.shortWrite = false; hash.error = -7;
  auto hashResult = fireWriteSdBlock(writer, hash, bytes, sizeof(bytes));
  assert(!hashResult.ok(sizeof(bytes)) && hashResult.written == 4 && hashResult.hashError == -7);

  const FireSdPublishPaths paths = {"bin.stage","bin","bin.backup","cat.stage","cat","cat.backup"};
  const auto fresh = []() { Fs fs; fs.files = {{"bin.stage","new"},{"cat.stage","signed-new"},
      {"bin","old"},{"cat","signed-old"}}; return fs; };
  auto corrupt = fresh(); bool catalogCalled = false;
  assert(fireFinalizeSdPair(corrupt,paths,[](){return false;},[&](){catalogCalled=true;return true;})
      == FireSdPublishResult::BinaryReadback);
  assert(!catalogCalled && corrupt.renames == 0 && corrupt.files["bin"] == "old");
  auto badCatalog = fresh();
  assert(fireFinalizeSdPair(badCatalog,paths,[](){return true;},[](){return false;})
      == FireSdPublishResult::CatalogReadback);
  assert(badCatalog.renames == 0 && badCatalog.files["cat"] == "signed-old");
  for (int failure = 1; failure <= 4; ++failure) {
    auto fs = fresh(); fs.failAt = failure;
    assert(fireFinalizeSdPair(fs,paths,[](){return true;},[](){return true;}) != FireSdPublishResult::Ok);
    assert(fs.files["bin"] == "old" && fs.files["cat"] == "signed-old");
  }
  auto good = fresh();
  assert(fireFinalizeSdPair(good,paths,[](){return true;},[](){return true;}) == FireSdPublishResult::Ok);
  assert(good.files["bin"] == "new" && good.files["cat"] == "signed-new");
  assert(good.files["bin.backup"] == "old" && good.files["cat.backup"] == "signed-old");
  puts("PASS actual SD short-write/readback/publish guards");
}
