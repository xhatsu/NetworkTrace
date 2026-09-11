#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OLD="$ROOT/oldkernel"
BOOT="$ROOT/bootstrap"
cd "$ROOT"
python3 -m py_compile bootstrap/nt-bootstrap.py
sh -n oldkernel/build-firstrun.sh oldkernel/install-oldkernel.sh oldkernel/cpp-e2e.sh oldkernel/nt-run-cpp.sh oldkernel/nt-resource-guard.sh oldkernel/nt-supervise.sh oldkernel/nt-test.sh oldkernel/verify-centos-runbook.sh
python3 -m py_compile oldkernel/nt-sniff.py oldkernel/nt-ship.py oldkernel/nt-control.py oldkernel/nt_control.py
make -C oldkernel clean all
sh oldkernel/build-firstrun.sh
TMP=$(mktemp -d /tmp/nt-bootstrap-verify.XXXXXX)
trap 'rm -rf "$TMP"' EXIT INT TERM
for spec in \
    'SNIFF_B64 nt-sniff.py END_SNIFF' \
    'SHIP_B64 nt-ship.py END_SHIP' \
    'CONTROL_B64 nt_control.py END_CONTROL' \
    'CONTROL_RUN_B64 nt-control.py END_CONTROL_RUN' \
    'CPP_SHIP_B64 nt-ship-cpp.cpp END_CPP_SHIP' \
    'CPP_B64 nt-sniff-cpp.cpp END_CPP' \
    'CPP_MAKE_B64 Makefile END_CPP_MAKE' \
    'CPP_RUN_B64 nt-run-cpp.sh END_CPP_RUN' \
    'RESOURCE_GUARD_B64 nt-resource-guard.sh END_RESOURCE_GUARD' \
    'SUPERVISOR_B64 nt-supervise.sh END_SUPERVISOR'; do
    set -- $spec
    sed -n "/^#__$1__\$/,/^#__$3__\$/p" oldkernel/install-firstrun-el68.sh | sed '1d;$d' | base64 -d > "$TMP/$2"
    cmp "$OLD/$2" "$TMP/$2"
done

# Package oldkernel agent code into bundle/oldkernel
BUNDLE_OLD="$ROOT/bundle/oldkernel"
mkdir -p "$BUNDLE_OLD"
for f in \
    install-firstrun-el68.sh \
    install-oldkernel.sh \
    nt-sniff-cpp \
    nt-ship-cpp \
    nt-sniff-cpp.cpp \
    nt-ship-cpp.cpp \
    nt-sniff-mock.cpp \
    Makefile \
    nt-sniff.py \
    nt-ship.py \
    nt-control.py \
    nt_control.py \
    nt-run-cpp.sh \
    nt-resource-guard.sh \
    nt-supervise.sh \
    AGENT-STATS-PROTOCOL.md \
    README.md \
    HOW-TO-USE.md \
    ANSIBLE.md \
    RUNNING.md \
    test_installer_cli.py; do
    if [ -f "$OLD/$f" ]; then
        cp -p "$OLD/$f" "$BUNDLE_OLD/$f"
    fi
done
chmod 755 "$BUNDLE_OLD"/*.sh "$BUNDLE_OLD"/nt-sniff-cpp "$BUNDLE_OLD"/nt-ship-cpp 2>/dev/null || true

sh bootstrap/package-bundle.sh
printf '%s\n' 'BOOTSTRAP-PACKAGE PASS'
printf 'firstrun_bytes=%s\n' "$(wc -c < oldkernel/install-firstrun-el68.sh | tr -d ' ')"
printf 'bundle_bytes=%s\n' "$(wc -c < bootstrap/bundle.tar.gz | tr -d ' ')"
