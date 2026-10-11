"""
utils.py
--------
Presentation helpers for the Country Benchmarking Dashboard: design constants,
colour-band maths, Plotly figure builders and the small reusable Dash
components (header, footer, legend, KPI strip, ranking list, country profile).

Nothing in here talks to Databricks - queries.py does that. This module takes
the "view model" produced by datasets.py and turns it into pixels.
"""

import json
import os

import plotly.graph_objects as go
from dash import html, dcc

# ══════════════════════════════════════════════════════════════════════════
# Brand + design constants
# ══════════════════════════════════════════════════════════════════════════
# Taken from the CBD logo: indigo, teal and orange, on a deep navy.

NAVY = "#0B2B4B"
INDIGO = "#2E3C8F"
TEAL = "#64CBD6"
ORANGE = "#F26B23"

BASE_TITLE = "Country Benchmarking Dashboard"
FONT_STACK = "'Fira Sans', 'Segoe UI', Arial, sans-serif"

# Orange (low) -> indigo (high). Chosen to stay readable for people with
# red-green colour blindness, unlike the previous red/yellow/green ramp.
HEX_CODES_5 = ["#C4501B", "#F2A65A", "#F3E3A3", "#6CBFCB", "#2E3C8F"]
HEX_CODES_3 = ["#C4501B", "#F3E3A3", "#2E3C8F"]
NO_DATA_COLOR = "#C9D1DC"
COUNTRY_COLORS = ["#4345aa", "#64cbd6", "#f26b23", "#37b37f", "#3675b7"]

HOME_HREF = "?"                      # relative on purpose - see page_href()
DASHBOARD_HREF = "?page=dashboard"
RELEASE_NOTES_URL = "https://pim-pam.net/cbd-release-notes/"


GLOBAL_REGIONS = [
    "Europe and Central Asia",
    "South Asia",
    "Middle East and North Africa",
    "East Asia & Pacific",
    "Western and Central Africa",
    "Eastern and South Africa",
    "Latin and Central America",
    "North America",
]

LOCAL_REGIONS = [
    "Western Balkans 6",
    "Central Asia",
    "European Union 27",
]

# (lat, lon, zoom) per region. Zoom is tuned for a ~1000 px wide map so each
# region fills the frame; the old single zoom (3.5) cut most regions off.
MAP_VIEWS = {
    "Western Balkans 6": (43.0, 19.6, 5.2),
    "Central Asia": (43.0, 67.0, 3.3),
    "European Union 27": (52.0, 12.0, 3.2),
    "Europe and Central Asia": (51.0, 38.0, 2.3),
    "East Asia & Pacific": (2.0, 122.0, 1.5),
    "Latin and Central America": (-14.0, -68.0, 1.5),
    "South Asia": (22.0, 79.0, 3.0),
    "Eastern and South Africa": (-6.0, 30.0, 2.2),
    "Western and Central Africa": (7.0, 10.0, 2.5),
    "Middle East and North Africa": (26.0, 22.0, 3.0),
    "North America": (54.0, -100.0, 1.75),
    "World": (20.0, 10.0, 1.4),
}


def get_map_style() -> str:
    """Basemap. Defaults to what the app used before; override with CBD_MAP_STYLE
    (e.g. 'carto-positron' for a cleaner, label-light basemap)."""
    return os.environ.get("CBD_MAP_STYLE", "open-street-map")


def page_href(page_key, view=None):
    """
    Internal link using ?page=xxx (prefix-agnostic, so it keeps working when
    Posit Connect mounts the app under /content/<guid>/). The selected topic
    lives in the URL hash, e.g. ?page=dashboard#gtmi, so views are shareable.
    """
    if not page_key:
        return HOME_HREF
    href = f"?page={page_key}"
    return f"{href}#{view}" if view else href


# ══════════════════════════════════════════════════════════════════════════
# Colour-band maths (unchanged behaviour)
# ══════════════════════════════════════════════════════════════════════════

def heatmap_bucket(score, vmin, vmax):
    """0-4 bucket index for a continuous score, or None if score is missing."""
    if score is None:
        return None
    if vmax == vmin:
        return 2
    normalized = (score - vmin) / (vmax - vmin)
    if normalized < 0.2:
        return 0
    if normalized < 0.4:
        return 1
    if normalized < 0.6:
        return 2
    if normalized < 0.8:
        return 3
    return 4


def categorical_bucket(score, n_categories):
    """Direct integer bucket for an already-categorical score (e.g. grade index)."""
    if score is None:
        return None
    idx = int(round(score))
    return max(0, min(n_categories - 1, idx))


def _discrete_colorscale(colors):
    n = len(colors)
    scale = []
    for i, c in enumerate(colors):
        scale.append([i / n, c])
        scale.append([(i + 1) / n, c])
    return scale


def ink_on(hex_color):
    """Readable text colour (dark or white) for a given background hex."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return NAVY if lum > 0.6 else "#FFFFFF"


def fmt_num(v, fmt="{:.2f}"):
    if v is None:
        return "N/A"
    if isinstance(v, (int, float)):
        return fmt.format(v)
    return str(v)


def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ══════════════════════════════════════════════════════════════════════════
# Figures
# ══════════════════════════════════════════════════════════════════════════

_HOVER = dict(bgcolor="white", font_size=13, font_family=FONT_STACK, align="left",
              bordercolor="#D5DCE6")
_AXIS_FONT = dict(family=FONT_STACK, size=12, color="#44546A")


def build_map_figure(vm, geojson, rev):
    """
    Choropleth for a continuous / categorical view model.

    Trace 0 = the coloured countries. Trace 1 = an empty "selection outline"
    trace that app.py fills with a Patch() when a country is selected, so
    picking a country never re-sends the (large) boundary geometry.

    rev: uirevision string. It changes with the view/region so the map
    re-frames itself, but stays the same when only a pillar changes, so
    the user's pan/zoom survives.
    """
    colors = vm["colors"]
    n_colors = len(colors)
    colorscale = _discrete_colorscale(list(colors) + [NO_DATA_COLOR])

    locations, z, opacity, customdata = [], [], [], []
    for r in vm["rows"]:
        band = r["band"] if r["band"] is not None else n_colors   # last band = no data
        locations.append(r["iso"])
        z.append(band + 0.5)
        opacity.append(0.86 if r["band"] is not None else 0.7)
        customdata.append([r["iso"], r["tooltip"]])

    lat, lon, zoom = MAP_VIEWS.get(vm.get("region"), MAP_VIEWS["World"])

    fig = go.Figure()
    fig.add_trace(go.Choroplethmap(
        geojson=geojson, locations=locations, z=z,
        featureidkey="properties.ISO_A3",
        colorscale=colorscale, zmin=0, zmax=n_colors + 1, showscale=False,
        marker=dict(opacity=opacity, line=dict(width=0.6, color="#ffffff")),
        customdata=customdata,
        hovertemplate="%{customdata[1]}<extra></extra>",
    ))
    fig.add_trace(go.Choroplethmap(
        geojson={"type": "FeatureCollection", "features": []}, locations=[], z=[],
        featureidkey="properties.ISO_A3", showscale=False, hoverinfo="skip",
    ))
    fig.update_layout(
        map=dict(style=get_map_style(), center={"lat": lat, "lon": lon}, zoom=zoom),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=_HOVER,
        font=dict(family=FONT_STACK),
        uirevision=rev,
    )
    return fig


def selection_outline_trace(iso, geojson):
    """Dict for trace 1 of the map: a transparent fill with a bold outline."""
    return {
        "type": "choroplethmap",
        "geojson": geojson,
        "locations": [iso],
        "z": [1],
        "featureidkey": "properties.ISO_A3",
        "colorscale": [[0, "rgba(255,255,255,0)"], [1, "rgba(255,255,255,0)"]],
        "showscale": False,
        "marker": {"opacity": 1, "line": {"width": 3.2, "color": NAVY}},
        "hoverinfo": "skip",
    }


EMPTY_OUTLINE_TRACE = {
    "type": "choroplethmap",
    "geojson": {"type": "FeatureCollection", "features": []},
    "locations": [], "z": [],
    "featureidkey": "properties.ISO_A3", "showscale": False, "hoverinfo": "skip",
}


def build_frontier_figure(vm, selected):
    """Efficiency frontier scatter (DEA + FDH lines), selected countries highlighted."""
    rows = vm["rows"]
    dea, fdh = vm["frontier"]["dea"], vm["frontier"]["fdh"]
    sel = list(selected or [])

    fig = go.Figure()
    others = [p for p in rows if p["iso"] not in sel]
    fig.add_trace(go.Scatter(
        x=[p["x"] for p in others], y=[p["y"] for p in others],
        mode="markers", name="Other countries",
        marker=dict(color="#B8C3D3", size=8, opacity=0.8),
        customdata=[[p["iso"], p["name"]] for p in others],
        hovertemplate="<b>%{customdata[1]}</b><br>Public investment: %{x:.2f}"
                      "<br>Infrastructure quality: %{y:.2f}<extra></extra>",
    ))
    if dea:
        pts = sorted(dea, key=lambda p: p["x"])
        fig.add_trace(go.Scatter(
            x=[p["x"] for p in pts], y=[p["y"] for p in pts], mode="lines",
            name="DEA frontier", line=dict(color=INDIGO, width=2.4), hoverinfo="skip"))
    if fdh:
        pts = sorted(fdh, key=lambda p: p["x"])
        fig.add_trace(go.Scatter(
            x=[p["x"] for p in pts], y=[p["y"] for p in pts], mode="lines",
            name="FDH frontier", line=dict(color=ORANGE, width=2.4, dash="dash"),
            hoverinfo="skip"))
    for i, iso in enumerate(sel):
        pts = [p for p in rows if p["iso"] == iso]
        if not pts:
            continue
        color = COUNTRY_COLORS[i % len(COUNTRY_COLORS)]
        fig.add_trace(go.Scatter(
            x=[p["x"] for p in pts], y=[p["y"] for p in pts],
            mode="markers+text", name=pts[0]["name"], showlegend=False,
            text=[pts[0]["name"]], textposition="top center",
            textfont=dict(family=FONT_STACK, size=12, color=NAVY),
            marker=dict(color=color, size=14, line=dict(width=2, color="#ffffff")),
            customdata=[[p["iso"], p["name"]] for p in pts],
            hovertemplate="<b>%{customdata[1]}</b><br>Public investment: %{x:.2f}"
                          "<br>Infrastructure quality: %{y:.2f}<extra></extra>",
        ))

    fig.update_layout(
        margin=dict(l=64, r=20, t=44, b=56),
        font=dict(family=FONT_STACK, color="#44546A"),
        xaxis=dict(title=dict(text="Public investment per person (log scale)", font=_AXIS_FONT),
                   gridcolor="#E8EDF3", zeroline=False, tickfont=_AXIS_FONT),
        yaxis=dict(title=dict(text="Infrastructure quality (GQII)", font=_AXIS_FONT),
                   gridcolor="#E8EDF3", zeroline=False, tickfont=_AXIS_FONT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(family=FONT_STACK, size=12)),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=_HOVER, uirevision="frontier", clickmode="event",
    )
    return fig


def build_components_figure(df, selected, names):
    """Grouped bar chart of the efficiency components for the selected countries."""
    fig = go.Figure()
    if df is None or df.empty or not selected:
        return fig
    by_var = {}
    for _, row in df.iterrows():
        short = row["short_name"] or ""
        by_var.setdefault(short, {})[row["ISO"]] = row["score"]
    ordered = _EF_ORDER_HOLDER["order"]
    names_sorted = sorted(by_var.keys(), key=lambda n: ordered.index(n) if n in ordered else 999)
    for i, iso in enumerate(selected):
        fig.add_trace(go.Bar(
            x=names_sorted, y=[by_var[n].get(iso) for n in names_sorted],
            name=names.get(iso, iso), marker_color=COUNTRY_COLORS[i % len(COUNTRY_COLORS)],
        ))
    fig.update_layout(
        barmode="group", margin=dict(l=56, r=16, t=36, b=96),
        font=dict(family=FONT_STACK, color="#44546A"),
        yaxis=dict(title=dict(text="Score", font=_AXIS_FONT), gridcolor="#E8EDF3", tickfont=_AXIS_FONT),
        xaxis=dict(tickfont=dict(family=FONT_STACK, size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(family=FONT_STACK, size=12)),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)", hoverlabel=_HOVER,
    )
    return fig


# app.py sets this to queries.EF_SHORT_NAME_ORDER at start-up (utils.py never imports queries).
_EF_ORDER_HOLDER = {"order": []}


def set_ef_order(order):
    _EF_ORDER_HOLDER["order"] = list(order)


# ══════════════════════════════════════════════════════════════════════════
# Small building blocks
# ══════════════════════════════════════════════════════════════════════════

def icon(name, cls=""):
    return html.Span(className=f"ico ico-{name} {cls}".strip(), **{"aria-hidden": "true"})


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _band_edges(vm):
    lo, hi = vm["vmin"], vm["vmax"]
    return [lo + (hi - lo) * i / 5 for i in range(6)]


def _edge_fmt(vm):
    span = abs((vm["vmax"] or 0) - (vm["vmin"] or 0))
    return "{:.0f}" if span >= 20 else "{:.2f}"


def stats_for(vm):
    """Summary numbers shared by the KPI strip, legend and profile."""
    rows = vm["rows"]
    scored = [r for r in rows if r["band"] is not None]
    counts = {}
    for r in scored:
        counts[r["band"]] = counts.get(r["band"], 0) + 1
    out = {"n_total": len(rows), "n_scored": len(scored), "counts": counts}
    nums = [r["score"] for r in scored if _is_num(r["score"])]
    if vm["kind"] == "continuous" and nums:
        out["mean"] = sum(nums) / len(nums)
        top = max(scored, key=lambda r: r["score"])
        bottom = min(scored, key=lambda r: r["score"])
        out["top"], out["bottom"] = top, bottom
    return out


def sorted_rows(vm):
    """Rows best-first, no-data rows last."""
    rows = vm["rows"]
    if vm["kind"] == "frontier":
        has = [r for r in rows if r.get("theta") is not None]
        no = [r for r in rows if r.get("theta") is None]
        return sorted(has, key=lambda r: (-r["theta"], r["name"])), sorted(no, key=lambda r: r["name"])
    has = [r for r in rows if r["band"] is not None]
    no = [r for r in rows if r["band"] is None]
    if vm["kind"] == "continuous":
        has.sort(key=lambda r: (-r["score"], r["name"]))
    else:
        sign = -1 if vm["higher_is_better"] else 1
        has.sort(key=lambda r: (sign * r["band"], r["name"]))
    return has, sorted(no, key=lambda r: r["name"])


# ══════════════════════════════════════════════════════════════════════════
# Header / footer
# ══════════════════════════════════════════════════════════════════════════

def build_header(current_page="", logo_src=None):
    """current_page: '' (overview) or 'dashboard'."""
    def nav_link(label, href, key):
        current = key == current_page
        return dcc.Link(label, href=href, className="nav-link" + (" is-current" if current else ""))

    def ext_link(label, href):
        return html.A([label, icon("external")], href=href, target="_blank",
                      rel="noopener noreferrer", className="nav-link")

    return html.Header(
        className="app-header",
        children=html.Div(className="app-header-inner", children=[
            dcc.Link(
                [html.Img(src=logo_src, className="header-logo", alt="CBD"),
                 html.Span(BASE_TITLE, className="header-name")],
                href=HOME_HREF, className="header-brand",
            ),
            html.Nav(className="header-nav", **{"aria-label": "Main"}, children=[
                nav_link("Overview", HOME_HREF, ""),
                nav_link("Dashboard", DASHBOARD_HREF, "dashboard"),
                ext_link("Release notes", RELEASE_NOTES_URL),
            ]),
        ]),
    )


def build_footer(wb_logo_src=None):
    return html.Footer(className="site-footer", children=html.Div(className="site-footer-inner", children=[
        html.Div(className="footer-about", children=[
            html.Img(src=wb_logo_src, className="footer-wb", alt="World Bank Group") if wb_logo_src else None,
            html.P("A World Bank initiative promoting digital tools for smarter public investment and "
                   "asset management"),
        ]),
        html.Nav(className="footer-links", **{"aria-label": "Footer"}, children=[
            html.A("Release notes", href=RELEASE_NOTES_URL, target="_blank", rel="noopener noreferrer"),
        ]),
    ]))


# ══════════════════════════════════════════════════════════════════════════
# Dashboard components
# ══════════════════════════════════════════════════════════════════════════

def build_context(spec):
    """Title, the question it answers, how to read it, and a collapsible 'About'."""
    about_items = []
    for label, text in spec["about"]:
        about_items += [html.Dt(label), html.Dd(text)]
    about_items += [
        html.Dt("Official name"), html.Dd(spec["official"]),
        html.Dt("Coverage and source"), html.Dd(f"{spec['coverage']}. Source: {spec['source']}."),
    ]
    return html.Div(className="context", children=[
        html.Div(className="context-main", children=[
            html.H1(spec["title"], className="context-title"),
            html.P(spec["question"], className="context-question"),
        ]),
        html.Div(className="context-side", children=[
            html.P([html.Strong("How to read this. "), spec["how_to"]], className="context-howto"),
            html.Details(className="about", children=[
                html.Summary([icon("info"), "About this data"]),
                html.Dl(about_items, className="about-list"),
            ]),
        ]),
    ])


def _legend_items(vm, counts):
    n = len(vm["colors"])
    edges, efmt = (_band_edges(vm), _edge_fmt(vm)) if vm["kind"] == "continuous" else (None, None)

    def item(color, label, rng, count):
        return html.Li(className="legend-item", children=[
            html.Span(className="legend-swatch", style={"backgroundColor": color}),
            html.Span(className="legend-text", children=[
                html.Span(label, className="legend-label"),
                html.Span(rng, className="legend-range") if rng else None,
            ]),
            html.Span(str(count), className="legend-count"),
        ])

    items = []
    for i in range(n):
        rng = f"{efmt.format(edges[i])} to {efmt.format(edges[i + 1])}" if edges else None
        items.append(item(vm["colors"][i], vm["labels"][i], rng, counts.get(i, 0)))
    items.append(item(NO_DATA_COLOR, "No data", None, vm["n_nodata"]))
    return items


def build_legend(vm):
    """Legend under the map that doubles as a summary: band, value range, number of countries."""
    st = stats_for(vm)
    vm = dict(vm, n_nodata=st["n_total"] - st["n_scored"])
    head = [html.P(vm["legend_title"], className="legend-title")]
    head.append(html.P(vm["legend_note"] or "Bold numbers show how many countries are in each group.",
                       className="legend-note"))
    return html.Div(className="legend", children=[
        html.Div(head, className="legend-head"),
        html.Ul(_legend_items(vm, st["counts"]), className="legend-list"),
    ])


def _kpi(label, value, sub=None, tone=None):
    return html.Div(className="kpi" + (f" kpi-{tone}" if tone else ""), children=[
        html.Dt(label), html.Dd(value, className="kpi-value"),
        html.Dd(sub or "\u00a0", className="kpi-sub"),
    ])


def build_kpis(vm, selected=None):
    st = stats_for(vm)
    fmt = vm.get("score_fmt", "{:.2f}")
    mode = vm["kpi"]["mode"]
    n_tot, n_sc = st["n_total"], st["n_scored"]
    missing = n_tot - n_sc
    covered = _kpi("Countries with data", str(n_sc),
                   f"{missing} more with no data" if missing else f"of {n_tot} in this view")
    items = [covered]

    if mode == "score" and n_sc:
        scale = f"on a scale of {fmt_num(vm['vmin'], '{:g}')} to {fmt_num(vm['vmax'], '{:g}')}"
        items += [
            _kpi("Average score", fmt_num(st["mean"], fmt), scale),
            _kpi("Highest", fmt_num(st["top"]["score"], fmt), st["top"]["name"]),
            _kpi("Lowest", fmt_num(st["bottom"]["score"], fmt), st["bottom"]["name"]),
        ]
    elif mode == "split" and n_sc:
        above = sum(1 for r in vm["rows"] if r["band"] is not None and _is_num(r["score"]) and r["score"] > 0)
        items += [
            _kpi("Ahead of regional average", str(above), "countries above 0"),
            _kpi("Behind regional average", str(n_sc - above), "countries below 0"),
            _kpi("Highest", fmt_num(st["top"]["score"], "{:.0f}"), st["top"]["name"]),
        ]
    elif mode == "groups":
        for g in vm["kpi"]["groups"]:
            c = sum(st["counts"].get(b, 0) for b in g["bands"])
            share = f"{round(100 * c / n_sc)}% of countries" if n_sc else None
            items.append(_kpi(g["label"], str(c), share))
    elif mode == "frontier":
        thetas = [r["theta"] for r in vm["rows"] if r.get("theta") is not None]
        on = sum(1 for t in thetas if t >= 0.9999)
        items = [
            _kpi("Countries analysed", str(len(thetas)), "with spending and quality data"),
            _kpi("On the efficient frontier", str(on), "best quality for their spending"),
            _kpi("Average efficiency", fmt_num(sum(thetas) / len(thetas) if thetas else None),
                 "1.00 = on the frontier"),
        ]
    return html.Dl(items, className=f"kpis kpis-{len(items)}")


# ── Detail pane ──────────────────────────────────────────────────────────────

TERNARY = {0: "None", 0.5: "Partial", 1: "Present"}


def _band_chip(vm, band):
    if band is None:
        return html.Span(className="chip chip-nodata", children="No data")
    color = vm["colors"][band]
    return html.Span(className="chip", style={"backgroundColor": color, "color": ink_on(color)},
                     children=vm["labels"][band])


def _rank_rows(vm, rows, selected, scored=True):
    fmt = vm.get("score_fmt", "{:.2f}")
    out = []
    lo, hi = vm.get("vmin"), vm.get("vmax")
    for i, r in enumerate(rows, start=1):
        sel = r["iso"] in selected
        if vm["kind"] == "continuous" and scored:
            pct = 0 if hi == lo else max(0, min(1, (r["score"] - lo) / (hi - lo)))
            color = vm["colors"][r["band"]]
            tail = [
                html.Span(className="rank-bar", children=html.I(style={"width": f"{pct * 100:.0f}%",
                                                                       "backgroundColor": color})),
                html.Span(fmt_num(r["score"], fmt if vm["vmax"] - vm["vmin"] < 20 else "{:.0f}"),
                          className="rank-score"),
            ]
        elif vm["kind"] == "frontier" and scored:
            pct = max(0, min(1, r["theta"]))
            tail = [
                html.Span(className="rank-bar", children=html.I(style={"width": f"{pct * 100:.0f}%",
                                                                       "backgroundColor": INDIGO})),
                html.Span(fmt_num(r["theta"]), className="rank-score"),
            ]
        elif vm["kind"] == "categorical" and scored:
            tail = [_band_chip(vm, r["band"])]
        else:
            tail = [html.Span("No data", className="rank-nodata")]
        out.append(html.Li(html.Button(
            [html.Span(str(i) if scored else "", className="rank-n"),
             html.Span(r["name"], className="rank-name")] + tail,
            id={"type": "rank-row", "iso": r["iso"]}, n_clicks=0,
            className="rank-row" + (" is-selected" if sel else ""),
            **{"aria-pressed": "true" if sel else "false"},
        )))
    return out


def _ranking_block(vm, selected, heading, help_text):
    has, no = sorted_rows(vm)
    children = [html.H3(heading, className="pane-h"), html.P(help_text, className="pane-help"),
                html.Ul(_rank_rows(vm, has, selected), className="rank-list")]
    if no:
        children += [html.H4(f"No data ({len(no)})", className="pane-h2"),
                     html.Ul(_rank_rows(vm, no, selected, scored=False), className="rank-list rank-list-muted")]
    return children


def _indicator_rows(vm, popup_rows):
    mode = vm["popup"]["mode"]
    fmt = "{:.2f}"
    items = []
    for r in popup_rows:
        name, val = r.get("indicator", ""), r.get("score")
        if mode == "bars" and _is_num(val):
            lo, hi = vm["popup"]["lo"], vm["popup"]["hi"]
            pct = max(0, min(1, (val - lo) / (hi - lo))) if hi != lo else 0
            band = heatmap_bucket(val, lo, hi)
            color = HEX_CODES_5[band]
            label = TERNARY.get(val) if vm["popup"].get("ternary") and val in TERNARY else None
            items.append(html.Li(className="ind-row", children=[
                html.Span(name, className="ind-name"),
                html.Span(className="ind-bar", children=html.I(style={"width": f"{pct * 100:.0f}%",
                                                                      "backgroundColor": color})),
                html.Span(label or fmt.format(val), className="ind-val"),
            ]))
        elif mode == "grades" and isinstance(val, str):
            try:
                color = vm["colors"][vm["labels"].index(val)]
                chip = html.Span(val, className="chip", style={"backgroundColor": color, "color": ink_on(color)})
            except ValueError:
                chip = html.Span(val, className="chip chip-nodata")
            items.append(html.Li(className="ind-row ind-row-plain", children=[
                html.Span(name, className="ind-name"), chip]))
        else:
            items.append(html.Li(className="ind-row ind-row-plain", children=[
                html.Span(name, className="ind-name"),
                html.Span(fmt_num(val, fmt), className="ind-val ind-val-plain")]))
    return html.Ul(items, className="ind-list")


def build_profile(vm, iso):
    """Right-hand pane for a selected country on a map view."""
    row = next((r for r in vm["rows"] if r["iso"] == iso), None)
    back = html.Button([icon("chevron-left"), "All countries"], id={"type": "sel-clear", "i": 0}, n_clicks=0,
                       className="link-btn")
    if row is None:
        return [back, html.H3("Not in this view", className="profile-name"),
                html.P("This country is not part of the current filter.", className="pane-help")]

    st = stats_for(vm)
    fmt = vm.get("score_fmt", "{:.2f}")
    head = [back, html.H3(row["name"], className="profile-name")]

    if row["band"] is None:
        head.append(html.P("No score is available for this country in the current view.",
                           className="pane-help"))
        if row["popup"]:
            head += [html.H4("What is available", className="pane-h2"), _indicator_rows(vm, row["popup"])]
        return head

    if vm["kind"] == "continuous":
        has, _ = sorted_rows(vm)
        rank = 1 + sum(1 for r in has if r["score"] > row["score"])
        score_txt = fmt_num(row["score"], "{:.0f}" if vm["vmax"] - vm["vmin"] >= 20 else fmt)
        meta = [f"Ranks {ordinal(rank)} of {st['n_scored']} countries in this view."]
        if vm["kpi"]["mode"] == "score":
            diff = row["score"] - st["mean"]
            if abs(diff) < 0.005:
                meta.append(f" Level with the average of {st['mean']:.2f}.")
            else:
                word = "above" if diff > 0 else "below"
                meta.append(f" {abs(diff):.2f} {word} the average of {st['mean']:.2f}.")
        head += [
            html.Div(className="profile-score", children=[
                html.Span(score_txt, className="profile-big"), _band_chip(vm, row["band"])]),
            html.P(meta, className="profile-meta"),
        ]
    else:
        same = st["counts"].get(row["band"], 0)
        head += [
            html.Div(className="profile-score", children=[_band_chip(vm, row["band"])]),
            html.P(f"{same} of {st['n_scored']} countries in this view share this status.",
                   className="profile-meta"),
        ]

    if row["popup"]:
        heading = "Behind the score" if vm["popup"]["mode"] != "grades" else "All PEFA grades"
        head += [html.H4(heading, className="pane-h2"), _indicator_rows(vm, row["popup"])]
    return head


def build_pane(vm, selected):
    """Dynamic content pane: ranking by default, country profile once one is picked."""
    selected = selected or []
    kind = vm["kind"]

    if kind == "frontier":
        return _frontier_pane(vm, selected)

    if selected:
        return build_profile(vm, selected[0])

    return _ranking_block(
        vm, selected, "Countries in this view",
        "Click a country on the map, or a name below, to see the indicators behind its score.")


def _frontier_pane(vm, selected):
    top = []
    if selected:
        items = []
        by_iso = {r["iso"]: r for r in vm["rows"]}
        for i, iso in enumerate(selected):
            r = by_iso.get(iso)
            if not r:
                continue
            color = COUNTRY_COLORS[i % len(COUNTRY_COLORS)]
            th = r.get("theta")
            on = th is not None and th >= 0.9999
            hint = ("On the frontier" if on else
                    f"Could reach the same quality with about {round(th * 100)}% of today's spending"
                    if th is not None else "No efficiency score")
            items.append(html.Li(className="cmp-row", children=[
                html.Span(className="cmp-dot", style={"backgroundColor": color}),
                html.Div(className="cmp-main", children=[
                    html.Span(r["name"], className="cmp-name"),
                    html.Span(hint, className="cmp-hint"),
                ]),
                html.Span(fmt_num(th), className="cmp-score"),
                html.Button(icon("close"), id={"type": "sel-remove", "iso": iso}, n_clicks=0,
                            className="icon-btn", **{"aria-label": f"Remove {r['name']}"}),
            ]))
        top = [
            html.Div(className="pane-head-row", children=[
                html.H3(f"Comparing {len(selected)} of 5", className="pane-h"),
                html.Button("Clear all", id={"type": "sel-clear", "i": 1}, n_clicks=0, className="link-btn"),
            ]),
            html.P("Efficiency score: 1.00 means the country is on the frontier.", className="pane-help"),
            html.Ul(items, className="cmp-list"),
        ]
    else:
        top = [
            html.H3("Compare countries", className="pane-h"),
            html.P("Add up to five countries with the search box, by clicking dots on the chart, or by "
                   "choosing names below.", className="pane-help"),
        ]
    has, _ = sorted_rows(vm)
    return [
        html.Div(top, className="pane-split pane-split-top"),
        html.Div([html.H4("Efficiency ranking", className="pane-h2 pane-h2-first"),
                  html.Ul(_rank_rows(vm, has, selected), className="rank-list")],
                 className="pane-split pane-split-list"),
    ]
