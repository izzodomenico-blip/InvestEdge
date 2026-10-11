"""Official news pages and a pure, bounded decoder; no sockets or trading."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

from backend.app.data_providers.alpaca_market import AlpacaProviderError, _ns
from backend.app.intraday.contracts import MAX_NS, canonical_json


class NewsError(ValueError):
    def __init__(self, code):
        self.code = self.reason_code = code if code in {
            "NEWS_ROW_INVALID", "NEWS_PAGE_INVALID", "NEWS_RIGHTS_INVALID", "PUBLICATION_MISSING",
            "TIMESTAMP_INVALID", "TIMESTAMP_ORDER", "TIMESTAMP_FUTURE", "MODE_MISMATCH", "NEWS_LIMIT",
            "NEWS_INPUT_MISSING", "TRANSACTION_ALREADY_OPEN", "CANCELLED", "TOKEN_LOOP", "PAGE_LIMIT",
        } else "NEWS_ROW_INVALID"
        super().__init__(self.code)


@dataclass(frozen=True)
class NewsRights:
    """No finite retention can be promised by this append-only archive."""
    allow_summary: bool = False
    allow_content: bool = False
    retention: str = "NONE"
    evidence_hash: str | None = None
    version: str = "news-rights-v1"

    def __post_init__(self):
        if (type(self.allow_summary) is not bool or type(self.allow_content) is not bool or
                self.version != "news-rights-v1" or self.retention not in {"NONE", "ARCHIVE_ALLOWED"} or
                (self.evidence_hash is not None and (not isinstance(self.evidence_hash, str) or
                 re.fullmatch(r"[a-f0-9]{64}", self.evidence_hash) is None)) or
                ((self.allow_summary or self.allow_content) and
                 (self.retention != "ARCHIVE_ALLOWED" or self.evidence_hash is None))):
            raise NewsError("NEWS_RIGHTS_INVALID")


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.blocked = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "template", "svg"}:
            self.blocked += 1
        elif tag in {"p", "br", "div", "li"} and not self.blocked:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object", "template", "svg"}:
            self.blocked = max(0, self.blocked - 1)
        elif not self.blocked:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def plain_text(value, maximum):
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise NewsError("NEWS_ROW_INVALID")
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    # Angle brackets are removed even when HTMLParser interprets them as data.
    return " ".join("".join(parser.parts).replace("<", " ").replace(">", " ").split())


def decode_news_row(row, *, source, rights):
    try:
        if (type(row) is not dict or source not in {"REST", "STREAM"} or
                not isinstance(rights, NewsRights) or ("T" in row and row["T"] != "n")):
            raise ValueError
        canonical_json(row)  # Bound input and reject non-finite/duplicate-shaped structures before filtering.
        if type(row.get("id")) is not int or not 1 <= row["id"] <= MAX_NS:
            raise ValueError
        origin = row["source"]
        if not isinstance(origin, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", origin) is None:
            raise ValueError
        symbols = row["symbols"]
        if (type(symbols) is not list or len(symbols) > 100 or
                any(type(symbol) is not str or re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,31}", symbol) is None for symbol in symbols)):
            raise ValueError
        headline = plain_text(row["headline"], 8192)
        if not headline:
            raise ValueError
        if row.get("created_at") is None:
            raise NewsError("PUBLICATION_MISSING")
        try:
            # News times are RFC3339, not calendar dates with an invented midnight.
            if any(type(row.get(k)) is not str or "T" not in row[k] for k in ("created_at", "updated_at")):
                raise ValueError
            published, updated = (_ns(row[k]) for k in ("created_at", "updated_at"))
            if not 0 <= published <= MAX_NS or not 0 <= updated <= MAX_NS:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise NewsError("TIMESTAMP_INVALID") from None
        if updated < published:
            raise NewsError("TIMESTAMP_ORDER")
        for key in ("summary", "content"):
            if row.get(key) is not None and (type(row[key]) is not str or len(row[key].encode()) > 262144):
                raise ValueError
        summary = plain_text(row["summary"], 262144) if rights.allow_summary and row.get("summary") is not None else None
        content = plain_text(row["content"], 262144) if rights.allow_content and row.get("content") is not None else None
        url = row.get("url")
        if url is not None:
            if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 32 for c in url):
                url = None
            else:
                try:
                    parsed = urlsplit(url)
                    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                            parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
                        url = None
                except ValueError:
                    url = None  # Never fetch links; malformed or token-bearing URLs are discarded.
        author = row.get("author")
        if author is not None and (not isinstance(author, str) or len(author.encode()) > 1024):
            raise ValueError
        return {"version": "alpaca-news-row-v1", "wire_source": source, "source": origin,
                "source_article_id": str(row["id"]), "headline": headline, "summary": summary,
                "content": content, "content_state": ("AVAILABLE" if content is not None else
                    "CONTENT_UNAVAILABLE" if rights.allow_content else "RIGHTS_UNATTESTED"),
                "url": url, "author": author, "symbols": sorted(set(symbols)), "language": None,
                "published_at_ns": published, "updated_at_ns": updated, "rights": asdict(rights)}
    except NewsError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        raise NewsError("NEWS_ROW_INVALID") from None


def article_key(payload):
    # Source article ID is documented; URL and updated_at are not revision IDs.
    return hashlib.sha256(canonical_json({"source": payload["source"], "id": payload["source_article_id"]}).encode()).hexdigest()


class AlpacaNewsProvider:
    def __init__(self, market):
        self.market = market

    def get_page(self, *, start, end, symbols=(), limit=50, page_token=None, bypass_cache=False):
        if type(symbols) is not tuple or type(limit) is not int or not 1 <= limit <= 50:
            raise NewsError("NEWS_PAGE_INVALID")
        params = {"start": start, "end": end, "sort": "asc", "limit": str(limit),
                  "include_content": "false", "exclude_contentless": "false"}
        if symbols:
            if any(type(symbol) is not str for symbol in symbols):
                raise NewsError("NEWS_PAGE_INVALID")
            params["symbols"] = ",".join(symbols)
        if page_token is not None:
            params["page_token"] = page_token
        try:
            response = self.market.request_page("news", params, bypass_cache=bypass_cache)
        except AlpacaProviderError as exc:
            if exc.code == "INVALID_PAYLOAD":
                raise NewsError("NEWS_PAGE_INVALID") from None
            raise
        if (type(response.payload) is not dict or "next_page_token" not in response.payload or
                type(response.payload.get("news")) is not list or len(response.payload["news"]) > limit):
            raise NewsError("NEWS_PAGE_INVALID")
        return response
