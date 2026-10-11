"""Local snapshots of official schedules; original text and manual row evidence frozen.

Sources: BLS /schedule/, Fed FOMC/monthly calendars, externally attested issuer
domains. A URL/hash makes a copy auditable, not proof of remote authenticity or
complete coverage. No fetch, consensus, surprise or inferred release time.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from backend.app.data_providers.alpaca_events import DIGEST, EventError, day_bounds
from backend.app.data_providers.alpaca_market import _ns
from backend.app.intraday.contracts import canonical_json


@dataclass(frozen=True)
class IssuerAuthority:
    listing_id: int
    hostname: str
    evidence_hash: str

    def __post_init__(self):
        if (type(self.listing_id) is not int or self.listing_id <= 0 or type(self.hostname) is not str or
                re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', self.hostname) is None or
                type(self.evidence_hash) is not str or not DIGEST.fullmatch(self.evidence_hash)):
            raise EventError('EVENT_CALENDAR_INVALID')


def _scheduled(day, clock):
    if clock is None:
        return None
    if type(clock) is not str or re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock) is None:
        raise ValueError
    local = datetime.fromisoformat(f'{day}T{clock}:00')
    zone = ZoneInfo('America/New_York')
    possibilities = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == local:
            possibilities.add(candidate)
    if len(possibilities) != 1:
        raise ValueError  # Nonexistent or ambiguous civil time cannot be guessed.
    return _ns(possibilities.pop().isoformat())


def _time_evidence(evidence, clock, day, source):
    hour, minute = map(int, clock.split(':'))
    pattern = r'(?<![0-9:])([0-9]{1,2}):([0-9]{2})\s*(a\.?m\.?|p\.?m\.?)?\s*(EST|EDT|ET|PST|PDT|PT|CST|CDT|CT|UTC|GMT)?(?![A-Za-z0-9:])'
    expected_zone = datetime.fromisoformat(f'{day}T{clock}').replace(tzinfo=ZoneInfo('America/New_York')).tzname()
    for match in re.finditer(pattern, evidence, re.I):
        hh, mm, meridian, zone = match.groups()
        hh, mm = int(hh), int(mm)
        if meridian:
            if not 1 <= hh <= 12:
                continue
            hh = hh % 12 + (12 if meridian.lower().startswith('p') else 0)
        if (hh, mm) != (hour, minute):
            continue
        if zone and zone.upper() not in {'ET', expected_zone}:
            continue
        if source == 'ISSUER_OFFICIAL' and zone is None:
            continue
        return True
    return False


def decode_calendar(document, *, issuer_authority=None):
    try:
        canonical_json(document)
        source, original, url = document['source'], document['original_text'], document['source_url']
        if type(original) is not str or not original or len(original.encode()) > 262144:
            raise ValueError
        if hashlib.sha256(original.encode()).hexdigest() != document['original_sha256']:
            raise ValueError
        if type(url) is not str or len(url) > 2048 or any(ord(c) < 32 for c in url):
            raise ValueError
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or
                parsed.query or parsed.fragment or parsed.port is not None):
            raise ValueError
        if source == 'BLS':
            if parsed.hostname != 'www.bls.gov' or not parsed.path.startswith('/schedule/'):
                raise ValueError
            provider = 'bls'
        elif source == 'FED':
            if parsed.hostname != 'www.federalreserve.gov' or not (
                    parsed.path == '/monetarypolicy/fomccalendars.htm' or
                    re.fullmatch(r'/newsevents/\d{4}-[a-z]+\.htm', parsed.path)):
                raise ValueError
            provider = 'fed'
        elif source == 'ISSUER_OFFICIAL':
            if not isinstance(issuer_authority, IssuerAuthority) or parsed.hostname != issuer_authority.hostname:
                raise ValueError
            provider = 'issuer'
        else:
            raise ValueError
        rows = document['rows']
        if type(rows) is not list or not rows or len(rows) > 500:
            raise ValueError
        result, seen = [], set()
        for row in rows:
            if type(row) is not dict:
                raise ValueError
            local_id, name, day, clock = (row[k] for k in ('event_id', 'name', 'event_date', 'local_time'))
            evidence, cancelled = row['source_row_text'], row.get('cancelled', False)
            if (type(local_id) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', local_id) is None or
                    local_id in seen or type(name) is not str or not 1 <= len(name) <= 256 or
                    type(evidence) is not str or not evidence or len(evidence) > 8192 or evidence not in original or
                    name.casefold() not in evidence.casefold() or type(cancelled) is not bool or
                    row.get('timezone') != 'America/New_York'):
                raise ValueError
            start, end = day_bounds(day)
            parsed_day = date.fromisoformat(day)
            date_forms = {day, parsed_day.strftime('%B %d, %Y'),
                          f'{parsed_day.strftime("%B")} {parsed_day.day}, {parsed_day.year}'}
            if not any(form in evidence for form in date_forms):
                raise ValueError  # Row projection must quote an explicit date; no guessed year.
            scheduled = _scheduled(day, clock)
            if clock is not None:
                if not _time_evidence(evidence, clock, day, source):
                    raise ValueError
                if source == 'ISSUER_OFFICIAL' and re.search(r'conference|webcast|call', evidence, re.I):
                    raise ValueError  # Conference time alone never proves the earnings publication time.
            if cancelled and re.search(r'\bcancel(?:led|ed)\b', evidence, re.I) is None:
                raise ValueError
            listing, event_type = row.get('listing_id'), row['event_type']
            if source == 'ISSUER_OFFICIAL':
                if event_type != 'EARNINGS' or type(listing) is not int or listing != issuer_authority.listing_id:
                    raise ValueError
            elif event_type != 'MACRO' or listing is not None:
                raise ValueError
            seen.add(local_id)
            result.append({'version': 'official-event-calendar-v1', 'source': provider, 'event_type': event_type,
                'local_event_id': local_id, 'source_event_id': None, 'source_revision_id': None, 'name': name,
                'listing_id': listing, 'event_date': day, 'scheduled_at_ns': scheduled, 'effective_at_ns': None,
                'day_start_ns': start, 'day_end_ns': end, 'timezone': 'America/New_York',
                'time_uncertainty': 'EXACT' if scheduled is not None else 'WHOLE_SESSION', 'cancelled': cancelled,
                'source_url': url, 'source_row_text': evidence, 'original_sha256': document['original_sha256'],
                'issuer_authority': asdict(issuer_authority) if source == 'ISSUER_OFFICIAL' else None,
                'coverage': 'ANNOUNCED_EVENTS_ONLY', 'authenticity_basis': 'LOCAL_OFFICIAL_COPY',
                'consensus': None, 'surprise': None})
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        raise EventError('EVENT_CALENDAR_INVALID') from None
