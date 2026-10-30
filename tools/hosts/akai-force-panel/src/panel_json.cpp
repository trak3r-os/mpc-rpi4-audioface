// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_json.h"

#include <cstdlib>
#include <cstring>

namespace panel {
namespace {

struct Parser {
  const char* p;
  const char* e;

  void ws() { while (p < e && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++; }
  bool lit(const char* s, size_t n) {
    if (static_cast<size_t>(e - p) < n || std::memcmp(p, s, n) != 0) return false;
    p += n;
    return true;
  }

  bool string(std::string& out) {
    if (p >= e || *p != '"') return false;
    p++;
    out.clear();
    while (p < e) {
      unsigned char c = static_cast<unsigned char>(*p++);
      if (c == '"') return true;
      if (c < 0x20) return false;
      if (c != '\\') { out += static_cast<char>(c); continue; }
      if (p >= e) return false;
      char x = *p++;
      switch (x) {
        case '"': case '\\': case '/': out += x; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'n': out += '\n'; break;
        case 'r': out += '\r'; break;
        case 't': out += '\t'; break;
        case 'u': {
          if (e - p < 4) return false;
          unsigned cp = 0;
          for (int i = 0; i < 4; i++) {
            char h = *p++;
            cp <<= 4;
            if (h >= '0' && h <= '9') cp |= h - '0';
            else if (h >= 'a' && h <= 'f') cp |= h - 'a' + 10;
            else if (h >= 'A' && h <= 'F') cp |= h - 'A' + 10;
            else return false;
          }
          out += (cp >= 0x20 && cp < 0x7f) ? static_cast<char>(cp) : '?';
          break;
        }
        default: return false;
      }
    }
    return false;
  }

  bool value(Json& v, int depth) {
    if (depth > 12) return false;
    ws();
    if (p >= e) return false;
    char c = *p;
    if (c == '{') {
      p++;
      v.type = Json::Obj;
      ws();
      if (p < e && *p == '}') { p++; return true; }
      for (;;) {
        ws();
        std::string k;
        if (!string(k)) return false;
        ws();
        if (p >= e || *p++ != ':') return false;
        Json child;
        if (!value(child, depth + 1)) return false;
        v.obj.emplace_back(std::move(k), std::move(child));
        ws();
        if (p >= e) return false;
        if (*p == ',') { p++; continue; }
        if (*p == '}') { p++; return true; }
        return false;
      }
    }
    if (c == '[') {
      p++;
      v.type = Json::Arr;
      ws();
      if (p < e && *p == ']') { p++; return true; }
      for (;;) {
        Json child;
        if (!value(child, depth + 1)) return false;
        v.arr.push_back(std::move(child));
        ws();
        if (p >= e) return false;
        if (*p == ',') { p++; continue; }
        if (*p == ']') { p++; return true; }
        return false;
      }
    }
    if (c == '"') { v.type = Json::Str; return string(v.str); }
    if (lit("true", 4)) { v.type = Json::Bool; v.b = true; return true; }
    if (lit("false", 5)) { v.type = Json::Bool; v.b = false; return true; }
    if (lit("null", 4)) { v.type = Json::Null; return true; }
    const char* s = p;
    while (p < e && std::strchr("+-0123456789.eE", *p)) p++;
    if (p == s || p - s > 40) return false;
    std::string tok(s, p);
    char* end = nullptr;
    v.num = std::strtod(tok.c_str(), &end);
    if (!end || *end) return false;
    v.type = Json::Num;
    return true;
  }
};

}  // namespace

bool parse_json(const std::string& text, Json& out) {
  Parser ps{text.data(), text.data() + text.size()};
  Json v;
  if (!ps.value(v, 0)) return false;
  ps.ws();
  if (ps.p != ps.e) return false;
  out = std::move(v);
  return true;
}

}  // namespace panel
