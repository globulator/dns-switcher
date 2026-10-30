# -*- coding: utf-8 -*-
"""
Storage, configuration, and state management for DNS Switcher.
Cross-platform support for Linux and Windows.
"""

import contextlib
import ipaddress
import json
import os
import re
import shutil
import sys
import time

CORE_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = getattr(sys, '_MEIPASS', os.path.dirname(CORE_DIR))

def get_config_dir():
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        d = os.path.join(appdata, "DNS-Switcher") if appdata else os.path.expanduser("~/.dns-switcher")
    else:
        d = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "dns-switcher")
    os.makedirs(d, exist_ok=True)
    return d

def get_cache_dir():
    if os.name == "nt":
        localappdata = os.environ.get("LOCALAPPDATA")
        d = os.path.join(localappdata, "DNS-Switcher", "cache") if localappdata else os.path.expanduser("~/.cache/dns-switcher")
    else:
        d = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "dns-switcher")
    os.makedirs(d, exist_ok=True)
    return d

CONFIG_DIR = get_config_dir()
CACHE_DIR = get_cache_dir()

PRESETS_PATH = os.path.join(CONFIG_DIR, "dns_presets.json")
TARGETS_PATH = os.path.join(CONFIG_DIR, "targets_list.txt")
CURRENT_TARGET_PATH = os.path.join(CONFIG_DIR, "current_target.json")
STATE_PATH = os.path.join(CONFIG_DIR, "current_dns.json")
CACHE_PATH = os.path.join(CACHE_DIR, "cache_latencies.json")
LOCK_PATH = os.path.join(CONFIG_DIR, ".lock")

def _migrate_old_files():
    file_map = {
        os.path.join(PROJECT_ROOT, "dns_presets.json"): PRESETS_PATH,
        os.path.join(PROJECT_ROOT, "targets_list.txt"): TARGETS_PATH,
        os.path.join(PROJECT_ROOT, "current_target.json"): CURRENT_TARGET_PATH,
        os.path.join(PROJECT_ROOT, "current_dns.json"): STATE_PATH,
    }
    for old_path, new_path in file_map.items():
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                shutil.copy2(old_path, new_path)
            except OSError:
                pass

_migrate_old_files()

DEFAULT_TARGETS = [
    "google.com",
    "youtube.com",
    "rutracker.org",
    "discord.com",
    "gemini.google.com",
    "vk.ru",
    "chatgpt.com",
    "brawlstars.com"
]

CATEGORIES_DEF = [
    {
        "id": "bypass",
        "title": "Антиблокировочные",
        "icon": "network-vpn-symbolic",
        "domains": [
            "d.webshiftvpn.ru",
            "dns.dns-ai.ru",
            "dns.comss.one",
            "router.comss.one",
            "geohide.ru",
            "dns.bezmezhau.com",
            "dns.malw.link",
            "dns.wlrus.cfd",
            "free.shecan.ir"
        ]
    },
    {
        "id": "security",
        "title": "Защитные",
        "icon": "security-high-symbolic",
        "domains": [
            "dns.adguard-dns.com",
            "dns.quad9.net",
            "family.adguard-dns.com"
        ]
    },
    {
        "id": "global",
        "title": "Глобальные",
        "icon": "globe-symbolic",
        "domains": [
            "one.one.one.one",
            "dns.google",
            "dns.umbrella.com"
        ]
    },
    {
        "id": "national",
        "title": "Национальные",
        "icon": "emoji-flags-symbolic",
        "domains": [
            "common.dot.dns.yandex.net",
            "safe.dot.dns.yandex.net"
        ]
    }
]

HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")

def normalize_host(s):
    if not isinstance(s, str):
        raise ValueError("некорректное имя хоста")
    s = s.strip().rstrip(".").lower()
    try:
        ipaddress.IPv4Address(s)
        return s
    except ValueError:
        pass
    try:
        s = s.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("некорректное имя хоста")
    if s == "default" or not HOST_RE.match(s):
        raise ValueError("некорректное имя хоста")
    return s

def atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

@contextlib.contextmanager
def file_lock(timeout=5.0):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.name != "nt":
        import fcntl
        with open(LOCK_PATH, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    else:
        # Cross-process spinlock for Windows
        start = time.time()
        while True:
            try:
                fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                try:
                    yield
                finally:
                    os.close(fd)
                    try:
                        os.unlink(LOCK_PATH)
                    except OSError:
                        pass
                break
            except OSError:
                if time.time() - start > timeout:
                    try:
                        os.unlink(LOCK_PATH)
                    except OSError:
                        pass
                    yield
                    break
                time.sleep(0.05)

def load_targets_list():
    if not os.path.exists(TARGETS_PATH):
        save_targets_list(DEFAULT_TARGETS)
        return list(DEFAULT_TARGETS)
    items = []
    try:
        with open(TARGETS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if line not in items:
                        items.append(line)
    except OSError:
        pass
    if not items:
        items = list(DEFAULT_TARGETS)
        save_targets_list(items)
    return items

def save_targets_list(items):
    os.makedirs(os.path.dirname(TARGETS_PATH), exist_ok=True)
    tmp = f"{TARGETS_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for item in items:
            f.write(f"{item}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TARGETS_PATH)

def get_active_target():
    if os.path.exists(CURRENT_TARGET_PATH):
        try:
            with open(CURRENT_TARGET_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                target = data.get("target")
                if target:
                    return target
        except Exception:
            pass
    targets = load_targets_list()
    return targets[0] if targets else "google.com"

def set_active_target(target):
    norm = normalize_host(target)
    atomic_write_json(CURRENT_TARGET_PATH, {"target": norm})
    return norm

def load_cached_latencies():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}

def save_cached_latencies(data):
    with file_lock():
        atomic_write_json(CACHE_PATH, data)

def init_presets():
    categories = json.loads(json.dumps(CATEGORIES_DEF))
    existing_list = []
    seed_path = os.path.join(PROJECT_ROOT, "dns_list.txt")
    if os.path.exists(seed_path):
        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        try:
                            norm = normalize_host(line)
                            if norm not in existing_list:
                                existing_list.append(norm)
                        except ValueError:
                            pass
        except OSError:
            pass

    all_cat_domains = set()
    for cat in categories:
        all_cat_domains.update(cat.get("domains", []))

    for item in existing_list:
        if item not in all_cat_domains:
            categories[0]["domains"].append(item)
            all_cat_domains.add(item)

    data = {"categories": categories}
    atomic_write_json(PRESETS_PATH, data)
    return data

def load_presets():
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("categories"), list):
            return data
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        try:
            corrupt_backup = f"{PRESETS_PATH}.corrupt-{int(time.time())}"
            os.replace(PRESETS_PATH, corrupt_backup)
        except OSError:
            pass
    return init_presets()

def save_presets(data):
    atomic_write_json(PRESETS_PATH, data)

def load_dns_list():
    data = load_presets()
    all_domains = []
    for cat in data.get("categories", []):
        for d in cat.get("domains", []):
            if d not in all_domains:
                all_domains.append(d)
    return all_domains

def add_dns(domain, category_id="bypass"):
    domain = normalize_host(domain)
    with file_lock():
        data = load_presets()
        categories = data.get("categories", [])
        target_cat = None
        for cat in categories:
            if cat.get("id") == category_id:
                target_cat = cat
                break
        if not target_cat and categories:
            target_cat = categories[0]

        for cat in categories:
            domains = cat.setdefault("domains", [])
            if domain in domains:
                if target_cat and cat.get("id") != target_cat.get("id"):
                    domains.remove(domain)

        if target_cat and domain not in target_cat.setdefault("domains", []):
            target_cat["domains"].append(domain)

        save_presets(data)
        all_domains = []
        for cat in categories:
            for d in cat.get("domains", []):
                if d not in all_domains:
                    all_domains.append(d)

    return {
        "success": True,
        "domain": domain,
        "category": target_cat["id"] if target_cat else category_id,
        "categories": categories,
        "domains": all_domains
    }

def remove_dns(domain):
    with file_lock():
        data = load_presets()
        categories = data.get("categories", [])
        for cat in categories:
            domains = cat.get("domains", [])
            if domain in domains:
                domains.remove(domain)

        save_presets(data)
        all_domains = []
        for cat in categories:
            for d in cat.get("domains", []):
                if d not in all_domains:
                    all_domains.append(d)

    return {
        "success": True,
        "removed": domain,
        "categories": categories,
        "domains": all_domains
    }

def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def save_state(state):
    atomic_write_json(STATE_PATH, state)
