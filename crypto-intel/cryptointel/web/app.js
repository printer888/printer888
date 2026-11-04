/* CryptoIntel dashboard — React 18 (UMD) + htm, TradingView Lightweight Charts. No build step. */
const { useState, useEffect, useRef, useCallback } = React;
const html = htm.bind(React.createElement);

const api = async (path, opts) => {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${r.status}`);
  return body;
};
const fmt = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x)) ? "—" :
  Math.abs(x) >= 1000 ? x.toLocaleString(undefined, { maximumFractionDigits: d }) :
  Math.abs(x) >= 1 ? x.toFixed(d) : x.toPrecision(4);
const fmtUsd = (x) => x == null ? "—" : "$" + (Math.abs(x) >= 1e9 ? (x / 1e9).toFixed(2) + "B" :
  Math.abs(x) >= 1e6 ? (x / 1e6).toFixed(1) + "M" : Math.round(x).toLocaleString());
const pct = (x, d = 2) => x == null ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(d)}%`;
const cls = (x) => x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "";

function usePoll(fn, ms, deps = []) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => fn().then((d) => { setData(d); setErr(null); }).catch((e) => setErr(e.message)), deps);
  useEffect(() => { load(); if (!ms) return; const t = setInterval(load, ms); return () => clearInterval(t); }, [load]);
  return [data, err, load];
}

function Kpi({ label, value, sub, className }) {
  return html`<div class="card kpi"><div class="label">${label}</div>
    <div class=${"value " + (className || "")}>${value}</div>${sub && html`<div class="small muted">${sub}</div>`}</div>`;
}

/* ------------------------------------------------------------------ Overview */
function Overview({ onOpen }) {
  const [ov, err] = usePoll(() => api("/api/overview"), 30000);
  const [opps] = usePoll(() => api("/api/opportunities"), 30000);
  if (err) return html`<p class="err">Overview unavailable: ${err}</p>`;
  if (!ov) return html`<p class="muted">Loading…</p>`;
  if (!ov.ready) return html`<div class="card"><b>Waiting for first scan…</b><p class="muted">${ov.message}</p>
    ${(ov.errors || []).map((e) => html`<div class="small err">${e.where}: ${e.error}</div>`)}</div>`;
  const s = ov.sentiment || {}, idx = ov.market_index || {}, vol = ov.btc_realised_vol || {};
  const signals = (opps?.items || []).filter((o) => o.status === "SIGNAL");
  const noTrade = (opps?.items || []).filter((o) => o.status !== "SIGNAL");
  return html`
    <div class="grid">
      <${Kpi} label="BTC/USDT" value=${fmt(ov.btc.price)} sub=${html`<span class=${cls(ov.btc.change_24h_pct)}>${pct(ov.btc.change_24h_pct)} 24h</span> · age ${ov.prices_age}`} />
      <${Kpi} label="ETH/USDT" value=${fmt(ov.eth.price)} sub=${html`<span class=${cls(ov.eth.change_24h_pct)}>${pct(ov.eth.change_24h_pct)} 24h</span>`} />
      <${Kpi} label="Market direction" value=${ov.direction?.label} sub=${(ov.direction?.evidence || []).join(" · ")} />
      <${Kpi} label="Universe index (liq-weighted 24h)" value=${pct(idx.liquidity_weighted_change_24h_pct)}
        className=${cls(idx.liquidity_weighted_change_24h_pct)} sub=${idx.available ? `breadth ${idx.breadth_pct?.toFixed(0)}% up · ${idx.n} assets` : "unavailable"} />
      <${Kpi} label="BTC realised vol (30d, ann.)" value=${vol.available ? vol.annualised_pct.toFixed(1) + "%" : "—"}
        sub=${vol.percentile_vs_history != null ? `${vol.percentile_vs_history.toFixed(0)}th pct vs history` : ""} />
      <${Kpi} label="Universe 24h turnover" value=${fmtUsd(idx.total_turnover_24h_usd)} sub="Bybit USDT perpetuals" />
      <${Kpi} label="Fear & Greed" value=${s.fear_greed ?? "—"} sub=${s.fear_greed != null ? `${s.fear_greed_label} · 7d ${s.fear_greed_change_7d ?? "—"} · age ${s.age}` : "unavailable"} />
      <${Kpi} label="Paper equity" value=${fmt(ov.paper?.equity)} sub=${`DD ${fmt(ov.paper?.current_drawdown_pct)}% · open ${ov.paper?.open_trades}`} />
    </div>
    ${(s.divergences || []).length > 0 && html`<div class="card" style=${{ marginTop: 12 }}><h3>Sentiment vs price observations</h3>
      <ul class="ev">${s.divergences.map((d) => html`<li>${d}</li>`)}</ul></div>`}
    <div class="grid2" style=${{ marginTop: 12 }}>
      <div class="card"><h3>Upcoming economic events (7d)</h3>
        ${!ov.calendar?.loaded ? html`<p class="warn small">Calendar not loaded (${ov.calendar?.path}). Event risk is treated as UNKNOWN (0 points).</p>` :
          ov.upcoming_events.length === 0 ? html`<p class="muted small">No events in loaded calendar.</p>` :
          html`<table><tbody>${ov.upcoming_events.map((e) => html`<tr><td>${e.name}</td><td>${e.impact}</td><td>in ${e.in}</td>
            <td><a href=${e.source_url} target="_blank" rel="noopener">source</a></td></tr>`)}</tbody></table>`}
      </div>
      <div class="card"><h3>On-chain</h3>
        ${ov.onchain?.metrics?.stablecoin_supply ? html`<div>Stablecoin supply ${fmtUsd(ov.onchain.metrics.stablecoin_supply.value_usd)}
           · 30d <span class=${cls(ov.onchain.metrics.stablecoin_supply.change_30d_pct)}>${pct(ov.onchain.metrics.stablecoin_supply.change_30d_pct)}</span>
           <div class="small muted">${ov.onchain.metrics.stablecoin_supply.interpretation} (age ${ov.onchain.metrics.stablecoin_supply.age})</div></div>` : ""}
        <ul class="ev small muted">${Object.entries(ov.onchain?.unavailable || {}).map(([k, v]) => html`<li>${k}: ${v}</li>`)}</ul>
      </div>
    </div>
    <h2 class="section-title">Analytical opportunities (${signals.length} signal${signals.length === 1 ? "" : "s"})</h2>
    ${signals.length === 0 && html`<div class="card"><span class="notrade">NO TRADE — INSUFFICIENT CONFIRMATION</span>
      <p class="muted small">No instrument currently passes every gate. The system does not manufacture opportunities.</p></div>`}
    <div class="grid2">${signals.map((o) => html`<${OppCard} key=${o.symbol} o=${o} onOpen=${onOpen} />`)}</div>
    <h2 class="section-title">Monitored — no trade</h2>
    <div class="card scroll"><table><thead><tr><th>Pair</th><th>Price</th><th>Trend 1h / 4h / 1d</th><th>Long</th><th>Short</th><th>Main reasons</th></tr></thead>
      <tbody>${noTrade.map((o) => html`<tr key=${o.symbol}>
        <td><a href="#" onClick=${(e) => { e.preventDefault(); onOpen(o.symbol); }}>${o.symbol}</a></td>
        <td>${fmt(o.price)}</td>
        <td>${["1h", "4h", "1d"].map((tf) => html`<span class=${"chip " + (o.trend?.[tf] || "")}>${o.trend?.[tf] || "n/a"}</span>`)}</td>
        <td>${o.score_long?.toFixed(0)}</td><td>${o.score_short?.toFixed(0)}</td>
        <td class="small muted">${(o.gate_failures || []).slice(0, 3).join("; ")}</td></tr>`)}</tbody></table></div>`;
}

function ScoreBreakdown({ card }) {
  if (!card) return null;
  return html`<details><summary>Score breakdown (${card.total}/100) — why this score</summary>
    ${Object.values(card.categories).map((c) => html`<div style=${{ margin: "6px 0" }}>
      <div class="row"><b>${c.name}</b><span class="muted">${c.points}/${c.max}</span></div>
      <div class="bar"><div style=${{ width: (100 * c.points / c.max) + "%" }}></div></div>
      <ul class="ev small">${c.components.map((x) => html`<li class=${x.available ? "" : "warn"}>${x.name}: ${x.points}/${x.max} — ${x.evidence}${x.available ? "" : " [DATA MISSING → 0]"}</li>`)}</ul>
    </div>`)}
  </details>`;
}

function OppCard({ o, onOpen }) {
  const sim = o.simulation || {};
  return html`<div class="card">
    <div class="row" style=${{ justifyContent: "space-between" }}>
      <h3><a href="#" onClick=${(e) => { e.preventDefault(); onOpen(o.symbol); }}>${o.symbol}</a> · ${fmt(o.price)}</h3>
      <span class="signal">${o.direction.toUpperCase()} · ${o.score.toFixed(0)}/100</span></div>
    <div class="small">${["15m", "1h", "4h", "1d", "1w"].map((tf) => html`<span class=${"chip " + (o.trend?.[tf] || "")}>${tf} ${o.trend?.[tf] || "n/a"}</span>`)}</div>
    <p class="small">${o.scenario}</p>
    <table><tbody>
      <tr><th>Entry zone (sim)</th><td>${fmt(o.entry_zone[0])} – ${fmt(o.entry_zone[1])}</td></tr>
      <tr><th>Hypothetical stop</th><td>${fmt(o.stop)}</td></tr>
      <tr><th>Take-profits</th><td>${o.take_profits.map((t) => fmt(t)).join(" / ")} (gross ${o.rr_gross.map((r) => r.toFixed(1) + "R").join(" / ")})</td></tr>
      <tr><th>Net R:R (blended)</th><td>${o.rr_net_blended?.toFixed(2)}</td></tr>
      <tr><th>Est. costs</th><td>fees ${fmt(o.costs.entry_fee + o.costs.exit_fee_at_stop)} · funding ${fmt(o.costs.funding_estimate)} USDT
        <div class="small muted">${o.costs.assumptions}</div></td></tr>
      <tr><th>Sim @ ${sim.leverage}x</th><td>size ${fmtUsd(sim.notional)}, margin ${fmtUsd(sim.margin)}, est. liq ${fmt(sim.liquidation_price)}, max loss ${fmt(sim.max_hypothetical_loss)} USDT</td></tr>
    </tbody></table>
    <details><summary>Supporting evidence</summary><ul class="ev small">${o.supporting.map((s) => html`<li>${s}</li>`)}</ul></details>
    <details><summary>Invalidation & risks</summary><ul class="ev small">${o.invalidation.map((s) => html`<li><b>${s}</b></li>`)}
      ${o.risks.map((s) => html`<li class="warn">${s}</li>`)}</ul></details>
    ${o.news?.length > 0 && html`<details><summary>Relevant news (${o.news.length})</summary><ul class="ev small">${o.news.map((n) => html`<li>
      <a href=${n.url} target="_blank" rel="noopener">${n.title}</a> <span class="muted">· ${n.source} · ${n.age} · ${n.confirmation}</span></li>`)}</ul></details>`}
    <${ScoreBreakdown} card=${o.scorecard} />
    <p class="small muted">${o.disclaimer}</p>
  </div>`;
}

/* ------------------------------------------------------------------ Symbol */
function Chart({ symbol, tf, opp }) {
  const ref = useRef(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!ref.current) return;
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const chart = LightweightCharts.createChart(ref.current, {
      autoSize: true, layout: { background: { color: "transparent" }, textColor: dark ? "#c9d1d9" : "#333" },
      grid: { vertLines: { color: dark ? "#222a35" : "#eee" }, horzLines: { color: dark ? "#222a35" : "#eee" } },
      timeScale: { timeVisible: true },
    });
    const candles = chart.addCandlestickSeries();
    const lines = { ema20: "#5b8def", ema50: "#e0a43a", ema200: "#a371f7" };
    const series = Object.fromEntries(Object.entries(lines).map(([k, c]) => [k, chart.addLineSeries({ color: c, lineWidth: 1, priceLineVisible: false })]));
    api(`/api/candles/${symbol}?tf=${tf}&limit=400`).then((d) => {
      candles.setData(d.rows.map((r) => ({ time: r.t, open: r.open, high: r.high, low: r.low, close: r.close })));
      for (const k of Object.keys(lines)) series[k].setData(d.rows.filter((r) => r[k] != null).map((r) => ({ time: r.t, value: r[k] })));
      if (opp && opp.status === "SIGNAL") {
        candles.createPriceLine({ price: opp.stop, color: "#f05252", title: "stop (sim)" });
        opp.take_profits.forEach((t, i) => candles.createPriceLine({ price: t, color: "#3fb871", title: `TP${i + 1} (sim)` }));
      }
    }).catch((e) => setErr(e.message));
    return () => chart.remove();
  }, [symbol, tf, opp?.created_at]);
  return html`<div>${err && html`<p class="err">${err}</p>`}<div id="chart" ref=${ref}></div>
    <div class="small muted">Closed candles only · EMA20 (blue) · EMA50 (amber) · EMA200 (purple)</div></div>`;
}

function SymbolView({ symbol, setSymbol }) {
  const [tf, setTf] = useState("1h");
  const [a, err] = usePoll(() => api(`/api/analysis/${symbol}`), 60000, [symbol]);
  const [opps] = usePoll(() => api("/api/opportunities"), 0);
  const o = a?.opportunity;
  const t = a?.timeframes?.[tf];
  return html`<div>
    <div class="row" style=${{ marginBottom: 10 }}>
      <select value=${symbol} onChange=${(e) => setSymbol(e.target.value)}>
        ${(opps?.items || []).map((x) => html`<option value=${x.symbol}>${x.symbol}</option>`)}</select>
      ${["1m", "5m", "15m", "1h", "4h", "1d", "1w"].map((x) => html`<button class=${"chip " + (x === tf ? "bullish" : "")} onClick=${() => setTf(x)}>${x}</button>`)}
    </div>
    <div class="card"><${Chart} symbol=${symbol} tf=${tf} opp=${o} /></div>
    ${err && html`<p class="err">${err}</p>`}
    ${o && html`<div class="card" style=${{ marginTop: 12 }}>
      ${o.status === "SIGNAL" ? html`<span class="signal">${o.headline}</span>` : html`<span class="notrade">${o.headline}</span>`}
      <div class="small muted">long ${o.score_long} · short ${o.score_short} · analysed ${a.as_of}</div>
      ${o.gate_failures?.length > 0 && html`<ul class="ev small">${o.gate_failures.map((g) => html`<li class="warn">${g}</li>`)}</ul>`}
      ${o.missing_data?.length > 0 && html`<div class="small muted">Missing data (scored 0): ${o.missing_data.join(", ")}</div>`}
      <${ScoreBreakdown} card=${o.scorecard} />
      <details><summary>Opposite scenario scorecard</summary><${ScoreBreakdown} card=${o.scorecard_opposite} /></details>
    </div>`}
    ${t && html`<div class="grid2" style=${{ marginTop: 12 }}>
      <div class="card"><h3>${tf} — ${t.sufficient ? `${t.trend} (bias ${t.bias.toFixed(2)})` : "insufficient data"}</h3>
        <div class="small muted">last close ${t.last_close_time} · age ${t.age} ${t.stale ? "· STALE" : ""} · volatility ${t.volatility_regime}</div>
        <b class="small up">Bullish evidence</b><ul class="ev small">${t.bullish_evidence.map((x) => html`<li>${x}</li>`)}</ul>
        <b class="small down">Bearish evidence</b><ul class="ev small">${t.bearish_evidence.map((x) => html`<li>${x}</li>`)}</ul>
        <b class="small">Notes</b><ul class="ev small muted">${t.notes.map((x) => html`<li>${x}</li>`)}</ul></div>
      <div class="card"><h3>Indicators</h3><table><tbody>
        ${Object.entries(t.snapshot || {}).map(([k, v]) => html`<tr><th>${k}</th><td>${fmt(v, 4)}</td></tr>`)}</tbody></table></div>
      <div class="card"><h3>Levels & structure</h3>
        <div class="small">Structure: <b>${t.structure?.trend}</b> ${(t.structure?.labels || []).join("/")} ${t.structure?.bos ? `· BOS ${t.structure.bos}` : ""}</div>
        <div class="small">Resistances: ${t.resistances.map((l) => `${fmt(l.price)} (${l.touches})`).join(", ") || "—"}</div>
        <div class="small">Supports: ${t.supports.map((l) => `${fmt(l.price)} (${l.touches})`).join(", ") || "—"}</div>
        <div class="small">Volume profile: POC ${fmt(t.volume_profile?.poc)} · VA ${fmt(t.volume_profile?.val)}–${fmt(t.volume_profile?.vah)}</div>
        <div class="small">Breakout: ${t.breakout?.evidence}</div>
        <div class="small">FVGs: ${t.fvgs.map((g) => `${g.type} ${fmt(g.bottom)}–${fmt(g.top)}`).join("; ") || "—"}</div>
        <div class="small">Liquidity: ${t.liquidity.map((g) => `${g.type} @ ${fmt(g.price)}`).join("; ") || "—"}</div>
        <div class="small">Patterns: ${t.patterns.map((p) => p.pattern).join(", ") || "—"} · Divergence: ${t.divergence || "—"}</div></div>
      <div class="card"><h3>Derivatives</h3>
        <div class="small">Funding ${a.derivatives.funding_rate != null ? (a.derivatives.funding_rate * 100).toFixed(4) + "%" : "—"}
          ${a.derivatives.funding_percentile != null ? `(${a.derivatives.funding_percentile.toFixed(0)}th pct)` : ""} · OI regime ${a.derivatives.oi_regime || "—"}
          · L/S ${fmt(a.derivatives.long_short_ratio)}</div>
        <ul class="ev small">${a.derivatives.observations.map((x) => html`<li>${x}</li>`)}${a.derivatives.warnings.map((x) => html`<li class="warn">${x}</li>`)}</ul></div>
    </div>`}
  </div>`;
}

/* ------------------------------------------------------------------ Leverage */
function LeverageView() {
  const [f, setF] = useState({ equity: 10000, side: "long", entry: 100, stop: 97, targets: "106,109", risk_pct: 1, margin_fraction: 10, funding_rate: 0.01, funding_intervals: 3 });
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const run = (e) => {
    e && e.preventDefault();
    api("/api/leverage/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      equity: +f.equity, side: f.side, entry: +f.entry, stop: +f.stop, targets: f.targets.split(",").map(Number),
      risk_pct: f.risk_pct / 100, margin_fraction: f.margin_fraction / 100, funding_rate: f.funding_rate / 100, funding_intervals: +f.funding_intervals }) })
      .then((r) => { setRes(r); setErr(null); }).catch((e) => setErr(e.message));
  };
  useEffect(() => { run(); }, []);
  const Table = ({ rows, title }) => html`<div class="card scroll"><h3>${title}</h3><table><thead><tr>
      <th>Lev</th><th>Position</th><th>Margin</th><th>Est. liq</th><th>Liq dist</th><th>Stop dist</th><th>Loss @ stop</th><th>% equity</th>
      <th>Profit @ TPs</th><th>Net R:R</th><th>Fees+funding</th><th>Status</th></tr></thead><tbody>
      ${rows.map((r) => html`<tr><td>${r.leverage}x</td><td>${fmtUsd(r.notional)}</td><td>${fmtUsd(r.margin)}</td><td>${fmt(r.liquidation_price)}</td>
        <td>${r.liquidation_distance_pct.toFixed(2)}%</td><td>${r.stop_distance_pct.toFixed(2)}%</td>
        <td class="down">${fmt(r.loss_at_stop)}</td><td>${r.loss_at_stop_pct_equity.toFixed(2)}%</td>
        <td class="up">${r.profit_at_targets.map((p) => fmt(p)).join(" / ")}</td><td>${r.rr_at_targets.map((x) => x.toFixed(2)).join(" / ")}</td>
        <td>${fmt(r.entry_fee + r.exit_fee_at_stop + r.funding_cost)}</td>
        <td class=${r.liquidation_before_stop ? "bad" : ""}>${r.liquidation_before_stop ? "LIQUIDATED BEFORE STOP" : r.margin_capped ? "margin-capped" : "ok"}</td></tr>`)}
    </tbody></table></div>`;
  return html`<div>
    <div class="disclaimer">Educational simulation. Liquidation estimates assume isolated margin and a flat maintenance-margin rate; actual Bybit liquidation depends on risk-limit tiers, margin mode, mark price, fees and account configuration. Higher leverage never improves a setup.</div>
    <form class="inline card" onSubmit=${run}>
      <label class="f">Equity (USDT)<input value=${f.equity} onInput=${set("equity")} /></label>
      <label class="f">Side<select value=${f.side} onChange=${set("side")}><option>long</option><option>short</option></select></label>
      <label class="f">Entry<input value=${f.entry} onInput=${set("entry")} /></label>
      <label class="f">Stop<input value=${f.stop} onInput=${set("stop")} /></label>
      <label class="f">Targets (comma)<input value=${f.targets} onInput=${set("targets")} /></label>
      <label class="f">Risk % (fixed-risk)<input value=${f.risk_pct} onInput=${set("risk_pct")} /></label>
      <label class="f">Margin % (fixed-margin)<input value=${f.margin_fraction} onInput=${set("margin_fraction")} /></label>
      <label class="f">Funding %/interval<input value=${f.funding_rate} onInput=${set("funding_rate")} /></label>
      <label class="f">Funding intervals<input value=${f.funding_intervals} onInput=${set("funding_intervals")} /></label>
      <button class="primary">Simulate</button></form>
    ${err && html`<p class="err">${err}</p>`}
    ${res && html`<div><ul class="ev">${res.lessons.map((l) => html`<li>${l}</li>`)}</ul>
      <${Table} rows=${res.fixed_risk} title="Fixed-risk sizing (loss at stop ≈ risk %)" />
      <div style=${{ height: 12 }}></div>
      <${Table} rows=${res.fixed_margin} title="Fixed-margin sizing (same margin × leverage)" /></div>`}
  </div>`;
}

/* ------------------------------------------------------------------ Paper */
function PaperView() {
  const [perf] = usePoll(() => api("/api/paper/performance"), 30000);
  const [trades] = usePoll(() => api("/api/paper/trades"), 30000);
  return html`<div>
    <div class="disclaimer">Paper trading only — no real orders are ever sent. Fills, fees, slippage and funding are modelled from live public data.</div>
    ${perf && html`<div class="grid">
      <${Kpi} label="Equity" value=${fmt(perf.equity)} sub=${`balance ${fmt(perf.balance)}`} />
      <${Kpi} label="Total return" value=${pct(perf.total_return_pct)} className=${cls(perf.total_return_pct)} />
      <${Kpi} label="Max drawdown" value=${pct(perf.max_drawdown_pct)} className="down" />
      <${Kpi} label="Closed trades" value=${perf.n_trades} sub=${`win rate ${fmt(perf.win_rate_pct)}%`} />
      <${Kpi} label="Profit factor" value=${fmt(perf.profit_factor)} sub=${`expectancy ${fmt(perf.expectancy)} USDT / ${fmt(perf.expectancy_r)}R`} />
      <${Kpi} label="Fees / funding" value=${fmt(perf.total_fees)} sub=${`funding ${fmt(perf.total_funding)}`} />
    </div>`}
    <div class="card scroll" style=${{ marginTop: 12 }}><h3>Trade history</h3><table><thead><tr>
      <th>#</th><th>Symbol</th><th>Side</th><th>Lev</th><th>Entry</th><th>Stop</th><th>TPs</th><th>Est. liq</th><th>Status</th><th>Exit</th><th>P&L</th><th>R</th><th>Fees</th><th>Funding</th><th>Opened</th></tr></thead>
      <tbody>${(trades || []).map((t) => html`<tr><td>${t.id}</td><td>${t.symbol}</td><td>${t.side}</td><td>${t.leverage}x</td>
        <td>${fmt(t.entry_price)}</td><td>${fmt(t.stop)}</td><td>${t.take_profits.map((x) => fmt(x)).join(" / ")}</td><td>${fmt(t.liq_price)}</td>
        <td>${t.status}</td><td>${t.exit_reason || "—"}</td><td class=${cls(t.realized_pnl)}>${fmt(t.realized_pnl)}</td><td>${fmt(t.r_multiple)}</td>
        <td>${fmt(t.fees)}</td><td>${fmt(t.funding)}</td><td class="small">${t.entry_time.slice(0, 16)}</td></tr>`)}</tbody></table>
      ${(trades || []).length === 0 && html`<p class="muted small">No simulated trades yet. Trades are only opened when an opportunity passes every gate.</p>`}</div>
  </div>`;
}

/* ------------------------------------------------------------------ Backtest */
function BacktestView() {
  const [f, setF] = useState({ symbol: "BTCUSDT", timeframe: "1h", strategy: "trend_pullback", mode: "walk_forward", days: 365 });
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const run = (e) => {
    e.preventDefault(); setBusy(true); setErr(null);
    api("/api/backtest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...f, days: +f.days }) })
      .then(setRes).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  const m = res && (res.out_of_sample_metrics || res.holdout || res.metrics);
  const b = res && res.benchmark_buy_and_hold;
  const rows = [["Total return %", "total_return_pct"], ["CAGR %", "cagr_pct"], ["Max drawdown %", "max_drawdown_pct"], ["Sharpe", "sharpe"],
    ["Sortino", "sortino"], ["Trades", "n_trades"], ["Win rate %", "win_rate_pct"], ["Profit factor", "profit_factor"],
    ["Avg win", "avg_win"], ["Avg loss", "avg_loss"], ["Expectancy (USDT)", "expectancy"], ["Expectancy (R)", "expectancy_r"],
    ["Fees", "total_fees"], ["Funding", "total_funding"]];
  return html`<div>
    <form class="inline card" onSubmit=${run}>
      <label class="f">Symbol<input value=${f.symbol} onInput=${set("symbol")} /></label>
      <label class="f">Timeframe<select value=${f.timeframe} onChange=${set("timeframe")}>${["15m", "1h", "4h", "1d"].map((x) => html`<option>${x}</option>`)}</select></label>
      <label class="f">Strategy<select value=${f.strategy} onChange=${set("strategy")}>${["trend_pullback", "donchian_breakout", "bollinger_reversion"].map((x) => html`<option>${x}</option>`)}</select></label>
      <label class="f">Mode<select value=${f.mode} onChange=${set("mode")}><option value="walk_forward">walk-forward</option><option value="holdout">OOS holdout</option><option value="single">single (in-sample)</option></select></label>
      <label class="f">Days<input value=${f.days} onInput=${set("days")} /></label>
      <button class="primary" disabled=${busy}>${busy ? "Running…" : "Run backtest"}</button></form>
    ${err && html`<p class="err">${err}</p>`}
    ${res && html`<div class="grid2" style=${{ marginTop: 12 }}>
      <div class="card"><h3>Verdict</h3><ul class="ev">${(res.verdict || [res.warning]).map((v) => html`<li class=${/FAIL|Under|overfit/.test(v) ? "bad" : ""}>${v}</li>`)}</ul>
        <div class="small muted">Data: ${res.data?.bars} bars ${res.data?.from?.slice(0, 10)} → ${res.data?.to?.slice(0, 10)} · funding: ${res.data?.funding}</div>
        ${res.parameter_combinations_tested_per_fold && html`<div class="small muted">Parameter combinations tested per fold: ${res.parameter_combinations_tested_per_fold} · profitable folds ${res.profitable_folds}</div>`}
        <ul class="ev small muted">${(res.notes || []).map((n) => html`<li>${n}</li>`)}</ul></div>
      <div class="card scroll"><h3>${res.out_of_sample_metrics ? "Out-of-sample" : res.holdout ? "Holdout" : "In-sample"} vs buy-and-hold</h3>
        <table><thead><tr><th>Metric</th><th>Strategy</th><th>Buy & hold</th></tr></thead><tbody>
        ${rows.map(([l, k]) => html`<tr><td>${l}</td><td>${fmt(m?.[k])}</td><td>${fmt(b?.[k])}</td></tr>`)}</tbody></table></div>
    </div>`}
  </div>`;
}

/* ------------------------------------------------------------------ News & alerts */
function NewsView() {
  const [news] = usePoll(() => api("/api/news"), 120000);
  const [alerts] = usePoll(() => api("/api/alerts?limit=50"), 60000);
  return html`<div class="grid2">
    <div class="card"><h3>News & macro events</h3><p class="small muted">${news?.note} Classification is automated keyword matching — always read the original source.</p>
      ${(news?.items || []).map((n) => html`<div style=${{ borderBottom: "1px solid var(--border)", padding: "6px 0" }}>
        <a href=${n.url} target="_blank" rel="noopener">${n.title}</a>
        <div class="small muted">${n.source} · ${n.published_at ? n.published_at.slice(0, 16).replace("T", " ") : "no timestamp"} (age ${n.age}) · <b>${n.confirmation}</b> · importance ${n.importance}</div>
        ${n.event_types.length > 0 && html`<div class="small">${n.event_types.map((t) => html`<span class="chip">${t}</span>`)} assets: ${n.assets.join(", ") || "—"} · impact: ${n.impact_duration}</div>`}
        ${n.bullish_case.length > 0 && html`<details><summary class="small">Bullish / bearish implications</summary><ul class="ev small">
          ${n.bullish_case.map((x) => html`<li class="up">${x}</li>`)}${n.bearish_case.map((x) => html`<li class="down">${x}</li>`)}</ul></details>`}
      </div>`)}</div>
    <div class="card"><h3>Alerts</h3>${(alerts || []).map((a) => html`<div style=${{ borderBottom: "1px solid var(--border)", padding: "6px 0" }}>
      <b class=${a.severity === "critical" ? "bad" : a.severity === "warning" ? "warn" : ""}>${a.title}</b>
      <div class="small muted">${a.created_at?.slice(0, 16).replace("T", " ")} UTC · ${a.sent ? "sent to Telegram" : "logged"}</div>
      <ul class="ev small">${a.evidence.map((x) => html`<li>${x}</li>`)}${a.risks.map((x) => html`<li class="warn">${x}</li>`)}</ul></div>`)}
      ${(alerts || []).length === 0 && html`<p class="muted small">No alerts yet.</p>`}</div>
  </div>`;
}

/* ------------------------------------------------------------------ App */
function App() {
  const [tab, setTab] = useState("overview");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [health] = usePoll(() => api("/api/health"), 60000);
  const open = (s) => { setSymbol(s); setTab("symbol"); };
  const tabs = [["overview", "Overview"], ["symbol", "Symbol analysis"], ["leverage", "Leverage simulator"], ["paper", "Paper trading"], ["backtest", "Backtesting"], ["news", "News & alerts"]];
  return html`<div>
    <header><h1>CryptoIntel</h1>
      <nav>${tabs.map(([k, l]) => html`<button class=${tab === k ? "active" : ""} onClick=${() => setTab(k)}>${l}</button>`)}</nav>
      <span class="small muted">last scan ${health?.last_scan_at ? health.last_scan_at.slice(11, 19) + " UTC" : "pending"}</span></header>
    <main>
      <div class="disclaimer">${health?.disclaimer || "Research and simulation only. Not financial advice."}</div>
      ${tab === "overview" && html`<${Overview} onOpen=${open} />`}
      ${tab === "symbol" && html`<${SymbolView} symbol=${symbol} setSymbol=${setSymbol} />`}
      ${tab === "leverage" && html`<${LeverageView} />`}
      ${tab === "paper" && html`<${PaperView} />`}
      ${tab === "backtest" && html`<${BacktestView} />`}
      ${tab === "news" && html`<${NewsView} />`}
    </main></div>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
