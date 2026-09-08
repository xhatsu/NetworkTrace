#!/usr/bin/env python3
"""
inspect_pcap_auth.py

High-performance, zero-dependency PCAP analyzer for extracting authenticated identity
(usernames) from HTTP traffic:
  1. HTTP Basic Auth: Authorization: Basic <base64> (decodes username, scrubs passwords)
  2. WSSE SOAP Auth: <wsse:Username>...</wsse:Username> inside SOAP XML Security headers
  3. WSSE HTTP Headers: X-WSSE: UsernameToken Username="..."
  4. Bearer Tokens: Decodes JWT payload to extract 'sub', 'username', 'preferred_username'

Pure Python 3 standard library - no external packages (scapy, dpkt, pyshark) required.
Compatible with standard pcap, nanosecond pcap, gzip-compressed pcap, Linux cooked v1/v2, and Ethernet.
"""

import sys
import os
import re
import struct
import base64
import json
import gzip
import argparse
from collections import defaultdict, Counter

# Regular expressions for auth identification
RE_BASIC_AUTH = re.compile(
    rb'(?:Authorization|Proxy-Authorization)\s*:\s*Basic\s+([A-Za-z0-9+/=]+)',
    re.IGNORECASE
)

RE_WSSE_XML = re.compile(
    rb'<(?:[a-zA-Z0-9_-]+:)?Username(?:Token)?(?:\s+[^>]*)?>\s*([^<>\s]+)\s*</(?:[a-zA-Z0-9_-]+:)?Username(?:Token)?>',
    re.IGNORECASE
)

RE_WSSE_HEADER = re.compile(
    rb'(?:X-WSSE|Authorization)\s*:[^\r\n]*Username="([^"]+)"',
    re.IGNORECASE
)

RE_BEARER_JWT = re.compile(
    rb'Authorization\s*:\s*Bearer\s+(ey[A-Za-z0-9_-]+\.ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)',
    re.IGNORECASE
)

RE_HTTP_REQ = re.compile(
    rb'^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+([^\s\r\n]+)\s+HTTP/1\.[01]',
    re.IGNORECASE
)

RE_SOAP_ACTION = re.compile(
    rb'SOAPAction\s*:\s*["\']?([^"\'\r\n]+)["\']?',
    re.IGNORECASE
)

def decode_basic_auth(b64_str: bytes) -> str:
    """Safely decodes base64 Basic auth, extracts username, scrubs password."""
    try:
        raw = base64.b64decode(b64_str, validate=False)
        decoded = raw.decode('utf-8', errors='replace')
        if ':' in decoded:
            username = decoded.split(':', 1)[0].strip()
        else:
            username = decoded.strip()
        return username if username else "<empty>"
    except Exception:
        return "<malformed-base64>"

def decode_jwt_username(jwt_token: bytes) -> str:
    """Extracts username or subject claim from JWT payload without verification."""
    try:
        parts = jwt_token.split(b'.')
        if len(parts) >= 2:
            payload_b64 = parts[1]
            rem = len(payload_b64) % 4
            if rem > 0:
                payload_b64 += b'=' * (4 - rem)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode('utf-8', errors='replace')
            data = json.loads(payload_json)
            for key in ('preferred_username', 'username', 'user_name', 'sub', 'client_id'):
                if key in data and str(data[key]).strip():
                    return str(data[key]).strip()
    except Exception:
        pass
    return ""

class PcapAuthScanner:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.total_packets = 0
        self.ipv4_packets = 0
        self.tcp_packets = 0
        self.http_packets = 0
        self.records = []
        self.auth_counts = Counter()
        self.user_counts = Counter()
        self.user_types = defaultdict(set)
        self.user_endpoints = defaultdict(set)
        self.user_sources = defaultdict(set)

    def scan(self):
        if not os.path.isfile(self.filepath):
            raise FileNotFoundError(f"File not found: {self.filepath}")

        # Open file (support gzip or raw pcap)
        if self.filepath.endswith('.gz'):
            opener = gzip.open(self.filepath, 'rb')
        else:
            opener = open(self.filepath, 'rb')

        with opener as f:
            header_bytes = f.read(24)
            if len(header_bytes) < 24:
                # Try raw scan if too short for pcap header
                f.seek(0)
                self._fallback_stream_scan(f)
                return

            magic = header_bytes[0:4]
            if magic in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1'):
                endian = '<'
            elif magic in (b'\xa1\xb2\xc3\xd4', b'\xa1\xb2\x3c\x4d'):
                endian = '>'
            else:
                # Unknown magic (could be pcapng or raw stream), fallback to stream regex
                f.seek(0)
                self._fallback_stream_scan(f)
                return

            # Read network / linktype from global header
            # struct format: Magic(4), Major(2), Minor(2), Zone(4), SigFigs(4), SnapLen(4), LinkType(4)
            _, _, _, _, _, snaplen, linktype = struct.unpack(f'{endian}IHHiIII', header_bytes)

            pkt_hdr_struct = f'{endian}IIII'

            while True:
                hdr = f.read(16)
                if len(hdr) < 16:
                    break
                self.total_packets += 1
                ts_sec, ts_usec, incl_len, orig_len = struct.unpack(pkt_hdr_struct, hdr)
                packet_data = f.read(incl_len)
                if len(packet_data) < incl_len:
                    break

                self._process_packet(packet_data, linktype, ts_sec)

    def _process_packet(self, data: bytes, linktype: int, ts_sec: int):
        # 1. Strip Link Layer
        payload = b''
        eth_type = 0

        if linktype == 1:  # LINKTYPE_ETHERNET
            if len(data) < 14:
                return
            eth_type = struct.unpack('>H', data[12:14])[0]
            payload = data[14:]
            if eth_type == 0x8100:  # 802.1Q VLAN tag
                if len(payload) < 4:
                    return
                eth_type = struct.unpack('>H', payload[2:4])[0]
                payload = payload[4:]

        elif linktype == 113:  # LINKTYPE_LINUX_SLL (Linux cooked v1)
            if len(data) < 16:
                return
            eth_type = struct.unpack('>H', data[14:16])[0]
            payload = data[16:]

        elif linktype == 276:  # LINKTYPE_LINUX_SLL2 (Linux cooked v2)
            if len(data) < 20:
                return
            eth_type = struct.unpack('>H', data[0:2])[0]
            payload = data[20:]

        elif linktype in (12, 101):  # LINKTYPE_RAW / LINKTYPE_IPV4
            eth_type = 0x0800
            payload = data
        else:
            # Fallback: test if payload looks like IPv4
            if len(data) > 20 and (data[0] >> 4) == 4:
                eth_type = 0x0800
                payload = data
            else:
                self._extract_auth_from_chunk(data, ts_sec, "raw_stream")
                return

        # 2. Process IPv4
        if eth_type != 0x0800 or len(payload) < 20:
            # Check for direct auth in non-IPv4 or unhandled frames
            self._extract_auth_from_chunk(payload, ts_sec, "non_ip")
            return

        self.ipv4_packets += 1
        ip_ver_ihl = payload[0]
        ihl = (ip_ver_ihl & 0x0F) * 4
        protocol = payload[9]
        src_ip = f"{payload[12]}.{payload[13]}.{payload[14]}.{payload[15]}"
        dst_ip = f"{payload[16]}.{payload[17]}.{payload[18]}.{payload[19]}"

        if protocol != 6:  # TCP
            return

        self.tcp_packets += 1
        tcp_data = payload[ihl:]
        if len(tcp_data) < 20:
            return

        src_port, dst_port = struct.unpack('>HH', tcp_data[0:4])
        tcp_hdr_len = ((tcp_data[12] >> 4) & 0x0F) * 4
        app_data = tcp_data[tcp_hdr_len:]

        if not app_data:
            return

        conn_str = f"{src_ip}:{src_port} -> {dst_ip}:{dst_port}"
        self._extract_auth_from_chunk(app_data, ts_sec, conn_str)

    def _extract_auth_from_chunk(self, data: bytes, ts_sec: int, flow_info: str):
        # Check HTTP / SOAP presence
        has_http = (
            b'HTTP/' in data or
            b'Authorization' in data or
            b'wsse:' in data or
            b'UsernameToken' in data or
            b'soapenv:' in data or
            b'SOAP-ENV:' in data
        )
        if not has_http:
            return

        self.http_packets += 1

        # Extract Request URI / Action
        uri = ""
        m_req = RE_HTTP_REQ.search(data)
        if m_req:
            uri = f"{m_req.group(1).decode('utf-8', 'ignore')} {m_req.group(2).decode('utf-8', 'ignore')}"
        else:
            m_soap = RE_SOAP_ACTION.search(data)
            if m_soap:
                uri = f"SOAPAction: {m_soap.group(1).decode('utf-8', 'ignore')}"

        # 1. HTTP Basic Auth
        for m in RE_BASIC_AUTH.finditer(data):
            b64_cred = m.group(1)
            username = decode_basic_auth(b64_cred)
            self._record_auth(
                auth_type="HTTP_BASIC_AUTH",
                username=username,
                ts_sec=ts_sec,
                flow=flow_info,
                endpoint=uri or "HTTP Request"
            )

        # 2. WSSE SOAP Auth (<wsse:Username>...)
        for m in RE_WSSE_XML.finditer(data):
            uname_bytes = m.group(1)
            username = uname_bytes.decode('utf-8', errors='replace').strip()
            if username and not username.startswith('<'):
                self._record_auth(
                    auth_type="WSSE_SOAP_XML",
                    username=username,
                    ts_sec=ts_sec,
                    flow=flow_info,
                    endpoint=uri or "SOAP Envelope"
                )

        # 3. WSSE Header Auth (X-WSSE: UsernameToken Username="...")
        for m in RE_WSSE_HEADER.finditer(data):
            uname_bytes = m.group(1)
            username = uname_bytes.decode('utf-8', errors='replace').strip()
            if username:
                self._record_auth(
                    auth_type="WSSE_HTTP_HEADER",
                    username=username,
                    ts_sec=ts_sec,
                    flow=flow_info,
                    endpoint=uri or "WSSE Header"
                )

        # 4. Bearer JWT
        for m in RE_BEARER_JWT.finditer(data):
            token = m.group(1)
            username = decode_jwt_username(token)
            if username:
                self._record_auth(
                    auth_type="HTTP_BEARER_JWT",
                    username=username,
                    ts_sec=ts_sec,
                    flow=flow_info,
                    endpoint=uri or "Bearer Request"
                )

    def _record_auth(self, auth_type: str, username: str, ts_sec: int, flow: str, endpoint: str):
        self.auth_counts[auth_type] += 1
        self.user_counts[username] += 1
        self.user_types[username].add(auth_type)
        if endpoint:
            self.user_endpoints[username].add(endpoint[:60])
        if flow:
            self.user_sources[username].add(flow)

        self.records.append({
            "timestamp": ts_sec,
            "auth_type": auth_type,
            "username": username,
            "flow": flow,
            "endpoint": endpoint
        })

    def _fallback_stream_scan(self, f):
        """Streaming scanner for raw packet streams or damaged headers."""
        chunk_size = 1024 * 1024
        buf = b''
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            data = buf + chunk
            self._extract_auth_from_chunk(data, 0, "stream_scan")
            buf = data[-1024:]  # keep overlap for boundary regex

    def report(self, verbose: bool = False, as_json: bool = False):
        if as_json:
            out = {
                "file": self.filepath,
                "stats": {
                    "total_packets": self.total_packets,
                    "ipv4_packets": self.ipv4_packets,
                    "tcp_packets": self.tcp_packets,
                    "http_packets": self.http_packets,
                    "total_auth_occurrences": len(self.records),
                    "unique_usernames": len(self.user_counts),
                    "auth_type_counts": dict(self.auth_counts)
                },
                "users": [
                    {
                        "username": u,
                        "count": self.user_counts[u],
                        "auth_types": list(self.user_types[u]),
                        "sample_endpoints": list(self.user_endpoints[u])[:5],
                        "sample_flows": list(self.user_sources[u])[:5]
                    }
                    for u, _ in self.user_counts.most_common()
                ]
            }
            if verbose:
                out["records"] = self.records
            print(json.dumps(out, indent=2))
            return

        print("=" * 80)
        print(f" PCAP Authentication & Username Inspection Report")
        print(f" File: {self.filepath}")
        print("=" * 80)
        print(" Packet Telemetry:")
        print(f"   - Total Packets:            {self.total_packets:,}")
        print(f"   - IPv4 Packets:             {self.ipv4_packets:,}")
        print(f"   - TCP Segments:             {self.tcp_packets:,}")
        print(f"   - HTTP/SOAP Segments:       {self.http_packets:,}")
        print(f"   - Total Auth Occurrences:   {len(self.records):,}")
        print(f"   - Unique Usernames:         {len(self.user_counts):,}")
        print("-" * 80)
        print(" Auth Type Breakdown:")
        for atype, cnt in self.auth_counts.most_common():
            pct = (cnt / max(1, len(self.records))) * 100
            print(f"   - {atype:<22}: {cnt:>6,}  ({pct:>5.1f}%)")
        print("-" * 80)
        print(f" Authenticated Identities (Usernames):")
        if not self.user_counts:
            print("   [!] No authenticated usernames detected in file.")
        else:
            print(f"   {'USERNAME':<28} {'AUTH TYPE':<20} {'COUNT':<8} {'SAMPLE FLOW / ENDPOINT'}")
            print(f"   {'-'*27} {'-'*19} {'-'*7} {'-'*24}")
            for u, cnt in self.user_counts.most_common():
                types_str = ",".join(self.user_types[u])
                ep = list(self.user_endpoints[u])[0] if self.user_endpoints[u] else ""
                print(f"   {u:<28} {types_str:<20} {cnt:>6,}   {ep}")

        if verbose and self.records:
            print("-" * 80)
            print(" Recent Auth Sample Log (First 25 occurrences):")
            for i, r in enumerate(self.records[:25], 1):
                print(f"   [{i:02d}] {r['auth_type']} | User: '{r['username']}' | Flow: {r['flow']} | {r['endpoint']}")

        print("=" * 80)

def main():
    parser = argparse.ArgumentParser(description="Inspect PCAP for HTTP Basic Auth & WSSE Auth Usernames")
    parser.add_argument("pcap", help="Path to PCAP / PCAP.GZ file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed occurrence trace")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    scanner = PcapAuthScanner(args.pcap)
    try:
        scanner.scan()
        scanner.report(verbose=args.verbose, as_json=args.json)
    except Exception as exc:
        print(f"Error inspecting PCAP: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
