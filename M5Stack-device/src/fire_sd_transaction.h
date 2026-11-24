#pragma once
#include <stddef.h>
#include <errno.h>

struct FireSdWriteResult {
  size_t written;
  int writeError;
  int hashError;
  bool ok(size_t requested) const { return written == requested && !hashError; }
};

// A short fwrite is an error, never a reason to blindly retry its suffix.
// Capture errno before any other filesystem operation changes it.
template<class File, class Hash>
FireSdWriteResult fireWriteSdBlock(File& file, Hash& hash,
                                  const unsigned char* data, size_t size) {
  errno = 0;
  const size_t written = file.write(data, size);
  const int error = errno;
  return {written, error, written == size ? hash.update(data, size) : 0};
}

struct FireSdPublishPaths {
  const char* binaryStage;
  const char* binaryFinal;
  const char* binaryBackup;
  const char* catalogStage;
  const char* catalogFinal;
  const char* catalogBackup;
};
enum class FireSdPublishResult {
  Ok, BinaryReadback, CatalogReadback, BackupExists,
  CatalogBackup, CatalogActivate, BinaryBackup, BinaryActivate, Restore
};

// All staging bytes must already have survived close/reopen verification.
// Original files are renamed to unique backups and never deleted here.
template<class Fs>
FireSdPublishResult firePublishSdPair(Fs& fs, const FireSdPublishPaths& p) {
  if (fs.exists(p.binaryBackup) || fs.exists(p.catalogBackup))
    return FireSdPublishResult::BackupExists;
  const bool oldCatalog = fs.exists(p.catalogFinal);
  const bool oldBinary = fs.exists(p.binaryFinal);
  if (oldCatalog && !fs.rename(p.catalogFinal, p.catalogBackup))
    return FireSdPublishResult::CatalogBackup;
  if (!fs.rename(p.catalogStage, p.catalogFinal)) {
    if (oldCatalog && !fs.rename(p.catalogBackup, p.catalogFinal))
      return FireSdPublishResult::Restore;
    return FireSdPublishResult::CatalogActivate;
  }
  const auto restoreCatalog = [&]() {
    if (!fs.rename(p.catalogFinal, p.catalogStage)) return false;
    return !oldCatalog || fs.rename(p.catalogBackup, p.catalogFinal);
  };
  if (oldBinary && !fs.rename(p.binaryFinal, p.binaryBackup)) {
    if (!restoreCatalog()) return FireSdPublishResult::Restore;
    return FireSdPublishResult::BinaryBackup;
  }
  if (!fs.rename(p.binaryStage, p.binaryFinal)) {
    const bool binaryRestored = !oldBinary || fs.rename(p.binaryBackup, p.binaryFinal);
    const bool catalogRestored = restoreCatalog();
    if (!binaryRestored || !catalogRestored) return FireSdPublishResult::Restore;
    return FireSdPublishResult::BinaryActivate;
  }
  return FireSdPublishResult::Ok;
}

template<class Fs, class VerifyBinary, class WriteVerifyCatalog>
FireSdPublishResult fireFinalizeSdPair(Fs& fs, const FireSdPublishPaths& paths,
                                      VerifyBinary verifyBinary,
                                      WriteVerifyCatalog writeVerifyCatalog) {
  if (!verifyBinary()) return FireSdPublishResult::BinaryReadback;
  if (!writeVerifyCatalog()) return FireSdPublishResult::CatalogReadback;
  return firePublishSdPair(fs, paths);
}
