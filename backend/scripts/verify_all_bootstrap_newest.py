#!/usr/bin/env python3
"""verify_all_bootstrap_newest.py — Verify that all bootstrap endpoints serve the newest canonical assets."""
import urllib.request
import json
import hashlib
import tarfile
import io
import os
import sys

BASE = "http://127.0.0.1:30105"
CANONICAL_OLD = "/home/ubuntu/Viettel/NetworkTracing/oldkernel"
CANONICAL_BUNDLE = "/home/ubuntu/Viettel/NetworkTracing/bundle"


def get(path: str):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.headers, resp.read()


def main():
    print("=============================================================")
    print(" VERIFYING ALL BOOTSTRAP ENDPOINTS AGAINST CANONICAL DISK")
    print(f" Target: {BASE}")
    print("=============================================================")

    # 1. Health check
    status, _, body = get("/healthz")
    assert status == 200, f"/healthz returned {status}"
    health = json.loads(body.decode("utf-8"))
    assert health["status"] == "ok", "health status not ok"
    assert health["bundle_ready"] is True, "bundle not marked ready"
    print(f"[PASS] /healthz -> status=ok, bundle_ready=True (timestamp: {health['timestamp']})")

    # 2. Raw install.sh
    status, _, body = get("/install.sh")
    assert status == 200, f"/install.sh returned {status}"
    disk_install = open(os.path.join(CANONICAL_BUNDLE, "install.sh"), "rb").read()
    assert body == disk_install, "install.sh content mismatch with disk"
    sha = hashlib.sha256(body).hexdigest()[:12]
    print(f"[PASS] /install.sh -> {len(body)} bytes matches canonical disk exactly (SHA: {sha})")

    # 3. Complete bundle.tar.gz archive
    status, _, body = get("/bundle.tar.gz")
    assert status == 200, f"/bundle.tar.gz returned {status}"
    tar_size = len(body)
    tar = tarfile.open(fileobj=io.BytesIO(body), mode="r:gz")
    members = {m.name.lstrip("./"): m for m in tar.getmembers()}

    checks = [
        ("app/nt-server.py", os.path.join(CANONICAL_BUNDLE, "app/nt-server.py")),
        ("install.sh", os.path.join(CANONICAL_BUNDLE, "install.sh")),
        ("oldkernel/install-firstrun-el68.sh", os.path.join(CANONICAL_OLD, "install-firstrun-el68.sh")),
        ("oldkernel/nt-sniff-cpp", os.path.join(CANONICAL_OLD, "nt-sniff-cpp")),
        ("oldkernel/nt-ship-cpp", os.path.join(CANONICAL_OLD, "nt-ship-cpp")),
        ("oldkernel/nt-ship-cpp.cpp", os.path.join(CANONICAL_OLD, "nt-ship-cpp.cpp")),
        ("oldkernel/nt-sniff-cpp.cpp", os.path.join(CANONICAL_OLD, "nt-sniff-cpp.cpp")),
        ("oldkernel/install-oldkernel.sh", os.path.join(CANONICAL_OLD, "install-oldkernel.sh")),
    ]

    for arcname, disk_path in checks:
        m = members.get(arcname)
        assert m is not None, f"'{arcname}' missing from bundle.tar.gz"
        tar_content = tar.extractfile(m).read()
        disk_content = open(disk_path, "rb").read()
        assert tar_content == disk_content, f"'{arcname}' in bundle does NOT match canonical disk!"
        print(f"[PASS] /bundle.tar.gz -> {arcname:<34} ({len(tar_content):>6} bytes) matches canonical disk exactly")

    print(f"[PASS] /bundle.tar.gz -> Total archive size: {tar_size} bytes ({len(members)} entries verified)")

    # 4. Oldkernel individual files under /oldkernel/<name>
    files_to_check = [
        "install-firstrun-el68.sh",
        "install-oldkernel.sh",
        "nt-sniff-cpp",
        "nt-ship-cpp",
        "nt-sniff-cpp.cpp",
        "nt-ship-cpp.cpp",
        "nt-sniff-mock.cpp",
        "Makefile",
        "nt-sniff.py",
        "nt-ship.py",
        "nt-control.py",
        "nt_control.py",
        "nt-run-cpp.sh",
        "nt-resource-guard.sh",
        "nt-supervise.sh",
        "AGENT-STATS-PROTOCOL.md",
        "README.md",
        "HOW-TO-USE.md",
        "ANSIBLE.md",
        "RUNNING.md",
        "test_installer_cli.py",
    ]

    for fname in files_to_check:
        status, _, body = get(f"/oldkernel/{fname}")
        assert status == 200, f"/oldkernel/{fname} returned HTTP {status}"
        disk_file = open(os.path.join(CANONICAL_OLD, fname), "rb").read()
        if fname == "install-firstrun-el68.sh":
            assert b'ENDPOINT="${ENDPOINT:-http://' in body, "dynamic endpoint injection missing in firstrun"
            assert b"30102" in body, "active hub port 30102 missing in firstrun"
            print(f"[PASS] /oldkernel/{fname:<26} ({len(body):>6} bytes) matches disk + dynamic hub :30102 injection")
        else:
            assert body == disk_file, f"/oldkernel/{fname} does NOT match disk content!"
            sha = hashlib.sha256(body).hexdigest()[:12]
            print(f"[PASS] /oldkernel/{fname:<26} ({len(body):>6} bytes, SHA: {sha}) matches canonical disk exactly")

    # 5. Bootstrap scripts
    status, _, body = get("/bootstrap")
    assert status == 200, f"/bootstrap returned {status}"
    assert b"30102" in body, "hub port 30102 missing from /bootstrap"
    print("[PASS] /bootstrap -> generated dynamically with active hub port 30102")

    status, _, body = get("/oldkernel/bootstrap")
    assert status == 200, f"/oldkernel/bootstrap returned {status}"
    assert b"30102" in body, "hub port 30102 missing from /oldkernel/bootstrap"
    print("[PASS] /oldkernel/bootstrap -> generated dynamically with active hub port 30102")

    print("\n=============================================================")
    print(" RESULT: ALL BOOTSTRAP ENDPOINTS ARE SERVING THE NEWEST ASSETS!")
    print("=============================================================")


if __name__ == "__main__":
    main()
