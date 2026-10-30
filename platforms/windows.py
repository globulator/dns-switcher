# -*- coding: utf-8 -*-
"""
Windows Network Adapter implementation using PowerShell and netsh.
"""

import json
import os
import socket
import subprocess
import time

from core.adapter import BaseNetworkAdapter
from core.storage import load_state, save_state, file_lock
from core.engine import probe_domain

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def run_powershell(command, timeout=10):
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return False, "", str(e)

class WindowsNetworkAdapter(BaseNetworkAdapter):
    """Network adapter for Windows 10/11 environments."""

    def is_admin(self):
        if os.name == "nt":
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        return True

    def get_active_interface_win(self):
        ps_cmd = (
            "$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
            "Sort-Object {$_.RouteMetric + $_.InterfaceMetric} | Select-Object -First 1; "
            "if ($r) { "
            "  $iface = Get-NetIPInterface -InterfaceIndex $r.InterfaceIndex -AddressFamily IPv4 | Select-Object -First 1; "
            "  [PSCustomObject]@{ InterfaceIndex = $r.InterfaceIndex; InterfaceAlias = $iface.InterfaceAlias } | ConvertTo-Json -Compress "
            "}"
        )
        ok, out, _ = run_powershell(ps_cmd, timeout=5)
        if ok and out:
            try:
                data = json.loads(out)
                return data.get("InterfaceIndex"), data.get("InterfaceAlias")
            except Exception:
                pass
        return None, None

    def get_current_dns_win(self, if_index):
        ps_cmd = (
            f"$addrs = (Get-DnsClientServerAddress -InterfaceIndex {if_index} -AddressFamily IPv4).ServerAddresses; "
            "if ($addrs) { $addrs -join ',' } else { '' }"
        )
        ok, out, _ = run_powershell(ps_cmd, timeout=5)
        if ok and out:
            return [ip.strip() for ip in out.split(",") if ip.strip()]
        return []

    def get_active_connection(self):
        if_index, if_alias = self.get_active_interface_win()
        if if_index is not None:
            return {"name": if_alias or f"Adapter #{if_index}", "device": str(if_index), "uuid": str(if_index)}
        return None

    def get_current_dns(self):
        if os.name != "nt":
            state = load_state()
            dom = state.get("domain", "DEFAULT")
            return {"domain": dom, "is_default": (dom == "DEFAULT"), "connection": "Ethernet (Dev)"}

        if_index, if_alias = self.get_active_interface_win()
        if if_index is None:
            return {"domain": "DEFAULT", "is_default": True, "connection": "Не найдено"}

        current_ips = self.get_current_dns_win(if_index)
        state = load_state()

        if not current_ips:
            return {
                "domain": "DEFAULT",
                "is_default": True,
                "connection": if_alias or f"Adapter #{if_index}",
                "device": str(if_index)
            }

        saved_dom = state.get("domain")
        saved_ips = state.get("ips", [])
        if saved_dom and saved_dom != "DEFAULT" and set(current_ips) == set(saved_ips):
            return {
                "domain": saved_dom,
                "is_default": False,
                "ips": current_ips,
                "connection": if_alias or f"Adapter #{if_index}",
                "device": str(if_index)
            }

        return {
            "domain": "CUSTOM",
            "is_default": False,
            "ips": current_ips,
            "connection": if_alias or f"Adapter #{if_index}",
            "device": str(if_index)
        }

    def dns_really_works(self, timeout=3.0):
        for host in ("google.com", "cloudflare.com"):
            try:
                socket.gethostbyname(host)
                return True
            except Exception:
                continue
        return False

    def restore_original(self):
        if_index, if_alias = self.get_active_interface_win()
        if if_index is None:
            return False, "Сетевой адаптер не найден"
        ps_reset = f"Set-DnsClientServerAddress -InterfaceIndex {if_index} -ResetServerAddresses; Clear-DnsClientCache"
        ok, _, err = run_powershell(ps_reset)
        return ok, err

    def apply_dns(self, domain):
        if os.name != "nt":
            # Dev simulation
            state = load_state()
            state.update(domain=domain, timestamp=time.time())
            save_state(state)
            return {"success": True, "domain": domain, "ips": ["1.1.1.1"], "proto": "udp"}

        if not self.is_admin():
            return {"success": False, "error": "Требуются права Администратора для изменения DNS"}

        if_index, if_alias = self.get_active_interface_win()
        if if_index is None:
            return {"success": False, "error": "Активный сетевой адаптер не найден"}

        with file_lock():
            state = load_state()
            state.setdefault("original", {})

            # Snapshot
            if str(if_index) not in state["original"]:
                state["original"][str(if_index)] = self.get_current_dns_win(if_index)
                save_state(state)

            if domain == "DEFAULT":
                ok, err = self.restore_original()
                if not ok:
                    return {"success": False, "error": f"Ошибка сброса DNS: {err}"}
                state.update(domain="DEFAULT", connection=if_alias, timestamp=time.time())
                state.pop("ips", None)
                state.pop("proto", None)
                save_state(state)
                return {"success": True, "domain": "DEFAULT", "applied": "automatic"}

            # Fresh probe
            info = probe_domain(domain)
            if not info.get("ok") and not info.get("ips"):
                return {"success": False, "error": f"{domain}: {info.get('text', 'не отвечает')}"}

            ips = info.get("ips", [])
            if not ips:
                return {"success": False, "error": f"Не удалось определить IP для {domain}"}

            # Apply
            ip_args = ", ".join(f"'{ip}'" for ip in ips[:2])
            ps_apply = f"Set-DnsClientServerAddress -InterfaceIndex {if_index} -ServerAddresses @({ip_args}); Clear-DnsClientCache"
            ok, _, err = run_powershell(ps_apply)
            if not ok:
                return {"success": False, "error": f"Не удалось применить DNS: {err}"}

            time.sleep(0.5)
            if not self.dns_really_works():
                # Rollback
                orig = state.get("original", {}).get(str(if_index), [])
                if orig:
                    orig_args = ", ".join(f"'{ip}'" for ip in orig)
                    ps_rb = f"Set-DnsClientServerAddress -InterfaceIndex {if_index} -ServerAddresses @({orig_args}); Clear-DnsClientCache"
                else:
                    ps_rb = f"Set-DnsClientServerAddress -InterfaceIndex {if_index} -ResetServerAddresses; Clear-DnsClientCache"
                run_powershell(ps_rb)
                return {"success": False, "error": "DNS не отвечает после применения. Настройки возвращены."}

            state.update(
                domain=domain,
                ips=ips,
                proto=info.get("proto", "udp"),
                connection=if_alias,
                timestamp=time.time()
            )
            save_state(state)
            return {"success": True, "domain": domain, "ips": ips, "proto": info.get("proto", "udp")}

    def verify_active(self):
        cur = self.get_current_dns()
        if cur.get("is_default"):
            return {"status": "default", "domain": "DEFAULT"}
        domain = cur.get("domain", "DEFAULT")
        return {"status": "success" if self.dns_really_works() else "failed", "domain": domain}
