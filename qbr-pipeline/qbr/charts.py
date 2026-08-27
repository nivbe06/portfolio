"""Inline SVG charts, hand-authored.

No chart library, for the same reason the design artifact has none: the report
must be a single self-contained file that opens anywhere, with no CDN, no build
step and no runtime. Every chart is a handful of rects and a polyline computed
from the rows the semantic layer returned.

Colours come from CSS custom properties so the charts follow the report's light
and dark themes rather than pinning a palette.
"""

from __future__ import annotations

import html
import re
from typing import Any

SERIES_VARS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"]


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt(value: Any, style: str = "number") -> str:
    """Render one figure for a customer-facing document.

    One decimal place, everywhere. A QBR is read, not recomputed, and a rate
    printed as 0.06691291376615996 is not a number anybody can act on. Ratios
    are shown as percentages because that is what they are; counts and money
    are shown whole.
    """
    v = _num(value, None) if value is not None else None
    if v is None:
        return "n/a"
    if style == "percent":
        return f"{v * 100:,.1f}%"
    if style == "signed_percent":
        return f"{v * 100:+,.1f}%"
    if style == "money":
        return f"{v:,.0f}"
    if style == "count":
        return f"{v:,.0f}"
    if style == "score":
        # Salience is a 0-1 weight. At one decimal place every score below 0.05
        # collapses to 0.0 and the ranking becomes unreadable, so it is shown
        # rescaled to a 0-100 index. Order and relative distance are preserved.
        return f"{v * 100:,.1f}"
    if abs(v) >= 1000 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.1f}"


# --------------------------------------------------------------------------
# Grouped bar: this quarter against last
# --------------------------------------------------------------------------
def grouped_bar(rows: list[dict], series: list[str], by: str,
                title: str, style: str = "percent", limit: int = 8) -> str:
    rows = [r for r in rows if any(r.get(s) is not None for s in series)][:limit]
    if not rows:
        return _empty(title)

    labels = [str(r.get(by, "")) for r in rows]
    peak = max(
        (_num(r.get(s)) for r in rows for s in series),
        default=1.0,
    ) or 1.0

    row_h, gap, bar_h = 46, 10, 15
    left, right = 210, 70
    width = 760
    height = 34 + len(rows) * (row_h + gap)
    plot_w = width - left - right

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_esc(title)}" class="chart">'
    ]

    for i, (row, label) in enumerate(zip(rows, labels)):
        y = 24 + i * (row_h + gap)
        parts.append(
            f'<text x="0" y="{y + 16}" class="c-lbl">{_esc(label[:30])}</text>'
        )
        for j, key in enumerate(series):
            value = _num(row.get(key))
            w = max(1.0, (value / peak) * plot_w)
            by_ = y + j * (bar_h + 3)
            parts.append(
                f'<rect x="{left}" y="{by_}" width="{w:.1f}" height="{bar_h}" '
                f'rx="2" fill="{SERIES_VARS[j % len(SERIES_VARS)]}"/>'
            )
            parts.append(
                f'<text x="{left + w + 8:.1f}" y="{by_ + bar_h - 3}" class="c-val">'
                f'{fmt(row.get(key), style)}</text>'
            )

    parts.append("</svg>")
    legend = " ".join(
        f'<span class="key"><i style="background:{SERIES_VARS[j % len(SERIES_VARS)]}"></i>'
        f'{_esc(_pretty(s))}</span>'
        for j, s in enumerate(series)
    )
    return _figure(title, "".join(parts), legend)


# --------------------------------------------------------------------------
# Line: a metric over quarters, one line per group
# --------------------------------------------------------------------------
def line(rows: list[dict], metric: str, by: str, group: str | None,
         title: str, style: str = "number", max_groups: int = 5) -> str:
    points: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        if r.get(metric) is None:
            continue
        key = str(r.get(group, "all")) if group else "all"
        points.setdefault(key, []).append((str(r.get(by, "")), _num(r.get(metric))))

    if not points:
        return _empty(title)

    # Keep the busiest few series; a chart with fifteen lines communicates nothing.
    ordered = sorted(points.items(), key=lambda kv: -sum(v for _, v in kv[1]))[:max_groups]
    x_labels = sorted({x for _, series in ordered for x, _ in series})
    if len(x_labels) < 2:
        return _empty(title)

    peak = max((v for _, series in ordered for _, v in series), default=1.0) or 1.0
    width, height = 760, 260
    left, right, top, bottom = 56, 130, 18, 34
    plot_w = width - left - right
    plot_h = height - top - bottom
    step = plot_w / (len(x_labels) - 1)

    def x_at(label: str) -> float:
        return left + x_labels.index(label) * step

    def y_at(value: float) -> float:
        return top + plot_h - (value / peak) * plot_h

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_esc(title)}" class="chart">'
    ]

    # Horizontal guides
    for frac in (0, 0.5, 1.0):
        gy = top + plot_h - frac * plot_h
        parts.append(
            f'<line x1="{left}" y1="{gy:.1f}" x2="{left + plot_w}" y2="{gy:.1f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{gy + 4:.1f}" class="c-ax" text-anchor="end">'
            f'{fmt(peak * frac, style)}</text>'
        )

    for label in x_labels:
        parts.append(
            f'<text x="{x_at(label):.1f}" y="{height - 12}" class="c-ax" '
            f'text-anchor="middle">{_esc(label)}</text>'
        )

    for j, (name, series) in enumerate(ordered):
        series = sorted(series, key=lambda p: x_labels.index(p[0]))
        colour = SERIES_VARS[j % len(SERIES_VARS)]
        coords = " ".join(f"{x_at(x):.1f},{y_at(v):.1f}" for x, v in series)
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{colour}" '
            f'stroke-width="2" stroke-linejoin="round"/>'
        )
        for x, v in series:
            parts.append(
                f'<circle cx="{x_at(x):.1f}" cy="{y_at(v):.1f}" r="2.6" fill="{colour}"/>'
            )
        last_x, last_v = series[-1]
        parts.append(
            f'<text x="{x_at(last_x) + 10:.1f}" y="{y_at(last_v) + 4:.1f}" '
            f'class="c-val" fill="{colour}">{_esc(_pretty(name)[:16])}</text>'
        )

    parts.append("</svg>")
    return _figure(title, "".join(parts), "")


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------
FORMATS = {
    "usage_qoq": "signed_percent",
    "redemption_rate": "percent",
    "prior_redemption_rate": "percent",
    "redemption_rate_qoq": "signed_percent",
    "discount_value_qoq": "signed_percent",
    "relative_change": "signed_percent",
    "metric_value": "number",
    "baseline_mean": "number",
    "discount_value": "money",
    "usage_count": "count",
    "prior_usage_count": "count",
    "redemptions": "count",
    "redemption_attempts": "count",
    "rejections": "count",
    "effects_fired": "count",
    "volume": "count",
    "salience": "score",
    "z_score": "number",
}

# metric_value and baseline_mean carry whatever the row's metric measures, so
# they cannot be formatted from the column name alone. A redemption rate and an
# effect count share the column.
RATE_METRICS = {"redemption_rate", "server_error_rate"}


def _looks_numeric(value: Any) -> bool:
    """The semantic layer returns numbers as strings. Treat them as numbers."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
        except (TypeError, ValueError):
            return False
        return value.strip() != ""
    return False


ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})([T ].*)?$")


def _as_date(value: Any) -> str | None:
    """Trim a semantic-layer timestamp to the date. Weeks have no time of day."""
    if not isinstance(value, str):
        return None
    match = ISO_DATE_RE.match(value.strip())
    return match.group(1) if match else None


def _style_for(column: str, row: dict) -> str:
    """The format for one cell, using the row when the column is ambiguous."""
    if column in ("metric_value", "baseline_mean"):
        return "percent" if row.get("metric_name") in RATE_METRICS else "count"
    return FORMATS.get(column, "number")


def table(rows: list[dict], columns: list[str], title: str,
          highlight: str | None = None, limit: int = 15) -> str:
    rows = rows[:limit]
    if not rows:
        return _empty(title)

    head = "".join(f"<th>{_esc(_pretty(c))}</th>" for c in columns)
    body = []
    for r in rows:
        cells = []
        for c in columns:
            value = r.get(c)
            if isinstance(value, bool):
                shown = "yes" if value else "no"
                cls = "t-bool"
            elif _as_date(value):
                shown = _as_date(value)
                cls = ""
            elif _looks_numeric(value):
                shown = fmt(value, _style_for(c, r))
                cls = "t-num"
            else:
                shown = _pretty(str(value)) if c in ("adoption_state", "metric_name") else str(value or "")
                cls = ""
            cells.append(f'<td class="{cls}">{_esc(shown)}</td>')
        cls = ' class="row-hl"' if highlight and r.get(highlight) else ""
        body.append(f"<tr{cls}>{''.join(cells)}</tr>")

    return (
        f'<figure class="fig"><figcaption class="fig-t">{_esc(title)}</figcaption>'
        f'<div class="t-wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div></figure>"
    )


# --------------------------------------------------------------------------
def _pretty(name: str) -> str:
    return name.replace("_", " ").strip()


def _figure(title: str, svg: str, legend: str) -> str:
    legend_html = f'<div class="legend">{legend}</div>' if legend else ""
    return (
        f'<figure class="fig"><figcaption class="fig-t">{_esc(title)}</figcaption>'
        f"{legend_html}{svg}</figure>"
    )


def _empty(title: str) -> str:
    return (
        f'<figure class="fig"><figcaption class="fig-t">{_esc(title)}</figcaption>'
        f'<p class="empty">No data for this section in the selected period.</p></figure>'
    )
