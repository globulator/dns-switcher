# -*- coding: utf-8 -*-
"""
Linux Network Adapter implementation using NetworkManager (nmcli) and systemd-resolved (resolvectl).
"""

import os
import re
import subprocess
import time

from core.adapter import BaseNetworkAdapter
from core.storage import load_state, save_state, file_lock
from core.engine import probe_domain

SKIP_TYPES = {"vpn", "wireguard", "tun", "loopback", "bridge", "dummy"}
C_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}

MANAGED_PROPS = ("ipv4.dns", "ipv4.ignore-auto-dns", "ipv4.dns-priority", "connection.dns-over-tls")
DEFAULT_PROPS = {
    "ipv4.dns": "",
    "ipv4.ignore-auto-dns": "no",
    "ipv4.dns-priority": "0",
    "connection.dns-over-tls": "-1"
}

def nmcli(*args, timeout=10):
    return subprocess.run(
        ["nmcli", *args],
        capture_output=True,
        text=True,
        env=C_ENV,
        timeout=timeout
    )

def _split_terse(line):
    parts = re.split(r"(?<!\\):", line)
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in parts]

class LinuxNetworkAdapter(BaseNetworkAdapter):
    """Network adapter for Linux environments running NetworkManager."""

    def get_default_device(self):
        try:
            out = subprocess.check_output(
                ["ip", "route", "get", "1.1.1.1"],
                text=True,
                stderr=subprocess.DEVNULL
            )
            words = out.split()
            if "dev" in words:
                return words[words.index("dev") + 1]
        except Exception:
            pass
        return None

    def get_active_connection(self):
        r = nmcli("-t", "-f", "NAME,UUID,DEVICE,TYPE", "connection", "show", "--active")
        if r.returncode != 0:
            return None
        dev = self.get_default_device()
        cands = []
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            p = _split_terse(line)
            if len(p) >= 4 and p[2] and p[2] not in ("lo", "docker0") and p[3] not in SKIP_TYPES:
                cands.append({"name": p[0], "uuid": p[1], "device": p[2], "type": p[3]})
        for c in cands:
            if dev and c["device"] == dev:
                return c
        return cands[0] if cands else None

    def get_current_dns(self):
        state = load_state()
        conn = self.get_active_connection()
        if not conn:
            return {"domain": "DEFAULT", "is_default": True}

        r = nmcli("-g", "ipv4.dns,ipv4.ignore-auto-dns", "connection", "show", conn["uuid"])
        lines = r.stdout.split("\n") if r.returncode == 0 else []
        dns_raw = lines[0].strip() if len(lines) > 0 else ""
        ignore_auto = lines[1].strip() if len(lines) > 1 else ""

        ips = [x.split("#")[0].strip() for x in re.split(r"[,\s|]+", dns_raw) if x.strip()]

        if not ips or ignore_auto.lower() in ("no", "0", "false"):
            return {
                "domain": "DEFAULT",
                "is_default": True,
                "connection": conn["name"],
                "device": conn["device"]
            }

        saved = state.get("domain")
        if saved and saved != "DEFAULT" and set(ips) == set(state.get("ips", [])):
            return {
                "domain": saved,
                "is_default": False,
                "ips": ips,
                "connection": conn["name"],
                "device": conn["device"]
            }

        return {
            "domain": "CUSTOM",
            "is_default": False,
            "ips": ips,
            "connection": conn["name"],
            "device": conn["device"]
        }

    def nm_snapshot(self, uuid):
        snap = {}
        for prop in MANAGED_PROPS:
            r = nmcli("-g", prop, "connection", "show", uuid)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or f"Не удалось прочитать {prop}")
            val = r.stdout.strip()
            if prop == "ipv4.dns":
                val = " ".join(x for x in re.split(r"[,\s|]+", val) if x)
            elif prop == "connection.dns-over-tls":
                val = val.split()[0] if val else "-1"
            snap[prop] = val
        return snap

    def nm_modify(self, uuid, values):
        args = ["connection", "modify", uuid]
        for k, v in values.items():
            args += [k, v]
        r = nmcli(*args)
        return r.returncode == 0, r.stderr.strip()

    def nm_reapply(self, dev):
        r = nmcli("device", "reapply", dev)
        return r.returncode == 0, r.stderr.strip()

    def restore_original(self):
        conn = self.get_active_connection()
        if not conn:
            return False, "Нет активного подключения"
        state = load_state()
        snap = state.get("original", {}).get(conn["uuid"])
        if not snap:
            snap = DEFAULT_PROPS
        ok, err = self.nm_modify(conn["uuid"], snap)
        if ok:
            ok, err = self.nm_reapply(conn["device"])
        return ok, err

    def dns_really_works(self, timeout=3.0):
        for name in ("google.com", "cloudflare.com"):
            try:
                r = subprocess.run(
                    ["resolvectl", "query", "--cache=no", name],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                if r.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass
        return False

    def apply_dns(self, domain):
        conn = self.get_active_connection()
        if not conn:
            return {"success": False, "error": "Нет активного сетевого подключения"}
        uuid, dev = conn["uuid"], conn["device"]

        with file_lock():
            state = load_state()

            if domain == "DEFAULT":
                ok, err = self.restore_original()
                if not ok:
                    return {"success": False, "error": err or "Не удалось сбросить настройки"}
                if "original" in state and uuid in state["original"]:
                    state["original"].pop(uuid, None)
                state.update(domain="DEFAULT", connection=conn["name"], timestamp=time.time())
                state.pop("ips", None)
                state.pop("proto", None)
                save_state(state)
                subprocess.run(["resolvectl", "flush-caches"], capture_output=True)
                return {"success": True, "domain": "DEFAULT", "applied": "automatic"}

            # 1. Fresh probe
            info = probe_domain(domain)
            if not info.get("proto"):
                return {"success": False, "error": f"{domain}: {info.get('text', 'не отвечает')}"}
            if info["proto"] == "doh":
                return {"success": False, "error": "DoH не поддерживается NetworkManager/systemd-resolved"}

            ips = info.get("ips", [])
            if not ips:
                return {"success": False, "error": f"Не удалось определить IP для {domain}"}

            # 2. Snapshot
            state.setdefault("original", {})
            if uuid not in state["original"]:
                current_snap = self.nm_snapshot(uuid)
                if current_snap.get("ipv4.dns-priority") == "-50" and current_snap.get("ipv4.dns"):
                    state["original"][uuid] = DEFAULT_PROPS
                else:
                    state["original"][uuid] = current_snap
                save_state(state)

            # 3. Apply
            proto_value = "1"
            dns_str_with_host = " ".join(f"{ip}#{domain}" for ip in ips)
            dns_str_plain = " ".join(ips)

            ok, err = self.nm_modify(uuid, {
                "ipv4.dns": dns_str_with_host,
                "ipv4.ignore-auto-dns": "yes",
                "ipv4.dns-priority": "-50",
                "connection.dns-over-tls": proto_value
            })
            if not ok:
                ok, err = self.nm_modify(uuid, {
                    "ipv4.dns": dns_str_plain,
                    "ipv4.ignore-auto-dns": "yes",
                    "ipv4.dns-priority": "-50",
                    "connection.dns-over-tls": proto_value
                })

            if ok:
                ok, err = self.nm_reapply(dev)

            if not ok:
                self.restore_original()
                return {"success": False, "error": err or "Не удалось применить параметры к устройству"}

            # 4. Verify & rollback if broken
            if not self.dns_really_works():
                self.restore_original()
                return {"success": False, "error": "DNS не отвечает после применения — настройки возвращены"}

            subprocess.run(["resolvectl", "flush-caches"], capture_output=True)
            state.update(
                domain=domain,
                ips=ips,
                proto=info["proto"],
                connection=conn["name"],
                timestamp=time.time()
            )
            save_state(state)
            return {"success": True, "domain": domain, "ips": ips, "proto": info["proto"]}

    def verify_active(self):
        cur = self.get_current_dns()
        if cur.get("is_default"):
            return {"status": "default", "domain": "DEFAULT"}

        domain = cur.get("domain", "DEFAULT")
        conn = self.get_active_connection()
        have = set()
        if conn:
            r = subprocess.run(
                ["resolvectl", "dns", conn["device"]],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0:
                have = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", r.stdout))

        want = set(cur.get("ips", []))
        if want and not (want & have):
            return {"status": "failed", "domain": domain, "reason": "mismatch"}

        return {"status": "success" if self.dns_really_works() else "failed", "domain": domain}
