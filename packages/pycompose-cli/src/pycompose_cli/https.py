"""Downloads the CLI makes: over HTTPS, never another scheme.

Maven metadata and the pinned JDK and SDK archives are fetched from addresses
the CLI names itself; refusing every other scheme means a ``file:`` or custom
URL can never be opened through it, whatever a configuration says.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from http.client import HTTPResponse

from pycompose_cli.project import ProjectError


def open_https(url: str, *, timeout: float) -> HTTPResponse:
    """Open ``url`` for reading, if it is HTTPS.

    Args:
        url: The address to fetch.
        timeout: Seconds to wait for the connection and each read.

    Returns:
        The open response.

    Raises:
        ProjectError: If the address is not HTTPS.
    """
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ProjectError("refusing a download that is not HTTPS", url=url)
    response: HTTPResponse = urllib.request.urlopen(url, timeout=timeout)  # nosec B310 -- HTTPS checked above
    return response
