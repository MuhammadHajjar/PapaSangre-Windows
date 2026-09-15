#!/bin/bash
# Build OpenAL Soft for macOS (`libopenal.dylib`) and its `makemhr` tool.
#
# The Windows build carries `soft_oal.dll` committed in vendor/openal; the Mac
# build carries the same OpenAL Soft built for this platform as
# `libopenal.dylib` in vendor/openal-mac, and `makemhr` in vendor/makemhr-mac
# (the tool that turns the recovered IRCAM 1050 set into the .mhr the game
# loads).  Both are committed, so this script is only needed when building a
# fresh sources checkout on a new machine - run it once, commit the results.
#
# Usage:
#     tools/build_openal_mac.sh [--source DIR] [--arch arm64|x86_64]
#
#   --source DIR   an OpenAL Soft source tree to build.  Default: fetch the
#                  pinned 1.25.2 release (the version the port targets) into
#                  vendor/build-openal/.
#   --arch ARCH    the architecture to build for.  Default: this machine's.
#
# Requires cmake and a C++ toolchain (Xcode command line tools).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=1.25.2
SOURCE="${ROOT}/vendor/build-openal/openal-soft"
BUILD="${ROOT}/vendor/build-openal/build-mac"
ARCH="$(uname -m)"
if [[ "${1:-}" == "--source" ]]; then SOURCE="$2"; shift 2; fi
if [[ "${1:-}" == "--arch" ]]; then ARCH="$2"; shift 2; fi

if [[ ! -f "${SOURCE}/CMakeLists.txt" ]]; then
  echo "Fetching OpenAL Soft ${VERSION} into vendor/build-openal/..."
  mkdir -p "$(dirname "${SOURCE}")"
  curl -fL "https://github.com/kcat/openal-soft/archive/refs/tags/${VERSION}.tar.gz" \
    | tar xz -C "$(dirname "${SOURCE}")"
  mv "$(dirname "${SOURCE}")/openal-soft-${VERSION}" "${SOURCE}"
fi

echo "Configuring ($(uname -m)) ..."
cmake -S "${SOURCE}" -B "${BUILD}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON \
  -DALSOFT_UTILS=ON \
  -DALSOFT_EXAMPLES=OFF \
  -DALSOFT_TESTS=OFF \
  -DALSOFT_DLOPEN=ON \
  -DCMAKE_OSX_ARCHITECTURES="${ARCH}"

cmake --build "${BUILD}" --config Release

install -m 755 "${BUILD}/libopenal.dylib" "${ROOT}/vendor/openal-mac/libopenal.dylib"
install -m 755 "${BUILD}/makemhr"          "${ROOT}/vendor/makemhr-mac/makemhr"

echo
echo "Built for ${ARCH}:"
ls -l "${ROOT}/vendor/openal-mac/libopenal.dylib" "${ROOT}/vendor/makemhr-mac/makemhr"
echo "Commit them so a fresh clone builds without a toolchain."