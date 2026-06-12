"""HTTP client helpers with tenacity retry logic.

Used by scrapers and API clients — never called from the hot path.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

logger = logging.getLogger(__name__)

_RETRY_KWARGS = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


@retry(**_RETRY_KWARGS)
def get(url: str, **kwargs) -> httpx.Response:
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, **kwargs)
        resp.raise_for_status()
        return resp


@retry(**_RETRY_KWARGS)
def post(url: str, **kwargs) -> httpx.Response:
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, **kwargs)
        resp.raise_for_status()
        return resp
