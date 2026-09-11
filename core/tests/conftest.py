"""Shared fixtures: minimal valid configs per role, as plain dicts."""

from typing import Any

import pytest

REPO_ROOT_PARTS = 2  # tests/ -> core/ -> repository root


def home_config() -> dict[str, Any]:
    return {
        "version": 1,
        "role": "home",
        "network": {"lan_interface": "eth0", "lan_subnet": "192.168.1.0/24"},
        "routing": {"mode": "off", "default_upstream": "dpn"},
        "upstreams": {"dpn": {"enabled": True}},
        "provider": {"enabled": True},
    }


def vps_config() -> dict[str, Any]:
    return {
        "version": 1,
        "role": "vps",
        "provider": {"enabled": True},
        "wg_server": {"endpoint": "vps.example.com"},
    }


def client_config() -> dict[str, Any]:
    return {
        "version": 1,
        "role": "client",
        "network": {"lan_interface": "eth0", "lan_subnet": "192.168.1.0/24"},
        "routing": {"mode": "full", "default_upstream": "vps"},
        "upstreams": {"vps": {"enabled": True, "peer_config": "secrets/home.conf"}},
    }


@pytest.fixture
def home() -> dict[str, Any]:
    return home_config()


@pytest.fixture
def vps() -> dict[str, Any]:
    return vps_config()


@pytest.fixture
def client() -> dict[str, Any]:
    return client_config()
