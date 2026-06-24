#!/usr/bin/env python3
"""
market_data_demo.py — live terminal dashboard for the AI Trading Workstation.

Features:
  • Live price table with colour-coded ↑ / ↓ / → arrows
  • Per-ticker sparkline chart (unicode block characters ▁▂▃▄▅▆▇█)
  • Event log — highlights big movers and simulated market events
  • Session summary strip — top gainer, loser, most-active
  • Fully offline: powered by SimulatorProvider (no API key required)

Usage:
    python market_data_demo.py                        # 60 ticks at 0.4 s
    python market_data_demo.py --ticks 120 --interval 0.2
    python market_data_demo.py --ticks 0              # run until Ctrl-C
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from datetime import date
from pathlib import Path

# ── path setup ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent / "backend"))

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ModuleNotFoundError:
    print("This demo requires 'rich'.  Run:  pip install rich")
    sys.exit(1)

from app.services.data_ingestion.simulator_provider import SimulatorProvider

# ── constants ─────────────────────────────────────────────────────────────────
WATCHLIST     = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
                 "META", "TSLA", "SPY",  "QQQ",  "BRK.B"]
SPARK_CHARS   = "▁▂▃▄▅▆▇█"
HISTORY_LEN   = 18     # sparkline width in characters
EVENT_MAX     = 12     # lines kept in the event log
BIG_MOVE_PCT  = 1.5    # % threshold for an event log entry
SHOCK_PCT     = 3.0    # % threshold for a ⚡ shock event

# ── helpers ───────────────────────────────────────────────────────────────────

def _spark(prices: list[float]) -> str:
    if len(prices) < 2:
        return "─" * max(len(prices), 1)
    mn, mx = min(prices), max(prices)
    rng = mx - mn or 1.0
    n   = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[min(int((p - mn) / rng * n), n)] for p in prices)


def _vol(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return str(v)


def _pct_color(pct: float) -> str:
    if pct >  0.05: return "green"
    if pct < -0.05: return "red"
    return "grey50"


def _arrow(pct: float) -> str:
    if pct >  0.05: return "[bold green]↑[/]"
    if pct < -0.05: return "[bold red]↓[/]"
    return "[grey50]→[/]"


# ── UI builders ───────────────────────────────────────────────────────────────

def _price_table(
    prices:  dict[str, float],
    prev:    dict[str, float],
    history: dict[str, deque],
    volumes: dict[str, int],
    quotes:  dict[str, tuple[float, float]],
) -> Table:

    tbl = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold white on grey19",
        border_style="grey35",
        expand=True,
        show_edge=True,
        padding=(0, 1),
    )
    tbl.add_column("",        width=2,              no_wrap=True)   # arrow
    tbl.add_column("Symbol",  width=6,              no_wrap=True, style="bold")
    tbl.add_column("Price",   width=11, justify="right")
    tbl.add_column("Chg $",   width=9,  justify="right")
    tbl.add_column("Chg %",   width=8,  justify="right")
    tbl.add_column(f"  ──── last {HISTORY_LEN} bars ────",
                   width=HISTORY_LEN + 4, no_wrap=True)
    tbl.add_column("Volume",  width=8,  justify="right")
    tbl.add_column("Bid",     width=10, justify="right")
    tbl.add_column("Ask",     width=10, justify="right")
    tbl.add_column("Spread",  width=8,  justify="right")

    for tkr in WATCHLIST:
        px    = prices.get(tkr, 0.0)
        pv    = prev.get(tkr, px)
        chg   = px - pv
        pct   = (chg / pv * 100) if pv else 0.0
        vol   = volumes.get(tkr, 0)
        bid, ask = quotes.get(tkr, (px, px))
        hist  = list(history.get(tkr, [px]))
        col   = _pct_color(pct)
        spark = _spark(hist)

        tbl.add_row(
            _arrow(pct),
            f"[bold {col}]{tkr}[/]",
            f"[bold {col}]${px:>10,.2f}[/]",
            f"[{col}]{'+' if chg >= 0 else ''}{chg:,.2f}[/]",
            f"[{col}]{'+' if pct >= 0 else ''}{pct:.2f}%[/]",
            f"  [{col}]{spark}[/]",
            f"[dim]{_vol(vol)}[/]",
            f"[dim]${bid:>9,.2f}[/]",
            f"[dim]${ask:>9,.2f}[/]",
            f"[dim]{ask - bid:.3f}[/]",
        )
    return tbl


def _header(tick: int, ts: str) -> Panel:
    t = Text(justify="center")
    t.append("🏦  AI Trading Workstation", style="bold cyan")
    t.append("   ·   SimulatorProvider (GBM offline)", style="italic magenta")
    t.append("   ·   ", style="dim")
    t.append(f"Tick #{tick}", style="bold white")
    t.append("   ·   ", style="dim")
    t.append(ts, style="bold green")
    return Panel(t, border_style="blue", padding=(0, 2))


def _event_panel(events: deque) -> Panel:
    body = Text()
    for line in reversed(list(events)):
        body.append(line + "\n")
    return Panel(
        body,
        title="[bold yellow]⚡ Event Log[/]",
        border_style="yellow",
        padding=(0, 1),
    )


def _summary_panel(prices: dict, prev: dict, volumes: dict) -> Panel:
    pcts = {
        t: (prices[t] - prev.get(t, prices[t])) / prev.get(t, prices[t]) * 100
        for t in prices if prev.get(t)
    }
    if not pcts:
        return Panel("loading…", title="Summary", border_style="white")

    gainer = max(pcts, key=pcts.get)
    loser  = min(pcts, key=pcts.get)
    active = max(volumes, key=volumes.get) if volumes else "—"

    body = Text()
    body.append("\n")
    body.append("  Top Gainer  ", style="dim")
    body.append(f"{gainer}  +{pcts[gainer]:.2f}%\n", style="bold green")
    body.append("  Top Loser   ", style="dim")
    body.append(f"{loser}  {pcts[loser]:.2f}%\n", style="bold red")
    body.append("  Most Active ", style="dim")
    body.append(f"{active}  {_vol(volumes.get(active, 0))}\n", style="bold cyan")

    return Panel(
        Align(body, vertical="middle"),
        title="[bold white]Session Summary[/]",
        border_style="white",
    )


def _build_layout(
    tick:    int,
    ts:      str,
    prices:  dict,
    prev:    dict,
    history: dict,
    volumes: dict,
    quotes:  dict,
    events:  deque,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header",  size=3),
        Layout(name="table",   ratio=4),
        Layout(name="bottom",  size=16),
    )
    layout["bottom"].split_row(
        Layout(name="events",  ratio=3),
        Layout(name="summary", ratio=1),
    )

    layout["header"].update(_header(tick, ts))
    layout["table"].update(
        Panel(
            _price_table(prices, prev, history, volumes, quotes),
            title=f"[bold]Live Prices — {len(WATCHLIST)} Symbols[/]",
            border_style="blue",
        )
    )
    layout["events"].update(_event_panel(events))
    layout["summary"].update(_summary_panel(prices, prev, volumes))
    return layout


# ── main ──────────────────────────────────────────────────────────────────────

def run(ticks: int, interval: float) -> None:
    console = Console()

    console.print(Panel(
        "[cyan]Loading 2-year price history for 10 symbols…[/]",
        border_style="blue",
    ))

    provider = SimulatorProvider(db_session=None, seed=42)
    all_bars = provider.get_bars(WATCHLIST, date(2022, 1, 3), date(2024, 6, 28))
    frames   = {t: df.to_dict("records") for t, df in all_bars.items()}
    n_frames = min(len(v) for v in frames.values())

    # State
    history: dict[str, deque] = {t: deque(maxlen=HISTORY_LEN) for t in WATCHLIST}
    prices:  dict[str, float] = {}
    prev:    dict[str, float] = {}
    volumes: dict[str, int]   = {}
    quotes:  dict[str, tuple] = {}
    events:  deque            = deque(maxlen=EVENT_MAX)

    # Seed sparkline history with first HISTORY_LEN frames
    for i in range(min(HISTORY_LEN, n_frames)):
        for tkr in WATCHLIST:
            history[tkr].append(float(frames[tkr][i]["close"]))

    frame_idx  = HISTORY_LEN
    tick_count = 0
    t0         = time.monotonic()

    with Live(console=console, refresh_per_second=8, screen=True) as live:
        try:
            while True:
                if frame_idx >= n_frames:
                    frame_idx = HISTORY_LEN   # loop the dataset

                ts = time.strftime("%H:%M:%S")

                for tkr in WATCHLIST:
                    row  = frames[tkr][frame_idx]
                    px   = float(row["close"])
                    vol  = int(row["volume"])
                    bid  = round(px * (1 - 0.0001), 2)
                    ask  = round(px * (1 + 0.0001), 2)

                    prev[tkr]    = prices.get(tkr, px)
                    prices[tkr]  = px
                    volumes[tkr] = vol
                    quotes[tkr]  = (bid, ask)
                    history[tkr].append(px)

                    pct = ((px - prev[tkr]) / prev[tkr] * 100) if prev[tkr] else 0.0
                    if abs(pct) >= BIG_MOVE_PCT:
                        col = "green" if pct > 0 else "red"
                        icon = "⚡" if abs(pct) >= SHOCK_PCT else ("📈" if pct > 0 else "📉")
                        events.append(
                            f"[dim]{ts}[/]  [{col}]{'↑' if pct>0 else '↓'} {tkr:<6}[/]"
                            f"  {icon} [{col}]{'+' if pct>0 else ''}{pct:.2f}%  "
                            f"${px:,.2f}[/]"
                        )

                tick_count += 1
                live.update(_build_layout(
                    tick_count, ts, prices, prev, history, volumes, quotes, events
                ))
                frame_idx += 1

                if ticks and tick_count >= ticks:
                    break
                time.sleep(interval)

        except KeyboardInterrupt:
            pass

    elapsed = time.monotonic() - t0
    console.print(f"\n[bold green]✓[/] Demo complete — "
                  f"[bold]{tick_count}[/] ticks in [bold]{elapsed:.1f}s[/]\n")

    # Final summary to stdout
    pcts = {
        t: (prices[t] - prev.get(t, prices[t])) / prev.get(t, prices[t]) * 100
        for t in prices if prev.get(t)
    }
    if pcts:
        gainer = max(pcts, key=pcts.get)
        loser  = min(pcts, key=pcts.get)
        console.print(f"  Top gainer: [bold green]{gainer} +{pcts[gainer]:.2f}%[/]")
        console.print(f"  Top loser:  [bold red]{loser} {pcts[loser]:.2f}%[/]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="AI Trading Workstation — market data demo")
    ap.add_argument("--ticks",    type=int,   default=60,  help="ticks to run  (0 = ∞)")
    ap.add_argument("--interval", type=float, default=0.4, help="seconds between ticks")
    args = ap.parse_args()
    run(ticks=args.ticks, interval=args.interval)
