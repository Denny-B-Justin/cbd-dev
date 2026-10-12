"""
app.py
------
Country Benchmarking Dashboard - Dash app.

Run with:  python app.py        then open  http://127.0.0.1:8050

Structure
  app.py        this file: app object, routing and the Dashboard's callbacks
  pages.py      layouts for the Overview page and the one-page Dashboard
  datasets.py   registry of the seven benchmarks (copy, filters, data adapters)
  utils.py      colours, Plotly figure builders, reusable components
  queries.py    all Databricks access (unchanged)

  country_page.py     the country-wise page: layout + its callbacks (attached below)
  country_data.py     what to show for one country (re-uses datasets.py, no Dash)
  country_figures.py  its maps and charts: selected country red, others lighter

How the Dashboard page works
  view-store   which benchmark tab is active (mirrors the URL hash, e.g. #gtmi)
  filters      f0..f2 are generic dropdown "slots"; each benchmark decides how
               many it needs and what they are called (datasets.FILTERS)
  vm-store     the "view model" for the current view + filters (datasets.py)
  sel-store    the selected country (or up to 5 on the efficiency tab)
Callbacks only talk to each other through those stores, so adding a benchmark
never needs a new page or new callbacks.
"""

import json
import logging
import warnings
from urllib.parse import parse_qs

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, ALL, ctx, dcc, html, no_update, Patch
from dash.exceptions import PreventUpdate
from plotly.utils import PlotlyJSONEncoder

import country_page
import datasets as ds
import exports as ex
import pages
import queries as q
import utils as u

warnings.filterwarnings("ignore", category=DeprecationWarning)
log = logging.getLogger(__name__)

app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    title=u.BASE_TITLE,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server

u.set_ef_order(q.EF_SHORT_NAME_ORDER)

# ══════════════════════════════════════════════════════════════════════════
# Asset URLs - resolved here because only app.py owns the Dash instance.
# ══════════════════════════════════════════════════════════════════════════

LOGO_WHITE_URL = app.get_asset_url("cbd_logo_white.png")
WB_LOGO_URL = app.get_asset_url("The-World-Bank-group-white.png")
FAVICON_URL = app.get_asset_url("favicon.ico")

app.index_string = """<!DOCTYPE html>
<html lang="en">
    <head>
        {%metas%}
        <title>{%title%}</title>
        <link rel="icon" type="image/x-icon" href=\"""" + FAVICON_URL + """\">
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""

# ══════════════════════════════════════════════════════════════════════════
# Routing: ?page=  (kept query-string based so it works behind Posit Connect)
# ══════════════════════════════════════════════════════════════════════════
#   (none)               Overview page
#   ?page=dashboard      the dashboard; topic in the hash, e.g. #gtmi
#   ?page=gtmi (etc.)    old per-dataset links still work and open that tab
#   ?page=country-wise-cbd-analysis
#                        every benchmark for one country on a single page;
#                        country and peers in the hash, e.g. #country=KHM&peers=VNM,THA

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Div(id="page-content"),
    html.Div(id="title-sink", hidden=True),
])


def _get_page_key(search):
    if not search:
        return ""
    return parse_qs(search.lstrip("?")).get("page", [""])[0]


def _view_from_url(search, hash_):
    """Which tab the URL asks for: #gtmi, or an old-style ?page=gtmi link."""
    key = (hash_ or "").lstrip("#")
    if key in ds.DATASETS:
        return key
    legacy = _get_page_key(search)
    return legacy if legacy in ds.DATASETS else ds.DEFAULT_VIEW


@app.callback(Output("page-content", "children"), Input("url", "search"), State("url", "hash"))
def render_page(search, hash_):
    page = _get_page_key(search)
    if page == "":
        return pages.home_layout(LOGO_WHITE_URL, WB_LOGO_URL)
    if page == "dashboard" or page in ds.DATASETS:
        # Seed the tab from the URL here: the hash callback below can fire before
        # this layout exists, which would leave a deep link on the default tab.
        return pages.dashboard_layout(LOGO_WHITE_URL, _view_from_url(search, hash_))
    if page == u.COUNTRY_PAGE:
        # Country and peers come from the hash and seed the dropdowns; after that the
        # dropdowns are the source of truth (country_page keeps the hash in step).
        return country_page.layout(LOGO_WHITE_URL, WB_LOGO_URL, hash_)
    return pages.not_found_layout(LOGO_WHITE_URL)


app.clientside_callback(
    """
    function(search, hash) {
        const base = %s;
        const views = %s;
        const page = new URLSearchParams(search || "").get("page") || "";
        let title = base;
        if (page === "dashboard") {
            const t = views[(hash || "").replace("#", "")];
            title = (t || "Dashboard") + " - " + base;
        } else if (page === %s) {
            title = "Country-wise analysis - " + base;
        } else if (views[page]) {
            title = views[page] + " - " + base;
        }
        document.title = title;
        return "";
    }
    """ % (json.dumps(u.BASE_TITLE), json.dumps({k: v["title"] for k, v in ds.DATASETS.items()}),
           json.dumps(u.COUNTRY_PAGE)),
    Output("title-sink", "title"),
    Input("url", "search"),
    Input("url", "hash"),
)

# ══════════════════════════════════════════════════════════════════════════
# Dashboard: which tab is active
# ══════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("url", "hash"),
    Input({"type": "tab", "key": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def tab_clicked(_clicks):
    trig = ctx.triggered[0] if ctx.triggered else None
    if not trig or not trig.get("value") or not isinstance(ctx.triggered_id, dict):
        raise PreventUpdate
    return "#" + ctx.triggered_id["key"]


@app.callback(
    Output("view-store", "data"),
    Input("url", "hash"),
    State("url", "search"),
    State("view-store", "data"),
)
def hash_to_view(hash_, search, current):
    key = _view_from_url(search, hash_)
    return no_update if key == current else key


@app.callback(
    Output({"type": "tab", "key": ALL}, "className"),
    Output({"type": "tab", "key": ALL}, "aria-selected"),
    Input("view-store", "data"),
    State({"type": "tab", "key": ALL}, "id"),
)
def style_tabs(view, ids):
    active = [i["key"] == view for i in ids]
    return (["tab is-active" if a else "tab" for a in active],
            ["true" if a else "false" for a in active])


# ══════════════════════════════════════════════════════════════════════════
# Dashboard: set up the filters, title and layout mode for the chosen tab
# ══════════════════════════════════════════════════════════════════════════

_CONFIG_OUTPUTS = [
    Output("context", "children"),
    Output("main-grid", "className"),
    Output("f-country-help", "children"),
]
for _i in range(ds.MAX_FILTERS):
    _CONFIG_OUTPUTS += [
        Output(f"f{_i}-field", "className"),
        Output(f"f{_i}-label", "children"),
        Output(f"f{_i}", "options"),
        Output(f"f{_i}", "value"),
        Output(f"f{_i}-help", "children"),
    ]


@app.callback(
    *_CONFIG_OUTPUTS,
    Input("view-store", "data"),
    *[State(f"f{i}", "value") for i in range(ds.MAX_FILTERS)],
)
def configure_view(view, *previous):
    spec = ds.DATASETS[view]
    filters = ds.FILTERS[view]
    is_ef = view == "ef"
    out = [
        u.build_context(spec),
        "main-grid is-frontier" if is_ef else "main-grid is-map",
        "Add up to five countries to compare." if is_ef else "",
    ]
    for i in range(ds.MAX_FILTERS):
        if i < len(filters):
            f = filters[i]
            options = f["options"]()
            valid = {o["value"] for o in options}
            # Keep the user's earlier choice (e.g. the same Region) when it still applies.
            value = previous[i] if previous[i] in valid else f["default"]()
            out += ["field", f["label"], options, value, f.get("help") or ""]
        else:
            out += ["field is-hidden", "", [], None, ""]
    return out


# ══════════════════════════════════════════════════════════════════════════
# Dashboard: compute the data for the current filters
# ══════════════════════════════════════════════════════════════════════════

def _error_block():
    return html.Div(className="error-block", role="alert", children=[
        html.H3("We couldn't load this data"),
        html.P("The data source did not respond. Try again in a moment, or choose another benchmark."),
    ])


@app.callback(
    Output("vm-store", "data"),
    Output("viz", "figure"),
    Output("legend", "children"),
    Output("kpis", "children"),
    Output("f-country", "options"),
    Input("f0", "value"),
    Input("f1", "value"),
    Input("f2", "value"),
    State("view-store", "data"),
    State("sel-store", "data"),
)
def compute(v0, v1, v2, view, sel):
    filters = ds.FILTERS[view]
    vals = [v0, v1, v2][:len(filters)]
    if view != "ef" and any(v is None for v in vals):
        raise PreventUpdate                      # filters are still being set up

    try:
        vm = ds.DATASETS[view]["resolve"](vals)
        vm = json.loads(json.dumps(vm, cls=PlotlyJSONEncoder))     # plain JSON types everywhere
        if vm["kind"] == "frontier":
            fig = u.build_frontier_figure(vm, sel)
            legend = None
        else:
            geojson = q.get_world_boundaries_geojson([r["iso"] for r in vm["rows"]])
            fig = u.build_map_figure(vm, geojson, rev=f"{view}|{vm['region']}")
            legend = u.build_legend(vm)
    except Exception:                                      # never leave the page blank
        log.exception("Could not build view %s with filters %s", view, vals)
        return None, go.Figure(), _error_block(), None, []

    options = [{"label": r["name"], "value": r["iso"]}
               for r in sorted(vm["rows"], key=lambda r: r["name"])]
    return vm, fig, legend, u.build_kpis(vm), options


# ══════════════════════════════════════════════════════════════════════════
# Dashboard: country selection (map click, search box, list, remove, clear)
# ══════════════════════════════════════════════════════════════════════════

def _iso_from_click(click_data):
    try:
        return click_data["points"][0]["customdata"][0]
    except (KeyError, IndexError, TypeError):
        return None


@app.callback(
    Output("sel-store", "data"),
    Output("viz", "clickData"),
    Output("f-country", "value"),
    Input("viz", "clickData"),
    Input("f-country", "value"),
    Input({"type": "rank-row", "iso": ALL}, "n_clicks"),
    Input({"type": "sel-remove", "iso": ALL}, "n_clicks"),
    Input({"type": "sel-clear", "i": ALL}, "n_clicks"),
    Input("vm-store", "data"),
    State("sel-store", "data"),
    State("view-store", "data"),
    prevent_initial_call=True,
)
def update_selection(click, picked, _rank, _remove, _clear, vm, sel, view):
    sel = list(sel or [])
    limit = ds.DATASETS[view]["max_select"]
    trig = ctx.triggered[0] if ctx.triggered else {}
    tid = ctx.triggered_id

    def add(iso):
        if not iso:
            return sel
        if limit == 1:
            return [iso]
        if iso in sel:                                   # clicking again removes it
            return [c for c in sel if c != iso]
        return sel + [iso] if len(sel) < limit else sel

    if tid == "viz":
        return add(_iso_from_click(click)), None, no_update
    if tid == "f-country":
        return add(picked), no_update, None
    if isinstance(tid, dict) and trig.get("value"):
        if tid["type"] == "rank-row":
            return add(tid["iso"]), no_update, no_update
        if tid["type"] == "sel-remove":
            return [c for c in sel if c != tid["iso"]], no_update, no_update
        if tid["type"] == "sel-clear":
            return [], None, no_update
    if tid == "vm-store" and vm:
        present = {r["iso"] for r in vm["rows"]}
        pruned = [c for c in sel if c in present][:limit]
        if pruned != sel:
            return pruned, no_update, no_update
    raise PreventUpdate


@app.callback(
    Output("pane-body", "children"),
    Input("vm-store", "data"),
    Input("sel-store", "data"),
)
def render_pane(vm, sel):
    if not vm:
        return _error_block()
    return u.build_pane(vm, sel)


@app.callback(
    Output("viz", "figure", allow_duplicate=True),
    Input("sel-store", "data"),
    State("vm-store", "data"),
    prevent_initial_call=True,
)
def show_selection_on_chart(sel, vm):
    """Outline the selected country (map) or recolour the chosen dots (frontier)
    without re-sending any boundary geometry."""
    if not vm:
        raise PreventUpdate
    if vm["kind"] == "frontier":
        return u.build_frontier_figure(vm, sel)
    patch = Patch()
    iso = (sel or [None])[0]
    if iso and any(r["iso"] == iso for r in vm["rows"]):
        patch["data"][1] = u.selection_outline_trace(iso, q.get_world_boundaries_geojson([iso]))
    else:
        patch["data"][1] = u.EMPTY_OUTLINE_TRACE
    return patch


app.clientside_callback(
    """
    function(which) {
        // Plotly needs a resize nudge when a hidden chart becomes visible.
        setTimeout(function() { window.dispatchEvent(new Event('resize')); }, 60);
        return 'viz-col show-' + (which || 'frontier');
    }
    """,
    Output("viz-col", "className"),
    Input("ef-chart", "value"),
)


@app.callback(
    Output("viz2", "figure"),
    Output("viz2-sub", "children"),
    Input("sel-store", "data"),
    Input("f0", "value"),
    Input("f1", "value"),
    State("view-store", "data"),
)
def update_components(sel, method, sample, view):
    """Efficiency tab only: component scores for the selected countries."""
    if view != "ef":
        raise PreventUpdate
    sel = sel or []
    fig = go.Figure()
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      margin=dict(l=0, r=0, t=0, b=0))
    if not sel:
        fig.add_annotation(text="Select countries to compare their component scores",
                           showarrow=False, font=dict(family=u.FONT_STACK, size=14, color="#6B7A90"))
        return fig, "Method and sample are set in the filters above."
    df = q.ef_get_scores(method=method, sample=sample, isos=sel)
    if df.empty:
        fig.add_annotation(text="No component scores for this method and sample",
                           showarrow=False, font=dict(family=u.FONT_STACK, size=14, color="#6B7A90"))
        return fig, f"Method: {method}  |  Sample: {sample}"
    return (u.build_components_figure(df, sel, q.get_country_name_map()),
            f"Method: {method}  |  Sample: {sample}")


# ── Downloads (the PNG is made in the browser by assets/export.js) ────────────

@app.callback(
    Output("dl-data", "data"),
    Input("dl-viz-csv", "n_clicks"), Input("dl-viz2-csv", "n_clicks"),
    State("vm-store", "data"), State("view-store", "data"), State("sel-store", "data"),
    *[State(f"f{i}", "value") for i in range(pages.MAX_FILTERS)],
    prevent_initial_call=True,
)
def download_csv(_viz, _viz2, vm, view, sel, *filter_values):
    """CSV of the data behind the main chart (every country in the view) or behind the component chart."""
    trig = ctx.triggered[0] if ctx.triggered else None
    if not trig or not trig.get("value") or not vm or view not in ds.DATASETS:
        raise PreventUpdate
    sel = sel or []
    roles = {iso: "Selected" for iso in sel} if sel else None
    title = ds.DATASETS[view]["title"]
    try:
        if ctx.triggered_id == "dl-viz2-csv":
            method, sample = (list(filter_values) + [None, None])[:2]
            if not sel:
                raise PreventUpdate
            df = q.ef_get_scores(method=method, sample=sample, isos=sel)
            if df.empty:
                raise PreventUpdate
            text = ex.components_csv(df, q.get_country_name_map(), roles, q.EF_SHORT_NAME_ORDER)
            return dcc.send_string(text, ex.filename("infrastructure-efficiency-components"))
        text = ex.vm_csv(vm, title, vm.get("region"), roles, ds.PEFA_LABELS if view == "pefa" else None)
        return dcc.send_string(text, ex.filename(title, vm.get("region")))
    except PreventUpdate:
        raise
    except Exception:
        log.exception("CSV download failed for view %s", view)
        raise PreventUpdate


# ══════════════════════════════════════════════════════════════════════════
# Country-wise page (?page=country-wise-cbd-analysis): its callbacks live in
# country_page.py and are attached here, to this app.
# ══════════════════════════════════════════════════════════════════════════

country_page.register_callbacks(app)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
