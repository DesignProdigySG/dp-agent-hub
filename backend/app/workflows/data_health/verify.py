"""Paid email / phone verification behind the Data Doctor's skills.

ZeroBounce validates emails in batches of up to 100 (the key travels in the request body,
never the URL). Twilio Lookup v2 validates phone numbers one at a time. Every result is
cached in verification_result, so re-running a scan never pays for the same value twice
within CACHE_DAYS. Errors are reported without the request URL or credentials.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any

import httpx
from sqlmodel import select

from app.db import VerificationResult, session
from app.events.schema import utcnow

log = logging.getLogger(__name__)

EMAIL_SKILL = "Email verification (ZeroBounce)"
PHONE_SKILL = "Phone verification (Twilio Lookup)"
CACHE_DAYS = 90
ZEROBOUNCE_BATCH_URL = "https://bulkapi.zerobounce.net/v2/validatebatch"
TWILIO_LOOKUP_URL = "https://lookups.twilio.com/v2/PhoneNumbers/"
# ZeroBounce statuses that are safe to send to.
USABLE_EMAIL = {"valid", "catch-all"}


class VerificationError(RuntimeError):
    pass


def cached(kind: str, values: list[str]) -> dict[str, dict[str, Any]]:
    fresh_after = utcnow() - timedelta(days=CACHE_DAYS)
    out: dict[str, dict[str, Any]] = {}
    with session() as s:
        for i in range(0, len(values), 500):
            for r in s.exec(select(VerificationResult).where(
                    VerificationResult.kind == kind,
                    VerificationResult.value.in_(values[i:i + 500]))):
                checked = r.checked_at if r.checked_at.tzinfo else \
                    r.checked_at.replace(tzinfo=fresh_after.tzinfo)
                if checked >= fresh_after:
                    out[r.value] = {"status": r.status, "usable": r.usable, **r.data}
    return out


def _save(kind: str, provider: str, results: dict[str, dict[str, Any]]) -> None:
    with session() as s:
        for value, r in results.items():
            row = s.get(VerificationResult, (kind, value)) or VerificationResult(
                kind=kind, value=value)
            row.provider, row.status, row.usable = provider, r["status"], r["usable"]
            row.data = {k: v for k, v in r.items() if k not in ("status", "usable")}
            row.checked_at = utcnow()
            s.add(row)
        s.commit()


def _fail(provider: str, e: Exception) -> VerificationError:
    if isinstance(e, httpx.HTTPStatusError):
        return VerificationError(f"{provider} answered HTTP {e.response.status_code}")
    return VerificationError(f"{provider} request failed ({type(e).__name__})")


async def zerobounce(emails: list[str], api_key: str,
                     http: httpx.AsyncClient | None = None) -> dict[str, dict[str, Any]]:
    """Validate emails (cached ones are skipped); returns {email: {status, usable, ...}}."""
    todo = [e for e in dict.fromkeys(emails) if e not in cached("email", emails)]
    results: dict[str, dict[str, Any]] = {}
    own = http is None
    http = http or httpx.AsyncClient(timeout=120)
    try:
        for i in range(0, len(todo), 100):
            body = {"api_key": api_key,
                    "email_batch": [{"email_address": e, "ip_address": ""}
                                    for e in todo[i:i + 100]]}
            try:
                resp = await http.post(ZEROBOUNCE_BATCH_URL, json=body)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise _fail("ZeroBounce", e) from None
            data = resp.json()
            if data.get("errors") and not data.get("email_batch"):
                raise VerificationError(f"ZeroBounce: {data['errors'][0].get('error', '')}"[:200])
            batch = {}
            for r in data.get("email_batch", []):
                status = (r.get("status") or "unknown").lower()
                batch[(r.get("address") or "").lower()] = {
                    "status": status, "usable": status in USABLE_EMAIL,
                    "sub_status": r.get("sub_status", ""), "free_email": r.get("free_email")}
            _save("email", "zerobounce", batch)
            results |= batch
    finally:
        if own:
            await http.aclose()
    return results


async def twilio(numbers: list[str], sid: str, token: str, concurrency: int = 4,
                 http: httpx.AsyncClient | None = None) -> dict[str, dict[str, Any]]:
    """Validate E.164 numbers with Lookup v2 (basic validation); returns {number: {...}}."""
    todo = [n for n in dict.fromkeys(numbers) if n not in cached("phone", numbers)]
    results: dict[str, dict[str, Any]] = {}
    own = http is None
    http = http or httpx.AsyncClient(timeout=30, auth=(sid, token))
    gate = asyncio.Semaphore(concurrency)

    async def one(number: str) -> None:
        async with gate:
            try:
                resp = await http.get(TWILIO_LOOKUP_URL + number)
                if resp.status_code == 404:
                    results[number] = {"status": "invalid", "usable": False}
                    return
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise _fail("Twilio Lookup", e) from None
            r = resp.json()
            valid = bool(r.get("valid"))
            results[number] = {"status": "valid" if valid else "invalid", "usable": valid,
                               "errors": r.get("validation_errors") or [],
                               "country": r.get("country_code")}

    try:
        for i in range(0, len(todo), 50):  # save as we go: a crash keeps what was paid for
            chunk = todo[i:i + 50]
            await asyncio.gather(*(one(n) for n in chunk))
            _save("phone", "twilio", {n: results[n] for n in chunk if n in results})
    finally:
        if own:
            await http.aclose()
    return results
