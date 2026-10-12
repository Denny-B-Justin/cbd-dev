"""
exports.py
----------
"Save PNG" and "Download CSV" for the charts, shared by the Dashboard and the
Country-wise analysis page. No callbacks live here; each page registers its own.

  toolbar(...)      the two small buttons that sit above a chart
  vm_csv(...)       a CSV (as text) of everything a map or frontier shows, from a view model
  components_csv()  a CSV of the efficiency component scores
  filename(...)     a tidy, dated file name

The PNG is made in the browser by assets/export.js (nothing is sent to the server).
The CSV is made here, from the same data the chart was drawn from, and handed to the
browser with dcc.Download.
"""

import csv
import io
import re
from datetime import date

from dash import html

# Excel opens a UTF-8 CSV correctly (Cote d'Ivoire, Sao Tome ...) only when it starts with this mark.
BOM = "﻿"


# ══════════════════════════════════════════════════════════════════════════
# Buttons
# ══════════════════════════════════════════════════════════════════════════

def toolbar(graph_id, csv_id, *, title=None, base=None, title_sel=None, sub_sel=None, sub_mode=None,
            legend_sel=None, key_sel=None, extra_cls=""):
    """
    Two small buttons for one chart.

    graph_id    id of the dcc.Graph that "Save PNG" captures
    csv_id      id (a string, or a dict for pattern-matching) of the "Download CSV" button
    title       heading printed at the top of the PNG (or title_sel: a CSS selector for an element that has it)
    base        start of the PNG file name, e.g. "pefa-grades" (default: made from the title)
    sub_sel     CSS selector of an element whose text becomes the PNG subtitle (e.g. the country summary)
    sub_mode    "filters" = use the dashboard's visible filter values as the subtitle
    legend_sel  CSS selector of the map legend to print under the chart
    key_sel     CSS selector of the colour key (selected country + peers) to print above the chart
    """
    attrs = {"data-png-graph": graph_id}
    if title:
        attrs["data-png-title"] = title
    if title_sel:
        attrs["data-png-title-sel"] = title_sel
    if base:
        attrs["data-png-file"] = base
    if sub_sel:
        attrs["data-png-sub-sel"] = sub_sel
    if sub_mode:
        attrs["data-png-sub-mode"] = sub_mode
    if legend_sel:
        attrs["data-png-legend-sel"] = legend_sel
    if key_sel:
        attrs["data-png-key-sel"] = key_sel
    return html.Div(className=("exp-row " + extra_cls).strip(), role="group", **{"aria-label": "Export this chart"}, children=[
        html.Button("Save PNG", type="button", className="exp-btn", title="Save this chart as an image", **attrs),
        html.Button("Download CSV", id=csv_id, n_clicks=0, type="button", className="exp-btn",
                    title="Download the data behind this chart"),
    ])


# ══════════════════════════════════════════════════════════════════════════
# CSV
# ══════════════════════════════════════════════════════════════════════════

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "data"


def filename(*parts, ext="csv"):
    """cbd_<part>_<part>_<YYYY-MM-DD>.csv"""
    bits = [p if (isinstance(p, str) and len(p) == 3 and p.isupper()) else slug(p) for p in parts if p]  # keep ISO3 codes
    return "cbd_" + "_".join(bits + [date.today().isoformat()]) + "." + ext


def _write(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return BOM + buf.getvalue()


def _cell(v):
    """Raw numbers stay numbers (full precision); missing values are left empty."""
    if v is None:
        return ""
    try:
        if v != v:                     # NaN
            return ""
    except Exception:
        pass
    return v


def vm_csv(vm, benchmark, scope=None, roles=None, indicator_labels=None):
    """
    One row per country in the view, in the order the map is ranked.

    vm                a view model (datasets.py). "continuous" and "categorical" views give the score,
                      its band and one column per indicator; the efficiency frontier gives the score
                      and the two values that place the dot.
    roles             optional {iso: "Selected" | "Peer"}; adds a Role column ("Other" for the rest)
    indicator_labels  optional {indicator: nicer label} for the column headers
    """
    rows = list(vm["rows"])
    labels = vm.get("labels") or []
    head = ["Benchmark"] + (["Scope"] if scope else []) + ["Country", "ISO3"] + (["Role"] if roles is not None else [])

    lead = lambda r: ([benchmark] + ([scope] if scope else []) + [r["name"], r["iso"]]
                      + ([roles.get(r["iso"], "Other")] if roles is not None else []))

    def ranked(items, score_of):
        """Highest score first when higher is better; countries without a score go last."""
        have = [i for i in items if _is_num(score_of(i))]
        none = [i for i in items if not _is_num(score_of(i))]
        have.sort(key=score_of, reverse=bool(vm.get("higher_is_better", True)))
        return have + none

    if vm["kind"] == "frontier":
        head += ["Efficiency score", "Public investment per person (log scale)", "Infrastructure quality (GQII)"]
        body = [lead(r) + [_cell(r.get("theta")), _cell(r.get("x")), _cell(r.get("y"))]
                for r in ranked(rows, lambda r: r.get("theta"))]
        return _write(head, body)

    indicators, seen = [], set()
    for r in rows:                                 # first-seen order, so the columns follow the table
        for p in r.get("popup") or []:
            if p["indicator"] and p["indicator"] not in seen:        # skip unnamed indicators
                seen.add(p["indicator"])
                indicators.append(p["indicator"])
    names = indicator_labels or {}
    # Categorical views (PEFA grades, GovTech status) have no meaningful number: their "score" is just
    # the category's position in the legend. They get one column, named after what the map shows.
    categorical = vm["kind"] == "categorical"
    head += ([vm.get("legend_title") or "Category"] if categorical else ["Score", "Band"]) \
        + [names.get(i, i) for i in indicators]

    body = []
    for r in ranked(rows, lambda r: r.get("score")):
        by_ind = {p["indicator"]: p["score"] for p in (r.get("popup") or [])}
        band = r.get("band")
        band_label = labels[band] if band is not None and band < len(labels) else ""
        body.append(lead(r) + ([band_label] if categorical else [_cell(r.get("score")), band_label])
                    + [_cell(by_ind.get(i)) for i in indicators])
    return _write(head, body)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def components_csv(df, names, roles=None, order=None):
    """Efficiency component scores: one row per country and component."""
    head = ["Country", "ISO3"] + (["Role"] if roles is not None else []) + ["Method", "Sample", "Component", "Score"]
    order = list(order or [])
    rows = []
    for _, r in df.iterrows():
        iso = r["ISO"]
        rows.append([names.get(iso, iso), iso] + ([roles.get(iso, "Other")] if roles is not None else [])
                    + [r.get("method", ""), r.get("sample", ""), r["short_name"], _cell(r["score"])])
    key_i = len(head) - 2
    rows.sort(key=lambda x: (x[0], order.index(x[key_i]) if x[key_i] in order else 999))
    return _write(head, rows)