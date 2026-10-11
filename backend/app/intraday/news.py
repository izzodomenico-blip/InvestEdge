"""Versioned factual news with immutable mapping and post-durability admission."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import replace
from itertools import islice

from backend.app.data_providers.alpaca_market import _ns
from backend.app.data_providers.alpaca_metadata import (
    AlpacaMetadataService,
    check_ns,
    datetime_ns,
    decode_row,
    read_evidence,
    scope,
)
from backend.app.data_providers.alpaca_news import (
    AlpacaNewsProvider,
    NewsError,
    NewsRights,
    article_key,
    decode_news_row,
)
from backend.app.intraday.contracts import EventEnvelope, canonical_json
from backend.app.intraday.identity import _at, _versions

_COMMON = ("provider", "feed", "profile_id", "data_mode", "provenance", "replay_grade", "schema_version",
           "listing_id", "logical_key", "capture_id", "ingest_sequence", "event_time_ns", "received_at_ns",
           "persisted_at_ns", "admitted_at_ns", "availability_floor_ns", "payload_json", "source_event_id", "source_revision_id")
_TABLES = {"intraday_news_versions", "intraday_news_links", "intraday_capture_events"}


def classify_news(payload):
    text = payload["headline"].lower()
    rules = (
        ("GUIDANCE", r"\b(?:raises|cuts|withdraws|updates)\b.*\bguidance\b"),
        ("EARNINGS", r"\breports?\b.*\b(?:earnings|quarterly results|annual results)\b"),
        ("M_AND_A", r"\b(?:acquired|acquires|completes acquisition|agrees to acquire)\b"),
        ("FINANCING_DILUTION", r"\b(?:announces|prices|completes)\b.*\b(?:stock offering|equity offering|capital raise)\b"),
        ("REGULATORY", r"\b(?:fda approves|regulator approves|regulator rejects)\b"),
        ("SEC_FILING", r"\bfiles\b.*\b(?:8-k|10-k|10-q|sec)\b"),
        ("MACRO", r"\b(?:federal reserve announces|bls releases)\b"),
        ("SECTOR", r"\bindustry association reports\b"),
    )
    category, evidence = "UNKNOWN", None
    if not re.search(r"\b(?:may|might|rumou?rs?|expects?|denies|could|potential|talks|not|no|never|unconfirmed|reportedly|plans?|will|would)\b", text):
        matches = [(category, pattern) for category, pattern in rules if re.search(pattern, text)]
        if len(matches) == 1:
            category, evidence = matches[0]
    return {"category": category, "rule_version": "news-facts-v1", "evidence": evidence,
            "scope": "FACTUAL_HEADLINE_ONLY", "predictive": False}


def cluster_key(payload, facts):
    # Exact factual headline + subjects + publication day only; no fuzzy or later reclassification.
    key = {"version": "news-cluster-v1", "category": facts["category"],
           "headline": " ".join(payload["headline"].casefold().split()), "symbols": payload["symbols"],
           "publication_day": payload["published_at_ns"] // 86_400_000_000_000}
    if facts["category"] == "UNKNOWN":
        key["article_key"] = article_key(payload)
    return hashlib.sha256(canonical_json(key).encode()).hexdigest()


class NewsStore:
    def __init__(self, provider, *, clock_ns=time.time_ns, rights=None, data_mode="REAL",
                 provenance="CAPTURED", replay_grade="STRICT_PIT"):
        self.archive = AlpacaMetadataService(provider, clock_ns=clock_ns, data_mode=data_mode,
                                            provenance=provenance, replay_grade=replay_grade)
        self.provider, self.connection, self.profile = provider, provider.connection, provider.profile
        self.rights = rights or NewsRights()
        if not isinstance(self.rights, NewsRights):
            raise NewsError("NEWS_RIGHTS_INVALID")
        self.archive.safe_json({"rights": self.rights.__dict__})
        self.data_mode, self.provenance, self.replay_grade = data_mode, provenance, replay_grade

    @property
    def namespace(self):
        return self.archive.namespace

    def _begin(self):
        if self.connection.in_transaction:
            raise NewsError("TRANSACTION_ALREADY_OPEN")
        self.connection.execute("BEGIN IMMEDIATE")
        self._used = self.archive._archive_bytes()

    def _insert(self, table, envelope, run, fields):
        if table not in _TABLES:
            raise NewsError("NEWS_ROW_INVALID")
        text = self.archive.safe_json(envelope.payload)
        size = len(text.encode())
        config = self.archive.settings
        if size > min(self.profile.max_frame_bytes, config.alpaca_max_frame_bytes):
            raise NewsError("NEWS_LIMIT")
        if self._used + size > min(self.profile.max_archive_bytes, config.alpaca_max_archive_bytes):
            raise NewsError("NEWS_LIMIT")
        sequence = self.connection.execute("SELECT accepted_count+1 FROM intraday_ingest_runs WHERE id=?", (run,)).fetchone()[0]
        row = {name: getattr(envelope, name) for name in _COMMON}
        row.update(ingest_run_id=run, ingest_sequence=sequence, available_at_ns=envelope.available_at_ns,
                   payload_hash=envelope.payload_hash, **fields)
        row_id = self.connection.execute(f"INSERT INTO {table}({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                                         tuple(row.values())).lastrowid
        self.connection.execute("UPDATE intraday_ingest_runs SET accepted_count=accepted_count+1 WHERE id=?", (run,))
        self._used += size
        return int(row_id)

    def _envelope(self, payload, received, key, capture, *, listing_id=None):
        stamp = self.archive.now()
        result = EventEnvelope("alpaca", self.profile.feed, *self.namespace[:2], *self.namespace[2:],
                               "NEWS", listing_id, key, capture, 1, payload["published_at_ns"], received,
                               stamp, None, self.archive.safe_json(payload), payload["updated_at_ns"])
        result.validate_at(stamp)
        return result

    def _links(self, payload, received):
        scope = {"data_mode": self.data_mode, "provenance": "CAPTURED" if self.data_mode == "REAL" else "SYNTHETIC",
                 "replay_grade": "STRICT_PIT" if self.data_mode == "REAL" else "RESEARCH_ONLY"}
        versions = _versions(self.connection, received, (self.profile.profile_id, *scope.values()))
        facts, result = classify_news(payload), []
        cluster = cluster_key(payload, facts)
        for symbol in payload["symbols"] or [None]:
            candidates = [_at([v for v in versions if v["listing_id"] == listing], payload["updated_at_ns"])
                          for listing in {v["listing_id"] for v in versions}]
            candidates = [v for v in candidates if v is not None and v["ticker"] == symbol and
                          "NEWS" in v["payload"]["capabilities"]]
            identity = candidates[0] if len(candidates) == 1 else None
            reason = "IDENTITY_AMBIGUOUS" if len(candidates) > 1 else "IDENTITY_UNVERIFIED" if symbol and identity is None else None
            proof = {k: identity[k] for k in ("id", "payload_hash", "publication_id")} if identity else None
            result.append({"listing_id": identity["listing_id"] if identity else None,
                           "instrument_id": identity["instrument_id"] if identity else None,
                           "cluster_id": cluster, "category": facts["category"], "rule_version": facts["rule_version"],
                           "payload": {"symbol": symbol, "identity": proof, "reason_code": reason,
                                       "facts": facts, "cluster_version": "news-cluster-v1", "event_id": cluster,
                                       "target": "LISTING" if identity else "UNMAPPED" if symbol else "MARKET"}})
        return result

    def _duplicate(self, payload, received, capture):
        key = article_key(payload)
        row = self.connection.execute("""SELECT * FROM intraday_news_versions
            WHERE profile_id=? AND data_mode=? AND provenance=? AND replay_grade=? AND article_id=?
              AND capture_id=? AND (received_at_ns<? OR (received_at_ns=? AND
                COALESCE(json_extract(payload_json,'$.intake_sequence'),ingest_sequence)<=?))
              ORDER BY received_at_ns DESC,COALESCE(json_extract(payload_json,'$.intake_sequence'),ingest_sequence) DESC,id DESC LIMIT 1""",
            (*self.namespace, key, capture, received, received, payload["intake_sequence"])).fetchone()
        previous = decode_row(row)["payload"] if row is not None else None
        incoming = dict(payload)
        incoming.pop("intake_sequence", None)
        if previous is not None:
            previous.pop("intake_sequence", None)
        return row["id"] if row is not None and previous == incoming else None

    def _quarantine(self, row, received, reason):
        # Invalid publication has no invented timestamp and never becomes a NEWS version.
        safe = {key: row[key] for key in ("id", "source", "created_at", "updated_at") if key in row}
        with self.archive.transaction():
            run = self.archive.begin_run()
            self.archive.bootstrap(run, {"metadata_kind": "NEWS_QUARANTINE", "reason_code": reason,
                                         "metadata": safe}, received, "news-quarantine")
            self.connection.execute("UPDATE intraday_ingest_runs SET rejected_count=1 WHERE id=?", (run,))

    def persist(self, rows, *, received_at_ns, source="STREAM", capture_id="news-local", admit=True, intake_sequence=None):
        check_ns(received_at_ns)
        if received_at_ns > self.archive.now():
            raise NewsError("TIMESTAMP_FUTURE")
        if source == "REST" and (self.provenance != "HISTORICAL_CURRENT" or self.replay_grade != "RESEARCH_ONLY"):
            raise NewsError("MODE_MISMATCH")
        cap = min(self.profile.max_queue_events, self.archive.settings.alpaca_max_queue_events)
        values = tuple(islice(iter(rows), max(0, cap)+1))
        if not values or len(values) > cap:
            raise NewsError("NEWS_LIMIT")
        if intake_sequence is None:
            intake_sequence = self.connection.execute("SELECT COALESCE(MAX(COALESCE(json_extract(payload_json,'$.intake_sequence'),ingest_sequence)),0)+1 FROM intraday_news_versions").fetchone()[0]
        if type(intake_sequence) is not int or intake_sequence <= 0:
            raise NewsError("NEWS_ROW_INVALID")
        prepared = []
        for index, row in enumerate(values):
            self.archive.safe_json(row)  # Check credential echo even in omitted HTML/fields.
            try:
                payload = decode_news_row(row, source=source, rights=self.rights)
                if payload["updated_at_ns"] > received_at_ns:
                    raise NewsError("TIMESTAMP_FUTURE")
                payload["intake_sequence"] = intake_sequence + index
                prepared.append(payload)
            except NewsError as exc:
                if exc.code not in {"PUBLICATION_MISSING", "TIMESTAMP_INVALID", "TIMESTAMP_ORDER", "TIMESTAMP_FUTURE"}:
                    raise
                self._quarantine(row, received_at_ns, exc.code)
        if not prepared:
            return ()
        self._begin()
        try:
            run, ids = self.archive.begin_run(), []
            for payload in prepared:
                key = article_key(payload)
                duplicate = self._duplicate(payload, received_at_ns, capture_id)
                if duplicate is not None:
                    ids.append(duplicate)
                    continue
                envelope = self._envelope(payload, received_at_ns, key, capture_id)
                previous = self.connection.execute("SELECT id FROM intraday_news_versions WHERE profile_id=? AND data_mode=? AND provenance=? AND replay_grade=? AND article_id=? ORDER BY updated_at_ns DESC,received_at_ns DESC,id DESC LIMIT 1",
                                                   (*self.namespace, key)).fetchone()
                row_id = self._insert("intraday_news_versions", envelope, run,
                                      {"article_id": key, "published_at_ns": payload["published_at_ns"],
                                       "updated_at_ns": payload["updated_at_ns"], "supersedes_id": previous[0] if previous else None})
                ids.append(row_id)
                for index, link in enumerate(self._links(payload, received_at_ns)):
                    link_payload = {**link.pop("payload"), "news_version_id": row_id, "news_hash": envelope.payload_hash}
                    link_envelope = replace(envelope, listing_id=link["listing_id"], logical_key=f"link:{row_id}:{index}",
                                            payload_json=self.archive.safe_json(link_payload))
                    self._insert("intraday_news_links", link_envelope, run, {"news_version_id": row_id, **link})
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        if admit:
            self.admit(ids)
        self.connection.execute("UPDATE intraday_ingest_runs SET state='COMPLETE',finished_at_ns=? WHERE id=?", (self.archive.now(), run))
        self.connection.commit()
        return tuple(ids)

    def admit(self, news_ids):
        ids = tuple(dict.fromkeys(news_ids))
        cap = min(self.profile.max_queue_events, self.archive.settings.alpaca_max_queue_events)
        if not ids or len(ids) > cap:
            raise NewsError("NEWS_LIMIT")
        durable = self.archive.now()
        self._begin()
        try:
            receipts = []
            for row_id in ids:
                raw = self.connection.execute("SELECT * FROM intraday_news_versions WHERE id=?", (row_id,)).fetchone()
                if raw is None or tuple(raw[k] for k in ("profile_id", "data_mode", "provenance", "replay_grade")) != self.namespace:
                    raise NewsError("NEWS_INPUT_MISSING")
                if self.connection.execute("SELECT 1 FROM intraday_capture_events WHERE kind='ADMISSION' AND news_version_id=?", (row_id,)).fetchone():
                    continue
                raw = decode_row(raw)
                links = [decode_row(row) for row in self.connection.execute("SELECT * FROM intraday_news_links WHERE news_version_id=? ORDER BY id", (row_id,))]
                if not links or durable < max(raw["persisted_at_ns"], raw["availability_floor_ns"], *(row["persisted_at_ns"] for row in links)):
                    raise NewsError("NEWS_INPUT_MISSING")
                payload = {"version": "news-admission-v1", "news_version_id": row_id, "payload_hash": raw["payload_hash"],
                           "durable_at_ns": durable, "links": [{"id": row["id"], "hash": row["payload_hash"]} for row in links]}
                stamp = self.archive.now()
                proof = EventEnvelope("alpaca", self.profile.feed, *self.namespace[:2], *self.namespace[2:],
                                      "EVENT", None, f"news-admission:{row_id}", raw["capture_id"], 1, durable, durable,
                                      stamp, stamp, self.archive.safe_json(payload), raw["availability_floor_ns"])
                proof.validate_at(stamp)
                receipts.append(self._insert("intraday_capture_events", proof, raw["ingest_run_id"],
                    {"kind": "ADMISSION", "lease_nonce": "news-archive-v1", "observation_id": None,
                     "news_version_id": row_id, "event_version_id": None}))
            self.connection.commit()
            return tuple(receipts)
        except Exception:
            self.connection.rollback()
            raise

    def read_as_of(self, *, cutoff_ns, listing_ids=None, revisions=False):
        check_ns(cutoff_ns)
        try:
            return self._read_as_of(cutoff_ns=cutoff_ns, listing_ids=listing_ids, revisions=revisions)
        except (sqlite3.DatabaseError, ValueError, TypeError, KeyError):
            raise NewsError("NEWS_INPUT_MISSING") from None

    def _read_as_of(self, *, cutoff_ns, listing_ids, revisions):
        rows = self.connection.execute("""SELECT raw.*, proof.id AS proof_id,proof.payload_json AS proof_json,
            proof.payload_hash AS proof_hash,proof.available_at_ns AS proof_available
            FROM intraday_news_versions raw JOIN intraday_capture_events proof ON proof.news_version_id=raw.id
            AND proof.kind='ADMISSION' WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=?
            AND raw.replay_grade=? AND proof.available_at_ns<=? ORDER BY raw.updated_at_ns,raw.received_at_ns,COALESCE(json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence),raw.id""",
            (*self.namespace, cutoff_ns))
        result = []
        for row in rows:
            raw = dict(row)
            item = decode_row({k:v for k,v in raw.items() if not k.startswith("proof_")})
            proof = decode_row({"payload_json":raw["proof_json"], "payload_hash":raw["proof_hash"]})["payload"]
            durable = proof.get("durable_at_ns")
            check_ns(durable)
            if proof.get("news_version_id") != item["id"] or proof.get("payload_hash") != item["payload_hash"] or durable < item["persisted_at_ns"]:
                raise NewsError("NEWS_INPUT_MISSING")
            item["available_at_ns"] = max(raw["proof_available"], durable, item["availability_floor_ns"])
            if item["available_at_ns"] > cutoff_ns:
                continue
            links = []
            references = proof.get("links")
            if not isinstance(references, list) or not references:
                raise NewsError("NEWS_INPUT_MISSING")
            for reference in references:
                link = self.connection.execute("SELECT * FROM intraday_news_links WHERE id=?", (reference["id"],)).fetchone()
                if link is None:
                    raise NewsError("NEWS_INPUT_MISSING")
                link = decode_row(link)
                if (link["news_version_id"] != item["id"] or link["payload_hash"] != reference["hash"] or
                        link["ingest_run_id"] != item["ingest_run_id"] or link["capture_id"] != item["capture_id"] or
                        link["payload"].get("news_hash") != item["payload_hash"] or durable < link["persisted_at_ns"]):
                    raise NewsError("NEWS_INPUT_MISSING")
                identity_ref = link["payload"].get("identity")
                if identity_ref is not None:
                    try:
                        metadata_scope = scope(self.profile.profile_id, self.data_mode,
                            "CAPTURED" if self.data_mode == "REAL" else "SYNTHETIC",
                            "STRICT_PIT" if self.data_mode == "REAL" else "RESEARCH_ONLY")
                        identity = read_evidence(self.connection, "intraday_identity_versions", identity_ref["id"], cutoff_ns, metadata_scope)
                        if (identity["payload_hash"] != identity_ref["payload_hash"] or
                                identity["publication_id"] != identity_ref["publication_id"] or
                                identity["listing_id"] != link["listing_id"] or identity["instrument_id"] != link["instrument_id"] or
                                identity["available_at_ns"] > item["received_at_ns"]):
                            raise ValueError
                    except (ValueError, KeyError, TypeError, sqlite3.DatabaseError):
                        raise NewsError("NEWS_INPUT_MISSING") from None
                link["available_at_ns"] = item["available_at_ns"]
                links.append(link)
            item.update(links=links, admission_id=raw["proof_id"], first_received_at_ns=item["received_at_ns"])
            result.append(item)
        captures = {}
        for item in result:
            key = (item["article_id"], item["updated_at_ns"], item["received_at_ns"], item["capture_id"])
            captures[key] = min(captures.get(key, item["id"]), item["id"])
        for item in result:
            key = (item["article_id"], item["updated_at_ns"], item["received_at_ns"], item["capture_id"])
            item["capture_order"] = captures[key]
        def order(item):
            return (item["received_at_ns"], item["capture_order"],
                    item["payload"].get("intake_sequence", item["ingest_sequence"]), item["id"])
        if not revisions:
            latest = {}
            for item in sorted(result, key=lambda row: (row["updated_at_ns"], *order(row))):
                latest[item["article_id"]] = item
            result = list(latest.values())
        # Filter after version selection: removing a symbol must not resurrect an old version.
        if listing_ids is not None:
            result = [item for item in result if any(link["listing_id"] in listing_ids for link in item["links"])]
        return sorted(result, key=lambda row: (row["available_at_ns"], *order(row)))

    def quarantine_as_of(self, *, cutoff_ns):
        from backend.app.data_providers.alpaca_metadata import captures_as_of
        return captures_as_of(self.connection, cutoff_ns, metadata_kind="NEWS_QUARANTINE",
                              profile_id=self.profile.profile_id, data_mode=self.data_mode,
                              provenance=self.provenance, replay_grade=self.replay_grade)

    def backfill(self, *, start, end, symbols=(), max_pages=100, cancel=None):
        if self.provenance != "HISTORICAL_CURRENT" or self.replay_grade != "RESEARCH_ONLY":
            raise NewsError("MODE_MISMATCH")
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise NewsError("PAGE_LIMIT")
        # validate before opening a run/transport, including empty covered-zero pages
        adapter = AlpacaNewsProvider(self.provider)
        params = {"start":start,"end":end,"sort":"asc","limit":"50","include_content":"false","exclude_contentless":"false"}
        if symbols:
            params["symbols"] = ",".join(symbols)
        self.archive.safe_json(params)
        self.provider._validate_params("news", params, self.provider.clock())
        token, seen, ids, page_count = None, set(), [], 0
        capture = hashlib.sha256(self.archive.safe_json({"request":params,"rights":self.rights.__dict__,"namespace":list(self.namespace)}).encode()).hexdigest()
        state, reason = "PARTIAL", None
        try:
            for _ in range(max_pages):
                if cancel and cancel():
                    raise NewsError("CANCELLED")
                response = adapter.get_page(start=start, end=end, symbols=symbols, page_token=token)
                received = datetime_ns(response.fetched_at) if response.fetched_at else self.archive.now()
                if response.payload["news"]:
                    source_rows = response.payload["news"]
                    for source_row in source_rows:
                        try:
                            updated = _ns(source_row["updated_at"])
                        except (ValueError, KeyError, TypeError):
                            continue  # Quarantine below; never certify this page as complete.
                        if not _ns(start) <= updated <= _ns(end) or (symbols and not set(symbols).intersection(source_row.get("symbols", []))):
                            raise NewsError("NEWS_PAGE_INVALID")
                    page_ids = self.persist(source_rows, received_at_ns=received, source="REST", capture_id=capture)
                    ids.extend(page_ids)
                    if len(page_ids) != len(source_rows):
                        raise NewsError("NEWS_PAGE_INVALID")
                page_count += 1
                if cancel and cancel():
                    raise NewsError("CANCELLED")
                token = response.payload["next_page_token"]
                if token is None:
                    state = "COMPLETE"
                    break
                if token in seen:
                    raise NewsError("TOKEN_LOOP")
                seen.add(token)
            else:
                raise NewsError("PAGE_LIMIT")
        except Exception as exc:
            reason = getattr(exc, "code", "NEWS_PAGE_INVALID")
        members = {row["id"]: row for row in self.read_as_of(cutoff_ns=self.archive.now(), revisions=True)}
        refs = [{"id": row_id, "hash": members[row_id]["payload_hash"], "admission_id": members[row_id]["admission_id"]}
                for row_id in dict.fromkeys(ids)]
        with self.archive.transaction():
            run = self.archive.begin_run()
            self.archive.bootstrap(run, {"metadata_kind":"NEWS_COVERAGE", "start_ns":_ns(start), "end_ns":_ns(end),
                "symbols":list(symbols), "state":state, "reason_code":reason, "pages":page_count,
                "news_ids":list(dict.fromkeys(ids)), "news_refs":refs, "continuity_attested":False}, self.archive.now(), "news-coverage")
        return {"state":state, "reason_code":reason, "pages":page_count, "news_ids":tuple(ids)}

    def coverage_as_of(self, *, start_ns, end_ns, cutoff_ns, symbols=(), max_age_ns=60_000_000_000):
        from backend.app.data_providers.alpaca_metadata import captures_as_of
        for stamp in (start_ns, end_ns, cutoff_ns, max_age_ns):
            check_ns(stamp)
        if start_ns > end_ns:
            raise NewsError("NEWS_PAGE_INVALID")
        config = self.archive.settings
        disabled = not config.enable_real_data or not config.enable_alpaca_data or "news" not in self.profile.attested_capabilities
        rows = captures_as_of(self.connection, cutoff_ns, metadata_kind="NEWS_COVERAGE", profile_id=self.profile.profile_id,
            data_mode=self.data_mode, provenance=self.provenance, replay_grade=self.replay_grade)
        matches = [row for row in rows if row["payload"]["start_ns"]<=start_ns and row["payload"]["end_ns"]>=end_ns and
                   (not row["payload"]["symbols"] or (bool(symbols) and set(symbols)<=set(row["payload"]["symbols"])))]
        if not matches:
            return {"state":"DISABLED" if disabled else "MISSING", "continuity_attested":False,
                    "acquisition_disabled": disabled}
        row = max(matches, key=lambda r:(r["received_at_ns"],r["ingest_sequence"],r["id"]))
        p = row["payload"]
        count = 0
        if p["state"] == "COMPLETE":
            try:
                members = {item["id"]: item for item in self.read_as_of(cutoff_ns=row["available_at_ns"], revisions=True)}
                refs = p["news_refs"]
                if {ref["id"] for ref in refs} != set(p["news_ids"]):
                    raise ValueError
                for ref in refs:
                    item = members[ref["id"]]
                    if item["payload_hash"] != ref["hash"] or item["admission_id"] != ref["admission_id"]:
                        raise ValueError
                    if start_ns <= item["updated_at_ns"] <= end_ns and (not symbols or set(symbols).intersection(item["payload"]["symbols"])):
                        count += 1
            except (ValueError, KeyError, TypeError, sqlite3.DatabaseError):
                raise NewsError("NEWS_INPUT_MISSING") from None
        state = "MISSING" if p["state"] != "COMPLETE" else "STALE" if cutoff_ns-row["received_at_ns"]>max_age_ns else "COVERED" if count else "COVERED_ZERO"
        return {"state":state, "continuity_attested":False, "acquisition_disabled":disabled,
                "news_count":count, "coverage_id":row["id"], "publication_id":row["publication_id"],
                "provenance":self.provenance,"replay_grade":self.replay_grade}
