"""Validate cover URLs before delegating downloads to Audiobookshelf."""

from __future__ import annotations

import re
import socket
from collections.abc import Collection
from ipaddress import ip_address
from urllib.parse import urlsplit

_HOSTNAME_RE = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", re.IGNORECASE)
_BLOCKED_HOST_MESSAGE = (
    "cover URL host must not resolve to a private, loopback, or link-local address"
)


def _normalize_allowed_host(host: str, env_name: str) -> str:
    host = host.strip()
    if not host:
        raise ValueError(f"{env_name} must contain exact hosts or IP addresses")
    if any(token in host for token in ("//", "/", "?", "#", "@")):
        raise ValueError(f"{env_name} entries must be bare hosts or IP addresses")
    if host.startswith("[") or host.endswith("]"):
        if not (host.startswith("[") and host.endswith("]")):
            raise ValueError(f"{env_name} contains an invalid IPv6 host")
        host = host[1:-1]

    try:
        return str(ip_address(host))
    except ValueError:
        pass

    if ":" in host or not _HOSTNAME_RE.fullmatch(host):
        raise ValueError(f"{env_name} must contain exact hosts or IP addresses")
    return host.lower()


def parse_cover_url_allowed_hosts(raw: str) -> list[str]:
    """Parse exact cover-URL host allowlist entries from the environment."""
    env_name = "COVER_URL_ALLOWED_HOSTS"
    if not raw.strip():
        return []
    hosts = [_normalize_allowed_host(value, env_name) for value in raw.split(",")]
    return list(dict.fromkeys(hosts))


def _is_allowlisted(hostname: str, allowed_hosts: Collection[str]) -> bool:
    try:
        normalized = str(ip_address(hostname))
    except ValueError:
        normalized = hostname.lower()
    return normalized in allowed_hosts


def _resolved_addresses(hostname: str, scheme: str) -> set[str]:
    port = 443 if scheme == "https" else 80
    addresses = {
        result[4][0]
        for result in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    }
    if not addresses:
        raise ValueError("cover URL host could not be resolved")
    return addresses


def validate_cover_url(url: str, allowed_hosts: Collection[str] = ()) -> str:
    """Allow only http(s) cover URLs whose hosts stay outside local/private networks."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("cover URL must be a non-empty string")

    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("cover URL must use http or https")
    if not parsed.hostname:
        raise ValueError("cover URL must include a host")

    hostname = parsed.hostname
    if _is_allowlisted(hostname, allowed_hosts):
        return url

    try:
        addresses = _resolved_addresses(hostname, parsed.scheme)
    except socket.gaierror as exc:
        raise ValueError("cover URL host could not be resolved") from exc

    for address in addresses:
        ip = ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError(_BLOCKED_HOST_MESSAGE)

    return url
