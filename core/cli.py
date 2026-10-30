# -*- coding: utf-8 -*-
"""
Unified CLI dispatcher for DNS Switcher.
Provides JSON-based RPC interface for GNOME Shell and command-line usage.
"""

import json
import sys

from core.storage import (
    load_presets,
    load_dns_list,
    load_targets_list,
    get_active_target,
    set_active_target,
    save_targets_list,
    normalize_host,
    load_cached_latencies,
    add_dns,
    remove_dns,
    DEFAULT_TARGETS
)
from core.engine import (
    probe_all,
    probe_domain
)
from core.adapter import get_adapter

def get_init_data():
    adapter = get_adapter()
    presets = load_presets()
    return {
        "categories": presets.get("categories", []),
        "domains": load_dns_list(),
        "targets": load_targets_list(),
        "active_target": get_active_target(),
        "cached": load_cached_latencies(),
        "active": adapter.get_current_dns(),
        "is_admin": adapter.is_admin(),
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No action specified"}, ensure_ascii=False))
        sys.exit(1)

    action = sys.argv[1]
    adapter = get_adapter()

    if action == "init":
        print(json.dumps(get_init_data(), ensure_ascii=False))

    elif action == "list":
        presets = load_presets()
        domains = load_dns_list()
        print(json.dumps({
            "categories": presets.get("categories", []),
            "domains": domains
        }, ensure_ascii=False))

    elif action == "targets-list":
        targets = load_targets_list()
        active = get_active_target()
        print(json.dumps({"targets": targets, "active": active}, ensure_ascii=False))

    elif action == "targets-set":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing target"}, ensure_ascii=False))
            sys.exit(1)
        norm = set_active_target(sys.argv[2])
        print(json.dumps({"success": True, "active": norm}, ensure_ascii=False))

    elif action == "targets-add":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing target"}, ensure_ascii=False))
            sys.exit(1)
        try:
            norm = normalize_host(sys.argv[2])
        except ValueError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            sys.exit(1)
        targets = load_targets_list()
        if norm not in targets:
            targets.append(norm)
            save_targets_list(targets)
        set_active_target(norm)
        print(json.dumps({"success": True, "active": norm, "targets": targets}, ensure_ascii=False))

    elif action == "targets-remove":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing target"}, ensure_ascii=False))
            sys.exit(1)
        target = sys.argv[2].strip()
        targets = load_targets_list()
        if target in targets:
            targets.remove(target)
            if not targets:
                targets = list(DEFAULT_TARGETS)
            save_targets_list(targets)
        active = get_active_target()
        if active == target:
            active = targets[0]
            set_active_target(active)
        print(json.dumps({"success": True, "active": active, "targets": targets}, ensure_ascii=False))

    elif action == "get-cached":
        print(json.dumps(load_cached_latencies(), ensure_ascii=False))

    elif action == "probe-stream":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        probe_all(target=target, stream=True)

    elif action == "probe":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        results = probe_all(target=target, stream=False)
        print(json.dumps(results, ensure_ascii=False))

    elif action == "probe-single":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing domain"}, ensure_ascii=False))
            sys.exit(1)
        target = sys.argv[3] if len(sys.argv) > 3 else None
        res = probe_domain(sys.argv[2], target)
        print(json.dumps(res, ensure_ascii=False))

    elif action == "get-active":
        print(json.dumps(adapter.get_current_dns(), ensure_ascii=False))

    elif action == "verify-active":
        print(json.dumps(adapter.verify_active(), ensure_ascii=False))

    elif action == "set":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing domain"}, ensure_ascii=False))
            sys.exit(1)
        res = adapter.apply_dns(sys.argv[2])
        print(json.dumps(res, ensure_ascii=False))

    elif action == "add":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing domain"}, ensure_ascii=False))
            sys.exit(1)
        new_dom = sys.argv[2].strip()
        cat_id = sys.argv[3].strip() if len(sys.argv) > 3 else "bypass"
        try:
            res = add_dns(new_dom, cat_id)
            print(json.dumps(res, ensure_ascii=False))
        except ValueError as e:
            print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
            sys.exit(1)

    elif action == "remove":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Missing domain"}, ensure_ascii=False))
            sys.exit(1)
        try:
            res = remove_dns(sys.argv[2].strip())
            print(json.dumps(res, ensure_ascii=False))
        except ValueError as e:
            print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
            sys.exit(1)

    else:
        print(json.dumps({"error": f"Unknown action {action}"}, ensure_ascii=False))
        sys.exit(1)
