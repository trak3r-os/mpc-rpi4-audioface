#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the rpi-audio Panel VST2.
#   build.sh gen    parameter table, skin and previews (build/)
#   build.sh host   native .so (build/host/)
#   build.sh test   unit tests under ASan+UBSan, then TSan, then the wrapper test
#   build.sh arm    armhf .so in Docker (glibc 2.31 ABI), with the ABI check
#   build.sh all    gen, test, arm
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
MODE="${1:-all}"
ARM_IMAGE="${PANEL_ARM_IMAGE:-rpi-audio-panel-armhf:bullseye}"
SO=rpi_audio_panel.so
MAX_GLIBC="2.32"   # MPC OS 2.x; barsiren's floor
WRAP=../vendor/mpc-vst-plugins/wrapper
CORE=(src/panel_json.cpp src/panel_protocol.cpp src/panel_model.cpp src/panel_core.cpp src/panel_engine.cpp src/panel_io_alsa.cpp)
INC=(-Ibuild -Isrc -I"$WRAP")
CXXW=(-std=c++17 -Wall -Wextra -Wno-unused-parameter -Wno-psabi -fPIC -pthread)
CW=(-std=gnu11 -Wall -Wextra -Wno-unused-parameter -fPIC)

gen() { python3 skin.py build; }

have_alsa() { [[ -f /usr/include/alsa/asoundlib.h ]]; }

build_so() {  # target cc cxx arch-flags... ; builds build/<target>/$SO
  local target="$1" cc="$2" cxx="$3"; shift 3
  local out="build/$target" extra=("$@") objs=() src
  mkdir -p "$out"
  "$cc" "${CW[@]}" -O2 -g -fvisibility=hidden "${INC[@]}" "${extra[@]}" -c "$WRAP/vst2_wrap.c" -o "$out/wrapper.o"
  objs+=("$out/wrapper.o")
  for src in "${CORE[@]}" src/panel_plugin.cpp; do
    "$cxx" "${CXXW[@]}" -O2 -g -fvisibility=hidden "${INC[@]}" "${extra[@]}" $ALSA_FLAGS -c "$src" -o "$out/$(basename "${src%.*}").o"
    objs+=("$out/$(basename "${src%.*}").o")
  done
  "$cxx" -shared -O2 "${extra[@]}" "${objs[@]}" $LINK_FLAGS -Wl,--no-undefined -Wl,--exclude-libs,ALL \
    -Wl,--version-script=exports.map -o "$out/$SO"
}

host() {
  gen
  ALSA_FLAGS=""; LINK_FLAGS="-lpthread"
  if have_alsa; then LINK_FLAGS="-lasound -lpthread"; else
    echo "note: no ALSA headers on this machine, the host .so is built without the sequencer link (PANEL_NO_ALSA)"
    ALSA_FLAGS="-DPANEL_NO_ALSA"
  fi
  build_so host gcc g++
  echo "Built build/host/$SO"
}

tests() {
  gen
  mkdir -p build/test
  local flavour opts
  for flavour in asan tsan; do
    if [[ $flavour == asan ]]; then opts=(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all)
    else opts=(-fsanitize=thread); fi
    g++ "${CXXW[@]}" -O1 -g "${opts[@]}" "${INC[@]}" -DPANEL_NO_ALSA -Itests "${CORE[@]}" tests/unit.cpp \
      -o "build/test/unit_$flavour" -lpthread
    echo "== unit tests ($flavour)"
    local run=()
    # TSan needs ASLR off on kernels with a high mmap_rnd_bits
    if [[ $flavour == tsan ]] && command -v setarch >/dev/null; then run=(setarch "$(uname -m)" -R); fi
    ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 TSAN_OPTIONS=halt_on_error=1 "${run[@]}" "build/test/unit_$flavour"
  done
  # the plugin as the host sees it: wrapper + engine + a scripted link
  gcc "${CW[@]}" -O1 -g -fsanitize=address,undefined "${INC[@]}" -c "$WRAP/vst2_wrap.c" -o build/test/wrapper.o
  g++ "${CXXW[@]}" -O1 -g -fsanitize=address,undefined "${INC[@]}" -DPANEL_NO_ALSA -DPANEL_TEST_IO -Itests \
    "${CORE[@]}" src/panel_plugin.cpp tests/wrapper_test.cpp build/test/wrapper.o -o build/test/wrapper_test -lpthread
  echo "== wrapper test"
  ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 build/test/wrapper_test
}

arm_internal() {
  gen_params_only
  local so=build/arm/$SO
  ALSA_FLAGS="-idirafter /usr/include"
  LINK_FLAGS="-static-libstdc++ -static-libgcc -L/usr/lib/arm-linux-gnueabihf -Wl,-rpath-link,/usr/lib/arm-linux-gnueabihf -lasound -lpthread"
  build_so arm arm-linux-gnueabihf-gcc arm-linux-gnueabihf-g++ -mcpu=cortex-a17 -mfpu=neon-vfpv4 -mfloat-abi=hard
  arm-linux-gnueabihf-strip "$so"
  echo "== armhf ABI check"
  arm-linux-gnueabihf-readelf -h "$so" | sed -n '/Class:/p;/Machine:/p;/Flags:/p'
  echo "Needed libraries:"; arm-linux-gnueabihf-readelf -d "$so" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/  \1/p'
  local highest
  highest="$(arm-linux-gnueabihf-readelf -V "$so" | grep -o 'GLIBC_[0-9.]\+' | sort -Vu | tail -1)"
  echo "Highest required glibc: $highest"
  echo "Other symbol versions: $(arm-linux-gnueabihf-readelf -V "$so" | grep -o '\(GLIBCXX\|CXXABI\|GCC\|ALSA\)_[0-9.]\+' | sort -Vu | tr '\n' ' ')"
  python3 - "$highest" "$MAX_GLIBC" <<'PY'
import sys
v = tuple(map(int, sys.argv[1].removeprefix('GLIBC_').split('.')))
m = tuple(map(int, sys.argv[2].split('.')))
if v > m:
    raise SystemExit('ARM artifact requires glibc newer than %s' % sys.argv[2])
PY
  local exports
  exports="$(arm-linux-gnueabihf-readelf --dyn-syms -W "$so" | awk '$5=="GLOBAL" && $7!="UND" && $8!="" {print $8}' | sort -u | tr '\n' ' ')"
  echo "Exports: $exports"
  [[ "$exports" == "VSTPluginMain " ]] || { echo "unexpected exports" >&2; exit 1; }
  echo "Built $so ($(stat -c %s "$so") bytes)"
}

gen_params_only() { [[ -f build/params.h ]] || { echo "run build.sh gen first" >&2; exit 1; }; }

arm() {
  gen
  if ! docker image inspect "$ARM_IMAGE" >/dev/null 2>&1; then
    docker build -f Dockerfile.arm -t "$ARM_IMAGE" .
  fi
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/..:/work" -w /work/akai-force-panel "$ARM_IMAGE" bash build.sh arm-internal
}

case "$MODE" in
  gen) gen ;;
  host) host ;;
  test) tests ;;
  arm) arm ;;
  arm-internal) arm_internal ;;
  all) tests; arm ;;
  *) echo "Usage: $0 [gen|host|test|arm|all]" >&2; exit 2 ;;
esac
