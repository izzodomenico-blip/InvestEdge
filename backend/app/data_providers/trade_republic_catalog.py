from __future__ import annotations

import hashlib
import io
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pypdf.filters
from pypdf import PdfReader
from pypdf.errors import LimitReachedError

from backend.app.models.schemas import CatalogEntryStatus, CatalogFailureReason, CatalogReason

TRADE_REPUBLIC_SOURCE = "TRADE_REPUBLIC_IT"
TRADE_REPUBLIC_CATALOG_BASE_URL = "https://assets.traderepublic.com"
TRADE_REPUBLIC_CATALOG_PATH = "/assets/files/IT/Instrument_Universe_IT_en.pdf"
TRADE_REPUBLIC_CATALOG_URL = TRADE_REPUBLIC_CATALOG_BASE_URL + TRADE_REPUBLIC_CATALOG_PATH
CATALOG_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
CATALOG_MAX_PAGES = 4096
CATALOG_PARSER_VERSION = "trade-republic-pdf-v1"

_ISIN_TOKEN = re.compile(
    r"(?<![A-Z0-9])([A-Z]{2}[A-Z0-9]{9}[0-9])(?![A-Z0-9])",
    re.IGNORECASE | re.ASCII,
)
_ISIN_EXACT = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", re.ASCII)
_TABLE_HEADERS = frozenset({"name isin", "isin name"})
_PYPDF_LIMIT_NAMES = (
    "MAX_DECLARED_STREAM_LENGTH",
    "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
    "JBIG2_MAX_OUTPUT_LENGTH",
    "LZW_MAX_OUTPUT_LENGTH",
    "RUN_LENGTH_MAX_OUTPUT_LENGTH",
    "ZLIB_MAX_OUTPUT_LENGTH",
    "FLATE_MAX_BUFFER_SIZE",
)
_PYPDF_LIMIT_LOCK = threading.Lock()


@dataclass(frozen=True)
class ParsedCatalogRow:
    row_number: int
    isin: str | None
    name: str | None
    status: CatalogEntryStatus
    reason_code: CatalogReason
    raw_row_sha256: str


class CatalogParseError(RuntimeError):
    def __init__(self, reason_code: CatalogFailureReason) -> None:
        self.reason_code = reason_code
        super().__init__(f"trade_republic_catalog:{reason_code}")


@contextmanager
def _bounded_pypdf_filters() -> Iterator[None]:
    """Applica il budget a ogni decoder pypdf e ripristina i limiti globali."""
    with _PYPDF_LIMIT_LOCK:
        original = {
            name: int(getattr(pypdf.filters, name))
            for name in _PYPDF_LIMIT_NAMES
        }
        for name, value in original.items():
            setattr(pypdf.filters, name, min(value, CATALOG_MAX_RESPONSE_BYTES))
        try:
            yield
        finally:
            for name, value in original.items():
                setattr(pypdf.filters, name, value)


def _normalize_spaces(value: str) -> str:
    return " ".join(value.split())


def _row_hash(normalized_row: str) -> str:
    return hashlib.sha256(normalized_row.encode("utf-8")).hexdigest()


def _isin_is_valid(value: str) -> bool:
    if _ISIN_EXACT.fullmatch(value) is None:
        return False
    expanded = "".join(str(ord(character) - 55) if character.isalpha() else character for character in value)
    total = 0
    for index, character in enumerate(reversed(expanded)):
        number = int(character) * (1 if index % 2 == 0 else 2)
        total += number // 10 + number % 10
    return total % 10 == 0


def _parse_row(
    normalized_row: str,
    row_number: int,
    seen_isins: set[str],
) -> ParsedCatalogRow:
    digest = _row_hash(normalized_row)
    matches = list(_ISIN_TOKEN.finditer(normalized_row))
    if len(matches) > 1:
        return ParsedCatalogRow(
            row_number=row_number,
            isin=None,
            name=None,
            status="AMBIGUOUS",
            reason_code="UNSUPPORTED_ROW",
            raw_row_sha256=digest,
        )
    if not matches:
        return ParsedCatalogRow(
            row_number=row_number,
            isin=None,
            name=normalized_row or None,
            status="REJECTED",
            reason_code="MISSING_ISIN" if normalized_row else "UNSUPPORTED_ROW",
            raw_row_sha256=digest,
        )

    match = matches[0]
    isin = match.group(1).upper()
    name = _normalize_spaces(
        (normalized_row[: match.start()] + " " + normalized_row[match.end() :]).strip(" |:-\t")
    )
    if not name:
        return ParsedCatalogRow(
            row_number=row_number,
            isin=isin,
            name=None,
            status="REJECTED",
            reason_code="MISSING_NAME",
            raw_row_sha256=digest,
        )
    if not _isin_is_valid(isin):
        return ParsedCatalogRow(
            row_number=row_number,
            isin=isin,
            name=name,
            status="REJECTED",
            reason_code="INVALID_ISIN",
            raw_row_sha256=digest,
        )
    if isin in seen_isins:
        return ParsedCatalogRow(
            row_number=row_number,
            isin=isin,
            name=name,
            status="REJECTED",
            reason_code="DUPLICATE_IN_SNAPSHOT",
            raw_row_sha256=digest,
        )
    seen_isins.add(isin)
    return ParsedCatalogRow(
        row_number=row_number,
        isin=isin,
        name=name,
        status="ACCEPTED",
        reason_code="VALID_ISIN",
        raw_row_sha256=digest,
    )


def _page_lines(page_text: str) -> list[str]:
    return [_normalize_spaces(line) for line in page_text.splitlines()]


def parse_trade_republic_pdf(payload: bytes) -> list[ParsedCatalogRow]:
    if len(payload) > CATALOG_MAX_RESPONSE_BYTES:
        raise CatalogParseError("PAYLOAD_TOO_LARGE")
    if not payload.startswith(b"%PDF-"):
        raise CatalogParseError("PARSER_ERROR")

    try:
        with _bounded_pypdf_filters():
            reader = PdfReader(
                io.BytesIO(payload),
                strict=True,
                root_object_recovery_limit=1000,
            )
            if reader.is_encrypted or len(reader.pages) > CATALOG_MAX_PAGES:
                raise CatalogParseError("PARSER_ERROR")

            parsed_rows: list[ParsedCatalogRow] = []
            seen_isins: set[str] = set()
            extracted_bytes = 0
            decoded_stream_bytes = 0
            for page in reader.pages:
                contents = page.get_contents()
                if contents is not None:
                    decoded_stream_bytes += len(contents.get_data())
                    if decoded_stream_bytes > CATALOG_MAX_RESPONSE_BYTES:
                        raise CatalogParseError("PAYLOAD_TOO_LARGE")
                page_text = page.extract_text() or ""
                extracted_bytes += len(page_text.encode("utf-8"))
                if extracted_bytes > CATALOG_MAX_RESPONSE_BYTES:
                    raise CatalogParseError("PAYLOAD_TOO_LARGE")

                in_table = False
                lines = _page_lines(page_text)
                index = 0
                while index < len(lines):
                    line = lines[index]
                    folded = line.casefold()
                    if folded in _TABLE_HEADERS:
                        in_table = True
                        index += 1
                        continue
                    if (
                        index + 1 < len(lines)
                        and {folded, lines[index + 1].casefold()} == {"name", "isin"}
                    ):
                        in_table = True
                        index += 2
                        continue
                    if in_table and line:
                        parsed_rows.append(
                            _parse_row(line, len(parsed_rows) + 1, seen_isins)
                        )
                    index += 1
            return parsed_rows
    except CatalogParseError:
        raise
    except LimitReachedError:
        raise CatalogParseError("PAYLOAD_TOO_LARGE") from None
    except Exception:
        raise CatalogParseError("PARSER_ERROR") from None
