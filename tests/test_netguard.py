"""SSRF protection: which addresses the web app refuses to fetch."""

import asyncio
import ipaddress

import httpx
import pytest

from wcag_scanner import netguard
from wcag_scanner.netguard import BlockedAddress, HostGuard, UnknownHost, is_public_ip


@pytest.mark.parametrize(
    "ip",
    [
        # loopback and RFC 1918 private ranges
        "127.0.0.1", "10.0.0.8", "172.16.5.4", "192.168.1.1",
        # the cloud metadata service (link-local), and carrier-grade NAT
        "169.254.169.254", "100.64.0.1",
        # unspecified, broadcast, multicast
        "0.0.0.0", "255.255.255.255", "224.0.0.1",
        # IPv6 loopback, link-local, unique-local, and IPv4-mapped loopback
        "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1",
    ],
)  # fmt: skip
def test_private_and_special_addresses_are_not_public(ip):
    assert not is_public_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_addresses_are_public(ip):
    assert is_public_ip(ipaddress.ip_address(ip))


def _check(guard, url):
    return asyncio.run(guard.check(url))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/",
        "http://localhost/admin",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_internal_urls_are_blocked(url):
    with pytest.raises(BlockedAddress, match="private network address"):
        _check(HostGuard(), url)


def test_allow_private_lets_local_development_through():
    _check(HostGuard(allow_private=True), "http://localhost:8000/")


def test_public_ip_literal_needs_no_dns():
    _check(HostGuard(), "https://1.1.1.1/")


def test_a_public_name_that_resolves_to_a_private_address_is_blocked(monkeypatch):
    async def resolve(host):
        return {ipaddress.ip_address("10.1.2.3")}  # e.g. an attacker's DNS record pointing inward

    monkeypatch.setattr(netguard, "resolve", resolve)
    with pytest.raises(BlockedAddress, match=r"10\.1\.2\.3"):
        _check(HostGuard(), "https://innocent-looking.example/")


def test_a_name_with_any_private_address_is_blocked(monkeypatch):
    async def resolve(host):
        return {ipaddress.ip_address("93.184.215.14"), ipaddress.ip_address("127.0.0.1")}

    monkeypatch.setattr(netguard, "resolve", resolve)
    with pytest.raises(BlockedAddress):
        _check(HostGuard(), "https://mixed.example/")


def test_unknown_hosts_get_a_friendly_error():
    with pytest.raises(UnknownHost, match=r"Couldn't find a website at nothing-here\.invalid"):
        _check(HostGuard(), "https://nothing-here.invalid/")


def test_each_host_is_resolved_once_per_scan(monkeypatch):
    calls = []

    async def resolve(host):
        calls.append(host)
        return {ipaddress.ip_address("93.184.215.14")}

    monkeypatch.setattr(netguard, "resolve", resolve)
    guard = HostGuard()

    async def many():
        for path in ("/", "/a", "/b?x=1", "/c"):
            await guard.check(f"https://Example.com{path}")

    asyncio.run(many())
    assert calls == ["example.com"]


def test_redirects_inside_http_clients_are_checked(monkeypatch):
    """robots.txt and sitemap fetches follow redirects; each hop must pass the guard."""

    async def resolve(host):
        return {ipaddress.ip_address("93.184.215.14" if host == "public.example" else "127.0.0.1")}

    monkeypatch.setattr(netguard, "resolve", resolve)

    def app(request):
        return httpx.Response(302, headers={"Location": "http://internal.example/secret"})

    async def fetch():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(app),
            follow_redirects=True,
            event_hooks={"request": [HostGuard().httpx_hook()]},
        ) as client:
            await client.get("https://public.example/robots.txt")

    with pytest.raises(BlockedAddress, match=r"internal\.example"):
        asyncio.run(fetch())
