"""Confirmed, versioned broker identity. Historical reads avoid mutable canonical projections."""
from __future__ import annotations

import hashlib
import hmac

from pydantic import ValidationError

from backend.app.data_providers.alpaca_metadata import (
    AlpacaMetadataService,
    MetadataError,
    check_ns,
    decode_published,
    published_select,
    scope,
)
from backend.app.models import AlpacaIdentityApplyOut, AlpacaIdentityPreviewIn, AlpacaIdentityPreviewOut

_EXCHANGE_MIC = {
    "NASDAQ": "XNAS", "NYSE": "XNYS", "AMEX": "XASE", "ARCA": "ARCX", "NYSEARCA": "ARCX", "BATS": "BATS",
}


def _versions(connection, cutoff_ns, namespace, listing_id=None):
    check_ns(cutoff_ns)
    sql = published_select("intraday_identity_versions") + """
        WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
          AND raw.available_at_ns<=? AND pub.available_at_ns<=?"""
    params = (*namespace, cutoff_ns, cutoff_ns)
    if listing_id is not None:
        sql += " AND raw.listing_id=?"
        params += (listing_id,)
    rows = connection.execute(sql + " ORDER BY pub.available_at_ns DESC,raw.available_at_ns DESC,raw.id DESC", params)
    # Corrections of the same economic transition replace its state before interval filtering.
    current = {}
    for row in rows:
        key = (row["listing_id"], row["valid_from_ns"])
        current.setdefault(key, decode_published(row, "intraday_identity_versions", cutoff_ns))
    return list(current.values())


def _at(versions, effective_at_ns):
    check_ns(effective_at_ns)
    candidates = [row for row in versions if row["valid_from_ns"] is not None and
                  row["valid_from_ns"] <= effective_at_ns]
    if not candidates:
        return None
    row = max(candidates, key=lambda item: (item["valid_from_ns"], item["available_at_ns"], item["id"]))
    if not row["confirmed"] or (row["valid_to_ns"] is not None and effective_at_ns >= row["valid_to_ns"]):
        return None
    return row


def read_identity_as_of(connection, listing_id, effective_at_ns, cutoff_ns, *, profile_id, data_mode="REAL",
                        provenance="CAPTURED", replay_grade="STRICT_PIT"):
    namespace = scope(profile_id, data_mode, provenance, replay_grade)
    versions = _versions(connection, cutoff_ns, namespace)
    row = _at([item for item in versions if item["listing_id"] == listing_id], effective_at_ns)
    if row is None:
        return None
    for other in {item["listing_id"] for item in versions} - {listing_id}:
        candidate = _at([item for item in versions if item["listing_id"] == other], effective_at_ns)
        if candidate is not None and (
            candidate["broker_asset_id"] == row["broker_asset_id"] or
            (candidate["ticker"], _EXCHANGE_MIC.get(candidate["venue"], candidate["venue"])) ==
            (row["ticker"], _EXCHANGE_MIC.get(row["venue"], row["venue"]))
        ):
            return None
    return row


class IdentityService:
    def __init__(self, archive: AlpacaMetadataService):
        self.archive = archive
        self.connection = archive.connection

    def _request(self, listing_id, request):
        # No caller-supplied text is hashed or persisted before the credential echo guard.
        values = request.model_dump(exclude={"confirmation_token"})
        self.archive.safe_json(values)
        try:
            request = AlpacaIdentityPreviewIn.model_validate(values)
        except ValidationError:
            raise MetadataError("IDENTITY_UNVERIFIED") from None
        if type(listing_id) is not int or listing_id <= 0:
            raise MetadataError("IDENTITY_UNVERIFIED")
        from backend.app.services.instrument_service import InstrumentService
        listing = InstrumentService.resolved_listing(self.connection, listing_id)
        if (listing is None or listing["listing_status"] != "ACTIVE" or
                InstrumentService.has_ambiguous_identity(self.connection, listing["instrument_id"])):
            raise MetadataError("IDENTITY_UNVERIFIED")
        capture = self.archive.read_capture(request.metadata_capture_id, "ASSETS")
        assets = [item for item in capture["assets"] if item["id"] == request.broker_asset_id]
        if len(assets) != 1:
            raise MetadataError("IDENTITY_UNVERIFIED")
        asset = assets[0]
        if (asset["class"] != "us_equity" or _EXCHANGE_MIC.get(asset["exchange"]) != listing["mic"] or
                asset["symbol"] != listing["ticker"] or listing["currency"] != "USD" or
                listing["timezone"] != "America/New_York" or listing["verified_instrument_type"] not in {"STOCK", "ETF"} or
                not request.capabilities or len(set(request.capabilities)) != len(request.capabilities)):
            raise MetadataError("IDENTITY_UNVERIFIED")
        valid_from = request.valid_from_ns
        if request.validity_source == "CURRENT_ASSETS":
            if valid_from is not None and valid_from != capture["received_at_ns"]:
                raise MetadataError("IDENTITY_UNVERIFIED")
            valid_from = capture["received_at_ns"]
        elif valid_from is None:
            raise MetadataError("IDENTITY_UNVERIFIED")
        check_ns(valid_from)
        if request.valid_to_ns is not None:
            check_ns(request.valid_to_ns)
            if request.valid_to_ns <= valid_from:
                raise MetadataError("IDENTITY_UNVERIFIED")
        values["capabilities"] = sorted(values["capabilities"])
        frozen = {"request": values, "asset": asset, "metadata_hash": capture["payload_hash"],
                  "instrument_id": listing["instrument_id"], "listing_id": listing_id, "mic": listing["mic"],
                  "currency": listing["currency"], "timezone": listing["timezone"],
                  "instrument_type": listing["verified_instrument_type"],
                  "leveraged": request.leveraged, "inverse": request.inverse, "capabilities": values["capabilities"],
                  "validity_basis": request.validity_source}
        return listing, asset, capture, valid_from, frozen

    def _current(self, listing_id, valid_from):
        rows = _versions(self.connection, self.archive.now(), self.archive.namespace, listing_id)
        return next((row for row in rows if row["valid_from_ns"] == valid_from), None)

    def _check_collisions(self, listing_id, asset, valid_from, valid_to):
        versions = _versions(self.connection, self.archive.now(), self.archive.namespace)
        for row in versions:
            if row["listing_id"] == listing_id:
                if row["broker_asset_id"] != asset["id"]:
                    raise MetadataError("IDENTITY_AMBIGUOUS")
                continue
            if row["broker_asset_id"] == asset["id"]:
                raise MetadataError("IDENTITY_AMBIGUOUS")
            if not row["confirmed"] or row["valid_from_ns"] is None:
                continue
            if (row["ticker"], _EXCHANGE_MIC.get(row["venue"], row["venue"])) != (
                asset["symbol"], _EXCHANGE_MIC.get(asset["exchange"], asset["exchange"]),
            ):
                continue
            # Later economic transitions implicitly end earlier ones on the same listing.
            transitions = [item["valid_from_ns"] for item in versions if item["listing_id"] == row["listing_id"]
                           and item["valid_from_ns"] is not None and item["valid_from_ns"] > row["valid_from_ns"]]
            row_end = min([row["valid_to_ns"] or MAX_VALIDITY, *transitions])
            if max(valid_from, row["valid_from_ns"]) < min(valid_to or MAX_VALIDITY, row_end):
                raise MetadataError("IDENTITY_AMBIGUOUS")

    def _token(self, frozen, current):
        return hashlib.sha256(self.archive.safe_json(
            {"mapping": frozen, "current_version_id": current["id"] if current else None},
        ).encode()).hexdigest()

    def preview(self, listing_id, request):
        _, asset, _, valid_from, frozen = self._request(listing_id, request)
        self._check_collisions(listing_id, asset, valid_from, request.valid_to_ns)
        current = self._current(listing_id, valid_from)
        return AlpacaIdentityPreviewOut(
            listing_id=listing_id, broker_asset_id=asset["id"], ticker=asset["symbol"], venue=asset["exchange"],
            current_version_id=current["id"] if current else None, confirmation_token=self._token(frozen, current),
        )

    def apply(self, listing_id, request):
        with self.archive.transaction():
            listing, asset, capture, valid_from, frozen = self._request(listing_id, request)
            current = self._current(listing_id, valid_from)
            if current is not None and current["payload"] == frozen:
                return AlpacaIdentityApplyOut(listing_id=listing_id, identity_version_id=current["id"], status="CONFIRMED")
            self._check_collisions(listing_id, asset, valid_from, request.valid_to_ns)
            if not hmac.compare_digest(request.confirmation_token, self._token(frozen, current)):
                raise MetadataError("MAPPING_CHANGED")
            run = self.archive.begin_run()
            result = self.archive.append(
                "intraday_identity_versions", run, frozen, received_at_ns=capture["received_at_ns"],
                event_time_ns=capture["received_at_ns"], listing_id=listing_id,
                logical_key=f"alpaca-identity:{listing_id}:{valid_from}",
                fields={"instrument_id": listing["instrument_id"], "broker_asset_id": asset["id"],
                        "ticker": asset["symbol"], "venue": asset["exchange"], "valid_from_ns": valid_from,
                        "valid_to_ns": request.valid_to_ns, "confirmed": 1, "supersedes_id": current["id"] if current else None},
            )
            self.archive.finish_run(run)
        return AlpacaIdentityApplyOut(listing_id=listing_id, identity_version_id=result, status="CONFIRMED")


MAX_VALIDITY = 2**63
