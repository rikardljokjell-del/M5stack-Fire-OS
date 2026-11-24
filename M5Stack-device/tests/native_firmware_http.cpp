#include "fire_firmware_http.h"

#include <cassert>
#include <cstdio>
#include <cstdint>
#include <string>

namespace {

bool accepted(const std::string& header, uint32_t expected = 1) {
  return fire_firmware_http::validResponse(header.data(), header.size(), expected);
}

std::string response(const std::string& fields,
                     const std::string& status = "HTTP/1.1 200 OK") {
  return status + "\r\n" + fields + "\r\n";
}

std::string lengthResponse(const std::string& value) {
  return response("Content-Length: " + value + "\r\n");
}

}  // namespace

int main() {
  const std::string valid = lengthResponse("1");
  assert(accepted(valid));
  assert(accepted(response("Content-Length: 1\r\n", "HTTP/1.0 200 OK")));
  assert(accepted(response("Content-Length: 1\r\n", "HTTP/1.1 200 ")));
  assert(accepted(response("cOnTeNt-LeNgTh:\t 1 \t\r\n")));
  assert(accepted(lengthResponse("0000000000000000000000000000001")));
  assert(accepted(response(
      "Date: Tue, 24 Nov 2026 12:00:00 GMT\r\n"
      "Server: GitHub.com\r\n"
      "Content-Type: application/octet-stream\r\n"
      "Content-Length: 4194304\r\n"
      "Content-Disposition: attachment; filename=fire.bin\r\n"
      "ETag: \"0123456789abcdef\"\r\n"
      "Accept-Ranges: bytes\r\n"
      "X-GitHub-Request-Id: A123:BCDE:456\r\n"
      "Connection: close\r\n"), 4194304));
  assert(accepted(response("Content-Length: 1\r\n"
                           "X!#$%&'*+-.^_`|~09AZaz: :value\t\r\n"
                           "X-Empty:\r\n")));

  assert(!fire_firmware_http::validResponse(nullptr, valid.size(), 1));
  assert(!accepted(valid, 0));
  assert(!accepted(valid, 2));
  assert(!accepted(valid, 4194305));
  assert(!accepted(valid, UINT32_MAX));
  assert(accepted(lengthResponse("4194303"), 4194303));
  assert(accepted(lengthResponse("4194304"), 4194304));
  assert(!accepted(lengthResponse("4194305"), 4194305));
  assert(!accepted(lengthResponse("4294967295"), 1));
  for (const char* value : {"", " ", "\t", "+1", "-1", "0", "2",
                            "1x", "x1", "1 0", "1\t0", "1,1", "1, 1",
                            "0x1", "1.0", "1e0", "4294967296",
                            "18446744073709551616",
                            "999999999999999999999999999999999999999999"}) {
    assert(!accepted(lengthResponse(value)));
  }
  assert(!accepted(response("Content-Type: application/octet-stream\r\n")));
  for (const char* duplicate : {"Content-Length: 1\r\n", "content-length: 1\r\n",
                                "CONTENT-LENGTH:\t1 \r\n", "Content-Length: 2\r\n"}) {
    assert(!accepted(response(std::string("Content-Length: 1\r\n") + duplicate)));
    assert(!accepted(response(std::string(duplicate) + "Content-Length: 1\r\n")));
  }

  for (const char* field : {"Transfer-Encoding: chunked\r\n",
                            "transfer-encoding: identity\r\n",
                            "tRaNsFeR-EnCoDiNg:\r\n",
                            "Content-Encoding: gzip\r\n",
                            "content-encoding: identity\r\n",
                            "cOnTeNt-EnCoDiNg:\r\n"}) {
    assert(!accepted(response(std::string("Content-Length: 1\r\n") + field)));
    assert(!accepted(response(std::string(field) + "Content-Length: 1\r\n")));
  }

  for (const char* status : {"HTTP/1.1 200", "HTTP/1.1 2000 OK", "HTTP/1.1 2001 OK",
                             "HTTP/1.1 200x OK", "HTTP/1.1 0200 OK",
                             "HTTP/1.1 20 OK", "HTTP/1.1 201 OK", "HTTP/1.1 206 OK",
                             "HTTP/1.1 301 OK", "HTTP/1.1 302 OK", "HTTP/1.1 307 OK",
                             "HTTP/1.1 308 OK", "HTTP/1.1 100 OK", "HTTP/1.1 404 OK",
                             "HTTP/1.1 500 OK", "HTTP/1.2 200 OK", "HTTP/2 200 OK",
                             "HTTP/1.10 200 OK", "http/1.1 200 OK", " HTTP/1.1 200 OK",
                             "HTTP/1.1\t200 OK", "HTTP/1.1  200 OK", "HTTP/1.1 200\tOK"}) {
    assert(!accepted(response("Content-Length: 1\r\n", status)));
  }

  for (const char* field : {": value\r\n", "X-No-Colon\r\n", "Content-Length : 1\r\n",
                            "Content-Length\t: 1\r\n", " Content-Length: 1\r\n",
                            "\tContent-Length: 1\r\n", "X Name: value\r\n",
                            "X(Name): value\r\n", "X/Name: value\r\n",
                            "X@Name: value\r\n", "X[Name]: value\r\n",
                            "X=Name: value\r\n", "X\\Name: value\r\n",
                            "X-Value: one\r\n two\r\n",
                            "X-Value: one\r\n\ttwo\r\n"}) {
    assert(!accepted(response(std::string("Content-Length: 1\r\n") + field)));
  }
  assert(!accepted(response("Content-Length: \r\n 1\r\n")));
  assert(!accepted(response("Content-Length: 1\r\n\tContent-Length: 1\r\n")));
  assert(!accepted("HTTP/1.1 200 OK\nContent-Length: 1\n\n"));
  assert(!accepted("HTTP/1.1 200 OK\rContent-Length: 1\r\r"));
  assert(!accepted("HTTP/1.1 200 OK\r\nContent-Length: 1\n\r\n"));
  assert(!accepted("HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\n"));

  // Every truncated prefix, including an empty input and a trailing bare CR.
  for (size_t length = 0; length < valid.size(); ++length) {
    assert(!fire_firmware_http::validResponse(valid.data(), length, 1));
  }
  assert(!accepted(valid + "x"));
  assert(!accepted(valid + "\r\n"));
  assert(!accepted(valid + "Content-Length: 1\r\n\r\n"));
  assert(!accepted(valid + valid));
  assert(!accepted(valid + std::string(1, '\0')));
  assert(!accepted(valid + std::string(1, static_cast<char>(0xff))));
  assert(!accepted("\r\n" + valid));
  assert(!accepted("HTTP/1.1 100 Continue\r\n\r\n" + valid));

  // Hostile bytes cannot hide a duplicate, split a line, or terminate a C string.
  const std::string withValue = response("Content-Length: 1\r\nX-Test: value\r\n");
  const size_t nameByte = withValue.find("X-Test") + 1;
  const size_t valueByte = withValue.find("value") + 1;
  for (unsigned int byte = 0; byte <= 255; ++byte) {
    if (byte >= 0x20 && byte <= 0x7e) continue;
    if (byte == '\t') continue;
    std::string badValue = withValue;
    badValue[valueByte] = static_cast<char>(byte);
    assert(!accepted(badValue));
    std::string badName = withValue;
    badName[nameByte] = static_cast<char>(byte);
    assert(!accepted(badName));
    std::string badStatus = valid;
    badStatus[13] = static_cast<char>(byte);
    assert(!accepted(badStatus));
  }
  // HTAB is valid in a field value, but never inside a field name.
  std::string tabName = withValue;
  tabName[nameByte] = '\t';
  assert(!accepted(tabName));
  std::string tabValue = withValue;
  tabValue[valueByte] = '\t';
  assert(accepted(tabValue));

  const std::string paddingBase = response("Content-Length: 1\r\nX-Padding: \r\n");
  for (size_t target : {size_t(8191), size_t(8192), size_t(8193)}) {
    const std::string padded = response("Content-Length: 1\r\nX-Padding: " +
        std::string(target - paddingBase.size(), 'a') + "\r\n");
    assert(padded.size() == target);
    assert(accepted(padded) == (target <= 8192));
  }
  // Explicit bounds do not rely on a NUL terminator and exclude nearby bytes.
  const std::string extra = valid + "body";
  assert(fire_firmware_http::validResponse(extra.data(), valid.size(), 1));
  assert(!fire_firmware_http::validResponse(extra.data(), extra.size(), 1));
  const std::string huge = valid + std::string(20000, 'a');
  assert(!accepted(huge));

  std::puts("PASS strict firmware HTTP");
}
