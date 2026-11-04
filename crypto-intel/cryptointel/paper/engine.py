"""Paper-trading engine driven by live public prices. NEVER sends real orders.

Fill model:
  • Entries: market at current price + slippage, taker fee.
  • Stops: market (taker fee + slippage); gaps fill at the worse observed price.
  • Take-profits: resting limits (maker fee), partial exits by `tp_fractions`.
  • If a stop and a target fall inside the same bar, the stop is assumed first.
  • After TP1 the stop moves to break-even (configurable).
  • Funding is charged/credited at each funding timestamp while open.
  • If price reaches the estimated liquidation price before the stop, the isolated
    margin is lost (should be prevented by the planner, but simulated anyway).
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..backtest.metrics import max_drawdown, performance
from ..data.freshness import utcnow
from ..risk.leverage import CostModel, liquidation_price

log = logging.getLogger(__name__)
_ids = itertools.count(1)


@dataclass
class PaperTrade:
    id: int
    symbol: str
    side: str
    leverage: float
    qty: float
    qty_open: float
    entry_price: float
    entry_time: str
    stop: float
    initial_stop: float
    take_profits: list[float]
    tp_fractions: list[float]
    tp_hit: list[bool]
    liq_price: float
    margin: float
    risk_usd: float
    score: float | None = None
    opportunity_id: int | None = None
    status: str = "open"
    fees: float = 0.0
    funding: float = 0.0
    realized_pnl: float = 0.0
    exits: list[dict] = field(default_factory=list)
    exit_reason: str | None = None
    closed_at: str | None = None
    last_price: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def d(self) -> int:
        return 1 if self.side == "long" else -1

    def unrealized(self, price: float) -> float:
        return self.d * (price - self.entry_price) * self.qty_open

    @property
    def r_multiple(self) -> float | None:
        return self.realized_pnl / self.risk_usd if self.risk_usd else None

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["r_multiple"] = self.r_multiple
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PaperTrade":
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**d)


class PaperBroker:
    def __init__(self, starting_equity: float, costs: CostModel, max_open: int = 5,
                 tp_fractions: tuple[float, ...] = (0.5, 0.5), move_stop_to_breakeven: bool = True):
        self.starting_equity = starting_equity
        self.balance = starting_equity  # realised cash balance
        self.costs = costs
        self.max_open = max_open
        self.tp_fractions = list(tp_fractions)
        self.move_be = move_stop_to_breakeven
        self.trades: dict[int, PaperTrade] = {}
        self.equity_history: list[tuple[str, float]] = [(utcnow().isoformat(), starting_equity)]
        self.marks: dict[str, float] = {}

    # ------------------------------------------------------------ state
    def open_trades(self) -> list[PaperTrade]:
        return [t for t in self.trades.values() if t.status == "open"]

    def closed_trades(self) -> list[PaperTrade]:
        return [t for t in self.trades.values() if t.status == "closed"]

    def equity(self) -> float:
        return self.balance + sum(t.unrealized(self.marks.get(t.symbol, t.entry_price)) - t.funding
                                  for t in self.open_trades())

    def load(self, trades: list[dict], balance: float | None = None) -> None:
        global _ids
        for d in trades:
            t = PaperTrade.from_dict(d)
            self.trades[t.id] = t
        if balance is not None:
            self.balance = balance
        if self.trades:
            _ids = itertools.count(max(self.trades) + 1)

    # ------------------------------------------------------------ actions
    def open(self, *, symbol: str, side: str, price: float, stop: float, take_profits: list[float],
             leverage: float, risk_pct: float, ts: datetime | None = None, score: float | None = None,
             opportunity_id: int | None = None) -> PaperTrade | None:
        if any(t.symbol == symbol for t in self.open_trades()):
            log.info("paper: %s already has an open trade; skipping", symbol)
            return None
        if len(self.open_trades()) >= self.max_open:
            log.info("paper: max open trades reached; skipping %s", symbol)
            return None
        d = 1 if side == "long" else -1
        fill = price * (1 + d * self.costs.slippage_bps / 1e4)
        if d * (fill - stop) <= 0 or any(d * (tp - fill) <= 0 for tp in take_profits):
            log.info("paper: price %s moved beyond plan levels for %s; skipping", price, symbol)
            return None
        stop_fill = stop * (1 - d * self.costs.slippage_bps / 1e4)
        per_unit = d * (fill - stop_fill) + (fill + stop_fill) * self.costs.taker_fee
        eq = self.equity()
        qty = eq * risk_pct / per_unit
        qty = min(qty, eq * leverage / fill)
        fee = qty * fill * self.costs.taker_fee
        self.balance -= fee
        fr = self.tp_fractions[: len(take_profits)]
        fr = [f / sum(fr) for f in fr]
        t = PaperTrade(
            id=next(_ids), symbol=symbol, side=side, leverage=leverage, qty=qty, qty_open=qty, entry_price=fill,
            entry_time=(ts or utcnow()).isoformat(), stop=stop, initial_stop=stop, take_profits=list(take_profits),
            tp_fractions=fr, tp_hit=[False] * len(take_profits),
            liq_price=liquidation_price(fill, side, leverage, self.costs.mmr, self.costs.taker_fee),
            margin=qty * fill / leverage, risk_usd=qty * per_unit, score=score, opportunity_id=opportunity_id,
            fees=fee, last_price=price,
        )
        self.trades[t.id] = t
        self.marks[symbol] = price
        self._record()
        return t

    def _exit(self, t: PaperTrade, qty: float, price: float, fee_rate: float, reason: str, ts: str) -> dict:
        gross = t.d * (price - t.entry_price) * qty
        fee = qty * price * fee_rate
        self.balance += gross - fee
        t.fees += fee
        t.qty_open -= qty
        t.realized_pnl += gross - fee
        ev = {"time": ts, "price": price, "qty": qty, "reason": reason, "pnl": gross - fee, "fee": fee}
        t.exits.append(ev)
        if t.qty_open <= t.qty * 1e-9:
            t.qty_open = 0.0
            t.status = "closed"
            t.exit_reason = reason
            t.closed_at = ts
            # entry fee and funding belong to the round trip
            t.realized_pnl -= t.fees - sum(e["fee"] for e in t.exits)
            t.realized_pnl -= t.funding
            self.balance -= t.funding
        return {"trade_id": t.id, "symbol": t.symbol, "side": t.side, **ev,
                "closed": t.status == "closed", "realized_pnl": t.realized_pnl, "r_multiple": t.r_multiple}

    def on_bar(self, symbol: str, o: float, h: float, l: float, c: float, ts: datetime | None = None) -> list[dict]:
        """Process a price bar (or a tick with o=h=l=c). Returns exit events."""
        ts_s = (ts or utcnow()).isoformat()
        events = []
        slip = self.costs.slippage_bps / 1e4
        self.marks[symbol] = c
        for t in [x for x in self.open_trades() if x.symbol == symbol]:
            t.last_price = c
            d = t.d
            # liquidation (estimated) — only if it lies before the stop
            liq_first = (t.liq_price >= t.stop) if d > 0 else (t.liq_price <= t.stop)
            if liq_first and ((l <= t.liq_price) if d > 0 else (h >= t.liq_price)):
                loss_px = t.liq_price
                events.append(self._exit(t, t.qty_open, loss_px, self.costs.taker_fee, "LIQUIDATION (est.)", ts_s))
                continue
            hit_stop = (l <= t.stop) if d > 0 else (h >= t.stop)
            if hit_stop:
                gap = (o <= t.stop) if d > 0 else (o >= t.stop)
                px = (o if gap else t.stop) * (1 - d * slip)
                reason = "breakeven stop" if t.stop != t.initial_stop else ("stop (gap)" if gap else "stop")
                events.append(self._exit(t, t.qty_open, px, self.costs.taker_fee, reason, ts_s))
                continue
            for k, tp in enumerate(t.take_profits):
                if t.tp_hit[k] or t.status != "open":
                    continue
                if (h >= tp) if d > 0 else (l <= tp):
                    t.tp_hit[k] = True
                    last = all(t.tp_hit)
                    q = t.qty_open if last else min(t.qty * t.tp_fractions[k], t.qty_open)
                    events.append(self._exit(t, q, tp, self.costs.maker_fee, f"TP{k + 1}", ts_s))
                    if k == 0 and self.move_be and t.status == "open":
                        t.stop = t.entry_price
                        t.notes.append(f"stop moved to break-even {t.entry_price:.6g} after TP1")
                else:
                    break
        if events:
            self._record()
        return events

    def apply_funding(self, symbol: str, rate: float, funding_ts: datetime) -> None:
        for t in self.open_trades():
            if t.symbol == symbol and funding_ts.isoformat() > t.entry_time:
                mark = self.marks.get(symbol, t.entry_price)
                t.funding += t.d * t.qty_open * mark * rate

    def close_all(self, reason: str = "manual close") -> list[dict]:
        out = []
        for t in self.open_trades():
            px = self.marks.get(t.symbol, t.entry_price) * (1 - t.d * self.costs.slippage_bps / 1e4)
            out.append(self._exit(t, t.qty_open, px, self.costs.taker_fee, reason, utcnow().isoformat()))
        self._record()
        return out

    def _record(self) -> None:
        self.equity_history.append((utcnow().isoformat(), self.equity()))
        self.equity_history = self.equity_history[-5000:]

    # ------------------------------------------------------------ reporting
    def performance(self) -> dict:
        import pandas as pd

        closed = self.closed_trades()
        trades = [{"pnl": t.realized_pnl, "r_multiple": t.r_multiple, "fees": t.fees, "funding": t.funding,
                   "bars_held": 0} for t in closed]
        eq = pd.Series([v for _, v in self.equity_history],
                       index=pd.to_datetime([k for k, _ in self.equity_history], utc=True, format="ISO8601"))
        eq = eq[~eq.index.duplicated(keep="last")]
        perf = performance(eq, trades, periods_per_year=365) if len(eq) > 1 else {"n_trades": len(trades)}
        perf.pop("sharpe", None)  # event-sampled equity → Sharpe/Sortino would be misleading
        perf.pop("sortino", None)
        perf["equity"] = self.equity()
        perf["balance"] = self.balance
        perf["open_trades"] = len(self.open_trades())
        perf["current_drawdown_pct"] = float((eq.iloc[-1] / eq.cummax().iloc[-1] - 1) * 100) if len(eq) else 0.0
        perf["max_drawdown_pct"] = max_drawdown(eq)
        perf["note"] = "Simulated with live public prices; fills, fees and funding are modelled, not real."
        return perf
