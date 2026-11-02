"""Webhook target checks: HTTPS only, standard port, no credentials in the URL, and never a private network address.

Blocked: loopback, private (RFC 1918 and IPv6 unique local), link-local (including the cloud metadata address
169.254.169.254), carrier-grade NAT (100.64.0.0/10), unspecified, multicast and reserved ranges. A host name is resolved and
every address it resolves to must be public. The check runs when the hook is saved and again before every delivery, so a
name that later points inside the network is blocked at send time. Redirects are never followed.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_PORTS = (None, 443, 8443)
CGNAT = ipaddress.ip_network("100.64.0.0/10")


class Unsafe(ValueError):
    pass


class Unresolvable(Unsafe):
    pass


def resolve_host(host: str) -> list[str]:
    """Every address the name resolves to. Replaced in tests, which never reach a real resolver."""
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except (socket.gaierror, UnicodeError) as exc:
        raise Unresolvable(host) from exc


def is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified or not ip.is_global:
        return False
    return not (isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT)


RESERVED_SUFFIXES = (".example", ".test", ".invalid")  # RFC 2606 / 6761: never resolve on the internet


def check_url(url: str, *, offline: bool = False) -> str:
    """Return the host when `url` is a safe webhook target, else raise Unsafe with a message for the person setting it up.

    `offline` (WEBHOOK_MODE=fake: nothing is ever sent) accepts the reserved example names without a DNS lookup, so demo
    and test data can use them. Every other rule still applies, and in live mode those names fail to resolve and are refused."""
    return vet(url, offline=offline)[0]


def vet(url: str, *, offline: bool = False) -> tuple[str, list[str]]:
    """check_url, also returning the public addresses the host resolved to. The sender connects to one of these addresses
    and never resolves the name again, so a name that changes between the check and the connection (DNS rebinding) cannot
    reach an internal address. Empty only for a reserved example name in offline mode."""
    try:
        parts = urlsplit((url or "").strip())
        port = parts.port
    except ValueError as exc:
        raise Unsafe("Enter a valid address.") from exc
    if parts.scheme != "https":
        raise Unsafe("The address must start with https://.")
    if parts.username or parts.password:
        raise Unsafe("Leave user names and passwords out of the address; the signature authenticates each delivery.")
    host = (parts.hostname or "").strip(".").lower()
    if not host:
        raise Unsafe("Enter a valid address.")
    if port not in ALLOWED_PORTS:
        raise Unsafe("Use the standard HTTPS port (443) or 8443.")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise Unsafe("The address points to a private network. Webhooks go only to public internet addresses.")
    try:
        addrs = [str(ipaddress.ip_address(host))]
    except ValueError:
        if offline and host.endswith(RESERVED_SUFFIXES):
            return host, []
        try:
            addrs = resolve_host(host)
        except Unresolvable as exc:
            raise Unresolvable("The host name could not be found.") from exc
    if not addrs or not all(is_public(a) for a in addrs):
        raise Unsafe("The address points to a private network. Webhooks go only to public internet addresses.")
    return host, addrs
