"""
country_page.py
---------------
The country-wise page:  ?page=country-wise-cbd-analysis#country=KHM&peers=VNM,THA

The Dashboard is organised benchmark by benchmark (one tab each). This page turns
that around: pick ONE country and see every benchmark for it on a single page.

    sticky bar    Country  |  Compare with (up to 3 peers)  |  colour key
    country head  name, region, which of the 7 benchmarks have data for it
    grid          Infrastructure            efficiency frontier  |  infrastructure gap
                  Public investment mgmt    PEFA                 |  GovTech
                  Climate readiness         climate institutions |  climate assessment
                  Regional deep-dive        PIM tracker

On every map and chart the selected country is red, peers have their own colour and
all other countries are shown light, for comparison. Peers are chosen once, in the bar,
and apply to the whole page.

Layout and ids first, then small components, then the callbacks (register_callbacks).
Data comes from country_data.py, figures from country_figures.py. Nothing here talks
to Databricks directly.
"""

import logging

import plotly.graph_objects as go
from dash import ALL, Input, Output, Patch, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

import country_data as cd
import country_figures as cf
import datasets as ds
import queries as q
import utils as u

log = logging.getLogger(__name__)

# Names used in the coverage chips under the country name.
SHORT = {
    "ef": "Infrastructure efficiency", "infra": "Infrastructure gap", "pefa": "PEFA grades",
    "gtmi": "GovTech readiness", "gccii": "Climate institutions", "ccia": "Climate assessment",
    "piiag": "PIM tracker",
}
WIDE = {"piiag"}                      # panels that span the full row (map left, table right)
MAP_HEIGHT = 380
MAP_WIDTH = {"piiag": 760}            # px, only used to pick a sensible zoom
DEFAULT_MAP_WIDTH = 560


def _safe(fn, default):
    """Layout must always render: if a table can't be read, show empty controls, not a crash."""
    try:
        return fn()
    except Exception:
        log.exception("Country page: could not load options")
        return default


# ══════════════════════════════════════════════════════════════════════════
# Layout
# ══════════════════════════════════════════════════════════════════════════

def layout(logo_src, wb_logo_src, hash_=""):
    country, peers = cd.parse_hash(hash_)
    options = _safe(cd.country_options, [])
    return html.Div(className="page page-country", children=[
        u.build_header("country", logo_src),
        html.Main(className="cw", children=[
            _bar(options, country, peers),
            html.Div(id="cw-root", className="cw-body " + ("has-country" if country else "no-country"), children=[
                _empty_state(),
                html.Div(id="cw-hero", className="cw-hero", **{"aria-live": "polite"}),
                html.P("The selected country is red on every map and chart. Peers you add get their own "
                       "colour. All other countries are shown lighter, for comparison. Maps show the "
                       "country's region; the climate assessment and PIM tracker cover only the countries "
                       "that were assessed.", className="cw-howto"),
                html.Div(className="cw-grid", children=[
                    item for title, keys in cd.SECTIONS for item in
                    [html.H2(title, className="cw-section-title")] + [_panel(k) for k in keys]
                ]),
            ]),
        ]),
        u.build_footer(wb_logo_src),
        html.Div(id="cw-url-sink", hidden=True),
    ])


def _bar(options, country, peers):
    return html.Div(className="cw-bar", role="region", **{"aria-label": "Choose a country"}, children=html.Div(
        className="cw-bar-inner", children=[
            html.Div(className="field cw-field", children=[
                html.Label("Country", htmlFor="cw-country", className="field-label"),
                dcc.Dropdown(id="cw-country", options=options, value=country, clearable=False,
                             searchable=True, placeholder="Select a country", className="select"),
            ]),
            html.Div(className="field cw-field", children=[
                html.Label("Compare with peers", htmlFor="cw-peers", className="field-label"),
                dcc.Dropdown(id="cw-peers", options=_peer_options(options, country, peers), value=peers,
                             multi=True, searchable=True, className="select",
                             placeholder=f"Add up to {cd.MAX_PEERS} countries (optional)"),
                html.Span(_peer_help(peers), id="cw-peers-help", className="field-help"),
            ]),
            html.Div(id="cw-legend", className="cw-legend", children=_legend(country, peers)),
        ]))


# What each row of the page holds, in words, for the "nothing selected yet" screen.
SECTION_BLURB = {
    "Infrastructure": "Efficiency frontier and infrastructure gap",
    "Public investment management": "PEFA grades and GovTech readiness",
    "Climate readiness": "Climate institutions and climate assessment",
    "Regional deep-dive": "PIM tracker, for the countries in the Western Balkans",
}


def _empty_state():
    return html.Div(className="cw-empty", children=[
        html.H1("Choose a country to see all its benchmarks on one page", className="cw-empty-title"),
        html.P("Pick a country in the bar above. It is shown in red on every map and chart, with all other "
               "countries lighter for comparison. Add up to three peers to see how it stacks up against them.",
               className="cw-empty-text"),
        html.Dl(className="cw-empty-list", children=[
            html.Div([html.Dt(title), html.Dd(SECTION_BLURB.get(title, ", ".join(SHORT[k] for k in keys)))])
            for title, keys in cd.SECTIONS]),
    ])


def _control(key, j, f):
    cid = f"cw-{key}-f{j}"
    options = _safe(f["options"], [])
    value = _safe(f["default"], None)
    return html.Div(className="cw-ctl", children=[
        html.Label(f["label"], htmlFor=cid, className="field-label"),
        dcc.Dropdown(id=cid, options=options, value=value, clearable=False, searchable=False, className="select"),
        html.Span(f.get("help") or "", className="field-help") if f.get("help") else None,
    ])


def _panel(key):
    spec = ds.DATASETS[key]
    filters = cd.user_filters(key)
    wide = key in WIDE
    graph_cfg = {"displayModeBar": False, "scrollZoom": True}

    if key == "ef":
        body = [
            html.Div(id="cw-ef-strip", className="cw-strip"),
            dcc.Graph(id="cw-ef-frontier", className="cw-chart", config=graph_cfg,
                      style={"height": "360px", "width": "100%"}),
            html.H4("What sits behind the efficiency score", className="cw-sub"),
            html.P(id="cw-ef-sub", className="cw-sub-help"),
            dcc.Graph(id="cw-ef-components", className="cw-chart", config={"displayModeBar": False},
                      style={"height": "320px", "width": "100%"}),
        ]
    else:
        strip = html.Div(id=f"cw-{key}-strip", className="cw-strip")
        table = html.Div(id=f"cw-{key}-table", className="cw-table-wrap")
        visual = [
            html.Div(className="cw-map-frame", children=dcc.Graph(
                id=f"cw-{key}-map", className="cw-map", config=graph_cfg,
                style={"height": f"{MAP_HEIGHT}px", "width": "100%"})),
            html.Div(id=f"cw-{key}-legend", className="cw-legend-wrap"),
        ]
        body = ([html.Div(visual, className="cw-col"), html.Div([strip, table], className="cw-col")] if wide
                else [strip, *visual, table])

    return html.Section(id=f"cw-{key}", className="cw-panel" + (" is-wide" if wide else ""),
                        **{"aria-labelledby": f"cw-{key}-title"}, children=[
        html.Div(className="cw-panel-head", children=[
            html.Div(className="cw-panel-titles", children=[
                html.H3(spec["title"], id=f"cw-{key}-title", className="cw-panel-title"),
                html.P(spec["question"], className="cw-panel-q"),
            ]),
            html.Div(className="cw-controls", children=[_control(key, j, f) for j, f in enumerate(filters)]),
        ]),
        html.Details(className="cw-about", children=[
            html.Summary([u.icon("info"), "How to read this"]),
            html.P(spec["how_to"]),
            html.P(f"Source: {spec['source']}. {spec['official']}.", className="cw-about-src"),
        ]),
        html.Div(id=f"cw-{key}-note", className="cw-note-wrap"),
        dcc.Loading(type="circle", color=u.INDIGO, delay_show=250, parent_className="cw-loading",
                    overlay_style={"visibility": "visible", "opacity": 0.55},
                    children=html.Div(id=f"cw-{key}-main", className="cw-panel-main is-hidden", children=body)),
    ])


# ══════════════════════════════════════════════════════════════════════════
# Small components
# ══════════════════════════════════════════════════════════════════════════

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _peer_options(options, country, peers):
    """All countries except the selected one; once the peer limit is reached the rest are greyed out."""
    full = len(peers or []) >= cd.MAX_PEERS
    return [{"label": o["label"], "value": o["value"], "disabled": bool(full and o["value"] not in (peers or []))}
            for o in options if o["value"] != country]


def _peer_help(peers):
    n = len(peers or [])
    if n >= cd.MAX_PEERS:
        return f"{cd.MAX_PEERS} of {cd.MAX_PEERS} peers. Remove one to add another."
    return f"Peers appear on every map and chart. Up to {cd.MAX_PEERS}."


def _dot(color, cls=""):
    return html.Span(className=f"cw-dot {cls}".strip(), style={"backgroundColor": color}, **{"aria-hidden": "true"})


def _legend(country, peers):
    if not country:
        return None
    names = cd.country_names()
    colors = cf.role_colors(country, peers)
    items = [html.Li(className="cw-key is-focus", children=[
        _dot(colors[country]), html.Strong(names.get(country, country)), html.Span(" selected", className="cw-key-tag")])]
    items += [html.Li(className="cw-key", children=[_dot(colors[p]), names.get(p, p)]) for p in (peers or [])]
    items.append(html.Li(className="cw-key is-context", children=[_dot("#E3E8F0", "is-light"), "All other countries"]))
    return html.Ul(items, className="cw-key-list", **{"aria-label": "Colour key"})


def _hero(iso):
    names = cd.country_names()
    name = names.get(iso, iso)
    region = cd.region_of(iso)
    cov = cd.coverage(iso)
    n_yes = sum(1 for v in cov.values() if v)
    chips = [html.Li(className="cw-cov " + ("is-yes" if cov.get(k) else "is-no"), children=[
        html.Span(className="cw-cov-mark", **{"aria-hidden": "true"}),
        SHORT[k],
        html.Span("" if cov.get(k) else " (no data)", className="sr-only"),
    ]) for k in cd.KEYS]
    return [
        html.Div(className="cw-hero-main", children=[
            html.H1(name, className="cw-hero-title"),
            html.P(region or "World Bank region not recorded", className="cw-hero-region"),
        ]),
        html.Div(className="cw-hero-cov", children=[
            html.P(f"Has data in {n_yes} of {len(cd.KEYS)} benchmarks", className="cw-hero-count"),
            html.Ul(chips, className="cw-cov-list"),
        ]),
    ]


def _error_note(text="We couldn't load this benchmark. Try again in a moment."):
    return html.Div(className="cw-notice is-error", role="alert", children=[
        html.Strong("Data unavailable. "), text])


def _not_covered_note(key, iso):
    """Shown instead of a panel when the country is outside the benchmark's coverage."""
    spec = ds.DATASETS[key]
    name = cd.country_names().get(iso, iso)
    if cd.SCOPE[key] == "local":
        covered = cd.covered_countries(key)
        return html.Div(className="cw-notice is-empty", children=[
            html.P([html.Strong(f"{name} was not assessed. "),
                    f"{spec['title']} covers only {len(covered)} countries."]),
            html.P("Open one that was:", className="cw-notice-lead"),
            html.Div(className="cw-chip-row", children=[
                html.Button(n, id={"type": "cw-goto", "panel": key, "iso": c}, n_clicks=0, className="cw-chip-btn")
                for c, n in covered]),
        ])
    return html.Div(className="cw-notice is-empty", children=[
        html.Strong(f"{name} is not placed in a World Bank region. "),
        f"{spec['title']} is shown region by region, so it can't be drawn for this country."])


def _score_text(vm, score):
    fmt = vm.get("score_fmt", "{:.2f}")
    span = (vm.get("vmax") or 0) - (vm.get("vmin") or 0)
    return u.fmt_num(score, "{:.0f}" if span >= 20 else fmt)


def _strip(vm, row, name, scope):
    """One line about the selected country: its score, where it ranks, how it compares."""
    lead = [_dot(cf.FOCUS_COLOR), html.Span(name, className="cw-strip-name")]
    if row is None or row.get("band") is None:
        return [html.Div(className="cw-strip-row", children=lead + [
            html.Span("No score in this benchmark", className="cw-strip-none")]),
            html.P(f"The map shows {scope} for comparison.", className="cw-strip-meta")]
    st = u.stats_for(vm)
    if vm["kind"] == "continuous":
        has, _ = u.sorted_rows(vm)
        rank = 1 + sum(1 for r in has if r["score"] > row["score"])
        meta = [f"Ranks {u.ordinal(rank)} of {st['n_scored']} in {scope}."]
        mode = vm["kpi"]["mode"]
        if mode == "score":
            diff = row["score"] - st["mean"]
            meta.append(" Level with the average of %.2f." % st["mean"] if abs(diff) < 0.005 else
                        " %.2f %s the average of %.2f." % (abs(diff), "above" if diff > 0 else "below", st["mean"]))
        elif mode == "split":
            meta.append(" Above the regional average." if row["score"] > 0 else " Below the regional average.")
        main = [html.Span(_score_text(vm, row["score"]), className="cw-strip-big"), u._band_chip(vm, row["band"])]
    else:
        same = st["counts"].get(row["band"], 0)
        meta = [f"{same} of {st['n_scored']} countries in {scope} share this result."]
        main = [u._band_chip(vm, row["band"])]
    return [html.Div(className="cw-strip-row", children=lead + main),
            html.P(meta, className="cw-strip-meta")]


# ── Comparison table: selected country and peers, side by side ───────────────

def _cell(vm, mode, val):
    if mode == "bars" and _is_num(val):
        lo, hi = vm["popup"]["lo"], vm["popup"]["hi"]
        pct = max(0, min(1, (val - lo) / (hi - lo))) if hi != lo else 0
        color = u.HEX_CODES_5[u.heatmap_bucket(val, lo, hi)]
        label = u.TERNARY.get(val) if vm["popup"].get("ternary") and val in u.TERNARY else "%.2f" % val
        return html.Div(className="cw-bar-cell", children=[
            html.Span(className="cw-minibar", children=html.I(style={"width": f"{pct * 100:.0f}%", "backgroundColor": color})),
            html.Span(label, className="cw-val")])
    if mode == "grades" and isinstance(val, str):
        try:
            color = vm["colors"][vm["labels"].index(val)]
            return html.Span(val, className="chip", style={"backgroundColor": color, "color": u.ink_on(color)})
        except ValueError:
            return html.Span(val, className="chip chip-nodata")
    if val is None:
        return html.Span("No data", className="cw-na")
    return html.Span(u.fmt_num(val, "{:.2f}") if _is_num(val) else str(val), className="cw-val")


def _headline_cell(vm, row):
    if row is None or row.get("band") is None:
        return html.Span("No data", className="cw-na")
    if vm["kind"] == "continuous":
        return html.Div(className="cw-bar-cell", children=[
            html.Span(className="cw-swatch", style={"backgroundColor": vm["colors"][row["band"]]}),
            html.Strong(_score_text(vm, row["score"]), className="cw-val")])
    return u._band_chip(vm, row["band"])


def _compare_table(key, iso, peers, vals, focus_scope):
    """Rows = the indicators behind the score, columns = selected country first, then peers."""
    names = cd.country_names()
    colors = cf.role_colors(iso, peers)
    cols, skipped = [], []
    for c in [iso] + list(peers):
        scope, vm, row = cd.locate(key, c, vals)
        if key == "infra" and c != iso and scope != focus_scope:
            skipped.append(c)        # the gap index is measured against each region's own average
            continue
        cols.append((c, names.get(c, c), colors[c], vm, row))

    ref = next((vm for _, _, _, vm, _ in cols if vm), None)
    if ref is None:
        return None
    mode = ref["popup"]["mode"]

    indicators, seen = [], set()
    by_length = sorted((c[4] for c in cols), key=lambda r: -len((r or {}).get("popup", [])))
    for row in by_length:                      # the fullest list sets the order, others add what it lacks
        for p in (row or {}).get("popup", []):
            if p["indicator"] not in seen:
                seen.add(p["indicator"])
                indicators.append(p["indicator"])

    head = html.Tr([html.Th("", scope="col", className="cw-th-label")] + [
        html.Th(scope="col", className="cw-th-country" + (" is-focus" if c == iso else ""), children=[
            _dot(color), name, html.Span(" (selected)" if c == iso else "", className="sr-only")])
        for c, name, color, _, _ in cols])

    # PEFA: the headline would repeat one of the five grades below it, so that grade is
    # marked "on the map" instead of getting a row of its own.
    on_map = vals[0] if key == "pefa" and vals else None
    body = []
    if key != "pefa":
        body.append(html.Tr(className="cw-tr-headline", children=[html.Th(cd.measure_label(key, vals), scope="row")] + [
            html.Td(_headline_cell(vm, row), className="is-focus" if c == iso else None) for c, _, _, vm, row in cols]))
    for ind in indicators:
        cells = []
        for c, _, _, vm, row in cols:
            val = next((p["score"] for p in (row or {}).get("popup", []) if p["indicator"] == ind), None)
            cells.append(html.Td(_cell(vm or ref, mode, val), className="is-focus" if c == iso else None))
        label = ds.PEFA_LABELS.get(ind, ind) if key == "pefa" else ind
        th = [label] + ([html.Span("on the map", className="cw-tag")] if ind == on_map else [])
        body.append(html.Tr([html.Th(th, scope="row")] + cells, className="cw-tr-measure" if ind == on_map else None))

    out = [html.Div(className="cw-table-scroll", children=html.Table(
        className="cw-table", children=[html.Thead(head), html.Tbody(body)]))]
    if skipped:
        who = ", ".join(names.get(c, c) for c in skipped)
        out.append(html.P(f"Not compared here: {who}. The gap index is measured against each region's own "
                          "average, so it can't be compared across regions.", className="cw-fine"))
    return out


# ══════════════════════════════════════════════════════════════════════════
# One map benchmark = one view (everything a panel shows for a country + peers)
# ══════════════════════════════════════════════════════════════════════════

def _members_on_map(key, iso, peers, scope):
    """Selected country first, then the peers that live in the same region / group as it."""
    return [iso] + [p for p in peers if cd.scope_for(key, p) == scope]


def _map_view(key, iso, peers, vals):
    """Everything a map panel shows: figure, summary strip, legend, table, note."""
    names = cd.country_names()
    scope = cd.scope_for(key, iso)
    if not scope:
        return {"hidden": True, "note": _not_covered_note(key, iso)}

    vm = cd.panel_vm(key, scope, vals)
    row = cd.row_of(vm, iso)
    colors = cf.role_colors(iso, peers)
    members = _members_on_map(key, iso, peers, scope)

    geo_context = cd.light_geojson([r["iso"] for r in vm["rows"]], cd.CONTEXT_TOL)
    geo_focus = cd.light_geojson(members, cd.FOCUS_TOL)
    frame = cd.map_frame(iso, scope, MAP_WIDTH.get(key, DEFAULT_MAP_WIDTH))
    fig = cf.build_map(vm, members, colors, geo_context, geo_focus, frame, f"cw|{key}|{iso}|{scope}", names)

    notes = []
    off = [p for p in peers if p not in members]
    if off:
        notes.append(html.P("Not on the map (outside %s): %s. Their values are in the table." % (
            scope, ", ".join(names.get(p, p) for p in off)), className="cw-fine"))

    return {
        "hidden": False, "fig": fig,
        "strip": _strip(vm, row, names.get(iso, iso), scope),
        "legend": u.build_legend(vm),
        "table": _compare_table(key, iso, peers, vals, scope),
        "note": notes or None,
    }


def _peers_view(key, iso, peers, vals):
    """Only what changes when the peers change: the map overlay and the table."""
    scope = cd.scope_for(key, iso)
    if not scope:
        return None
    vm = cd.panel_vm(key, scope, vals)
    members = _members_on_map(key, iso, peers, scope)
    traces = cf.overlay_traces(vm, members, cf.role_colors(iso, peers),
                               cd.light_geojson(members, cd.FOCUS_TOL), cd.country_names())
    patch = Patch()
    for i, trace in enumerate(traces, start=1):          # traces 1-4: peers, then the selected country
        patch["data"][i] = trace
    off = [p for p in peers if p not in members]
    table = _compare_table(key, iso, peers, vals, scope)
    if off and table is not None:
        table = list(table) + [html.P("Not on the map (outside %s): %s." % (
            scope, ", ".join(cd.country_names().get(p, p) for p in off)), className="cw-fine")]
    return patch, table


# ══════════════════════════════════════════════════════════════════════════
# Callbacks
# ══════════════════════════════════════════════════════════════════════════

HIDDEN = "cw-panel-main is-hidden"
SHOWN = "cw-panel-main"


def register_callbacks(app):
    """Called once from app.py. Every id here starts with 'cw-'."""
    options = _safe(cd.country_options, [])

    # ── The selection bar ────────────────────────────────────────────────

    @app.callback(Output("cw-hero", "children"), Output("cw-root", "className"), Input("cw-country", "value"))
    def hero(iso):
        if not iso:
            return None, "cw-body no-country"
        try:
            return _hero(iso), "cw-body has-country"
        except Exception:
            log.exception("Could not build country header for %s", iso)
            return html.H1(cd.country_names().get(iso, iso), className="cw-hero-title"), "cw-body has-country"

    @app.callback(Output("cw-peers", "value"), Input("cw-country", "value"), State("cw-peers", "value"),
                  prevent_initial_call=True)
    def drop_selected_from_peers(iso, peers):
        """If the new country was one of the peers, it is the selected country now, not a peer."""
        clean = cd.clean_selection(iso, peers)[1]
        return no_update if clean == (peers or []) else clean

    @app.callback(Output("cw-peers", "options"), Output("cw-peers-help", "children"),
                  Input("cw-country", "value"), Input("cw-peers", "value"), State("cw-peers", "options"))
    def peer_choices(iso, peers, current):
        peers = peers or []
        full = len(peers) >= cd.MAX_PEERS
        had_disabled = any(o.get("disabled") for o in current or [])
        # Re-sending options while the menu is open can reset it, so only do it when they really change.
        if ctx.triggered_id == "cw-peers" and had_disabled == full:
            return no_update, _peer_help(peers)
        return _peer_options(options, iso, peers), _peer_help(peers)

    @app.callback(Output("cw-legend", "children"), Input("cw-country", "value"), Input("cw-peers", "value"))
    def colour_key(iso, peers):
        return _legend(iso, cd.clean_selection(iso, peers)[1])

    # Keep the address bar shareable without re-rendering the page: only the hash changes.
    app.clientside_callback(
        """
        function(country, peers) {
            var frag = "";
            if (country) {
                frag = "#country=" + encodeURIComponent(country);
                if (peers && peers.length) { frag += "&peers=" + peers.map(encodeURIComponent).join(","); }
            }
            var url = window.location.pathname + window.location.search + frag;
            if (window.history && window.history.replaceState) {
                window.history.replaceState(window.history.state, "", url);
            }
            return "";
        }
        """,
        Output("cw-url-sink", "children"), Input("cw-country", "value"), Input("cw-peers", "value"),
        prevent_initial_call=True,
    )

    @app.callback(Output("cw-country", "value"),
                  Input({"type": "cw-goto", "panel": ALL, "iso": ALL}, "n_clicks"), prevent_initial_call=True)
    def open_covered_country(_clicks):
        """The 'not assessed' note lists the countries that were; clicking one switches to it."""
        trig = ctx.triggered[0] if ctx.triggered else None
        if not trig or not trig.get("value") or not isinstance(ctx.triggered_id, dict):
            raise PreventUpdate
        return ctx.triggered_id["iso"]

    # ── Panels ───────────────────────────────────────────────────────────
    _register_ef(app)
    for key in cd.KEYS:
        if key != "ef":
            _register_map_panel(app, key)


def _register_ef(app):
    @app.callback(
        Output("cw-ef-strip", "children"), Output("cw-ef-note", "children"), Output("cw-ef-main", "className"),
        Output("cw-ef-frontier", "figure"), Output("cw-ef-components", "figure"), Output("cw-ef-sub", "children"),
        Input("cw-country", "value"), Input("cw-peers", "value"),
        Input("cw-ef-f0", "value"), Input("cw-ef-f1", "value"),
    )
    def efficiency(iso, peers, method, sample):
        blank = cf.empty_figure()
        if not iso:
            return None, None, HIDDEN, blank, blank, None
        iso, peers = cd.clean_selection(iso, peers)
        try:
            names = cd.country_names()
            vm = cd.ef_vm()
            colors = cf.role_colors(iso, peers)
            row = cd.row_of(vm, iso)

            frontier = cf.build_frontier(vm, iso, peers, colors, names)
            members = [iso] + peers
            df = cd.ef_scores(method, sample, members)
            components = cf.build_components(df, iso, peers, colors, names, q.EF_SHORT_NAME_ORDER)

            strip = [html.Div(className="cw-strip-row", children=[
                _dot(cf.FOCUS_COLOR), html.Span(names.get(iso, iso), className="cw-strip-name")])]
            theta = (row or {}).get("theta")
            if theta is None:
                strip[0].children.append(html.Span("No efficiency score", className="cw-strip-none"))
                strip.append(html.P("It needs both public-investment and infrastructure-quality data.",
                                    className="cw-strip-meta"))
            else:
                scored = [r["theta"] for r in vm["rows"] if r.get("theta") is not None]
                rank = 1 + sum(1 for t in scored if t > theta)
                hint = ("On the efficiency frontier." if theta >= 0.9999 else
                        f"Could reach the same infrastructure quality with about {round(theta * 100)}% of today's spending.")
                strip[0].children.append(html.Span(u.fmt_num(theta), className="cw-strip-big"))
                strip.append(html.P(f"Ranks {u.ordinal(rank)} of {len(scored)} countries. {hint}", className="cw-strip-meta"))
            missing = [p for p in peers if cd.row_of(vm, p) is None]
            if missing:
                strip.append(html.P("Not in the analysis: %s." % ", ".join(names.get(p, p) for p in missing),
                                    className="cw-strip-meta"))
            sub = f"Method: {method}  |  Sample: {sample}"
            return strip, None, SHOWN, frontier, components, sub
        except Exception:
            log.exception("Efficiency panel failed for %s", iso)
            return None, _error_note(), HIDDEN, blank, blank, None


def _register_map_panel(app, key):
    filters = cd.user_filters(key)
    filter_inputs = [Input(f"cw-{key}-f{j}", "value") for j in range(len(filters))]
    filter_states = [State(f"cw-{key}-f{j}", "value") for j in range(len(filters))]
    n_f = len(filters)

    @app.callback(
        Output(f"cw-{key}-map", "figure"), Output(f"cw-{key}-strip", "children"),
        Output(f"cw-{key}-legend", "children"), Output(f"cw-{key}-table", "children"),
        Output(f"cw-{key}-note", "children"), Output(f"cw-{key}-main", "className"),
        Input("cw-country", "value"), *filter_inputs, State("cw-peers", "value"),
    )
    def build(iso, *rest):
        vals, peers = tuple(rest[:n_f]), rest[n_f]
        blank = cf.empty_figure()
        if not iso:
            return blank, None, None, None, None, HIDDEN
        iso, peers = cd.clean_selection(iso, peers)
        if n_f and any(v is None for v in vals):
            raise PreventUpdate                          # filters are still being set up
        try:
            view = _map_view(key, iso, peers, vals)
        except Exception:
            log.exception("Panel %s failed for %s", key, iso)
            return blank, None, None, None, _error_note(), HIDDEN
        if view["hidden"]:
            return blank, None, None, None, view["note"], HIDDEN
        return view["fig"], view["strip"], view["legend"], view["table"], view["note"], SHOWN

    @app.callback(
        Output(f"cw-{key}-map", "figure", allow_duplicate=True),
        Output(f"cw-{key}-table", "children", allow_duplicate=True),
        Input("cw-peers", "value"), State("cw-country", "value"), *filter_states,
        prevent_initial_call=True,
    )
    def change_peers(peers, iso, *vals):
        """Peers changed: re-outline the maps and refresh the table, without resending any boundaries."""
        if not iso or (n_f and any(v is None for v in vals)):
            raise PreventUpdate
        iso, peers = cd.clean_selection(iso, peers)
        try:
            view = _peers_view(key, iso, peers, tuple(vals))
        except Exception:
            log.exception("Peers update failed for %s / %s", key, iso)
            raise PreventUpdate
        if view is None:
            raise PreventUpdate
        return view
