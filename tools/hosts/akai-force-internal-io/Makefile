# SPDX-License-Identifier: GPL-3.0-or-later
#
#   make test     host test of the resampler core (gcc, libm)
#   make so       the add-on for the Force (armhf); normally run by build.sh inside Docker

CROSS ?= arm-linux-gnueabihf-
CFLAGS ?= -O2 -Wall -Wextra -std=gnu11
B = build

all: test

$(B):
	mkdir -p $(B)

test: | $(B)
	$(CC) $(CFLAGS) -o $(B)/test_mio_core test_mio_core.c mio_core.c -lm
	$(B)/test_mio_core

so: | $(B)
	$(CROSS)gcc $(CFLAGS) -fPIC -fvisibility=hidden -shared -Wl,--no-undefined \
		-o $(B)/mpc_internal_io.so mpc_internal_io.c mio_core.c -lasound -ldl -lm -lpthread

clean:
	rm -rf $(B)

.PHONY: all test so clean
