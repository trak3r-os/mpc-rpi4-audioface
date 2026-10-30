// SPDX-License-Identifier: GPL-3.0-or-later
// Minimal JSON reader for rpi-audiod replies: objects, arrays, strings, numbers, booleans, null.
#pragma once
#include <string>
#include <utility>
#include <vector>

namespace panel {

struct Json {
  enum Type { Null, Bool, Num, Str, Arr, Obj } type = Null;
  bool b = false;
  double num = 0;
  std::string str;
  std::vector<Json> arr;
  std::vector<std::pair<std::string, Json>> obj;

  const Json* get(const char* key) const {
    if (type != Obj) return nullptr;
    for (const auto& kv : obj)
      if (kv.first == key) return &kv.second;
    return nullptr;
  }
  int as_int(int def) const { return type == Num ? static_cast<int>(num) : def; }
  bool as_bool(bool def) const { return type == Bool ? b : def; }
  std::string as_str(const std::string& def = "") const { return type == Str ? str : def; }
};

// false on a syntax error, nesting deeper than 12, or trailing text. \uXXXX outside ASCII becomes '?'.
bool parse_json(const std::string& text, Json& out);

}  // namespace panel
