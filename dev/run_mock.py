"""
dev/run_mock.py
---------------
Run the dashboard WITHOUT Databricks, on synthetic data, for UI work and demos:

    python dev/run_mock.py            # then open http://127.0.0.1:8050

How it works: your real queries.py is imported (so all the scoring, popup and
DEA-frontier logic is exercised), but the two functions that touch the network
are replaced:
    queries.load_csv(name)                  -> synthetic DataFrames (below)
    queries.get_world_boundaries_geojson()  -> boundaries from assets/world_countries.geojson

EVERY NUMBER SHOWN IS RANDOM. A "Demo data" badge is injected into the page so
nobody mistakes it for the real thing. Nothing here is used in production.
"""

import json
import os
import pathlib
import sys
import types

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── 1. Make `import queries` possible without credentials / Databricks libs ──
for k in ("DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH",
          "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
    os.environ.setdefault(k, "mock")
try:
    import databricks.sql  # noqa: F401
    import databricks.sdk.core  # noqa: F401
except ImportError:
    pkg = types.ModuleType("databricks"); sql = types.ModuleType("databricks.sql")
    sdk = types.ModuleType("databricks.sdk"); core = types.ModuleType("databricks.sdk.core")
    core.Config = object; core.oauth_service_principal = lambda *_: None
    pkg.sql, pkg.sdk, sdk.core = sql, sdk, core
    sys.modules.update({"databricks": pkg, "databricks.sql": sql,
                        "databricks.sdk": sdk, "databricks.sdk.core": core})

import queries as q  # noqa: E402

rng = np.random.default_rng(7)
GEO = json.load(open(ROOT / "assets" / "world_countries.geojson"))
NAMES = {f["properties"]["iso_a3"]: f["properties"]["name"] for f in GEO["features"]
         if len(f["properties"]["iso_a3"]) == 3 and f["properties"]["iso_a3"].isalpha()}
NAMES["XKX"] = "Kosovo"

REGIONS = {
    "Europe and Central Asia": "ALB ARM AUT AZE BLR BEL BIH BGR HRV CYP CZE DNK EST FIN FRA GEO DEU GRC HUN ISL IRL ITA XKX KAZ KGZ LVA LTU LUX MLT MDA MNE NLD MKD NOR POL PRT ROU RUS SRB SVK SVN ESP SWE CHE TJK TUR TKM UKR GBR UZB",
    "South Asia": "AFG BGD BTN IND MDV NPL PAK LKA",
    "Middle East and North Africa": "DZA BHR DJI EGY IRN IRQ ISR JOR KWT LBN LBY MAR OMN QAT SAU SYR TUN ARE YEM PSE",
    "East Asia & Pacific": "AUS BRN KHM CHN FJI IDN JPN KIR PRK KOR LAO MYS MHL FSM MNG MMR NRU NZL PLW PNG PHL WSM SGP SLB THA TLS TON TUV VUT VNM",
    "Western and Central Africa": "AGO BEN BFA CMR CPV CAF TCD COM COG COD CIV GNQ GAB GMB GHA GIN GNB LBR MLI MRT NER NGA STP SEN SLE TGO",
    "Eastern and South Africa": "BDI BWA ERI SWZ ETH KEN LSO MDG MWI MUS MOZ NAM RWA SYC SOM ZAF SSD SDN TZA UGA ZMB ZWE",
    "Latin and Central America": "ARG BLZ BOL BRA CHL COL CRI CUB DOM ECU SLV GTM GUY HTI HND JAM MEX NIC PAN PRY PER SUR URY VEN",
    "North America": "CAN USA",
    "Western Balkans 6": "ALB BIH XKX MKD MNE SRB",
    "Central Asia": "KAZ KGZ TJK TKM UZB",
    "European Union 27": "AUT BEL BGR HRV CYP CZE DNK EST FIN FRA DEU GRC HUN IRL ITA LVA LTU LUX MLT NLD POL PRT ROU SVK SVN ESP SWE",
}
REGIONS = {k: [c for c in v.split() if c in NAMES] for k, v in REGIONS.items()}
ALL_GLOBAL = sorted({c for k in list(REGIONS)[:8] for c in REGIONS[k]})


def _bias():
    return {c: rng.uniform(0.15, 0.95) for c in NAMES}


BIAS = _bias()


def _tables():
    t = {}
    t["country"] = pd.DataFrame({"cntr_code": list(NAMES), "country_name": list(NAMES.values())})
    t["country_group"] = pd.DataFrame([(c, g) for g, cs in REGIONS.items() for c in cs],
                                      columns=["cntr_code", "grp_name"])

    # GCCII - 12 indicators, 0 / 0.5 / 1
    g_names = ["Climate law", "Institutional coordination", "Long-term strategy", "National adaptation plan",
               "Fiscal risk statements", "Local climate risk", "Budget guidelines", "Expenditure tracking",
               "Public investment", "SOE disclosure", "Sub-national strategies and risk assessments",
               "Environment in procurement"]
    t["gccii_desc"] = pd.DataFrame({"gccii_id": [f"G{i}" for i in range(12)], "indicator_name": g_names})
    rows = []
    for c in ALL_GLOBAL:
        if rng.random() < 0.06:
            continue
        p = BIAS[c]
        probs = np.array([1 - p, 0.25, p]); probs = probs / probs.sum()
        for i in range(12):
            rows.append((c, f"G{i}", float(rng.choice([0, 0.5, 1], p=probs))))
    t["gccii_score"] = pd.DataFrame(rows, columns=["cntr_code", "gccii_id", "score"])

    # Infrastructure services
    i_ids = q.INFRA_IDS
    i_names = ["Road quality", "Railroad quality", "Electricity supply quality", "Reliable water supply",
               "4G coverage (%)", "4G penetration (%)"]
    t["infra_desc"] = pd.DataFrame({"infra_id": i_ids, "indicator_name": i_names})
    rows = []
    for c in ALL_GLOBAL:
        for j, iid in enumerate(i_ids):
            if rng.random() < 0.04:
                continue
            v = (1 + 6 * BIAS[c] * rng.uniform(.7, 1.1)) if j < 4 else 100 * BIAS[c] * rng.uniform(.6, 1.05)
            rows.append((c, iid, round(float(min(v, 100 if j >= 4 else 7)), 2)))
    t["infra_score"] = pd.DataFrame(rows, columns=["cntr_code", "infra_id", "score"])

    # CCIA - pillars, 1-6
    pillars = {"Policy and strategy": 6, "Public investment": 5, "Budgeting": 5, "Reporting and audit": 4}
    ids, descs = [], []
    for p, n in pillars.items():
        for k in range(n):
            ids.append(f"C-{p[:3]}-{k}"); descs.append((f"C-{p[:3]}-{k}", p, f"{p}: indicator {k + 1}"))
    t["ccia_desc"] = pd.DataFrame(descs, columns=["ccid_id", "pillar", "indicator_name"])
    ccia_c = REGIONS["Western Balkans 6"] + REGIONS["Central Asia"][:5]
    t["ccia_score"] = pd.DataFrame(
        [(c, i, int(np.clip(round(1 + 5 * BIAS[c] + rng.normal(0, 1)), 1, 6))) for c in ccia_c for i in ids],
        columns=["cntr_code", "ccid_id", "score"])

    # GTMI
    pill = ["GTMI", "CGSI", "PSDI", "DCEI", "GTEI"]
    drows = [("I-14", "PIMS", "PIMS in place")] + [(s, "PIMS", f"PIMS sub-indicator {s}") for s in q.PIMS_SUB_IDS]
    for p in pill:
        drows.append((p, p, f"{p} index"))
        drows += [(f"{p}.{k}", p, f"{p} detail indicator {k}") for k in (1, 2, 3, 4)]
    t["gtmi_desc"] = pd.DataFrame(drows, columns=["gtmi_id", "gtmi_group", "indicator_name"])
    rows = []
    for c in ALL_GLOBAL:
        b = BIAS[c]
        none_p = 0.3 * (1 - b) + 0.1
        rows.append((c, "I-14", int(rng.choice([0, 1, 2], p=[none_p, 0.25, 0.75 - none_p])), np.nan))
        rows += [(c, s, int(rng.random() < b), np.nan) for s in q.PIMS_SUB_IDS]
        for p in pill:
            rows.append((c, p, round(float(np.clip(b + rng.normal(0, .15), 0, 1)), 2), np.nan))
            rows += [(c, f"{p}.{k}", round(float(np.clip(b + rng.normal(0, .25), 0, 1)), 2), np.nan) for k in (1, 2, 3, 4)]
    t["gtmi_score"] = pd.DataFrame(rows, columns=["cntr_code", "gtmi_id", "score", "version"])

    # PIIAG
    secs = {"Policy": 11, "Implementation": 10, "Climate": 8}
    pd_rows, ids = [], []
    for s, n in secs.items():
        for k in range(n):
            pid = f"P-{s[:3]}-{k}"; ids.append((pid, s)); pd_rows.append((pid, s, f"{s}: indicator {k + 1}"))
    t["piiag_desc"] = pd.DataFrame(pd_rows, columns=["piiag_id", "piiag_section", "indicator_name"])
    t["piiag_score"] = pd.DataFrame(
        [(c, pid, float(rng.choice([0, .5, 1], p=[.8 - .6 * BIAS[c], .2, .0 + .6 * BIAS[c]])), "ok")
         for c in REGIONS["Western Balkans 6"] for pid, _ in ids],
        columns=["cntr_code", "piiag_id", "score", "status"])

    # Efficiency
    eff_c = [c for c in ALL_GLOBAL if rng.random() < .85]
    rows = []
    for c in eff_c:
        x = 1.5 + 5.5 * BIAS[c] ** 1.2 + rng.normal(0, .35)
        y = 2.6 + 2.2 * np.log1p(x) * rng.uniform(.75, 1.0)
        rows.append((c, q.EF_INPUT_VAR, "Input", None, None, round(float(x), 3)))
        rows.append((c, q.EF_OUTPUT_VAR, "Output", None, None, round(float(y), 3)))
        for m in ["Bootstrapped DEA", "Conditional DEA", "Conditional FDH"]:
            for smp in ["All countries", "Developing economies"]:
                for nme in q.EF_SHORT_NAME_ORDER:
                    rows.append((c, f"INF.{nme[:6]}", nme, m, smp, round(float(np.clip(rng.normal(.6 + .3 * BIAS[c], .15), .05, 1)), 3)))
    df = pd.DataFrame(rows, columns=["ISO", "varname", "short_name", "method", "sample", q.EF_VALUE_COL])
    t["infra_eff_app_clean"] = df

    # PEFA
    grades = ["A", "B+", "B", "C+", "C", "D+", "D"]
    rows = []
    for c in ALL_GLOBAL:
        if rng.random() < .35:
            continue
        r = [c, NAMES[c], NAMES[c], int(rng.integers(2012, 2024)), "Annex 2011"]
        for _ in q.PEFA_INDICATORS:
            k = int(np.clip(round((1 - BIAS[c]) * 6 + rng.normal(0, 1)), 0, 6)); r.append(grades[k])
        rows.append(r)
    t["pefa_master"] = pd.DataFrame(rows, columns=["Code", "Country", "Economy", "Year", "Framework"] + q.PEFA_INDICATORS)
    return t


TABLES = _tables()
FEATURES = {f["properties"]["iso_a3"]: f for f in GEO["features"]}


def fake_load_csv(name):
    return TABLES[name].copy()


def fake_boundaries(iso_codes):
    feats = []
    for c in sorted({str(c).upper() for c in iso_codes or []}):
        f = FEATURES.get(c)
        if f:
            feats.append({"type": "Feature", "properties": {"ISO_A3": c}, "geometry": f["geometry"]})
    return {"type": "FeatureCollection", "features": feats}


q.load_csv = fake_load_csv
q.get_world_boundaries_geojson = fake_boundaries

import app as cbd  # noqa: E402  (imports the real app, now backed by mock data)

BADGE = ("<div style=\"position:fixed;z-index:999;right:12px;bottom:12px;background:#F26B23;color:#0B2B4B;"
         "font:600 13px 'Fira Sans',sans-serif;padding:6px 12px;border-radius:6px;"
         "box-shadow:0 2px 8px rgba(0,0,0,.25)\">Demo data: random numbers</div>")
cbd.app.index_string = cbd.app.index_string.replace("<body>", "<body>" + BADGE)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8050"))
    cbd.app.run(debug=False, host="127.0.0.1", port=port)
