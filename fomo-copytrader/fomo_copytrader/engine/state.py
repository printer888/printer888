"""Runtime state persisted in the DB so restarts resume safely."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..models import KV, AuditLog
from ..schemas import RiskLimits

log = logging.getLogger(__name__)

DEFAULT_STATUS: dict[str, Any] = {
    "monitoring": False,        # watching the trader (read-only)
    "copying": False,           # mirroring trades
    "paused": False,            # no new entries; exits still mirrored
    "emergency_stop": False,    # nothing new; set by operator or safety trip
    "live_armed": False,        # runtime arming of the live executor
    "consecutive_failures": 0,
    "equity_peak_usd": 0.0,
    "inactive_alert_sent": False,
    "last_daily_report": None,
    "suspended_reason": None,
}


class StateStore:
    def __init__(self, sm: async_sessionmaker):
        self.sm = sm
        self._status: dict[str, Any] | None = None
        self._limits: RiskLimits | None = None

    async def _get(self, key: str) -> dict | None:
        async with self.sm() as s:
            row = await s.get(KV, key)
            return row.value if row else None

    async def _set(self, key: str, value: dict) -> None:
        async with self.sm() as s:
            row = await s.get(KV, key)
            if row:
                row.value = value
            else:
                s.add(KV(key=key, value=value))
            await s.commit()

    async def status(self) -> dict[str, Any]:
        if self._status is None:
            self._status = {**DEFAULT_STATUS, **(await self._get("status") or {})}
        return dict(self._status)

    async def update_status(self, **kw: Any) -> dict[str, Any]:
        st = await self.status()
        st.update(kw)
        self._status = st
        await self._set("status", st)
        return dict(st)

    async def limits(self) -> RiskLimits:
        if self._limits is None:
            raw = await self._get("risk_limits")
            self._limits = RiskLimits(**raw) if raw else RiskLimits()
        return self._limits

    async def set_limits(self, limits: RiskLimits) -> None:
        self._limits = limits
        await self._set("risk_limits", limits.model_dump())

    async def audit(self, category: str, message: str, data: dict | None = None, level: str = "INFO") -> None:
        getattr(log, level.lower(), log.info)("[%s] %s", category, message)
        async with self.sm() as s:
            s.add(AuditLog(category=category, message=message, data=data, level=level))
            await s.commit()

    @property
    def cached_live_armed(self) -> bool:
        return bool(self._status and self._status.get("live_armed") and not self._status.get("emergency_stop"))

    async def recent_audit(self, limit: int = 100) -> list[AuditLog]:
        async with self.sm() as s:
            return list((await s.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars())
