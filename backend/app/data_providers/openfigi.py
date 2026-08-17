from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from backend.app.config import get_settings
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.models import InstrumentType
from backend.app.services.provider_budget_service import ProviderBudgetPolicy

OPENFIGI_PROVIDER = "OPENFIGI"
OPENFIGI_BASE_URL = "https://api.openfigi.com"
OPENFIGI_MAPPING_PATH = "/v3/mapping"
OPENFIGI_MAX_JOBS = 5
OPENFIGI_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_FIGI_PATTERN = re.compile(r"^[A-Z0-9]{12}$")


@dataclass(frozen=True)
class OpenFigiCandidate:
    figi: str
    ticker: str | None
    exchange_code: str | None
    market_sector: str | None
    security_type: str | None
    name: str | None
    currency_hint: str | None

    def compatible_types(self) -> frozenset[InstrumentType]:
        value = " ".join(
            part for part in (self.security_type, self.market_sector) if part
        ).upper()
        if "ETN" in value:
            return frozenset({"ETN"})
        if "ETC" in value:
            return frozenset({"ETC"})
        if any(token in value for token in ("ETP", "EXCHANGE TRADED PRODUCT")):
            return frozenset({"ETF", "ETC", "ETN"})
        if any(token in value for token in ("ETF", "EXCHANGE TRADED FUND", "FUND")):
            return frozenset({"ETF"})
        if any(token in value for token in ("BOND", "MUNICIPAL", "FIXED INCOME")):
            return frozenset({"BOND"})
        if any(token in value for token in ("COMMON STOCK", "PREFERRED STOCK", "EQUITY")):
            return frozenset({"STOCK"})
        if any(token in value for token in ("CRYPTO", "DIGITAL ASSET")):
            return frozenset({"CRYPTO"})
        if any(token in value for token in ("FOREX", "CURRENCY", " FX")):
            return frozenset({"FX"})
        if "INDEX" in value:
            return frozenset({"INDEX"})
        if "RATE" in value:
            return frozenset({"RATE"})
        return frozenset()


@dataclass(frozen=True)
class OpenFigiJobResult:
    isin: str
    candidates: tuple[OpenFigiCandidate, ...]
    request_fingerprint: str
    candidate_hash: str
    evidence_hash: str
    invalid_payload: bool


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_text(value: object, *, uppercase: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("provider candidate field must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return normalized.upper() if uppercase else normalized


def _is_valid_isin(value: str) -> bool:
    if not _ISIN_PATTERN.fullmatch(value):
        return False
    expanded = "".join(
        str(ord(character) - ord("A") + 10) if character.isalpha() else character
        for character in value
    )
    total = 0
    double = False
    for character in reversed(expanded):
        digit = int(character)
        if double:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        double = not double
    return total % 10 == 0


def _candidate(raw: object) -> OpenFigiCandidate:
    if not isinstance(raw, Mapping):
        raise ValueError("provider candidate must be an object")
    figi = _normalize_text(raw.get("figi"), uppercase=True)
    if figi is None or not _FIGI_PATTERN.fullmatch(figi):
        raise ValueError("provider candidate requires a valid FIGI")
    security_type_value = raw.get("securityType")
    if security_type_value is None:
        security_type_value = raw.get("securityType2")
    return OpenFigiCandidate(
        figi=figi,
        ticker=_normalize_text(raw.get("ticker"), uppercase=True),
        exchange_code=_normalize_text(raw.get("exchCode"), uppercase=True),
        market_sector=_normalize_text(raw.get("marketSector")),
        security_type=_normalize_text(security_type_value),
        name=_normalize_text(raw.get("name")),
        currency_hint=_normalize_text(raw.get("currency"), uppercase=True),
    )


def _invalid_result(isin: str, fingerprint: str) -> OpenFigiJobResult:
    candidate_hash = _sha256([])
    return OpenFigiJobResult(
        isin=isin,
        candidates=(),
        request_fingerprint=fingerprint,
        candidate_hash=candidate_hash,
        evidence_hash=_sha256(
            {"isin": isin, "invalid_payload": True, "candidate_hash": candidate_hash}
        ),
        invalid_payload=True,
    )


def _normalize_slot(isin: str, slot: object, fingerprint: str) -> OpenFigiJobResult:
    if not isinstance(slot, Mapping):
        return _invalid_result(isin, fingerprint)
    if "error" in slot:
        if not isinstance(slot["error"], str):
            return _invalid_result(isin, fingerprint)
        candidates: tuple[OpenFigiCandidate, ...] = ()
    else:
        raw_candidates = slot.get("data")
        if not isinstance(raw_candidates, list):
            return _invalid_result(isin, fingerprint)
        try:
            candidates = tuple(
                sorted(
                    (_candidate(raw) for raw in raw_candidates),
                    key=lambda item: (
                        item.figi,
                        item.ticker or "",
                        item.exchange_code or "",
                    ),
                )
            )
        except ValueError:
            return _invalid_result(isin, fingerprint)
    canonical_candidates = [asdict(candidate) for candidate in candidates]
    candidate_hash = _sha256(canonical_candidates)
    return OpenFigiJobResult(
        isin=isin,
        candidates=candidates,
        request_fingerprint=fingerprint,
        candidate_hash=candidate_hash,
        evidence_hash=_sha256(
            {
                "isin": isin,
                "invalid_payload": False,
                "candidates": canonical_candidates,
            }
        ),
        invalid_payload=False,
    )


def _sanitized_cache_slots(results: Sequence[OpenFigiJobResult]) -> list[object]:
    slots: list[object] = []
    for result in results:
        if result.invalid_payload:
            slots.append({"data": "INVALID_PROVIDER_PAYLOAD"})
            continue
        if not result.candidates:
            slots.append({"error": "NO_PROVIDER_MATCH"})
            continue
        candidates: list[dict[str, str]] = []
        for candidate in result.candidates:
            normalized = {"figi": candidate.figi}
            for key, value in (
                ("ticker", candidate.ticker),
                ("exchCode", candidate.exchange_code),
                ("marketSector", candidate.market_sector),
                ("securityType", candidate.security_type),
                ("name", candidate.name),
                ("currency", candidate.currency_hint),
            ):
                if value is not None:
                    normalized[key] = value
            candidates.append(normalized)
        slots.append({"data": candidates})
    return slots


def _replace_raw_cache(
    connection: sqlite3.Connection,
    request_fingerprint: str,
    results: Sequence[OpenFigiJobResult],
) -> None:
    serialized = json.dumps(
        {
            "status_code": 200,
            "decoder": "json",
            "payload": _sanitized_cache_slots(results),
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    owns_transaction = not connection.in_transaction
    connection.execute(
        """
        UPDATE api_cache
        SET response_json = ?, payload = ?
        WHERE provider = ?
          AND endpoint = 'isin-mapping'
          AND request_url_hash = ?
        """,
        (
            serialized,
            serialized,
            OPENFIGI_PROVIDER,
            request_fingerprint,
        ),
    )
    if owns_transaction:
        connection.commit()


class OpenFigiProvider:
    def __init__(
        self,
        *,
        transport: SafeProviderTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport or SafeProviderTransport(
            allowed_hosts={"api.openfigi.com"}
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper or time.sleep

    def map_isins(
        self,
        connection: sqlite3.Connection,
        isins: Sequence[str],
        *,
        now: datetime | None = None,
    ) -> list[OpenFigiJobResult]:
        normalized_isins = ["".join(value.split()).upper() for value in isins]
        if not normalized_isins:
            return []
        if len(normalized_isins) > OPENFIGI_MAX_JOBS:
            raise ValueError("OpenFIGI accepts at most 5 Phase 2 jobs per request")
        if any(not _is_valid_isin(value) for value in normalized_isins):
            raise ValueError("OpenFIGI mapping requires a valid ISIN for every job")

        settings = get_settings()
        headers = (
            {"X-OPENFIGI-APIKEY": settings.openfigi_api_key}
            if settings.openfigi_api_key
            else {}
        )
        jobs = [
            {"idType": "ID_ISIN", "idValue": isin}
            for isin in normalized_isins
        ]
        instant = now or self._clock()
        response = self._transport.request(
            connection=connection,
            policy=ProviderBudgetPolicy(
                minute_limit=settings.openfigi_minute_limit,
                daily_limit=settings.openfigi_daily_limit,
                monthly_limit=settings.openfigi_monthly_limit,
                max_attempts=settings.provider_default_max_attempts,
            ),
            provider=OPENFIGI_PROVIDER,
            method="POST",
            base_url=OPENFIGI_BASE_URL,
            path=OPENFIGI_MAPPING_PATH,
            headers=headers,
            params={},
            json_body=jobs,
            operation="IDENTITY",
            cache_scope="isin-mapping",
            cache_ttl_seconds=settings.openfigi_cache_ttl_hours * 3600,
            max_response_bytes=OPENFIGI_MAX_RESPONSE_BYTES,
            decoder="json",
            now=instant,
            sleeper=self._sleeper,
        )
        if not isinstance(response.payload, list) or len(response.payload) != len(jobs):
            results = [
                _invalid_result(isin, response.request_fingerprint)
                for isin in normalized_isins
            ]
        else:
            results = [
                _normalize_slot(isin, slot, response.request_fingerprint)
                for isin, slot in zip(normalized_isins, response.payload, strict=True)
            ]
        _replace_raw_cache(connection, response.request_fingerprint, results)
        return results
