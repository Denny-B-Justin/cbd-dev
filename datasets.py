"""
datasets.py
-----------
One place that describes every benchmark in the dashboard.

Why this file exists
~~~~~~~~~~~~~~~~~~~~
The old app had one hand-built page per dataset, each with its own sidebar,
its own callbacks and its own wording. The new dashboard is ONE page that
re-uses the same map / KPI strip / detail pane for every dataset, so each
dataset is now just an entry in DATASETS below:

  * plain-language copy (what question it answers, how to read it)
  * its filters (Region, Pillar, ...)
  * a `resolve(filter_values)` function that calls queries.py and returns a
    "view model" - a dict the UI knows how to draw. Nothing in here touches
    Dash; nothing in queries.py had to change.

To add a new benchmark: add a resolver + a DATASETS entry + put its key in
TAB_ORDER. No new page, layout or callback is needed.

View model (what every resolver returns)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
{
  "kind":        "continuous" | "categorical" | "frontier",
  "rows":        [{"iso","name","score","band","tooltip","popup":[{"indicator","score"}]}],
  "colors":      [hex, ...]          one per band (low -> high, or category order)
  "labels":      [str, ...]          one per band
  "vmin","vmax": numeric range used for the 5 bands (continuous only)
  "legend_title": str,
  "legend_note":  str | None,
  "higher_is_better": bool           how to rank rows
  "popup":       {"mode": "bars"|"text"|"grades", "lo","hi","ternary"}
  "kpi":         {"mode": "score"|"split"|"groups", "groups": [...]}
  "region":      str                 key into utils.MAP_VIEWS (map framing)
  "score_fmt":   "{:.2f}"
}
"""

import queries as q
import utils as u

# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

BAND_LABELS_5 = ["Low", "Medium-low", "Medium", "Medium-high", "High"]


def _opts(values):
    return [{"label": v, "value": v} for v in values]


def _pad(vals, n):
    vals = list(vals or [])
    return vals + [None] * (n - len(vals))


def _build_rows(country_data, kind, n_bands, vmin=None, vmax=None):
    """country_data (queries.py shape) -> rows with names + colour band."""
    names = q.get_country_name_map()
    rows = []
    for d in country_data:
        score = d.get("score")
        if kind == "continuous":
            band = u.heatmap_bucket(score, vmin, vmax)
        else:
            band = u.categorical_bucket(score, n_bands)
        iso = d["cntrCode"]
        rows.append({
            "iso": iso,
            "name": names.get(iso, iso),
            "score": score,
            "band": band,
            "tooltip": d.get("tooltip", iso),
            "popup": d.get("popupRows", []),
        })
    return rows


def _range_from_data(country_data, vmin, vmax):
    valid = [d["score"] for d in country_data if d.get("score") is not None]
    if vmin is None:
        vmin = min(valid) if valid else 0
    if vmax is None:
        vmax = max(valid) if valid else 1
    return vmin, vmax


def _continuous(country_data, *, vmin, vmax, legend_title, region, popup, legend_note=None,
                kpi=None, score_fmt="{:.2f}", labels=None):
    vmin, vmax = _range_from_data(country_data, vmin, vmax)
    return {
        "kind": "continuous",
        "rows": _build_rows(country_data, "continuous", 5, vmin, vmax),
        "colors": u.HEX_CODES_5,
        "labels": labels or BAND_LABELS_5,
        "vmin": vmin, "vmax": vmax,
        "legend_title": legend_title,
        "legend_note": legend_note,
        "higher_is_better": True,
        "popup": popup,
        "kpi": kpi or {"mode": "score"},
        "region": region,
        "score_fmt": score_fmt,
    }


def _categorical(country_data, *, colors, labels, legend_title, region, popup,
                 higher_is_better, kpi, legend_note=None):
    return {
        "kind": "categorical",
        "rows": _build_rows(country_data, "categorical", len(colors)),
        "colors": colors,
        "labels": labels,
        "vmin": None, "vmax": None,
        "legend_title": legend_title,
        "legend_note": legend_note,
        "higher_is_better": higher_is_better,
        "popup": popup,
        "kpi": kpi,
        "region": region,
        "score_fmt": "{}",
    }


# ══════════════════════════════════════════════════════════════════════════
# Resolvers - one per dataset. Each calls an existing queries.py function.
# ══════════════════════════════════════════════════════════════════════════

def _resolve_gccii(vals):
    (region,) = _pad(vals, 1)
    return _continuous(
        q.gccii_country_data(region),
        vmin=0, vmax=1, region=region,
        legend_title="Average climate-institutions score (0 to 1)",
        popup={"mode": "bars", "lo": 0, "hi": 1, "ternary": True},
    )


PIMS_LABELS = ["Not yet implemented", "Under implementation", "Implemented"]
GTMI_PILLAR_LABELS = {
    "PIMS": "PIMS status",
    "GTMI": "GTMI overall",
    "CGSI": "Core government systems (CGSI)",
    "PSDI": "Public service delivery (PSDI)",
    "DCEI": "Digital citizen engagement (DCEI)",
    "GTEI": "GovTech enablers (GTEI)",
}


def _resolve_gtmi(vals):
    region, pillar = _pad(vals, 2)
    pillar = pillar or "PIMS"
    cd = q.gtmi_country_data(region, pillar)
    if pillar == "PIMS":
        return _categorical(
            cd, colors=u.HEX_CODES_3, labels=PIMS_LABELS,
            legend_title="Public investment management system (PIMS)",
            region=region, popup={"mode": "text"}, higher_is_better=True,
            kpi={"mode": "groups", "groups": [
                {"label": "PIMS implemented", "bands": [2]},
                {"label": "Under implementation", "bands": [1]},
                {"label": "Not yet implemented", "bands": [0]},
            ]},
        )
    return _continuous(
        cd, vmin=0, vmax=1, region=region,
        legend_title=f"{GTMI_PILLAR_LABELS.get(pillar, pillar)} (0 to 1)",
        popup={"mode": "bars", "lo": 0, "hi": 1, "ternary": False},
    )


def _resolve_infra(vals):
    (region,) = _pad(vals, 1)
    return _continuous(
        q.infra_country_data(region),
        vmin=None, vmax=None, region=region,
        legend_title="Infrastructure services vs. regional peers",
        legend_note="0 = the regional average. Countries missing any of the six "
                    "indicators are left out of the index and shown in grey.",
        popup={"mode": "text"},
        kpi={"mode": "split"},
    )


GRADE_GROUPS = [
    {"label": "Grades A to B", "bands": [0, 1, 2]},
    {"label": "Grades C+ and C", "bands": [3, 4]},
    {"label": "Grades D+ and below", "bands": [5, 6, 7]},
]

PEFA_LABELS = {
    "PI-11": "PI-11 · Public investment management",
    "PI-11.3": "PI-11.3 · Project costing & budget alignment",
    "PI-11.4": "PI-11.4 · Investment project monitoring",
    "PI-12": "PI-12 · Public asset management",
    "PI-16": "PI-16 · Medium-term fiscal perspective",
}


def _countries_in_region(region):
    """ISO codes belonging to a World Bank region, or None if unknown."""
    try:
        df = q.get_country_groups_df()
        codes = set(df.loc[df["grpName"] == region, "cntrCode"])
        return codes or None
    except Exception:  # pragma: no cover - defensive; never break the page
        return None


def _resolve_pefa(vals):
    region, indicator = _pad(vals, 2)
    indicator = indicator or q.PEFA_INDICATORS[0]
    cd = q.pefa_country_data(indicator=indicator, framework="Annex 2011")
    # PEFA data has no region column, so Region used to only move the map.
    # In the new dashboard Region filters the list as well (via country_group),
    # so the ranking, KPIs and map always describe the same set of countries.
    members = _countries_in_region(region)
    if members:
        cd = [d for d in cd if d["cntrCode"] in members]
    return _categorical(
        cd, colors=[q.SCORE_COLOR_MAP[g] for g in q.GRADE_ORDER], labels=list(q.GRADE_ORDER),
        legend_title=f"PEFA {indicator} grade",
        legend_note="A is the strongest grade, D the weakest. NU = not used.",
        region=region, popup={"mode": "grades"}, higher_is_better=False,
        kpi={"mode": "groups", "groups": GRADE_GROUPS},
    )


def _resolve_ccia(vals):
    region, pillar = _pad(vals, 2)
    return _continuous(
        q.ccia_country_data(region, pillar or "Overall"),
        vmin=1, vmax=6, region=region,
        legend_title=f"Average CCIA score - {pillar or 'Overall'} (1 to 6)",
        popup={"mode": "bars", "lo": 1, "hi": 6, "ternary": False},
    )


def _resolve_piiag(vals):
    region, section = _pad(vals, 2)
    cd = q.piiag_country_data(region, section or "Overall")
    # The old page hard-coded a 1-6 range while its own notes describe a 0/0.5/1
    # scale. Pick the range from the data so the colours are right either way.
    valid = [d["score"] for d in cd if d.get("score") is not None]
    zero_to_one = bool(valid) and max(valid) <= 1
    lo, hi = (0, 1) if zero_to_one else (1, 6)
    return _continuous(
        cd, vmin=lo, vmax=hi, region=region,
        legend_title=f"Average PIIAG score - {section or 'Overall'} ({lo} to {hi})",
        popup={"mode": "bars", "lo": lo, "hi": hi, "ternary": zero_to_one},
    )


def _resolve_ef(vals):
    names = q.get_country_name_map()
    fr = q.ef_get_frontier()
    rows = []
    for p in fr["scatter"]:
        iso = p["iso"]
        rows.append({
            "iso": iso, "name": names.get(iso, iso),
            "x": p["x"], "y": p["y"], "theta": p.get("theta"),
            "score": p.get("theta"), "band": None, "tooltip": names.get(iso, iso), "popup": [],
        })
    return {
        "kind": "frontier",
        "rows": rows,
        "frontier": {"dea": fr["dea"], "fdh": fr["fdh"]},
        "colors": [], "labels": [], "vmin": None, "vmax": None,
        "legend_title": "", "legend_note": None,
        "higher_is_better": True,
        "popup": {"mode": "text"},
        "kpi": {"mode": "frontier"},
        "region": "World",
        "score_fmt": "{:.2f}",
    }


# ══════════════════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════════════════
# Each filter is {"label", "options": callable -> [{"label","value"}], "default": callable}
# (callables so that anything needing the database is only evaluated when used).

def _region_filter(label="Region", regions=None):
    regions = regions or u.GLOBAL_REGIONS
    return {"label": label, "options": lambda: _opts(regions), "default": lambda: regions[0],
            "help": None}


def _local_group_filter():
    return {"label": "Country group", "options": lambda: _opts(u.LOCAL_REGIONS),
            "default": lambda: u.LOCAL_REGIONS[0], "help": None}


def _with_overall(label, getter):
    return {
        "label": label,
        "options": lambda: _opts(["Overall"] + getter()),
        "default": lambda: "Overall",
        "help": None,
    }


FILTERS = {
    "gccii": [_region_filter()],
    "gtmi": [
        _region_filter(),
        {"label": "Topic", "options": lambda: [{"label": GTMI_PILLAR_LABELS.get(p, p), "value": p}
                                               for p in q.GTMI_PILLARS],
         "default": lambda: "PIMS", "help": None},
    ],
    "infra": [_region_filter()],
    "pefa": [
        _region_filter(),
        {"label": "Indicator", "options": lambda: [{"label": PEFA_LABELS.get(i, i), "value": i}
                                                    for i in q.PEFA_INDICATORS],
         "default": lambda: q.PEFA_INDICATORS[0], "help": None},
    ],
    "ef": [
        {"label": "Method", "options": lambda: _opts(q.ef_get_filters()["methods"]),
         "default": lambda: (q.ef_get_filters()["methods"] or [None])[0],
         "help": "Applies to the component chart."},
        {"label": "Sample", "options": lambda: _opts(q.ef_get_filters()["samples"]),
         "default": lambda: (q.ef_get_filters()["samples"] or [None])[0],
         "help": "Applies to the component chart."},
    ],
    "ccia": [_local_group_filter(), _with_overall("Pillar", q.ccia_pillars)],
    "piiag": [_local_group_filter(), _with_overall("Section", q.piiag_sections)],
}


# ══════════════════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════════════════

DATASETS = {
    "gccii": {
        "tab": "Climate institutions",
        "group": "global",
        "title": "Climate institutions",
        "official": "Global Climate Change Institutional Indicators (GCCIIs)",
        "question": "Which institutional building blocks for managing climate change "
                    "(laws, plans, budget rules) are already in place?",
        "how_to": "Each country is scored on 12 indicators. An indicator counts as 1 if it is in "
                  "place, 0.5 if partly in place and 0 if absent. The map shows the average.",
        "coverage": "Global",
        "source": "World Bank",
        "size": "12 indicators, 182 countries",
        "about": [
            ("What it is", "Global Climate Change Institutional Indicators (GCCIIs), produced by the "
                           "Climate Governance Program of the Prosperity Vertical Institutions Development."),
            ("Data", "The current draft dataset for 2024 covers 12 indicators for 182 countries."),
            ("Scoring", "Indicators are quantified as 0 (no information/none), partial (0.5), and present (1). "
                        "The summary is the average of these scores."),
        ],
        "focus": "12 Indicators: law, coordination, long term strategy, national adaptation plan, fiscal "
                 "risk statements, local climate risk, budget guidelines, expenditure tracking, public "
                 "investment, SOE disclosure, sub-national strategies and risk assessments, environment in "
                 "procurement",
        "resolve": _resolve_gccii,
        "max_select": 1,
    },
    "gtmi": {
        "tab": "GovTech readiness",
        "group": "global",
        "title": "GovTech readiness",
        "official": "GovTech Maturity Index (GTMI) - Core Government Systems Index (CGSI): "
                    "Public Investment Management Systems",
        "question": "How far has government digitisation progressed, and does the country run a "
                    "public investment management system (PIMS)?",
        "how_to": "Start with PIMS status to see which countries have a system in place. Switch "
                  "Topic to see each GTMI pillar as a 0 to 1 score.",
        "coverage": "Global",
        "source": "World Bank",
        "size": "48 indicators in 4 groups, 198 countries",
        "about": [
            ("What it is", "2022 Central Government (CG) GTMI survey data produced by the World Bank Group."),
            ("Data", "The current draft dataset for 2024 covers 48 key indicators with 4 main groups "
                     "for 198 countries."),
            ("PIMS status", "Shows whether a country has no PIMS yet, is implementing one, or has "
                            "implemented one. Click a country for the eight PIMS sub-indicators."),
        ],
        "focus": "I-14: Is there a Public Investment Management System (PIMS) in place? I-15: Is there a "
                 "government Open-Source Software (OSS) policy/action plan for public sector? I-17: Does "
                 "government have a national strategy on disruptive / innovative technologies? I-1: Is "
                 "there a cloud platform available for all government entities?",
        "resolve": _resolve_gtmi,
        "max_select": 1,
    },
    "infra": {
        "tab": "Infrastructure gap",
        "group": "global",
        "title": "Infrastructure gap",
        "official": "Infrastructure Services Evaluation",
        "question": "Where is the quality of infrastructure services behind, or ahead of, "
                    "regional peers?",
        "how_to": "The index adds up how far a country is above or below the regional average on six "
                  "services: roads, rail, electricity, water and 4G coverage and use. Higher is better; "
                  "0 is the regional average.",
        "coverage": "Global",
        "source": "IMF Methodology, Updated Global Data",
        "size": "6 indicators, 220 countries",
        "about": [
            ("What it is", "Infrastructure Services Evaluation, produced by the Climate Governance Program "
                           "of the Prosperity Vertical Institutions Development."),
            ("Data", "The current draft dataset for 2019 covers 6 indicators for 220 countries."),
            ("Notes", "The infrastructure gap is the difference between a country's scores and the regional "
                      "average score of each indicator. Countries in which one or more scores are missing "
                      "are exempted from the calculation and shown in grey."),
        ],
        "focus": "Measures of infrastructure services such as road, rail, power, water, and digital access",
        "resolve": _resolve_infra,
        "max_select": 1,
    },
    "ef": {
        "tab": "Efficiency frontier",
        "group": "global",
        "title": "Infrastructure efficiency",
        "official": "Infrastructure Efficient Frontier (with the Global Quality Infrastructure Index, GQII)",
        "question": "Which countries get the most infrastructure quality out of each dollar of "
                    "public investment?",
        "how_to": "Each dot is a country. The further up and to the left, the more quality for less "
                  "spending. Countries on the lines are the most efficient. Pick up to five countries "
                  "to compare them.",
        "coverage": "Global",
        "source": "World Bank",
        "size": "8 output indicators",
        "about": [
            ("What it is", "Based on the work of the Fiscal Policy Unit at the World Bank. The analysis uses "
                           "eight output indicators following the methodology developed by Herrera and "
                           "Ouedraogo (2018) and Herrera, Isaka, and Ouedraogo (2025)."),
            ("Indicators", "Quality of overall infrastructure, transport infrastructure, roads, port "
                           "infrastructure, air transport, railroads, electricity supply, and the country "
                           "scores on the World Bank's Logistics Performance Index."),
            ("Method", "Public investment per capita is treated as an input. Efficiency scores focus on "
                       "technical efficiency using non-parametric methods (Conditional DEA, Conditional FDH, "
                       "Bootstrapped DEA and Bootstrapped FDH) and the parametric Stochastic Frontier "
                       "Analysis."),
        ],
        "focus": "Based on the work of the Fiscal Policy Unit at the World Bank, the infrastructure "
                 "efficiency analysis uses eight output indicators following the methodology developed by "
                 "Herrera and Ouedraogo (2018) and Herrera, Isaka, and Ouedraogo (2025).",
        "resolve": _resolve_ef,
        "max_select": 5,
    },
    "pefa": {
        "tab": "PEFA grades",
        "group": "global",
        "title": "PEFA grades",
        "official": "Public Expenditure and Financial Accountability (PEFA) - PI-11, PI-12, PI-16",
        "question": "How well does the country manage public investment and public assets?",
        "how_to": "Countries are graded from A (strongest) to D (weakest) on the selected indicator, "
                  "using the latest assessment for each country.",
        "coverage": "Global",
        "source": "PEFA",
        "size": "5 indicators",
        "about": [
            ("What it is", "The Public Expenditure and Financial Accountability (PEFA) framework assesses "
                           "the strength of public financial management systems. Scores shown use the latest "
                           "assessment per country."),
            ("Indicators", "PI-11 Public Investment Management; PI-11.3 Project costing & budget alignment; "
                           "PI-11.4 Investment project monitoring; PI-12 Public Asset Management; "
                           "PI-16 Medium-term fiscal perspective."),
            ("Explore", "Select a region and indicator, then click a country to see all PI scores for that "
                        "assessment."),
        ],
        "focus": "PEFA indicators PI-11, PI-11.3, PI-11.4, PI-12 and PI-16",
        "resolve": _resolve_pefa,
        "max_select": 1,
    },
    "ccia": {
        "tab": "Climate assessment",
        "group": "regional",
        "title": "Climate assessment (CCIA)",
        "official": "Climate Change Institutional Assessment (CCIA)",
        "question": "How well prepared are a country's institutions for climate change, "
                    "pillar by pillar?",
        "how_to": "Scores run from 1 to 6. Overall is the average across pillars; pick a pillar to "
                  "see its score, then click a country for the indicators behind it.",
        "coverage": "ECA selected",
        "source": "World Bank",
        "size": "74 indicators, 11 countries",
        "about": [
            ("What it is", "Climate Change Institutional Assessment (CCIA), produced by the Climate "
                           "Governance Program of the Prosperity Vertical Institutions Development."),
            ("Data", "The current draft dataset for 2024 covers 74 indicators for 11 countries."),
            ("Scoring", "Indicators are quantified on a scale of 1 to 6. The summary is the average of "
                        "these scores."),
        ],
        "focus": "74 indicators",
        "resolve": _resolve_ccia,
        "max_select": 1,
    },
    "piiag": {
        "tab": "PIM tracker",
        "group": "regional",
        "title": "Public investment and asset governance tracker",
        "official": "ECA Public Infrastructure Investment and Asset Governance Tracker (PIIAG)",
        "question": "How strong are a country's policies, implementation and climate "
                    "considerations in public investment and asset management?",
        "how_to": "Pick a section to see its average score, then click a country for the indicators "
                  "behind it.",
        "coverage": "ECA selected (Western Balkans)",
        "source": "World Bank",
        "size": "29 indicators in 3 sections, 6 countries",
        "about": [
            ("What it is", "ECA Public Infrastructure Investment and Asset Governance Tracker (PIIAG)."),
            ("Data", "The current draft dataset for 2024 covers 29 indicators across 3 sections for "
                     "6 countries."),
            ("Scoring", "Indicators are quantified as 0 (no information/none), partial (0.5), and present "
                        "(1). The summary is the average of these scores."),
        ],
        "focus": "Policy (11), implementation (10), Climate (9)",
        "resolve": _resolve_piiag,
        "max_select": 1,
    },
}

TAB_ORDER = {
    "global": ["gccii", "gtmi", "infra", "ef", "pefa"],
    "regional": ["ccia", "piiag"],
}
GROUP_LABELS = {
    "global": "Global benchmarks",
    "regional": "Regional deep-dives",
}
GROUP_BLURBS = {
    "global": "Cover most countries, so you can see where any country sits worldwide.",
    "regional": "Cover a smaller set of countries in more depth, indicator by indicator.",
}
DEFAULT_VIEW = "gccii"
ALL_KEYS = [k for g in ("global", "regional") for k in TAB_ORDER[g]]
MAX_FILTERS = 3
