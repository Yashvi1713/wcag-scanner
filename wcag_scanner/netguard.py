"""Refuse to fetch addresses on private networks.

The web app scans whatever URL a visitor types, so without this it could be pointed at
http://localhost:5432, a router admin page or a cloud metadata service (169.254.169.254).
Every host is resolved and every address it resolves to must be public. The scanner checks
again after redirects, and the robots/sitemap client checks each request it makes.

Residual risk, documented in the README: DNS rebinding between this check and the browser's
own lookup, and sub-resources (images, scripts) a page loads from private addresses.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class BlockedAddress(ValueError):
    """The URL points at a private, loopback, link-local or otherwise non-public address."""


class UnknownHost(ValueError):
    """The host name doesn't resolve (usually a typo)."""


def is_public_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is loopback, not a public IPv6 address
    return ip.is_global and not ip.is_multicast


async def resolve(host: str) -> set[IPAddress]:
    try:
        return {ipaddress.ip_address(host.strip("[]"))}
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as e:
        raise UnknownHost(f"Couldn't find a website at {host}.") from e
    # Strip IPv6 zone ids ("fe80::1%en0") before parsing.
    return {ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos}


class HostGuard:
    """Checks hosts once per scan and remembers the answer."""

    def __init__(self, allow_private: bool = False):
        self.allow_private = allow_private
        self._verdicts: dict[str, str | None] = {}  # host -> reason it's blocked, or None if allowed

    async def check(self, url: str) -> None:
        """Raise BlockedAddress or UnknownHost if the URL must not be fetched."""
        host = (urlsplit(url).hostname or "").lower()
        if not host:
            raise BlockedAddress("The address has no host name.")
        if host not in self._verdicts:
            self._verdicts[host] = await self._reason(host)
        reason = self._verdicts[host]
        if reason:
            raise BlockedAddress(reason)

    async def _reason(self, host: str) -> str | None:
        addresses = await resolve(host)
        if self.allow_private:
            return None
        private = sorted(str(ip) for ip in addresses if not is_public_ip(ip))
        if private:
            return f"{host} points to a private network address ({private[0]}), which this scanner won't fetch."
        return None

    def httpx_hook(self):
        """An httpx request hook that applies the same rule to every request, including redirects."""

        async def hook(request: httpx.Request) -> None:
            await self.check(str(request.url))

        return hook
