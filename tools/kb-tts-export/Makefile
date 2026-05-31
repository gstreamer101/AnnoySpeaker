# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

SRC := kb-tts-export.m
BIN := kb-tts-export

CFLAGS  := -fobjc-arc -O2 -Wall -Wextra
LDFLAGS := -framework Foundation -framework AVFoundation

$(BIN): $(SRC)
	clang $(CFLAGS) -o $(BIN) $(SRC) $(LDFLAGS)

clean:
	rm -f $(BIN)

.PHONY: clean
