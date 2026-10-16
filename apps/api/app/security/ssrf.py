from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from app.errors import SsrfError

_DENIED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        any(address.version == network.version and address in network for network in _DENIED_NETWORKS)
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def guard_endpoint(connector: str, endpoint: str, resolver=socket.getaddrinfo) -> None:
    if endpoint.startswith(("http://", "https://")):
        assert_public_http_url(endpoint, resolver=resolver)
        return
    if connector != "fixture":
        raise SsrfError("Only http and https URLs are allowed.")


def assert_public_http_url(url: str, resolver=socket.getaddrinfo) -> None:
    """Refuse non-http(s), embedded credentials, and private DNS answers.

    Redirect targets must be passed through this function again by the caller.
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise SsrfError("Only http and https URLs are allowed.")
    if parts.username or parts.password:
        raise SsrfError("URLs must not contain credentials.")
    host = parts.hostname
    if not host:
        raise SsrfError("URL has no host.")
    if host.lower().rstrip(".") in {"localhost", "localhost.localdomain"}:
        raise SsrfError("Private or link-local addresses are refused.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and _blocked(literal):
        raise SsrfError("Private or link-local addresses are refused.")
    try:
        answers = resolver(host, parts.port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SsrfError("Host did not resolve.") from exc
    if not answers:
        raise SsrfError("Host did not resolve.")
    for answer in answers:
        sockaddr = answer[4]
        try:
            resolved = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise SsrfError("DNS answer was not an IP address.") from exc
        if _blocked(resolved):
            raise SsrfError("Private or link-local addresses are refused.")
