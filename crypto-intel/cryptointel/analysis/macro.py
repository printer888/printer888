"""Economic calendar and event-risk windows.

The calendar is a user-maintained JSON file (see config/economic_calendar.example.json).
Every entry must carry an official `source_url`; entries without one are rejected,
so the system never relies on unsourced dates.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..data.freshness import humanize_age, utcnow

log = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    name: str
    time: datetime
    impact: str  # high | medium | low
    region: str
    source_url: str
    notes: str = ""

    def to_dict(self, now: datetime | None = None) -> dict:
        delta = (self.time - (now or utcnow())).total_seconds()
        return {
            "name": self.name, "time": self.time.isoformat(), "impact": self.impact, "region": self.region,
            "source_url": self.source_url, "notes": self.notes,
            "in": humanize_age(delta) if delta >= 0 else f"{humanize_age(-delta)} ago",
        }


@dataclass
class Calendar:
    events: list[CalendarEvent]
    loaded: bool
    path: str
    errors: list[str]

    def upcoming(self, days: float = 7, now: datetime | None = None) -> list[CalendarEvent]:
        now = now or utcnow()
        return sorted((e for e in self.events if now <= e.time <= now + timedelta(days=days)), key=lambda e: e.time)

    def event_risk(self, hours_ahead: float = 24, hours_after: float = 2, now: datetime | None = None) -> dict:
        """High-impact events within the risk window around now."""
        now = now or utcnow()
        hits = [e for e in self.events if e.impact == "high"
                and now - timedelta(hours=hours_after) <= e.time <= now + timedelta(hours=hours_ahead)]
        return {"available": self.loaded, "high_impact_events": [e.to_dict(now) for e in hits]}


def load_calendar(path: str) -> Calendar:
    p = Path(path)
    if not p.exists():
        return Calendar([], False, path, [f"calendar file not found: {path}"])
    errors, events = [], []
    try:
        raw = json.loads(p.read_text())
    except ValueError as e:
        return Calendar([], False, path, [f"invalid JSON: {e}"])
    for i, r in enumerate(raw.get("events", [])):
        if not r.get("source_url"):
            errors.append(f"event #{i} '{r.get('name')}' rejected: missing source_url")
            continue
        try:
            t = datetime.fromisoformat(r["time"].replace("Z", "+00:00"))
            if t.tzinfo is None:
                errors.append(f"event #{i} '{r.get('name')}' rejected: time must include timezone")
                continue
            events.append(CalendarEvent(r["name"], t, r.get("impact", "medium"), r.get("region", ""),
                                        r["source_url"], r.get("notes", "")))
        except (KeyError, ValueError) as e:
            errors.append(f"event #{i} rejected: {e}")
    for e in errors:
        log.warning("calendar: %s", e)
    return Calendar(events, True, path, errors)
