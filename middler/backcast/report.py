"""Render a backcast into a single, self-contained HTML report (proposal §3).

The output embeds plotly.js inline, so the file opens in any browser with no
install, no server, and no internet — exactly what the non-technical Reviewer
needs (proposal §0, §9). Nothing here touches money or the detection maths; it
only summarises what the engine already found.
"""

from __future__ import annotations

import html
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import plotly.graph_objects as go

from middler.backcast.replay import BackcastResult, run_backcast
from middler.config import AppConfig, load_config
from middler.logging_setup import get_logger, setup_logging
from middler.models import Opportunity
from middler.store.history import HistoryStore
from middler.timeutil import fmt_sydney, to_sydney

log = get_logger(__name__)

MAX_TABLE_ROWS = 1000


# ── summary ──────────────────────────────────────────────────────────────────
def _summary(result: BackcastResult) -> dict[str, object]:
    middles = result.middles
    widths = [o.width for o in middles if o.width is not None]
    evs = [o.ev for o in middles if o.ev is not None]
    return {
        "total": len(result.opportunities),
        "middles": len(middles),
        "arbs": len(result.arbs),
        "risk_free": len(result.risk_free),
        "verified": sum(1 for o in result.opportunities if o.reference_verified),
        "avg_width": statistics.mean(widths) if widths else 0.0,
        "max_width": max(widths) if widths else 0.0,
        "avg_ev": statistics.mean(evs) if evs else 0.0,
        "total_ev": sum(evs) if evs else 0.0,
        "events": result.events_seen,
        "snapshots": result.snapshots,
        "quotes": result.total_quotes,
    }


# ── charts ───────────────────────────────────────────────────────────────────
def _chart_over_time(result: BackcastResult) -> go.Figure | None:
    if not result.opportunities:
        return None
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"middle": 0, "arb": 0})
    for o in result.opportunities:
        day = to_sydney(o.observed_at).strftime("%Y-%m-%d")
        by_day[day][o.kind] += 1
    days = sorted(by_day)
    fig = go.Figure()
    fig.add_bar(x=days, y=[by_day[d]["middle"] for d in days], name="Middles", marker_color="#2563eb")
    fig.add_bar(x=days, y=[by_day[d]["arb"] for d in days], name="Arbs", marker_color="#16a34a")
    fig.update_layout(
        barmode="stack",
        template="plotly_white",
        title="Opportunities flagged per day (Sydney)",
        height=360,
        margin=dict(t=50, b=40, l=40, r=20),
        legend=dict(orientation="h"),
    )
    return fig


def _chart_width(result: BackcastResult) -> go.Figure | None:
    widths = [o.width for o in result.middles if o.width is not None]
    if not widths:
        return None
    fig = go.Figure(go.Histogram(x=widths, marker_color="#2563eb", nbinsx=20))
    fig.update_layout(
        template="plotly_white",
        title="Middle width distribution (points)",
        height=360,
        margin=dict(t=50, b=40, l=40, r=20),
        xaxis_title="Window width",
        yaxis_title="Count",
    )
    return fig


def _chart_ev_by_market(result: BackcastResult) -> go.Figure | None:
    if not result.middles:
        return None
    totals: dict[str, float] = defaultdict(float)
    for o in result.middles:
        if o.ev is not None:
            totals[o.market_key] += o.ev
    markets = sorted(totals)
    fig = go.Figure(go.Bar(x=markets, y=[totals[m] for m in markets], marker_color="#7c3aed"))
    fig.update_layout(
        template="plotly_white",
        title="Summed expected value by market",
        height=360,
        margin=dict(t=50, b=40, l=40, r=20),
        yaxis_title="Σ EV (AUD, at default stake)",
    )
    return fig


def _fig_html(fig: go.Figure, include_js: bool) -> str:
    return str(fig.to_html(full_html=False, include_plotlyjs="inline" if include_js else False))


# ── table ────────────────────────────────────────────────────────────────────
def _legs_cell(opp: Opportunity) -> str:
    lines = []
    for leg in opp.legs:
        point = "" if leg.point is None else f" {leg.point:+g}"
        sel = html.escape(f"{leg.outcome_name}{point}")
        lines.append(
            f"<b>{html.escape(leg.bookmaker)}</b>: {sel} @ {leg.price:g} <span class='stake'>(${leg.stake:g})</span>"
        )
    return "<br>".join(lines)


def _num(value: float | None, fmt: str = "{:.2f}") -> str:
    return fmt.format(value) if value is not None else "—"


def _table_html(opps: list[Opportunity]) -> str:
    ordered = sorted(opps, key=lambda o: (o.is_risk_free, o.ev or 0.0, o.margin or 0.0), reverse=True)
    truncated = len(ordered) > MAX_TABLE_ROWS
    rows = []
    for o in ordered[:MAX_TABLE_ROWS]:
        match = html.escape(f"{o.home_team or '?'} v {o.away_team or '?'}")
        tag = "risk-free" if o.is_risk_free else o.kind
        verified = "✓" if o.reference_verified else "·"
        metric = _num(o.ev) if o.kind == "middle" else _num(o.profit)
        width = _num(o.width, "{:.1f}") if o.kind == "middle" else "—"
        rows.append(
            "<tr>"
            f"<td data-sort='{o.observed_at.timestamp()}'>{html.escape(fmt_sydney(o.observed_at))}</td>"
            f"<td>{html.escape(o.sport_key)}</td>"
            f"<td>{html.escape(o.market_key)}</td>"
            f"<td><span class='pill {tag}'>{html.escape(tag)}</span></td>"
            f"<td>{match}</td>"
            f"<td class='legs'>{_legs_cell(o)}</td>"
            f"<td data-sort='{o.width or 0}'>{width}</td>"
            f"<td data-sort='{o.ev or o.profit or 0}'>{metric}</td>"
            f"<td>{verified}</td>"
            "</tr>"
        )
    note = (
        f"<p class='muted'>Showing the top {MAX_TABLE_ROWS} of {len(ordered)} opportunities.</p>" if truncated else ""
    )
    return (
        note
        + "<table id='opps'><thead><tr>"
        + "".join(
            f"<th onclick='sortTable({i})'>{h}</th>"
            for i, h in enumerate(
                ["When (Syd)", "Sport", "Market", "Type", "Match", "Legs (stake split)", "Width", "EV / profit", "Ref"]
            )
        )
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


# ── page assembly ────────────────────────────────────────────────────────────
def _cards(summary: dict[str, object]) -> str:
    cards = [
        ("Opportunities", f"{summary['total']:,}", "middles + arbs flagged"),
        ("Middles", f"{summary['middles']:,}", f"avg width {summary['avg_width']:.2f} pts"),
        ("Arbitrages", f"{summary['arbs']:,}", "guaranteed-profit price gaps"),
        ("Risk-free", f"{summary['risk_free']:,}", "lose nothing even on a miss"),
        ("Avg EV / middle", f"${summary['avg_ev']:.2f}", "at the default stake"),
        ("Sharp-verified", f"{summary['verified']:,}", "passed the reference filter"),
        ("Events seen", f"{summary['events']:,}", f"{summary['snapshots']:,} snapshots"),
        ("Odds recorded", f"{summary['quotes']:,}", "observations in history"),
    ]
    return "".join(
        f"<div class='card'><div class='label'>{html.escape(label)}</div>"
        f"<div class='value'>{html.escape(value)}</div>"
        f"<div class='hint'>{html.escape(hint)}</div></div>"
        for label, value, hint in cards
    )


def render_report(
    result: BackcastResult,
    config: AppConfig,
    path: str | Path,
    generated_at: datetime | None = None,
) -> Path:
    """Render a backcast result to a self-contained HTML file.

    Args:
        result: The backcast result to render.
        config: Operating config (used for the methodology footer).
        path: Output HTML path.
        generated_at: Timestamp for the header (defaults to now).

    Returns:
        The path written.
    """
    generated_at = generated_at or datetime.now(UTC)
    summary = _summary(result)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if result.total_quotes == 0:
        coverage = "No odds recorded yet — the system records everything it sees, so this report fills in as it runs."
    else:
        span = f"{fmt_sydney(result.start)} → {fmt_sydney(result.end)}" if result.start and result.end else "—"
        coverage = (
            f"Replayed {summary['quotes']:,} odds observations across {summary['snapshots']:,} snapshots ({span})."
        )

    figs = [f for f in (_chart_over_time(result), _chart_width(result), _chart_ev_by_market(result)) if f is not None]
    charts_html = "".join(f"<div class='chart'>{_fig_html(f, include_js=(i == 0))}</div>" for i, f in enumerate(figs))
    if not charts_html:
        charts_html = (
            "<div class='empty'>No opportunities flagged yet. As history accumulates, charts appear here.</div>"
        )

    table_html = _table_html(result.opportunities) if result.opportunities else ""

    page = _TEMPLATE.format(
        generated=html.escape(fmt_sydney(generated_at)),
        coverage=html.escape(coverage),
        cards=_cards(summary),
        charts=charts_html,
        table=table_html,
        sports=html.escape(", ".join(config.sports) or "—"),
        stake=f"{config.staking.default_total_stake:g}",
        mode=html.escape(config.detection.stake_mode),
    )
    out.write_text(page, encoding="utf-8")
    log.info("wrote backcast report → %s (%d opportunities)", out, summary["total"])
    return out


def main() -> None:
    """CLI entry point: run a backcast over recorded history and write the report."""
    setup_logging()
    config = load_config()
    with HistoryStore(_duckdb_path()) as store:
        result = run_backcast(store, config)
    render_report(result, config, config.backcast.report_path)


def _duckdb_path() -> str:
    from middler.config import load_settings

    return load_settings().duckdb_path


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Middling &amp; Arbitrage — Backcast Report</title>
<style>
  :root {{ --bg:#0b1020; --card:#fff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:var(--ink); background:#f1f5f9; }}
  header {{ background:linear-gradient(135deg,#1e293b,#0b1020); color:#fff; padding:32px 28px; }}
  header h1 {{ margin:0 0 6px; font-size:24px; }}
  header p {{ margin:2px 0; color:#cbd5e1; font-size:14px; }}
  main {{ max-width:1180px; margin:0 auto; padding:24px 20px 64px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(165px,1fr)); gap:14px; margin:22px 0; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }}
  .card .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  .card .value {{ font-size:26px; font-weight:700; margin:4px 0; }}
  .card .hint {{ color:var(--muted); font-size:12px; }}
  .chart {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:8px; margin:16px 0; }}
  h2 {{ margin:28px 0 8px; font-size:18px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:12px; overflow:hidden; font-size:13px; }}
  th,td {{ text-align:left; padding:9px 11px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ background:#f8fafc; cursor:pointer; user-select:none; position:sticky; top:0; }}
  th:hover {{ background:#eef2f7; }}
  td.legs {{ font-size:12px; }}
  .stake {{ color:var(--muted); }}
  .pill {{ padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }}
  .pill.middle {{ background:#dbeafe; color:#1e40af; }}
  .pill.arb {{ background:#dcfce7; color:#166534; }}
  .pill.risk-free {{ background:#fef9c3; color:#854d0e; }}
  .muted,.empty {{ color:var(--muted); }}
  .empty {{ padding:40px; text-align:center; background:#fff; border:1px dashed var(--line); border-radius:12px; }}
  footer {{ max-width:1180px; margin:0 auto; padding:0 20px 48px; color:var(--muted); font-size:12px; }}
  footer code {{ background:#e2e8f0; padding:1px 5px; border-radius:4px; }}
</style></head>
<body>
<header>
  <h1>Pre-match Middling &amp; Arbitrage — Backcast</h1>
  <p>{coverage}</p>
  <p>Generated {generated} · no money was placed · this is what the system <em>would have</em> flagged.</p>
</header>
<main>
  <div class="grid">{cards}</div>
  {charts}
  <h2>Every opportunity</h2>
  {table}
</main>
<footer>
  <p>Tracking {sports}. Stakes shown at a ${stake} total, split mode <code>{mode}</code>. EV uses the conservative
  (worst-case) non-middle outcome and a historical middle-hit-rate prior; it is an estimate, not a promise. Detection
  and stake sizing are deterministic arithmetic — no model, no guessing. Click a column header to sort.</p>
</footer>
<script>
function sortTable(col) {{
  var t = document.getElementById('opps'); if (!t) return;
  var rows = Array.from(t.tBodies[0].rows);
  var asc = t.getAttribute('data-sort-col') == col ? t.getAttribute('data-sort-dir') != 'asc' : true;
  rows.sort(function(a, b) {{
    var x = a.cells[col].getAttribute('data-sort') ?? a.cells[col].innerText;
    var y = b.cells[col].getAttribute('data-sort') ?? b.cells[col].innerText;
    var nx = parseFloat(x), ny = parseFloat(y);
    if (!isNaN(nx) && !isNaN(ny)) {{ return asc ? nx - ny : ny - nx; }}
    return asc ? String(x).localeCompare(y) : String(y).localeCompare(x);
  }});
  rows.forEach(function(r) {{ t.tBodies[0].appendChild(r); }});
  t.setAttribute('data-sort-col', col); t.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
}}
</script>
</body></html>
"""
