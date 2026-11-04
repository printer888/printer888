"""Persistence helpers. All writes go through here."""
from __future__ import annotations

import json
import math
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, desc, select
from sqlalchemy.orm import Session, sessionmaker

from ..data.freshness import utcnow
from .models import (AlertRow, BacktestRun, Base, Candle, MarketSnapshot, NewsEventRow, OpportunityRow,
                     PaperAccount, PaperTradeRow)


def _clean(obj):
    """Make payloads JSON-safe (NaN/inf → None, timestamps → ISO)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (datetime, pd.Timestamp)):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy scalars
        return _clean(obj.item())
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    return json.loads(json.dumps(obj, default=str))


class Repository:
    def __init__(self, database_url: str):
        kw = {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {"pool_pre_ping": True}
        self.engine = create_engine(database_url, future=True, **kw)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self.Session()

    # ---------------------------------------------------------------- candles
    def save_candles(self, symbol: str, timeframe: str, df: pd.DataFrame, category: str = "linear") -> int:
        if df.empty:
            return 0
        with self.session() as s:
            existing = set(s.scalars(select(Candle.ts).where(
                Candle.symbol == symbol, Candle.timeframe == timeframe, Candle.category == category,
                Candle.ts >= df.index[0].to_pydatetime())).all())
            existing = {pd.Timestamp(t).tz_localize("UTC") if pd.Timestamp(t).tzinfo is None else pd.Timestamp(t)
                        for t in existing}
            rows = [Candle(symbol=symbol, category=category, timeframe=timeframe, ts=ts.to_pydatetime(),
                           open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume, turnover=r.turnover)
                    for ts, r in df.iterrows() if ts not in existing]
            s.add_all(rows)
            s.commit()
            return len(rows)

    def load_candles(self, symbol: str, timeframe: str, category: str = "linear") -> pd.DataFrame:
        with self.session() as s:
            rows = s.scalars(select(Candle).where(Candle.symbol == symbol, Candle.timeframe == timeframe,
                                                  Candle.category == category).order_by(Candle.ts)).all()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "turnover"])
        df = pd.DataFrame([{"ts": r.ts, "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                            "volume": r.volume, "turnover": r.turnover} for r in rows]).set_index("ts")
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    # ---------------------------------------------------------------- analysis
    def save_snapshot(self, symbol: str, ticker: dict, data: dict) -> None:
        with self.session() as s:
            s.add(MarketSnapshot(ts=utcnow(), symbol=symbol, price=_clean(ticker.get("last_price")),
                                 funding_rate=_clean(ticker.get("funding_rate")),
                                 open_interest_value=_clean(ticker.get("open_interest_value")),
                                 turnover_24h=_clean(ticker.get("turnover_24h")),
                                 spread_bps=_clean(ticker.get("spread_bps")), data=_clean(data)))
            s.commit()

    def save_opportunity(self, opp: dict) -> int:
        with self.session() as s:
            row = OpportunityRow(created_at=utcnow(), symbol=opp["symbol"], status=opp["status"],
                                 direction=opp.get("direction"), score=opp["score"], timeframe=opp["timeframe"],
                                 price=_clean(opp.get("price")), entry=_clean(opp.get("entry")),
                                 stop=_clean(opp.get("stop")), rr_net=_clean(opp.get("rr_net_blended")),
                                 payload=_clean(opp))
            s.add(row)
            s.commit()
            return row.id

    def recent_opportunities(self, limit: int = 100, status: str | None = None) -> list[dict]:
        with self.session() as s:
            q = select(OpportunityRow).order_by(desc(OpportunityRow.created_at)).limit(limit)
            if status:
                q = q.where(OpportunityRow.status == status)
            return [dict(r.payload, id=r.id) for r in s.scalars(q).all()]

    def save_news(self, events: list[dict]) -> int:
        n = 0
        with self.session() as s:
            known = set(s.scalars(select(NewsEventRow.uid).where(NewsEventRow.uid.in_([e["uid"] for e in events]))).all())
            for e in events:
                if e["uid"] in known:
                    continue
                s.add(NewsEventRow(uid=e["uid"], title=e["title"], url=e["url"], source=e["source"],
                                   published_at=datetime.fromisoformat(e["published_at"]) if e.get("published_at") else None,
                                   fetched_at=datetime.fromisoformat(e["fetched_at"]), importance=e["importance"],
                                   confirmation=e["confirmation"], sentiment=e["sentiment"], payload=_clean(e)))
                n += 1
            s.commit()
        return n

    def recent_news(self, limit: int = 100) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(select(NewsEventRow).order_by(desc(NewsEventRow.published_at)).limit(limit)).all()
            return [r.payload for r in rows]

    # ---------------------------------------------------------------- paper
    def upsert_paper_trade(self, t: dict) -> None:
        with self.session() as s:
            row = s.get(PaperTradeRow, t["id"])
            if row is None:
                row = PaperTradeRow(id=t["id"])
                s.add(row)
            row.symbol, row.side, row.status = t["symbol"], t["side"], t["status"]
            row.leverage, row.entry_price, row.entry_time = t["leverage"], t["entry_price"], t["entry_time"]
            row.realized_pnl, row.exit_reason, row.closed_at = t["realized_pnl"], t.get("exit_reason"), t.get("closed_at")
            row.payload = _clean(t)
            s.commit()

    def paper_trades(self, status: str | None = None) -> list[dict]:
        with self.session() as s:
            q = select(PaperTradeRow).order_by(desc(PaperTradeRow.id))
            if status:
                q = q.where(PaperTradeRow.status == status)
            return [r.payload for r in s.scalars(q).all()]

    def save_paper_account(self, balance: float, starting: float) -> None:
        with self.session() as s:
            row = s.get(PaperAccount, 1) or PaperAccount(id=1, starting_equity=starting)
            row.balance, row.updated_at = balance, utcnow()
            s.merge(row)
            s.commit()

    def paper_account(self) -> dict | None:
        with self.session() as s:
            row = s.get(PaperAccount, 1)
            return {"balance": row.balance, "starting_equity": row.starting_equity} if row else None

    # ---------------------------------------------------------------- backtests & alerts
    def save_backtest(self, kind: str, strategy: str, symbol: str, timeframe: str, params: dict, result: dict) -> int:
        with self.session() as s:
            row = BacktestRun(created_at=utcnow(), kind=kind, strategy=strategy, symbol=symbol, timeframe=timeframe,
                              params=_clean(params), result=_clean(result))
            s.add(row)
            s.commit()
            return row.id

    def backtests(self, limit: int = 50) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)).all()
            return [{"id": r.id, "created_at": r.created_at.isoformat(), "kind": r.kind, "strategy": r.strategy,
                     "symbol": r.symbol, "timeframe": r.timeframe, "params": r.params, "result": r.result} for r in rows]

    def save_alert(self, alert: dict, sent: bool) -> None:
        with self.session() as s:
            s.add(AlertRow(created_at=utcnow(), type=alert["type"], symbol=alert.get("symbol"), title=alert["title"],
                           sent=sent, payload=_clean(alert)))
            s.commit()

    def alerts(self, limit: int = 100) -> list[dict]:
        with self.session() as s:
            rows = s.scalars(select(AlertRow).order_by(desc(AlertRow.created_at)).limit(limit)).all()
            return [dict(r.payload, sent=r.sent) for r in rows]
