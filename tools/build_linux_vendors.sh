#!/bin/bash
# Build OpenAL Soft (libopenal.so + makemhr) and espeak-ng for Linux.
#
# The Windows build carries soft_oal.dll and the Mac build carries
# libopenal.dylib — both committed.  This script is the Linux equivalent:
# it builds the same OpenAL Soft 1.25.2 for Linux and espeak-ng 1.51.1
# (used as a self-contained TTS engine), then places the results under
# vendor/openal-linux/, vendor/makemhr-linux/, and vendor/espeak-linux/.
#
# Run once on a Linux machine, then commit the results so a fresh clone
# builds without a toolchain.  In CI, the release workflow calls this
# before build_exes.py.
#
# Usage:
#     tools/build_linux_vendors.sh
#
# Requires: cmake, g++, autoconf, automake, libtool, pkg-config
#   Ubuntu/Debian:  apt install -y cmake g++ autoconf automake libtool pkg-config
#   Fedora/RHEL:    dnf install -y cmake gcc-c++ autoconf automake libtool pkg-config
#   Arch:           pacman -S --needed cmake gcc autoconf automake libtool pkg-config
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OPENAL_VERSION=1.25.2
ESPEAK_VERSION=1.51.1

SRC_OPENAL="${ROOT}/vendor/build-linux/openal-soft"
BUILD_OPENAL="${ROOT}/vendor/build-linux/build-openal"
SRC_ESPEAK="${ROOT}/vendor/build-linux/espeak-ng"
ESPEAK_INSTALL="${ROOT}/vendor/build-linux/espeak-install"

mkdir -p "${ROOT}/vendor/openal-linux"
mkdir -p "${ROOT}/vendor/makemhr-linux"
mkdir -p "${ROOT}/vendor/espeak-linux"

# ── OpenAL Soft ────────────────────────────────────────────────────────────
if [[ ! -f "${SRC_OPENAL}/CMakeLists.txt" ]]; then
  echo "Fetching OpenAL Soft ${OPENAL_VERSION}..."
  mkdir -p "$(dirname "${SRC_OPENAL}")"
  curl -fL "https://github.com/kcat/openal-soft/archive/refs/tags/${OPENAL_VERSION}.tar.gz" \
    | tar xz -C "$(dirname "${SRC_OPENAL}")"
  mv "$(dirname "${SRC_OPENAL}")/openal-soft-${OPENAL_VERSION}" "${SRC_OPENAL}"
fi

echo "Configuring OpenAL Soft..."
cmake -S "${SRC_OPENAL}" -B "${BUILD_OPENAL}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON \
  -DALSOFT_UTILS=ON \
  -DALSOFT_EXAMPLES=OFF \
  -DALSOFT_TESTS=OFF \
  -DALSOFT_DLOPEN=ON

cmake --build "${BUILD_OPENAL}" --config Release -- -j"$(nproc)"

# Dereference any symlinks so we store the real file.
cp -L "${BUILD_OPENAL}/libopenal.so" "${ROOT}/vendor/openal-linux/libopenal.so"
chmod 755 "${ROOT}/vendor/openal-linux/libopenal.so"
install -m 755 "${BUILD_OPENAL}/makemhr" "${ROOT}/vendor/makemhr-linux/makemhr"
echo "  OpenAL Soft: vendor/openal-linux/libopenal.so"
echo "  makemhr:     vendor/makemhr-linux/makemhr"

# ── espeak-ng ──────────────────────────────────────────────────────────────
if [[ ! -f "${SRC_ESPEAK}/configure.ac" ]]; then
  echo "Fetching espeak-ng ${ESPEAK_VERSION}..."
  mkdir -p "$(dirname "${SRC_ESPEAK}")"
  curl -fL "https://github.com/espeak-ng/espeak-ng/archive/refs/tags/${ESPEAK_VERSION}.tar.gz" \
    | tar xz -C "$(dirname "${SRC_ESPEAK}")"
  mv "$(dirname "${SRC_ESPEAK}")/espeak-ng-${ESPEAK_VERSION}" "${SRC_ESPEAK}"
fi

echo "Building espeak-ng..."
cd "${SRC_ESPEAK}"
./autogen.sh
./configure \
  --prefix="${ESPEAK_INSTALL}" \
  --without-pcaudiolib \
  --with-async \
  --disable-rpath
make -j"$(nproc)"
make install

# Bundle the CLI binary, its shared library, and the voice data.
# espeak-ng reads voice data from ESPEAK_DATA_PATH at runtime; the game sets
# this to the bundled espeak-ng-data/ directory so no system install is needed.
install -m 755 "${ESPEAK_INSTALL}/bin/espeak-ng" \
               "${ROOT}/vendor/espeak-linux/espeak-ng"

# Find the real versioned .so (not the unversioned symlink).
ESPEAK_SO=$(find "${ESPEAK_INSTALL}/lib" -name "libespeak-ng.so.*" \
            ! -type l | head -1)
if [[ -z "${ESPEAK_SO}" ]]; then
  echo "ERROR: could not find libespeak-ng.so.* in ${ESPEAK_INSTALL}/lib" >&2
  exit 1
fi
cp -L "${ESPEAK_SO}" "${ROOT}/vendor/espeak-linux/libespeak-ng.so.1"
ln -sf libespeak-ng.so.1 "${ROOT}/vendor/espeak-linux/libespeak-ng.so"

# Voice data — espeak-ng cannot speak without it.
rm -rf "${ROOT}/vendor/espeak-linux/espeak-ng-data"
cp -r "${ESPEAK_INSTALL}/lib/espeak-ng-data" \
      "${ROOT}/vendor/espeak-linux/espeak-ng-data"

echo "  espeak-ng:      vendor/espeak-linux/espeak-ng"
echo "  libespeak-ng:   vendor/espeak-linux/libespeak-ng.so.1"
echo "  espeak-ng-data: vendor/espeak-linux/espeak-ng-data/"

echo ""
echo "Built for $(uname -m) (glibc $(ldd --version | head -1 | grep -oP '\d+\.\d+$')):"
ls -lh "${ROOT}/vendor/openal-linux/libopenal.so" \
       "${ROOT}/vendor/makemhr-linux/makemhr" \
       "${ROOT}/vendor/espeak-linux/espeak-ng"
echo ""
echo "Commit vendor/openal-linux/, vendor/makemhr-linux/, vendor/espeak-linux/"
echo "so a fresh clone builds without a toolchain."
