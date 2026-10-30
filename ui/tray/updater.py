# -*- coding: utf-8 -*-
"""
Update checker for DNS Switcher Desktop.
Checks GitHub Releases for new versions without blocking the UI.
"""

import json
import urllib.request
import re

CURRENT_VERSION = "1.0.1"
GITHUB_REPO = "globulator/dns-switcher"

def parse_version(v_str):
    """Normalizes version strings like 'v1.2.3' or '1.2.3' into a tuple of integers."""
    clean = re.sub(r"^[^\d]*", "", v_str.strip())
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(re.match(r"\d+", p).group()))
        except Exception:
            parts.append(0)
    return tuple(parts)

def check_for_updates(repo=GITHUB_REPO, current_ver=CURRENT_VERSION):
    """
    Queries GitHub API for the latest release.
    Returns a dict with update details if a newer version exists.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DNS-Switcher-Desktop-Updater",
            "Accept": "application/vnd.github.v3+json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tag_name = data.get("tag_name", "")
                remote_ver = parse_version(tag_name)
                local_ver = parse_version(current_ver)

                if remote_ver > local_ver:
                    exe_url = None
                    for asset in data.get("assets", []):
                        if asset.get("name", "").endswith(".exe"):
                            exe_url = asset.get("browser_download_url")
                            break

                    return {
                        "update_available": True,
                        "current_version": current_ver,
                        "latest_version": tag_name,
                        "html_url": data.get("html_url", f"https://github.com/{repo}/releases"),
                        "download_url": exe_url or data.get("html_url"),
                        "body": data.get("body", "").strip()
                    }
    except Exception:
        pass

    return {"update_available": False, "current_version": current_ver}
