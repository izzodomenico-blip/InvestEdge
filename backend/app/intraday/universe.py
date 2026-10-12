"""Append-only universe snapshots. Eligibility is evidence-based, never a trading signal."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.app.data_providers.alpaca_metadata import (
    AlpacaMetadataService,
    MetadataError,
    asset_rows,
    captures_as_of,
    check_ns,
    read_evidence,
)
from backend.app.intraday.calendar import session_as_of
from backend.app.intraday.identity import _EXCHANGE_MIC, read_identity_as_of


@dataclass(frozen=True)
class UniverseSnapshot:
    snapshot_id: int
    digest: str


def frozen_universe_dependencies(snapshot, timeline):
    """Bind exact member occurrences where the dataset schema has no member FK."""
    members = sorted((row for row in timeline if row['table'] == 'intraday_universe_members'
                      and row['snapshot_id'] == snapshot['id']), key=lambda row: row['listing_id'])
    if (len(members) != snapshot['member_count'] or
            [row['payload'] for row in members] != snapshot['payload']['members']):
        raise MetadataError('SNAPSHOT_INPUT_MISSING')
    return members


class UniverseService:
    def __init__(self, archive: AlpacaMetadataService):
        self.archive = archive
        self.connection = archive.connection

    def freeze(self, listing_ids, session_date, cutoff_ns):
        check_ns(cutoff_ns)
        if (type(listing_ids) is not list or not listing_ids or
                len(listing_ids) > min(self.archive.profile.max_symbols, self.archive.settings.alpaca_max_symbols) or
                any(type(item) is not int or item <= 0 for item in listing_ids) or
                len(listing_ids) != len(set(listing_ids))):
            raise MetadataError("METADATA_INVALID")
        namespace = {"profile_id": self.archive.profile.profile_id, "data_mode": self.archive.data_mode,
                     "provenance": self.archive.provenance, "replay_grade": self.archive.replay_grade}
        with self.archive.transaction():
            session = session_as_of(self.connection, session_date, cutoff_ns, **namespace)
            if session is None:
                raise MetadataError("CALENDAR_MISSING")
            now = self.archive.now()
            strict = self.archive.replay_grade == "STRICT_PIT"
            if cutoff_ns > now or (strict and now >= session.open_at_ns):
                raise MetadataError("SNAPSHOT_NOT_PIT")
            batches = captures_as_of(self.connection, cutoff_ns, **namespace, metadata_kind="ASSETS", latest_only=True)
            batch = batches[0] if batches else None
            assets = {item["id"]: item for item in asset_rows(self.connection, batch, cutoff_ns,
                      self.archive.namespace)} if batch else {}
            members, exclusions = [], []
            for listing in sorted(listing_ids):
                identity = read_identity_as_of(self.connection, listing, session.open_at_ns, cutoff_ns, **namespace)
                if identity is None:
                    exclusions.append({"listing_id": listing, "reason_code": "IDENTITY_UNVERIFIED"})
                    continue
                asset = assets.get(identity["broker_asset_id"])
                reason = None
                if asset is None:
                    reason = "METADATA_MISSING"
                elif asset["class"] != "us_equity" or (
                    asset["symbol"], _EXCHANGE_MIC.get(asset["exchange"], asset["exchange"]),
                ) != (identity["ticker"], identity["payload"]["mic"]):
                    reason = "IDENTITY_UNVERIFIED"
                elif asset["status"] != "active":
                    reason = "ASSET_INACTIVE"
                elif not asset["tradable"]:
                    reason = "ASSET_NOT_TRADABLE"
                elif (not {"BAR", "QUOTE", "NEWS"} <= set(identity["payload"]["capabilities"]) or
                      not {"bars", "quotes", "news"} <= set(self.archive.profile.attested_capabilities)):
                    reason = "CAPABILITY_UNVERIFIED"
                elif identity["payload"]["leveraged"] == "YES":
                    reason = "LEVERAGED_PRODUCT"
                elif identity["payload"]["inverse"] == "YES":
                    reason = "INVERSE_PRODUCT"
                elif identity["payload"]["instrument_type"] == "ETF" and (
                    identity["payload"]["leveraged"] != "NO" or identity["payload"]["inverse"] != "NO"
                ):
                    reason = "PRODUCT_LEVERAGE_UNKNOWN"
                members.append({"listing_id": listing, "identity_version_id": identity["id"],
                                "identity_hash": identity["payload_hash"], "identity_publication_id": identity["publication_id"],
                                "asset": asset,
                                "eligible": reason is None, "reason_code": reason})
            calendar = read_evidence(self.connection, "intraday_calendar_versions", session.version_id,
                                     cutoff_ns, self.archive.namespace)
            calendar_capture = self.archive.read_capture(session.capture_id, "CALENDAR", cutoff_ns)
            manifest = {
                "version": "intraday-universe-v1", "kind": "PROSPECTIVE" if strict else "RETROSPECTIVE",
                **namespace, "session_date": session_date, "cutoff_ns": cutoff_ns,
                "calendar_version_id": session.version_id, "calendar_hash": calendar["payload_hash"],
                "calendar_publication_id": calendar["publication_id"],
                "calendar_capture_id": session.capture_id, "calendar_capture_hash": calendar_capture["payload_hash"],
                "open_at_ns": session.open_at_ns,
                "close_at_ns": session.close_at_ns, "metadata_capture_id": batch["id"] if batch else None,
                "metadata_hash": batch["payload_hash"] if batch else None,
                "metadata_publication_id": batch["publication_id"] if batch else None,
                "requested_listing_ids": sorted(listing_ids), "members": members, "exclusions": exclusions,
            }
            digest = hashlib.sha256(self.archive.safe_json(manifest).encode()).hexdigest()
            manifest["digest"] = digest
            run = self.archive.begin_run()
            snapshot_id = self.archive.append(
                "intraday_universe_snapshots", run, manifest, received_at_ns=now, logical_key=f"universe:{session_date}",
                fields={"cutoff_ns": cutoff_ns, "member_count": len(members)},
            )
            for member in members:
                self.archive.append(
                    "intraday_universe_members", run, member, received_at_ns=now, listing_id=member["listing_id"],
                    logical_key=f"universe:{snapshot_id}:{member['listing_id']}",
                    fields={"snapshot_id": snapshot_id, "identity_version_id": member["identity_version_id"],
                            "eligible": int(member["eligible"]), "reason_code": member["reason_code"]},
                )
            # A changing clock must never publish a purported pre-cutoff snapshot.
            if strict and self.archive.now() >= session.open_at_ns:
                raise MetadataError("SNAPSHOT_NOT_PIT")
            self.archive.finish_run(run, deadline_ns=session.open_at_ns if strict else None)
        return UniverseSnapshot(snapshot_id, digest)

    def read(self, snapshot_id, *, cutoff_ns=None):
        try:
            result = read_evidence(self.connection, "intraday_universe_snapshots", snapshot_id,
                                   self.archive.now() if cutoff_ns is None else cutoff_ns, self.archive.namespace)
        except MetadataError:
            raise MetadataError("SNAPSHOT_INPUT_MISSING") from None
        if cutoff_ns is not None:
            check_ns(cutoff_ns)
            if result["available_at_ns"] > cutoff_ns:
                raise MetadataError("SNAPSHOT_INPUT_MISSING")
        manifest = dict(result["payload"])
        digest = manifest.pop("digest", None)
        if hashlib.sha256(self.archive.safe_json(manifest).encode()).hexdigest() != digest:
            raise MetadataError("SNAPSHOT_INPUT_MISSING")
        try:
            calendar_capture = self.archive.read_capture(manifest["calendar_capture_id"], "CALENDAR", result["cutoff_ns"])
            if (calendar_capture["payload_hash"] != manifest["calendar_capture_hash"] or
                    calendar_capture["payload"]["session_ids"].get(manifest["session_date"]) != manifest["calendar_version_id"]):
                raise MetadataError("SNAPSHOT_INPUT_MISSING")
            calendar = read_evidence(self.connection, "intraday_calendar_versions", manifest["calendar_version_id"],
                                     result["cutoff_ns"], self.archive.namespace)
            if (calendar["payload_hash"] != manifest["calendar_hash"] or
                    calendar["publication_id"] != manifest["calendar_publication_id"]):
                raise MetadataError("SNAPSHOT_INPUT_MISSING")
            if manifest["metadata_capture_id"] is not None:
                metadata = self.archive.read_capture(manifest["metadata_capture_id"], "ASSETS", result["cutoff_ns"])
                if (metadata["payload_hash"] != manifest["metadata_hash"] or
                        metadata["publication_id"] != manifest["metadata_publication_id"]):
                    raise MetadataError("SNAPSHOT_INPUT_MISSING")
        except (MetadataError, KeyError):
            raise MetadataError("SNAPSHOT_INPUT_MISSING") from None
        rows = self.connection.execute(
            "SELECT * FROM intraday_universe_members WHERE snapshot_id=? ORDER BY listing_id", (snapshot_id,),
        ).fetchall()
        try:
            members = [read_evidence(self.connection, "intraday_universe_members", item["id"],
                                     result["available_at_ns"], self.archive.namespace) for item in rows]
        except MetadataError:
            raise MetadataError("SNAPSHOT_INPUT_MISSING") from None
        if len(members) != result["member_count"] or [item["payload"] for item in members] != manifest["members"]:
            raise MetadataError("SNAPSHOT_INPUT_MISSING")
        for member in members:
            try:
                identity = read_evidence(self.connection, "intraday_identity_versions", member["identity_version_id"],
                                         result["cutoff_ns"], self.archive.namespace)
                if (identity["payload_hash"] != member["payload"]["identity_hash"] or
                        identity["publication_id"] != member["payload"]["identity_publication_id"]):
                    raise MetadataError("SNAPSHOT_INPUT_MISSING")
            except MetadataError:
                raise MetadataError("SNAPSHOT_INPUT_MISSING") from None
        return {"snapshot_id": snapshot_id, "known_at_ns": result["available_at_ns"],
                "replay_grade": result["replay_grade"],
                "manifest": result["payload"], "members": manifest["members"]}
