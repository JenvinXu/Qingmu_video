from urllib.request import getproxies
import httpx


def https_proxy():
    """Respect the current user's environment or Windows Internet proxy settings."""
    value = getproxies().get("https") or getproxies().get("http")
    return value if value and value.startswith(("http://", "https://")) else None


def async_client(target_url=None, **kwargs):
    # Transport retries only failed connections, before a request is sent. A
    # timed-out POST is never resubmitted here because it may incur another charge.
    from urllib.parse import urlsplit
    from urllib.request import proxy_bypass

    host = urlsplit(target_url).hostname if target_url else None
    proxy = (
        None
        if host and (host in {"localhost", "127.0.0.1"} or proxy_bypass(host))
        else https_proxy()
    )
    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(proxy=proxy, retries=2),
        trust_env=False,
        **kwargs,
    )
