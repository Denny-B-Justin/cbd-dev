"""
release_notes.py
----------------
The release-notes page:  ?page=release-notes   (opens in a new tab from the header and footer)

The notes are plain data (RELEASES, newest first) so a new release is one more
entry at the top of the list; the layout below never needs to change.

Versions follow MAJOR.MINOR.PATCH:
  0.x   pre-production (notebook prototype, front-end demo)
  1.0   first production release on World Bank infrastructure
  2.0   redesign: new navigation, new page, new features
"""

from dash import html

import utils as u

# Each release: version, name, status ("latest" or ""), date, one-line summary,
# and its changes as (group heading, [items]).
RELEASES = [
    {
        "version": "2.0.0",
        "name": "Redesign and country-wise analysis",
        "status": "latest",
        "date": "October 2026",
        "summary": "A redesigned interface written for clients and government staff, a new page that shows "
                   "every benchmark for one country, and chart downloads.",
        "changes": [
            ("Navigation", [
                "Seven separate benchmark pages replaced by three: Overview, Dashboard and Country-wise analysis.",
                "Every view has a shareable link: the active benchmark (e.g. #gtmi) or the country and peers "
                "(e.g. #country=KHM&peers=VNM,THA) are kept in the address.",
                "Old links such as ?page=gtmi still work and open the matching benchmark.",
            ]),
            ("Overview page", [
                "Plain-language introduction and a three-step \"How it works\" guide.",
                "The seven benchmarks grouped as Global and Regional deep-dives, each with coverage, source, "
                "size and what it measures.",
                "\"How to read the scores\": the colour scale and the scoring range of each benchmark.",
            ]),
            ("Dashboard", [
                "All seven benchmarks on one page, switched with tabs.",
                "Each benchmark states the question it answers, how to read it, and an \"About this data\" note.",
                "Filters (Region, Topic, Indicator, Pillar, Method, Sample) sit beside four headline numbers "
                "that update with them.",
                "Map legend counts the countries in each score band.",
                "Detail pane: a ranked list of countries; selecting a country shows its score, rank, comparison "
                "with the average and the indicators behind it.",
                "Countries can be selected from the map, the ranked list or a search box. The selection is kept "
                "when switching benchmarks.",
                "Infrastructure efficiency: compare up to five countries and switch between the efficiency "
                "frontier and component scores.",
            ]),
            ("Country-wise analysis (new)", [
                "One country, all seven benchmarks, on one page, grouped as Infrastructure, Public investment "
                "management, Climate readiness and Regional deep-dive.",
                "Compare with up to three peer countries. The selected country is red on every map and chart, "
                "each peer has its own colour and all other countries are shown lighter.",
                "Country header shows the region and which benchmarks have data for the country.",
                "Each map is framed on the country's region, with a table comparing the country and its peers "
                "indicator by indicator.",
                "Where a regional benchmark does not cover the country, the panel says so and lists the "
                "countries that were assessed.",
                "Opens in a new tab from the Overview page and the header.",
            ]),
            ("Downloads", [
                "\"Save PNG\" on every chart and map, with its title, filters and legend included in the image.",
                "\"Download CSV\" of the data behind each chart. Files open correctly in Excel, including "
                "country names with accents, and are named by chart and date.",
            ]),
            ("Design and accessibility", [
                "Orange-to-indigo colour scale, readable with red-green colour blindness, replaces the "
                "red-yellow-green scale. Grey means no data.",
                "Map framing tuned so each region fills the map.",
                "Fira Sans font is served by the app, so it also loads on networks that block Google Fonts.",
                "Keyboard focus outlines, labelled regions for screen readers, and support for reduced motion.",
                "Layouts adapt to laptop, tablet and phone screens.",
            ]),
            ("Other", [
                "Release notes now live inside the app (this page).",
            ]),
        ],
    },
    {
        "version": "1.0.0",
        "name": "Production release",
        "status": "",
        "date": "",
        "summary": "The dashboard rebuilt as a production Python Dash app, reading its data from the World Bank's "
                   "MEGA Databricks platform.",
        "changes": [
            ("Platform", [
                "Front end rebuilt in Python Dash (Flask).",
                "Deployed on datanalytics.worldbank.org.",
            ]),
            ("Data", [
                "All benchmark tables moved from CSV files into Unity Catalog on MEGA Databricks.",
                "Access through a Databricks service principal; the app checks its settings at start-up.",
                "Country codes aligned with official World Bank ISO3 codes: OKX to XKX (Kosovo) and "
                "WBG to PSE (West Bank and Gaza).",
                "Country boundaries taken from the official World Bank boundaries and stored in Unity Catalog.",
                "Overseas territories merged into their country (e.g. France, Spain, United Kingdom, Portugal, "
                "Australia), so each country has a single shape and no duplicates.",
            ]),
            ("Features", [
                "One page per benchmark, each with Region or Pillar filters and a world map.",
                "Click a country to see its indicator scores.",
                "Infrastructure efficiency frontier calculated in the app.",
            ]),
        ],
    },
    {
        "version": "0.2.0",
        "name": "Demo",
        "status": "",
        "date": "",
        "summary": "A Next.js web app to demonstrate the dashboard, built on the benchmark data as CSV files.",
        "changes": [
            ("Scope", [
                "Front end only; data read from CSV files bundled with the app.",
                "Interactive maps for the seven benchmarks, with region filters and country pop-ups.",
                "Not connected to World Bank data platforms.",
            ]),
        ],
    },
    {
        "version": "0.1.0",
        "name": "Prototype",
        "status": "",
        "date": "",
        "summary": "A Jupyter notebook that brought the benchmark datasets together and charted them.",
        "changes": [
            ("Scope", [
                "Loaded the source data: climate institutions, GovTech readiness (GTMI), infrastructure gap, "
                "infrastructure efficiency, PEFA, climate assessment (CCIA) and the PIM tracker (PIIAG).",
                "Produced one chart per dataset, viewed one at a time.",
                "Static output; no web interface.",
            ]),
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════
# Layout
# ══════════════════════════════════════════════════════════════════════════

def _anchor(version):
    return "v" + version.replace(".", "-")


def _release(r):
    meta = [html.Span("v" + r["version"], className="rn-version")]
    if r["status"] == "latest":
        meta.append(html.Span("Latest", className="rn-badge"))
    if r["date"]:
        meta.append(html.Span(r["date"], className="rn-date"))
    return html.Li(id=_anchor(r["version"]), className="rn-release", children=[
        html.Div(className="rn-side", children=[
            html.Div(className="rn-meta", children=meta),
            html.H2(r["name"], className="rn-name"),
        ]),
        html.Div(className="rn-body", children=[
            html.P(r["summary"], className="rn-summary"),
            *[html.Div(className="rn-group", children=[
                html.H3(heading, className="rn-group-title"),
                html.Ul([html.Li(item) for item in items], className="rn-list"),
            ]) for heading, items in r["changes"]],
        ]),
    ])


def layout(logo_src, wb_logo_src):
    return html.Div(className="page page-home page-notes", children=[
        u.build_header(u.RELEASE_NOTES_PAGE, logo_src),
        html.Main(children=[
            html.Section(className="rn-hero", children=html.Div(className="section-inner", children=[
                html.H1("Release notes", className="rn-title"),
                html.P("What changed in each version of the Country Benchmarking Dashboard, newest first.",
                       className="rn-lede"),
                html.Nav(className="rn-jump", **{"aria-label": "Versions"}, children=[
                    html.A("v" + r["version"], href="#" + _anchor(r["version"])) for r in RELEASES
                ]),
            ])),
            html.Section(className="section rn", children=html.Div(className="section-inner", children=[
                html.Ol([_release(r) for r in RELEASES], className="rn-releases"),
            ])),
        ]),
        u.build_footer(wb_logo_src),
    ])
