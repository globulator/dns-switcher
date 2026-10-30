# -*- coding: utf-8 -*-
"""
Base Network Adapter interface and platform loader.
"""

import sys

class BaseNetworkAdapter:
    """Abstract base class for platform-specific network configuration."""

    def get_active_connection(self):
        """Returns details about the active network interface."""
        raise NotImplementedError

    def get_current_dns(self):
        """Returns the currently active DNS state."""
        raise NotImplementedError

    def apply_dns(self, domain):
        """Applies specified DNS to the active network interface."""
        raise NotImplementedError

    def restore_original(self):
        """Restores original network adapter settings."""
        raise NotImplementedError

    def verify_active(self):
        """Verifies if the currently applied DNS is working."""
        raise NotImplementedError

    def is_admin(self):
        """Checks if current process has privileges to alter DNS."""
        return True

_adapter_instance = None

def get_adapter():
    """Returns the singleton network adapter for the current operating system."""
    global _adapter_instance
    if _adapter_instance is None:
        if sys.platform == "win32":
            from platforms.windows import WindowsNetworkAdapter
            _adapter_instance = WindowsNetworkAdapter()
        elif sys.platform.startswith("linux"):
            from platforms.linux import LinuxNetworkAdapter
            _adapter_instance = LinuxNetworkAdapter()
        else:
            # Fallback mock adapter
            _adapter_instance = BaseNetworkAdapter()
    return _adapter_instance
