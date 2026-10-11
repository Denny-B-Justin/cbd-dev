"""
pages.py
--------
Layout builders for the two pages of the app:

  home_layout()       the overview / landing page (with the "Launch Tool" button)
  dashboard_layout()  the single-page dashboard: tab switcher, top filter bar,
                      KPI strip, map + dynamic detail pane

Layouts only describe structure and ids. All behaviour lives in app.py.
Asset URLs are resolved by app.py (it owns the Dash instance) and passed in.
"""

from dash import dcc, html

import datasets as ds
import utils as u

MAX_FILTERS = ds.MAX_FILTERS


# ══════════════════════════════════════════════════════════════════════════
# Home / overview
# ══════════════════════════════════════════════════════════════════════════

def _launch_button(label="Launch Tool", cls="btn btn-primary"):
    return dcc.Link(label, href=u.DASHBOARD_HREF, className=cls)


def _hero():
    return html.Section(className="hero", children=[
        html.Div(className="hero-map", **{"aria-hidden": "true"}),
        html.Div(className="hero-inner", children=[
            html.H1("Compare countries on public investment, infrastructure and climate readiness",
                    className="hero-title"),
            html.P("The Country Benchmarking Dashboard brings seven World Bank benchmarks together on one "
                   "page. Choose a topic, pick a region, and click any country to see its score and the "
                   "indicators behind it.", className="hero-lede"),
            html.Div(className="hero-actions", children=[
                _launch_button(),
                html.A("See what's inside", href="#benchmarks", className="btn btn-ghost"),
            ]),
            html.P("Seven benchmarks. Up to 220 countries. Global comparisons and regional deep-dives.",
                   className="hero-facts"),
        ]),
    ])


def _how_it_works():
    steps = [
        ("Choose a topic",
         "Tabs across the top of the dashboard switch between climate institutions, GovTech readiness, "
         "infrastructure gaps and the other benchmarks."),
        ("Narrow it down",
         "Use the filters to focus on a region or a pillar. The map, the headline numbers and the "
         "ranking update straight away."),
        ("Click a country",
         "See its score, how it ranks against its peers, and every indicator behind the number."),
    ]
    return html.Section(className="section how", children=html.Div(className="section-inner", children=[
        html.H2("How it works", className="section-title"),
        html.Ol(className="steps", children=[
            html.Li(className="step", children=[
                html.Span(str(i), className="step-n"),
                html.H3(title, className="step-title"),
                html.P(text, className="step-text"),
            ]) for i, (title, text) in enumerate(steps, start=1)
        ]),
    ]))


def _bench_row(key):
    spec = ds.DATASETS[key]
    return html.Li(className="bench", children=[
        html.Div(className="bench-head", children=[
            html.H4(dcc.Link(spec["title"], href=u.page_href("dashboard", key)), className="bench-name"),
            dcc.Link("Open in dashboard", href=u.page_href("dashboard", key), className="bench-open"),
        ]),
        html.P(spec["question"], className="bench-question"),
        html.Dl(className="bench-facts", children=[
            html.Div([html.Dt("Coverage"), html.Dd(spec["coverage"])]),
            html.Div([html.Dt("Source"), html.Dd(spec["source"])]),
            html.Div([html.Dt("Size"), html.Dd(spec["size"])]),
        ]),
        html.Details(className="bench-more", children=[
            html.Summary("What it measures"),
            html.P(spec["focus"]),
            html.P(spec["official"], className="bench-official"),
        ]),
    ])


def _benchmarks():
    groups = []
    for g in ("global", "regional"):
        groups.append(html.Div(className="bench-group", children=[
            html.Div(className="bench-group-intro", children=[
                html.H3(ds.GROUP_LABELS[g], className="bench-group-title"),
                html.P(ds.GROUP_BLURBS[g], className="bench-group-blurb"),
            ]),
            html.Ul([_bench_row(k) for k in ds.TAB_ORDER[g]], className="bench-list"),
        ]))
    return html.Section(id="benchmarks", className="section benchmarks", children=html.Div(
        className="section-inner", children=[
            html.H2("Seven benchmarks, one dashboard", className="section-title"),
            html.P("Each benchmark answers a different question. Open any of them directly.",
                   className="section-lede"),
            *groups,
        ]))


def _reading_scores():
    ramp = [html.Li(className="ramp-step", children=[
        html.Span(className="ramp-swatch", style={"backgroundColor": c}),
        html.Span(lbl),
    ]) for c, lbl in zip(u.HEX_CODES_5, ds.BAND_LABELS_5)]
    ramp.append(html.Li(className="ramp-step", children=[
        html.Span(className="ramp-swatch", style={"backgroundColor": u.NO_DATA_COLOR}),
        html.Span("No data")]))
    scales = [
        ("Climate institutions", "0 to 1. The average of 12 indicators."),
        ("GovTech readiness", "0 to 1 for each pillar, plus a three-step PIMS status."),
        ("Infrastructure gap", "An index where 0 is the regional average and higher is better."),
        ("Efficiency frontier", "Up to 1.00. A score of 1.00 means the country is on the frontier."),
        ("PEFA grades", "Letter grades from A (strongest) to D (weakest)."),
        ("Climate assessment", "1 to 6. The average of its indicators."),
        ("PIM tracker", "The range is shown in the dashboard legend."),
    ]
    return html.Section(className="section reading", children=html.Div(className="section-inner reading-inner", children=[
        html.Div(className="reading-copy", children=[
            html.H2("How to read the scores", className="section-title"),
            html.P("Every map uses the same five colours, from orange for low scores to dark blue for high "
                   "ones. Grey means no data. Each benchmark has its own scale, so compare countries "
                   "within a benchmark rather than across benchmarks.", className="section-lede"),
            html.Ul(ramp, className="ramp"),
        ]),
        html.Dl(className="scales", children=[
            html.Div([html.Dt(name), html.Dd(text)]) for name, text in scales
        ]),
    ]))


def _closing_cta():
    return html.Section(className="closing", children=html.Div(className="section-inner closing-inner", children=[
        html.H2("Ready to explore?", className="closing-title"),
        _launch_button("Launch Tool", "btn btn-primary"),
    ]))


def home_layout(logo_src, wb_logo_src):
    return html.Div(className="page page-home", children=[
        u.build_header("", logo_src),
        html.Main(children=[_hero(), _how_it_works(), _benchmarks(), _reading_scores(), _closing_cta()]),
        u.build_footer(wb_logo_src),
    ])


# ══════════════════════════════════════════════════════════════════════════
# Dashboard
# ══════════════════════════════════════════════════════════════════════════

def _tabbar():
    groups = []
    for g in ("global", "regional"):
        groups.append(html.Div(className="tab-group", children=[
            html.Span(ds.GROUP_LABELS[g], className="tab-group-label", id=f"tabgroup-{g}"),
            html.Div(className="tab-list", role="group", **{"aria-labelledby": f"tabgroup-{g}"}, children=[
                html.Button(
                    ds.DATASETS[k]["tab"], id={"type": "tab", "key": k}, n_clicks=0,
                    className="tab", role="tab", **{"aria-selected": "false"},
                ) for k in ds.TAB_ORDER[g]
            ]),
        ]))
    return html.Div(className="tabbar", role="tablist", **{"aria-label": "Benchmarks"}, children=groups)


def _filter_field(i):
    return html.Div(className="field", id=f"f{i}-field", children=[
        html.Label("", id=f"f{i}-label", htmlFor=f"f{i}", className="field-label"),
        dcc.Dropdown(id=f"f{i}", options=[], value=None, clearable=False, searchable=False,
                     className="select"),
        html.Span("", id=f"f{i}-help", className="field-help"),
    ])


def _filterbar():
    return html.Div(className="filterbar", role="group", **{"aria-label": "Filters"},
                    children=[_filter_field(i) for i in range(MAX_FILTERS)])


def _pane_search():
    return html.Div(className="pane-search", children=[
        html.Label("Find a country", htmlFor="f-country", className="field-label"),
        dcc.Dropdown(id="f-country", options=[], value=None, clearable=False, searchable=True,
                     placeholder="Type a country name", className="select"),
        html.Span("", id="f-country-help", className="field-help"),
    ])


def dashboard_layout(logo_src, initial_view=ds.DEFAULT_VIEW):
    return html.Div(className="page page-dashboard", children=[
        u.build_header("dashboard", logo_src),
        html.Main(className="dash", children=[
            _tabbar(),
            html.Div(id="context", className="context-wrap"),
            html.Div(className="strip", children=[
                _filterbar(),
                html.Div(id="kpis", className="kpis-wrap"),
            ]),
            html.Div(id="main-grid", className="main-grid is-map", children=[
                html.Section(id="viz-col", className="viz-col show-frontier", **{"aria-label": "Chart"}, children=[
                    html.Div(className="viz-switch", children=dcc.RadioItems(
                        id="ef-chart", value="frontier", className="segmented", inline=True,
                        options=[{"label": "Efficiency frontier", "value": "frontier"},
                                 {"label": "Component scores", "value": "components"}])),
                    html.Div(className="viz-frame", children=[
                        dcc.Loading(
                            type="circle", color=u.INDIGO, delay_show=250,
                            overlay_style={"visibility": "visible", "opacity": 0.55},
                            className="viz-loading",
                            children=html.Div(className="viz-stack", children=dcc.Graph(
                                id="viz", className="viz",
                                config={"displayModeBar": False, "scrollZoom": True},
                                style={"height": "100%", "width": "100%"})),
                        ),
                        html.Div(id="legend", className="legend-wrap"),
                    ]),
                    html.Div(id="viz2-wrap", className="viz2-wrap", children=[
                        html.H3("What sits behind the efficiency scores", className="pane-h"),
                        html.P(id="viz2-sub", className="pane-help"),
                        dcc.Graph(id="viz2", config={"displayModeBar": False},
                                  style={"flex": "1 1 0", "minHeight": 0, "width": "100%"}),
                    ]),
                ]),
                html.Aside(className="pane", **{"aria-label": "Details"}, children=[
                    _pane_search(),
                    html.Div(id="pane-body", className="pane-body", **{"aria-live": "polite"}),
                ]),
            ]),
        ]),
        dcc.Store(id="view-store", data=initial_view),
        dcc.Store(id="sel-store", data=[]),
        dcc.Store(id="vm-store"),
    ])


def not_found_layout(logo_src):
    return html.Div(className="page", children=[
        u.build_header("", logo_src),
        html.Main(className="notfound", children=[
            html.H1("We can't find that page"),
            html.P("The address may be out of date. The overview lists everything that is available."),
            dcc.Link("Back to the overview", href=u.HOME_HREF, className="btn btn-primary"),
        ]),
    ])
