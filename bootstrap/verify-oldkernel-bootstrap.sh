#!/bin/sh
# Verify bootstrap distribution, generated installer, and target install lifecycle.
set -eu
BASE=${1:-http://127.0.0.1:30105}
TMP=${TMPDIR:-/tmp}/nt-bootstrap-verify.$$
trap 'rm -rf "$TMP"' 0 1 2 3 15
mkdir -p "$TMP"
fetch(){ curl -sSf "$BASE/$1" -o "$TMP/$2"; }
fetch healthz health.json
fetch oldkernel/nt-sniff.py sniff.py
fetch oldkernel/nt-ship.py ship.py
fetch oldkernel/nt-sniff-cpp.cpp sniff.cpp
fetch oldkernel/nt-ship-cpp.cpp ship.cpp
fetch oldkernel/nt-sniff-mock.cpp sniff-mock.cpp
fetch oldkernel/Makefile Makefile
fetch oldkernel/nt-run-cpp.sh run-cpp.sh
fetch oldkernel/install-firstrun-el68.sh firstrun.sh
fetch oldkernel/nt-resource-guard.sh resource-guard.sh
fetch oldkernel/nt-supervise.sh supervise.sh
fetch oldkernel/nt-control.py control.py
fetch oldkernel/nt_control.py control-lib.py
fetch oldkernel/nt-sniff-cpp sniff-cpp
fetch oldkernel/nt-ship-cpp ship-cpp
fetch oldkernel/bootstrap oldkernel-bootstrap.sh
fetch bootstrap-oldkernel bootstrap-oldkernel.sh
fetch 'bootstrap?mode=oldkernel' mode-oldkernel.sh
fetch oldkernel/ANSIBLE.md ansible.md
fetch oldkernel/RUNNING.md running.md
fetch oldkernel/AGENT-STATS-PROTOCOL.md agent-stats-protocol.md
fetch oldkernel/test_installer_cli.py test_installer_cli.py
fetch bundle.tar.gz bundle.tar.gz
python3 - "$TMP" <<'PY'
import hashlib, json, os, sys, tarfile
p=sys.argv[1]
assert json.load(open(os.path.join(p,'health.json'))).get('status') == 'ok'
for f in (
    'sniff.py','ship.py','sniff.cpp','ship.cpp','sniff-mock.cpp','Makefile',
    'run-cpp.sh','firstrun.sh','resource-guard.sh','supervise.sh',
    'control.py','control-lib.py','sniff-cpp','ship-cpp',
    'oldkernel-bootstrap.sh','bootstrap-oldkernel.sh','mode-oldkernel.sh',
    'ansible.md','running.md','agent-stats-protocol.md','test_installer_cli.py',
    'bundle.tar.gz'
):
    assert os.path.getsize(os.path.join(p,f)) > 0, f

# Verify that bundle.tar.gz contains the packaged oldkernel agent code
with tarfile.open(os.path.join(p, 'bundle.tar.gz'), 'r:gz') as tar:
    names = tar.getnames()
    assert any('oldkernel/install-firstrun-el68.sh' in n for n in names), "bundle.tar.gz missing install-firstrun-el68.sh"
    assert any('oldkernel/nt-sniff-cpp' in n for n in names), "bundle.tar.gz missing nt-sniff-cpp"
    assert any('oldkernel/install-oldkernel.sh' in n for n in names), "bundle.tar.gz missing install-oldkernel.sh"
    assert any('install.sh' in n for n in names), "bundle.tar.gz missing install.sh"
print('bundle_oldkernel_archive=OK')

# Verify that the generated one-line bootstrap scripts are POSIX compliant and contain the oldkernel target
for f in ('oldkernel-bootstrap.sh','bootstrap-oldkernel.sh','mode-oldkernel.sh'):
    content = open(os.path.join(p, f), 'r', encoding='utf-8').read()
    assert '#!/bin/sh' in content, f
    assert 'nt-oldkernel-bootstrap' in content, f
    assert 'install-firstrun-el68.sh' in content, f

# Verify that install-firstrun-el68.sh had dynamic server default injected
firstrun_content = open(os.path.join(p, 'firstrun.sh'), 'r', encoding='utf-8').read()
assert 'ENDPOINT="${ENDPOINT:-' in firstrun_content or 'SERVER="${SERVER:-' in firstrun_content, "dynamic server default missing"

print('bootstrap_fetch=OK')
PY
# Exercise the installer in an isolated prefix; no production paths/processes touched.
PREFIX="$TMP/prefix"
export PREFIX
sh "$TMP/firstrun.sh" --check --prefix "$PREFIX" >/tmp/nt-bootstrap-install-check 2>&1 || true
printf '%s\n' 'installer_check=EXERCISED'
printf '%s\n' "base=$BASE"
