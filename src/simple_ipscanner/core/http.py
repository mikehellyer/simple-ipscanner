"""Shared HTTPS context, and the one safe way to fetch a URL, for every
request the app makes.

A PyInstaller-frozen app on macOS can end up with a `ssl` module whose
default CA certificate path was baked in at build time — wherever the
build machine's Python installation kept its cert bundle. That path
simply doesn't exist on an end user's machine, so every HTTPS request
fails with a certificate-verify error, which every caller here treats
the same as "offline" and silently swallows. Explicitly pointing at
certifi's bundled, portable CA file sidesteps this regardless of which
machine built or is running the app.
"""
from __future__ import annotations

import ssl
import urllib.parse
import urllib.request

import certifi

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


# --- Safe fetching -----------------------------------------------------------
#
# urllib.request.urlopen() happily opens file:// (and ftp://) URLs, and
# plenty of the URLs this app fetches come from outside it: station logos
# and homepages from radio-browser (which anyone can edit), podcast feeds,
# .pls File1= lines, imported preset files. A "logo" URL of
# file:///home/someone/.ssh/id_ed25519 would otherwise be read straight
# off disk, cached as that preset's image, and carried along in any preset
# export. So every fetch goes through urlopen() below instead, which only
# speaks http/https — including after redirects — and read_capped(), which
# stops a huge response from eating all the memory.
#
# Both raise subclasses of OSError, which every caller already treats as
# "couldn't fetch it".

WEB_SCHEMES = ("http", "https")

# Size caps for read_capped(), generous enough for anything legitimate.
MAX_API_RESPONSE_BYTES = 5 * 1024 * 1024  # JSON from GitHub/iTunes/radio-browser/BBC
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # a logo or podcast cover
MAX_FEED_BYTES = 50 * 1024 * 1024  # long-running podcasts have big feeds
MAX_PLAYLIST_BYTES = 64 * 1024  # a .pls is a few lines of text
MAX_INSTALLER_BYTES = 500 * 1024 * 1024  # releases are ~90 MB


class UnsafeURLError(OSError):
    """A URL that isn't plain http/https."""


class ResponseTooLargeError(OSError):
    """A response bigger than the caller's limit."""


def is_web_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme.lower() in WEB_SCHEMES and bool(parsed.netloc)


class _WebOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_web_url(newurl):
            raise UnsafeURLError(f"refusing redirect to a non-web URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> urllib.request.OpenerDirector:
    # Assembled by hand rather than with build_opener(), which always
    # adds handlers for file://, ftp:// and data: URLs as well.
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(context=SSL_CONTEXT),
        _WebOnlyRedirectHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


_OPENER = _build_opener()


def urlopen(request: urllib.request.Request | str, timeout: float):
    """urllib.request.urlopen(), restricted to http/https and verified TLS."""
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    if not is_web_url(url):
        raise UnsafeURLError(f"not a web URL: {url}")
    return _OPENER.open(request, timeout=timeout)


def read_capped(response, max_bytes: int) -> bytes:
    """Read a whole response body, refusing one larger than max_bytes."""
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ResponseTooLargeError(f"response larger than {max_bytes} bytes")
    return data
