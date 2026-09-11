#!/bin/sh
# package-bundle.sh — Package bundle directory into bundle.tar.gz
# Strictly POSIX /bin/sh compliant.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BUNDLE_DIR="$REPO_DIR/bundle"
TARGET_TAR="$SCRIPT_DIR/bundle.tar.gz"

log()  { echo "[nt-package] $*"; }
die()  { echo "[nt-package] FAIL: $*" >&2; exit 1; }

[ -d "$BUNDLE_DIR" ] || die "bundle directory not found at $BUNDLE_DIR"

log "Source directory: $BUNDLE_DIR"
log "Target archive  : $TARGET_TAR"

TMP_TAR="$TARGET_TAR.tmp.$$"
tar -czf "$TMP_TAR" -C "$BUNDLE_DIR" . || die "tar command failed"
mv "$TMP_TAR" "$TARGET_TAR"

SIZE=$(wc -c < "$TARGET_TAR" | tr -d ' ')
log "Successfully created $TARGET_TAR ($SIZE bytes)"
