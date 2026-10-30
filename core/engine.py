# -*- coding: utf-8 -*-
"""
Core DNS Probing Engine.
Handles raw socket queries: UDP (port 53), DoT (port 853), DoH (port 443),
target reachability checks, and parallel latency measurements.
"""

import base64
import concurrent.futures
import http.client
import ipaddress
import json
import os
import random
import socket
import ssl
import struct
import threading
import time

from core.storage import (
    load_dns_list,
    get_active_target,
    save_cached_latencies,
    normalize_host
)

_STRICT_TLS_CTX = ssl.create_default_context()

_TLS_CTX = ssl.create_default_context()
_TLS_CTX.check_hostname = False
_TLS_CTX.verify_mode = ssl.CERT_NONE

def is_global(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False

def make_dns_query(domain):
    qid = random.randrange(65536)
    labels = domain.rstrip(".").encode("idna").split(b".")
    for l in labels:
        if not 1 <= len(l) <= 63:
            raise ValueError("некорректная метка домена")
    qname = b"".join(bytes([len(l)]) + l for l in labels) + b"\x00"
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    return qid, header + qname + struct.pack(">HH", 1, 1)

def response_matches(qid, resp):
    return len(resp) >= 12 and struct.unpack(">H", resp[:2])[0] == qid and bool(resp[2] & 0x80)

def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("соединение закрыто")
        buf += chunk
    return buf

def extract_ips_from_dns(resp):
    if not resp or len(resp) < 12:
        return []
    try:
        flags = struct.unpack(">H", resp[2:4])[0]
        rcode = flags & 0x0F
        if rcode != 0:
            return []
        ancount = struct.unpack(">H", resp[6:8])[0]
        if ancount == 0:
            return []
        idx = 12
        while idx < len(resp) and resp[idx] != 0:
            if (resp[idx] & 0xC0) == 0xC0:
                idx += 2
                break
            idx += 1 + resp[idx]
        else:
            idx += 1
        idx += 4
        ips = []
        for _ in range(ancount):
            if idx >= len(resp):
                break
            if (resp[idx] & 0xC0) == 0xC0:
                idx += 2
            else:
                while idx < len(resp) and resp[idx] != 0:
                    if (resp[idx] & 0xC0) == 0xC0:
                        idx += 2
                        break
                    idx += 1 + resp[idx]
                else:
                    idx += 1
            if idx + 10 > len(resp):
                break
            rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", resp[idx:idx+10])
            idx += 10
            if rtype == 1 and rdlen == 4 and idx + 4 <= len(resp):
                ips.append(socket.inet_ntoa(resp[idx:idx+4]))
            idx += rdlen
        return ips
    except Exception:
        return []

def resolve_v4(host, timeout=1.5):
    try:
        ipaddress.IPv4Address(host)
        return [host]
    except ValueError:
        pass

    result = []
    def work():
        try:
            infos = socket.getaddrinfo(host, 53, socket.AF_INET, socket.SOCK_DGRAM)
            result.extend(dict.fromkeys(info[4][0] for info in infos))
        except OSError:
            pass

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    return [] if t.is_alive() else list(result)

def check_target_reachability(ips, target_host):
    ips = [ip for ip in ips if is_global(ip)]
    if not ips:
        return False, 0

    had_sni_block = False
    for ip in ips[:3]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            t0 = time.monotonic()
            try:
                s.connect((ip, 443))
                with _STRICT_TLS_CTX.wrap_socket(s, server_hostname=target_host) as ssl_sock:
                    dt = max(1, int((time.monotonic() - t0) * 1000))
                    return True, dt
            except ssl.SSLError:
                had_sni_block = True
            except OSError:
                pass

    if had_sni_block:
        return False, 0

    for ip in ips[:2]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.7)
            t0 = time.monotonic()
            try:
                s.connect((ip, 80))
                dt = max(1, int((time.monotonic() - t0) * 1000))
                return True, dt
            except OSError:
                pass

    return False, 0

def udp_query(ip, qid, pkt, timeout):
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((ip, 53))
            t0 = time.monotonic()
            s.send(pkt)
            while True:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    return None
                s.settimeout(rem)
                resp = s.recv(2048)
                if response_matches(qid, resp):
                    return resp, max(1, int((time.monotonic() - t0) * 1000))
        except OSError:
            return None

def dot_query(ip, host, qid, pkt, timeout):
    t0 = time.monotonic()
    try:
        with socket.create_connection((ip, 853), timeout=timeout) as raw, \
             _STRICT_TLS_CTX.wrap_socket(raw, server_hostname=host) as tls:
            tls.sendall(struct.pack(">H", len(pkt)) + pkt)
            raw_len = recv_exact(tls, 2)
            n = struct.unpack(">H", raw_len)[0]
            resp = recv_exact(tls, n)
            if response_matches(qid, resp):
                return resp, max(1, int((time.monotonic() - t0) * 1000))
    except (OSError, struct.error):
        return None
    return None

def doh_query(host, qid, pkt, timeout):
    path = "/dns-query?dns=" + base64.urlsafe_b64encode(pkt).decode().rstrip("=")
    t0 = time.monotonic()
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=_STRICT_TLS_CTX)
    try:
        conn.request("GET", path, headers={
            "accept": "application/dns-message",
            "user-agent": "dns-switcher"
        })
        r = conn.getresponse()
        resp = r.read(4096) if r.status == 200 else b""
        if response_matches(qid, resp):
            return resp, max(1, int((time.monotonic() - t0) * 1000))
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()
    return None

def system_resolver_ips():
    ips = []
    if os.name == "nt":
        try:
            from platforms.windows import WindowsNetworkAdapter
            w = WindowsNetworkAdapter()
            if_index, _ = w.get_active_interface_win()
            if if_index is not None:
                win_ips = w.get_current_dns_win(if_index)
                for ip in win_ips:
                    try:
                        if ipaddress.ip_address(ip).version == 4:
                            ips.append(ip)
                    except ValueError:
                        pass
        except Exception:
            pass
    else:
        # On Linux, parse /etc/resolv.conf
        try:
            with open("/etc/resolv.conf", "r", encoding="utf-8") as f:
                for line in f:
                    p = line.split()
                    if len(p) >= 2 and p[0] == "nameserver":
                        try:
                            addr = ipaddress.ip_address(p[1])
                            if addr.version == 4:
                                ips.append(p[1])
                        except ValueError:
                            pass
        except OSError:
            pass

    return ips

def probe_default(target, qid, pkt):
    dns_dt, resp = None, None
    for ip in system_resolver_ips():
        r = udp_query(ip, qid, pkt, 0.8)
        if r:
            resp, dns_dt = r
            break

    if resp is not None:
        target_ips = extract_ips_from_dns(resp)
    else:
        t0 = time.monotonic()
        target_ips = resolve_v4(target, timeout=2.0)
        dns_dt = max(1, int((time.monotonic() - t0) * 1000)) if target_ips else None

    if not target_ips:
        return {"domain": "DEFAULT", "ok": False, "text": "не найден"}

    reach_ok, _ = check_target_reachability(target_ips, target)
    if not reach_ok:
        return {"domain": "DEFAULT", "ok": False, "text": "недоступен"}

    return {"domain": "DEFAULT", "ok": True, "latency": dns_dt, "text": f"{dns_dt} ms"}

def probe_domain(domain, target=None):
    target = target or get_active_target()
    try:
        qid, pkt = make_dns_query(target)
    except ValueError:
        return {"domain": domain, "ok": False, "text": "некорректное имя"}

    if domain == "DEFAULT":
        return probe_default(target, qid, pkt)

    ips = resolve_v4(domain, timeout=1.5)
    if not ips:
        return {"domain": domain, "ok": False, "text": "не найден"}

    best = None
    for ip in ips[:2]:
        r = udp_query(ip, qid, pkt, 0.6)
        if r and (best is None or r[1] < best[0]):
            best = (r[1], r[0], "udp")

    if best is None:
        r = dot_query(ips[0], domain, qid, pkt, 0.8)
        if r:
            best = (r[1], r[0], "dot")

    if best is None:
        r = doh_query(domain, qid, pkt, 0.8)
        if r:
            best = (r[1], r[0], "doh")

    if best is None:
        return {"domain": domain, "ok": False, "text": "не отвечает"}

    dt, resp, proto = best
    target_ips = extract_ips_from_dns(resp)
    if not target_ips:
        rcode = resp[3] & 0x0F if len(resp) >= 4 else 0
        text = "регион недоступен" if rcode == 5 else "не найден"
        return {"domain": domain, "ok": False, "text": text, "ips": ips, "proto": proto}

    reach_ok, _ = check_target_reachability(target_ips, target)
    if not reach_ok:
        return {"domain": domain, "ok": False, "text": "недоступен", "ips": ips, "proto": proto}

    return {"domain": domain, "ok": True, "latency": dt, "text": f"{dt} ms", "ips": ips, "proto": proto}

def probe_all(target=None, stream=False, callback=None):
    target = target or get_active_target()
    domains = load_dns_list()
    if "DEFAULT" not in domains:
        domains.append("DEFAULT")

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        future_to_dom = {executor.submit(probe_domain, d, target): d for d in domains}
        for future in concurrent.futures.as_completed(future_to_dom):
            d = future_to_dom[future]
            try:
                res = future.result(timeout=8.0)
            except Exception:
                res = {"domain": d, "ok": False, "text": "таймаут"}
            results[res.get("domain", d)] = res
            if callback:
                callback(res)
            elif stream:
                print(json.dumps(res, ensure_ascii=False), flush=True)

    save_cached_latencies(results)
    return results
