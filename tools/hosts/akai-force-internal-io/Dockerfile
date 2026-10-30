# SPDX-License-Identifier: GPL-3.0-or-later
# armhf cross build for the Akai Force (glibc 2.39, libasound 1.2.11 there).
# Debian bookworm ships glibc 2.36 and libasound 1.2.8: older than the Force's,
# which is the safe direction for binary compatibility.
FROM debian:bookworm
RUN dpkg --add-architecture armhf \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      crossbuild-essential-armhf libasound2-dev:armhf make \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
