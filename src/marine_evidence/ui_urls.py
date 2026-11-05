"""Browser-facing URLs are NOT the same as Compose service-to-service URLs.

Inside Docker, Streamlit talks to `api:8000`, but a desktop browser cannot
resolve `api`. Always use the explicit public endpoint in links shown to users.
"""
from __future__ import annotations

import os
from urllib.parse import quote


def pdf_link(source_id: str, page: int = 1, *, public_api_url: str | None = None) -> str:
    api_url = public_api_url
    if api_url is None:
        api_url = os.getenv('MARINE_PUBLIC_API_URL', 'http://127.0.0.1:8000')
    return f'{api_url.rstrip("/")}/documents/{quote(source_id, safe="")}/pdf#page={int(page)}'
