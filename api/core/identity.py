"""Which service account this process runs as, from the Cloud Run metadata server.

Diagnostics only. A PermissionDenied on a secret is an identity problem, and the
error should say whose identity, so nobody reaches for the credential values.
"""

from __future__ import annotations

import functools
import urllib.error
import urllib.request

METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"


@functools.lru_cache(maxsize=1)
def runtime_service_account() -> str | None:
    request = urllib.request.Request(METADATA_URL, headers={"Metadata-Flavor": "Google"})
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:  # noqa: S310 - fixed metadata host
            return response.read().decode("utf-8").strip() or None
    except (urllib.error.URLError, OSError, ValueError):
        return None
