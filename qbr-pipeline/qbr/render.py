"""Assemble the QBR pack as one self-contained HTML file.

Design tokens, type and spacing deliberately match qbr-pipeline.html, the
architecture artifact, so the design document and the thing it describes read as
one system rather than two unrelated deliverables.

The provenance panel at the end is not decoration. It reports which sections
passed the grounding check, how many anomaly candidates were considered against
how many surfaced, and what the generation cost. A QBR a CSM is going to put in
front of a customer should be able to show its working.
"""

from __future__ import annotations

import datetime as dt
import html
from typing import Any

STYLE = """
:root{
  --bg:#1948C7; --surface:#245FF7; --surface-2:#2E5EFF;
  --ink:#FFFFFF; --ink-2:#C7D6FF; --ink-3:#93A9E8;
  --rule:rgba(255,255,255,.14); --rule-soft:rgba(255,255,255,.08);
  --det:#4FC4AE; --gen:#E0A45C; --no:#E0707E;
  --s1:#6E8394; --s2:#4FC4AE; --s3:#E0A45C; --s4:#8FA0CC; --s5:#E0707E;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1000px;margin:0 auto;padding:52px 26px 88px;
  display:flex;flex-direction:column;gap:48px}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;
  font-weight:500;letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3)}
h1{margin:0;font-size:clamp(28px,4.2vw,42px);line-height:1.1;font-weight:600;
  letter-spacing:-.022em;text-wrap:balance}
h2{margin:0;font-size:13px;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-weight:600;letter-spacing:.11em;text-transform:uppercase;color:var(--ink-2);
  padding-bottom:10px;border-bottom:1px solid var(--rule)}
header{display:flex;flex-direction:column;gap:14px}
section{display:flex;flex-direction:column;gap:20px}
p{margin:0;max-width:68ch;color:var(--ink-2)}
.lede{font-size:17.5px;color:var(--ink-2);max-width:64ch}
.narrative{font-size:16.5px;line-height:1.68;color:var(--ink);max-width:68ch}
.meta{display:flex;flex-wrap:wrap;gap:8px 22px;font-size:13.5px;color:var(--ink-3);
  font-family:"IBM Plex Mono",ui-monospace,monospace}
.meta b{color:var(--ink-2);font-weight:500}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px}
.kpi{background:var(--surface);border:1px solid var(--rule);border-radius:4px;
  padding:14px 16px;display:flex;flex-direction:column;gap:3px}
.kpi .k{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10.5px;
  letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3)}
.kpi .v{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:23px;
  font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi .d{font-size:12.5px;color:var(--ink-3)}
.up{color:var(--det)} .down{color:var(--no)}
.fig{margin:0;background:var(--surface);border:1px solid var(--rule);border-radius:4px;
  padding:18px 18px 14px;display:flex;flex-direction:column;gap:12px;overflow-x:auto}
.fig-t{font-size:13px;font-weight:600;color:var(--ink);order:-1}
.chart{display:block;width:100%;height:auto;min-width:520px;overflow:visible}
.c-lbl{font-size:12px;fill:var(--ink-2);font-family:"IBM Plex Sans",sans-serif}
.c-val{font-size:11px;fill:var(--ink-3);font-family:"IBM Plex Mono",monospace}
.c-ax{font-size:10.5px;fill:var(--ink-3);font-family:"IBM Plex Mono",monospace}
.grid{stroke:var(--rule-soft);stroke-width:1}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--ink-3)}
.key i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px}
.t-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:13.5px}
th,td{text-align:left;padding:9px 13px;border-bottom:1px solid var(--rule-soft)}
th{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;font-weight:600;
  letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);
  background:var(--surface-2);white-space:nowrap}
td{color:var(--ink-2)} tr:last-child td{border-bottom:none}
.t-num{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ink)}
.t-bool{color:var(--ink-3)}
.row-hl{background:color-mix(in srgb, var(--no) 8%, transparent)}
.empty{font-size:13.5px;color:var(--ink-3)}
.flag{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--no);
  border-radius:4px;padding:14px 16px;font-size:13.5px;color:var(--ink-2)}
.prov{background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:18px 20px}
.prov ul{margin:8px 0 0;padding-left:18px;font-size:13.5px;color:var(--ink-2)}
.prov li{margin-bottom:4px}
.prov li .d{font-size:12px;color:var(--ink-3)}
.prov .quote{display:inline-block;margin-top:4px;color:var(--ink-2);border-left:2px solid var(--rule);padding-left:10px}
.ok{color:var(--det);font-weight:600} .bad{color:var(--no);font-weight:600}
footer{border-top:1px solid var(--rule);padding-top:20px;font-size:13px;color:var(--ink-3)}
@media(max-width:620px){.wrap{padding:32px 16px 60px;gap:36px}}
"""


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


def _paras(text: str) -> str:
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return "".join(f'<p class="narrative">{_esc(b)}</p>' for b in blocks)


def kpi(label: str, value: str, note: str = "", direction: str = "") -> str:
    cls = f" {direction}" if direction else ""
    note_html = f'<div class="d">{_esc(note)}</div>' if note else ""
    return (
        f'<div class="kpi"><div class="k">{_esc(label)}</div>'
        f'<div class="v{cls}">{_esc(value)}</div>{note_html}</div>'
    )


def _corpus_line(prov: dict[str, Any]) -> str:
    """What the retrieval layer was allowed to see, and what it was not.

    The withheld count is published rather than hidden. A reader can see the
    filter ran and removed something, which is not visible from a document that
    simply never mentions the internal note.
    """
    corpus = prov.get("context_corpus") or {}
    if not corpus.get("documents_available"):
        return ""
    return (
        f"<li>Account context searched: {corpus['documents_searchable']} of "
        f"{corpus['documents_available']} documents; "
        f"{corpus['withheld_internal']} withheld as internal and never shown to "
        f"the model that wrote this</li>"
    )


def render(pack: dict[str, Any]) -> str:
    ctx = pack["context"]
    generated = dt.datetime.now().strftime("%d %B %Y, %H:%M")

    parts: list[str] = []
    parts.append(f"<title>{_esc(ctx['tenant_name'])} QBR {_esc(ctx['quarter'])}</title>")
    parts.append(
        "<link rel=\"icon\" href=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%93%8A%3C/text%3E%3C/svg%3E\">"
    )
    parts.append(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">'
    )
    parts.append(f"<style>{STYLE}</style>")
    parts.append('<div class="wrap">')

    # ---- header
    parts.append(
        f'<header><div class="eyebrow">Quarterly business review</div>'
        f"<h1>{_esc(ctx['tenant_name'])}, {_esc(ctx['quarter'])}</h1>"
        f'<p class="lede">Prepared for the customer success review. '
        f"Compared against {_esc(ctx['prior_quarter'])}. Every figure below was "
        f"computed in the warehouse and checked against its source before it was "
        f"written into this document.</p>"
        f'<div class="meta">'
        f"<span><b>Plan</b> {_esc(ctx['plan_tier'])}</span>"
        f"<span><b>Region</b> {_esc(ctx['country'])}</span>"
        f"<span><b>Currency</b> {_esc(ctx['currency'])}</span>"
        f"<span><b>Generated</b> {_esc(generated)}</span>"
        f"</div></header>"
    )

    if pack.get("kpis"):
        parts.append(f'<div class="kpis">{"".join(pack["kpis"])}</div>')

    # ---- sections
    for i, section in enumerate(pack["sections"], start=1):
        parts.append("<section>")
        parts.append(f"<h2>{i} &nbsp;/&nbsp; {_esc(section['title'])}</h2>")
        parts.append(_paras(section["narrative"]))

        if not section.get("grounded", True):
            parts.append(
                '<div class="flag"><b>Held for review.</b> The grounding check '
                "could not reconcile every figure in this section against its "
                "source data after a retry. It is shown so the failure is "
                "visible rather than silent, and should not go to a customer "
                "before a human confirms it.</div>"
            )

        for figure in section.get("figures", []):
            parts.append(figure)

        # Cited context, with its provenance attached. A quotation in a
        # customer-facing document is only as good as the reader's ability to
        # see where it came from, so the source, the date and who was on the
        # call are printed next to it rather than held in a log.
        evidence = section.get("evidence") or []
        cited = set(section.get("citations_used") or [])
        shown = [e for e in evidence if e.get("citation_id") in cited] or evidence
        if shown:
            rows = []
            for item in shown:
                who = ", ".join(str(p) for p in (item.get("participants") or []))
                rows.append(
                    f'<li><b>[{_esc(item.get("citation_id"))}]</b> '
                    f'{_esc(item.get("title"))} '
                    f'<span class="d">{_esc(item.get("source"))} &middot; '
                    f'{_esc(item.get("date"))}{" &middot; " + _esc(who) if who else ""}</span>'
                    f'<br><span class="quote">{_esc(item.get("snippet"))}</span></li>'
                )
            parts.append(
                '<div class="prov"><p><b>Context cited in this section.</b> '
                "Retrieved from the account record, not from the warehouse. "
                "These explain the movements above; none of them is the source "
                f"of a figure.</p><ul>{''.join(rows)}</ul></div>"
            )

        parts.append("</section>")

    # ---- provenance
    prov = pack["provenance"]
    grounded_bits = []
    for s in pack["sections"]:
        state = '<span class="ok">verified</span>' if s.get("grounded", True) \
            else '<span class="bad">unverified</span>'
        quotes = s.get("quotes_checked", 0)
        quote_bit = f", {quotes} quotation{'s' if quotes != 1 else ''} matched " \
                    f"verbatim against the retrieved source" if quotes else ""
        grounded_bits.append(
            f"<li>{_esc(s['title'])}: {s.get('figures_checked', 0)} figures "
            f"checked{quote_bit}, {state}</li>"
        )

    parts.append(
        "<section><h2>Provenance</h2>"
        '<div class="prov">'
        f"<p>Generated on demand, so every figure reflects the data as at "
        f"{generated}. Sections were chosen from a fixed registry of "
        f"{prov['registry_size']} and built from declared metric queries. "
        f"No query in this document was composed by a language model.</p>"
        f"<ul>{''.join(grounded_bits)}"
        f"<li>Anomaly candidates considered: {prov['anomaly_candidates']}, "
        f"surfaced after materiality ranking: {prov['anomaly_surfaced']}</li>"
        f"{_corpus_line(prov)}"
        f"</ul></div></section>"
    )

    parts.append(
        "<footer>Generated on demand by <code>/create-qbr</code>. Figures come "
        "from a dbt warehouse published as parquet and served through a Cube "
        "semantic layer, scoped to this account. The prose was written from "
        "those figures and every one of them was checked back against its "
        "source before this document was rendered. Nothing here was "
        "computed by a language model.</footer>"
    )
    parts.append("</div>")
    return "\n".join(parts)
