"""
queries.py
----------
All data access for the PFM4CA Country Benchmarking Tool.

Every table that used to be a CSV in ./data now lives in Databricks Unity
Catalog, prefixed "cbd_" (e.g. ccia_score.csv -> cbd_ccia_score).

world_countries.geojson no longer lives in /assets as a static file. It has
been loaded into the Unity Catalog Delta table
prd_mega.sgpbpi163.cbd_world_boundaries (see ingest_world_boundaries.py for
the one-off Spark job that populates it). That table is ~164MB, so it is
never loaded in full: get_world_boundaries_geojson(iso_codes) fetches only
the specific countries a given map render needs (and permanently caches
each one, in-process, per ISO3 code, so repeat requests for the same
country cost nothing) and reconstructs an in-memory GeoJSON
FeatureCollection dict scoped to just those countries. Plotly's
Choroplethmapbox accepts either a URL *or* a decoded GeoJSON dict for its
`geojson` argument, so app.py computes this small per-request dict right
before every utils.build_map_figure() call instead of resolving one static
asset URL up front.

This file keeps the exact same public surface as the CSV version -
load_csv(name) still takes the old CSV basename (no prefix, no extension)
and returns the same shape of DataFrame - so nothing downstream (this file's
own *_load()/*_country_data() functions, or utils.py) needs to change.
Only load_csv()'s internals changed: file read -> Databricks SQL query.
"""

import os
import json
import logging
import threading
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from databricks import sql
from databricks.sdk.core import Config, oauth_service_principal

try:
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logging.info("Loaded environment from .env file")
except ImportError:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logging.warning("python-dotenv not installed — reading env vars from system only")

# ── Databricks connection config ───────────────────────────────────────────────
# CBD_CATALOG / CBD_SCHEMA point at the Unity Catalog catalog.schema that holds
# every cbd_* table. TABLE_PREFIX mirrors the naming convention you're using
# for this migration ("cbd_ccia_desc", "cbd_ccia_score", ... "cbd_piiag_score").

CBD_CATALOG = os.getenv("CBD_CATALOG", "prd_mega")
CBD_SCHEMA = os.getenv("CBD_SCHEMA", "sgpbpi163")
TABLE_PREFIX = "cbd_"

SERVER_HOSTNAME = os.getenv("DATABRICKS_SERVER_HOSTNAME")
HTTP_PATH = os.getenv("DATABRICKS_HTTP_PATH")

_REQUIRED = {
    "DATABRICKS_SERVER_HOSTNAME": SERVER_HOSTNAME,
    "DATABRICKS_HTTP_PATH": HTTP_PATH,
    "DATABRICKS_CLIENT_ID": os.getenv("DATABRICKS_CLIENT_ID"),
    "DATABRICKS_CLIENT_SECRET": os.getenv("DATABRICKS_CLIENT_SECRET"),
}
_missing = [k for k, v in _REQUIRED.items() if not v]
if _missing:
    raise EnvironmentError(
        "\n\nMissing required environment variables:\n"
        + "\n".join(f"  {k}" for k in _missing)
        + "\n\nCreate a .env file in the project folder with:\n"
        + "  DATABRICKS_SERVER_HOSTNAME=adb-xxxx.azuredatabricks.net\n"
        + "  DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abc123\n"
        + "  DATABRICKS_CLIENT_ID=your-client-id\n"
        + "  DATABRICKS_CLIENT_SECRET=your-client-secret\n"
        + "  CBD_CATALOG=your-catalog\n"
        + "  CBD_SCHEMA=your-schema\n"
    )


def credentials_provider():
    """OAuth2 service-principal credentials for the Databricks SQL connector."""
    config = Config(
        host=f"https://{SERVER_HOSTNAME}",
        client_id=os.getenv("DATABRICKS_CLIENT_ID"),
        client_secret=os.getenv("DATABRICKS_CLIENT_SECRET"),
    )
    return oauth_service_principal(config)


def _execute_query(query: str, parameters=None) -> pd.DataFrame:
    """
    Run a SQL query against the Databricks SQL warehouse, return a DataFrame.

    `parameters`, if given, is a flat sequence of scalar values bound
    positionally to `?` placeholders in `query` - this is the connector's
    native parameterized execution (safe against SQL injection, unlike
    f-string interpolation directly into the query text). Note: native
    parameter binding only infers scalar types (str/int/float/bool/date/
    datetime/Decimal/None) per placeholder - passing one Python list as a
    single parameter value is NOT supported and raises NotSupportedError.
    A dynamic-length `WHERE col IN (...)` clause is therefore built with one
    `?` per value, with `parameters` as the matching flat list of values -
    see get_world_boundaries_geojson() below for exactly this pattern.
    """
    with sql.connect(
        server_hostname=SERVER_HOSTNAME,
        http_path=HTTP_PATH,
        credentials_provider=credentials_provider,
    ) as conn:
        cursor = conn.cursor()
        if parameters:
            cursor.execute(query, parameters=parameters)
        else:
            cursor.execute(query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(rows, columns=columns)


# ── Generic table loader (cached - tables don't change while the app runs) ────
# Same contract as the old CSV version: pass the old CSV basename (no prefix,
# no extension), e.g. load_csv("ccia_score") now runs
#   SELECT * FROM {CBD_CATALOG}.{CBD_SCHEMA}.cbd_ccia_score
# Every *_load()/*_country_data() function below calls load_csv() exactly as
# before and is unaffected by this swap.

@lru_cache(maxsize=None)
def load_csv(name: str) -> pd.DataFrame:
    """Load a Unity Catalog table by its old CSV basename (cbd_ prefix added here)."""
    table = f"{CBD_CATALOG}.{CBD_SCHEMA}.{TABLE_PREFIX}{name}"
    query = f"SELECT * FROM {table}"
    logging.info("Loading table %s", table)
    try:
        df = _execute_query(query)
    except Exception as e:
        raise FileNotFoundError(f"Could not load table {table}: {e}") from e
    logging.info("Loaded %s (%d rows) from %s", name, len(df), table)
    return df


def refresh_all_tables() -> None:
    """
    Clear the in-process table cache so the next load_csv() call re-queries
    Databricks. Wire this up to an admin route or a scheduled job if the
    underlying tables get updated via ETL while the app is running (the old
    CSV version never needed this, since the files genuinely never changed
    mid-process).
    """
    load_csv.cache_clear()
    with _boundary_cache_lock:
        _boundary_feature_cache.clear()
    logging.info("Cleared table cache")


# ── World boundaries (country polygons, replaces world_countries.geojson) ────
# This table lives in a different catalog/schema than every other cbd_*
# table (prd_mega.sgpbpi163 vs. CBD_CATALOG/CBD_SCHEMA), so it gets its own
# fully-qualified name here rather than going through load_csv()/TABLE_PREFIX.
#
# The table is ~164MB of full-resolution polygon coordinates for every
# country - `SELECT *` (or even every column) for the whole table on every
# app load is what was slowing the app down. get_world_boundaries_geojson()
# below NEVER does that: it takes the specific ISO3 codes a given map render
# actually needs (region_country_data's cntrCode values - typically a
# handful to a few dozen countries, not the ~250 in the table) and:
#   1. Serves anything already seen this process from an in-memory cache
#      (_boundary_feature_cache, keyed by iso_a3) - zero network round trip.
#   2. For codes not yet cached, runs ONE query fetching ONLY the iso_a3 and
#      geometry_json columns (not properties_json, not the other flat
#      columns) for exactly those codes, via a parameterized
#      `WHERE iso_a3 IN (?, ?, ...)` clause - both the row filter and the
#      column filter cut the payload, on top of never re-fetching a country
#      already seen. The cache then makes every later request for that
#      country - a different region's map, a page revisit - free.

WORLD_BOUNDARIES_TABLE = os.getenv(
    "CBD_WORLD_BOUNDARIES_TABLE", "prd_mega.sgpbpi163.cbd_world_boundaries_dissolved"
)

# Caps how many `?` placeholders go into a single IN (...) clause. Region
# country lists in this app are at most a few dozen, so this is realistically
# never hit - it exists purely so a future call site passing an unexpectedly
# large code list degrades to a few queries instead of one enormous one.
_BOUNDARY_QUERY_BATCH_SIZE = 200

# iso_a3 -> {"type": "Feature", "properties": {"ISO_A3": ...}, "geometry": {...}}
# Populated incrementally, never cleared except by refresh_all_tables().
# A plain dict is safe here without per-read locking (each entry is written
# once and never mutated after; worst case under a race is two threads both
# fetching the same missing code and writing the same value twice) - the
# lock below only serializes the *fetch-and-populate* step so two threads
# racing on the same cache-miss can't both issue the same Databricks query.
_boundary_feature_cache: dict[str, dict] = {}
_boundary_cache_lock = threading.Lock()


def get_world_boundaries_geojson(iso_codes) -> dict:
    """
    Build a GeoJSON FeatureCollection containing ONLY the requested
    countries' boundaries - the dynamic replacement for the old "load the
    whole table" version.

    iso_codes: iterable of ISO3 codes (e.g. [d["cntrCode"] for d in
               country_data]) - exactly the countries a given map is about
               to render. Order and duplicates don't matter; codes are
               de-duplicated and upper-cased before use.

    Returns the same shape Plotly's Choroplethmapbox `geojson` argument
    expects when passed an in-memory object:
        {"type": "FeatureCollection", "features": [{"type": "Feature",
         "properties": {"ISO_A3": "..."}, "geometry": {...}}, ...]}

    Each feature's properties are deliberately minimal - just {"ISO_A3":
    code} - since that's the only key utils.py's featureidkey="properties.
    ISO_A3" lookup needs to match a location to its shape; the other 8
    properties (WB_A3, NAM_0, etc. - see ingest_world_boundaries.py) are not
    fetched at all here, on top of not fetching rows for countries that
    aren't being rendered. If you need those other fields for something
    (e.g. a tooltip), pull them from your existing cbd_ country/name tables
    instead of this one - this table now exists purely to serve geometry.
    """
    if not iso_codes:
        return {"type": "FeatureCollection", "features": []}

    codes = sorted({str(c).strip().upper() for c in iso_codes if c})
    if not codes:
        return {"type": "FeatureCollection", "features": []}

    missing = [c for c in codes if c not in _boundary_feature_cache]
    if missing:
        with _boundary_cache_lock:
            # Re-check inside the lock: another thread may have just
            # fetched these same codes while we were waiting to acquire it.
            missing = [c for c in missing if c not in _boundary_feature_cache]
            if missing:
                _fetch_and_cache_boundaries(missing)

    features = []
    not_found = []
    for c in codes:
        feature = _boundary_feature_cache.get(c)
        if feature is None:
            not_found.append(c)
        else:
            features.append(feature)

    if not_found:
        logging.warning(
            "No boundary geometry found in %s for %d requested code(s): %s",
            WORLD_BOUNDARIES_TABLE, len(not_found), not_found,
        )

    return {"type": "FeatureCollection", "features": features}


def _fetch_and_cache_boundaries(codes: list) -> None:
    """
    Fetch geometry_json for exactly `codes` (a list of ISO3 codes not yet in
    _boundary_feature_cache) and populate the cache. Batches into groups of
    _BOUNDARY_QUERY_BATCH_SIZE to keep any single IN (...) clause bounded.
    """
    for start in range(0, len(codes), _BOUNDARY_QUERY_BATCH_SIZE):
        batch = codes[start:start + _BOUNDARY_QUERY_BATCH_SIZE]
        placeholders = ", ".join(["?"] * len(batch))
        query = f"""
            SELECT iso_a3, geometry_json
            FROM {WORLD_BOUNDARIES_TABLE}
            WHERE geometry_json IS NOT NULL
              AND iso_a3 IN ({placeholders})
        """
        logging.info("Fetching %d boundary geometr%s from %s",
                     len(batch), "y" if len(batch) == 1 else "ies", WORLD_BOUNDARIES_TABLE)
        try:
            df = _execute_query(query, parameters=batch)
        except Exception as e:
            raise FileNotFoundError(
                f"Could not load boundaries for {batch} from {WORLD_BOUNDARIES_TABLE}: {e}"
            ) from e

        found = set()
        for _, row in df.iterrows():
            iso = row["iso_a3"]
            if not iso:
                continue
            try:
                geometry = json.loads(row["geometry_json"]) if row["geometry_json"] else None
            except (TypeError, ValueError) as e:
                logging.warning("Skipping malformed boundary row (iso_a3=%s): %s", iso, e)
                continue
            if geometry is None:
                continue

            _boundary_feature_cache[iso] = {
                "type": "Feature",
                "properties": {"ISO_A3": iso},
                "geometry": geometry,
            }
            found.add(iso)

        missing_in_table = set(batch) - found
        if missing_in_table:
            logging.warning(
                "%d requested code(s) not present in %s: %s",
                len(missing_in_table), WORLD_BOUNDARIES_TABLE, sorted(missing_in_table),
            )


# ── Reference data ────────────────────────────────────────────────────────────

def get_countries_df() -> pd.DataFrame:
    """cntrCode / cntrName1 lookup table."""
    try:
        df = load_csv("country")
        return df[["cntr_code", "country_name"]].rename(
            columns={"cntr_code": "cntrCode", "country_name": "cntrName1"}
        )
    except Exception as e:
        print(f"Error in get_countries_df: {e}")
        try:
            pefa_df = load_csv("pefa_master")
            res = pefa_df[["Code", "Country"]].drop_duplicates().dropna()
            return res.rename(columns={"Code": "cntrCode", "Country": "cntrName1"})
        except Exception:
            return pd.DataFrame(columns=["cntrCode", "cntrName1"])


def get_country_name_map() -> dict:
    """cntr_code -> country name dict, handy for tooltip building."""
    df = get_countries_df()
    return dict(zip(df["cntrCode"], df["cntrName1"]))


def get_regions_df() -> pd.DataFrame:
    try:
        df = load_csv("country_group")
        return df[["grp_name"]].drop_duplicates().sort_values("grp_name")
    except Exception:
        return pd.DataFrame(columns=["grp_name"])


def get_country_groups_df() -> pd.DataFrame:
    try:
        df = load_csv("country_group")
        return df[["cntr_code", "grp_name"]].rename(
            columns={"cntr_code": "cntrCode", "grp_name": "grpName"}
        )
    except Exception:
        return pd.DataFrame(columns=["cntrCode", "grpName"])


def region_query(region: str) -> pd.DataFrame:
    """All countries belonging to `region` (a grp_name in country_group.csv)."""
    try:
        country = load_csv("country").rename(columns={"country_name": "cntr_name_1"})
    except Exception:
        try:
            pefa_df = load_csv("pefa_master")
            country = pefa_df[["Code", "Country"]].drop_duplicates().dropna()
            country = country.rename(columns={"Code": "cntr_code", "Country": "cntr_name_1"})
        except Exception:
            cg = load_csv("country_group")
            country = pd.DataFrame({"cntr_code": cg["cntr_code"].unique()})
            country["cntr_name_1"] = country["cntr_code"]

    c_grp = load_csv("country_group")
    c_grp = c_grp[c_grp["grp_name"] == region]
    return pd.merge(country[["cntr_code", "cntr_name_1"]], c_grp, on="cntr_code", how="inner")


# ── Page-level "country data" builders ────────────────────────────────────────
# These mirror the useMemo() blocks that used to live in each React page
# component: they take the raw long-format score tables and turn them into
# one row per country with a map score, a hover tooltip, and the detailed
# rows to show in the click-popup. Every builder returns a list of dicts:
#   {"cntrCode": str, "score": Optional[float], "tooltip": str, "popupRows": [...]}

def _nan_to_none(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and np.isnan(v):
            return None
    except TypeError:
        pass
    return v


# ── GCCII ──────────────────────────────────────────────────────────────────────

def gccii_load(region: str):
    """Returns (region_df, long_df) for the Climate Change Institutional Indicators."""
    gdf = region_query(region)
    c_grp = load_csv("country_group")
    c_grp = c_grp[c_grp["grp_name"] == region]

    score = load_csv("gccii_score")
    desc = load_csv("gccii_desc")

    score_desc = pd.merge(score, desc, on="gccii_id", how="inner")
    df = pd.merge(c_grp[["cntr_code"]], score_desc, on="cntr_code", how="left")
    df = df[["cntr_code", "score", "indicator_name"]].copy()
    df["score"] = pd.to_numeric(df["score"], errors="coerce")

    df_mean = df.groupby(["cntr_code"])["score"].mean(numeric_only=True).reset_index().round(2)
    gdf = gdf.merge(df_mean, on="cntr_code", how="inner")
    return gdf, df


def gccii_country_data(region: str) -> list:
    """Map-ready rows: average GCCII score (0-1) + per-indicator popup rows."""
    _, df = gccii_load(region)
    names = get_country_name_map()
    out = []
    for code, items in df.groupby("cntr_code"):
        scores = items["score"].fillna(0)
        avg = float(scores.mean()) if len(scores) else 0.0
        avg = round(avg, 2)
        name = names.get(code, code)
        out.append({
            "cntrCode": code,
            "score": avg,
            "tooltip": f"Country: {name}<br>GCCII Index Score: {avg:.2f}",
            "popupRows": [
                {"indicator": r["indicator_name"], "score": _nan_to_none(r["score"]) or 0}
                for _, r in items.iterrows()
            ],
        })
    return out


# ── Infrastructure Efficiency (regional gap index) ────────────────────────────

INFRA_IDS = [
    "wef19roadqualeff", "wef19Railroad", "wef19Electsupplyqual",
    "wef19Relwatersup", "coverage4G", "penetration4G",
]


def infra_load(region: str):
    gdf = region_query(region)
    c_grp = load_csv("country_group")
    c_grp = c_grp[c_grp["grp_name"] == region]

    score = load_csv("infra_score")
    desc = load_csv("infra_desc")

    score_desc = pd.merge(score, desc, on="infra_id", how="inner")
    df = pd.merge(c_grp[["cntr_code"]], score_desc, on="cntr_code", how="left")
    df = df[["cntr_code", "infra_id", "score", "indicator_name"]].copy()
    df["score"] = pd.to_numeric(df["score"], errors="coerce")

    short_df = df.pivot_table(index="cntr_code", columns="infra_id", values="score").reset_index()
    short_df = short_df.dropna().reset_index(drop=True)
    existing_cols = [c for c in INFRA_IDS if c in short_df.columns]
    if existing_cols:
        short_df[existing_cols] = short_df[existing_cols] - short_df[existing_cols].mean()
        short_df[existing_cols] = short_df[existing_cols] / (short_df[existing_cols].std() / 100)
    short_df["score"] = short_df.sum(axis=1, numeric_only=True).round(2)
    gdf = gdf.merge(short_df[["cntr_code", "score"]], on="cntr_code", how="left")
    return gdf, df


def infra_country_data(region: str) -> list:
    """
    Map-ready rows: an additive z-score "Infrastructure Gap Index" built from six
    indicators. Countries missing any one of the six indicators are excluded from
    the gap calculation (score=None, shown gray) but still get a popup with
    whatever partial data exists.
    """
    _, df = infra_load(region)
    names = get_country_name_map()

    by_country = {}
    for code, items in df.groupby("cntr_code"):
        by_country[code] = {
            row["infra_id"]: {"score": _nan_to_none(row["score"]), "name": row["indicator_name"]}
            for _, row in items.iterrows()
        }

    pivot = {}
    for code, indicators in by_country.items():
        row = {}
        has_all = True
        for iid in INFRA_IDS:
            entry = indicators.get(iid)
            if entry and entry["score"] is not None:
                row[iid] = entry["score"]
            else:
                has_all = False
        if has_all:
            pivot[code] = row

    means, stds = {}, {}
    for iid in INFRA_IDS:
        vals = [row[iid] for row in pivot.values()]
        if vals:
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
            means[iid] = mean
            stds[iid] = std

    results = []
    for code, indicators in by_country.items():
        name = names.get(code, code)
        popup_rows = [
            {"indicator": entry["name"], "score": entry["score"] if entry["score"] is not None else "N/A"}
            for entry in indicators.values()
        ]

        if code not in pivot:
            results.append({
                "cntrCode": code,
                "score": None,
                "tooltip": f"{name} does not participate/finalize its scoring",
                "popupRows": popup_rows,
            })
            continue

        gap_score = sum(((pivot[code][iid] - means[iid]) / stds[iid]) * 100 for iid in INFRA_IDS)
        gap_score = round(gap_score, 2)
        results.append({
            "cntrCode": code,
            "score": gap_score,
            "tooltip": f"Country: {name}<br>Infrastructure Gap Index: {gap_score}",
            "popupRows": popup_rows,
        })

    return results


# ── CCIA ───────────────────────────────────────────────────────────────────────

def ccia_load(region: str):
    gdf = region_query(region)
    c_grp = load_csv("country_group")
    c_grp = c_grp[c_grp["grp_name"] == region]

    score = load_csv("ccia_score")
    desc = load_csv("ccia_desc")

    score_desc = pd.merge(score, desc, on="ccid_id", how="inner")
    df = pd.merge(c_grp[["cntr_code"]], score_desc, on="cntr_code", how="left")
    df = df[["cntr_code", "pillar", "score", "indicator_name"]].copy()
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    return gdf, df


def ccia_pillars() -> list:
    desc = load_csv("ccia_desc")
    return sorted(desc["pillar"].dropna().unique().tolist())


def ccia_country_data(region: str, pillar: str = "Overall") -> list:
    """
    "Overall" -> average-of-pillar-averages per country, popup shows one row
    per pillar. Otherwise -> average of just that pillar, popup shows one row
    per indicator within it.
    """
    _, df = ccia_load(region)
    names = get_country_name_map()
    out = []

    if pillar == "Overall":
        for code, items in df.groupby("cntr_code"):
            pillar_avgs = items.groupby("pillar")["score"].mean(numeric_only=True).dropna()
            if pillar_avgs.empty:
                continue
            overall = float(pillar_avgs.mean())
            name = names.get(code, code)
            out.append({
                "cntrCode": code,
                "score": round(overall, 2),
                "tooltip": f"Country: {name}<br>Overall CCIA Score: {overall:.2f}",
                "popupRows": [{"indicator": p, "score": round(float(v), 2)} for p, v in pillar_avgs.items()],
            })
    else:
        filtered = df[df["pillar"] == pillar]
        for code, items in filtered.groupby("cntr_code"):
            scores = items["score"].fillna(0)
            avg = float(scores.mean()) if len(scores) else 0.0
            name = names.get(code, code)
            out.append({
                "cntrCode": code,
                "score": round(avg, 2),
                "tooltip": f"Country: {name}<br>Average {pillar} Score: {avg:.2f}",
                "popupRows": [
                    {"indicator": r["indicator_name"], "score": _nan_to_none(r["score"]) or 0}
                    for _, r in items.iterrows()
                ],
            })

    return out


# ── GTMI ───────────────────────────────────────────────────────────────────────

PIMS_SUB_IDS = ["I-14.1", "I-14.2", "I-14.3", "I-14.4", "I-14.5", "I-14.6", "I-14.7", "I-14.7.1"]
GTMI_PILLARS = ["PIMS", "GTMI", "CGSI", "PSDI", "DCEI", "GTEI"]


def gtmi_load(region: str):
    gdf = region_query(region)
    c_grp = load_csv("country_group")
    c_grp = c_grp[c_grp["grp_name"] == region]

    score = load_csv("gtmi_score")
    desc = load_csv("gtmi_desc")

    score = score[score["version"].isna()]
    score_desc = pd.merge(score, desc, on="gtmi_id", how="inner")
    df = pd.merge(c_grp[["cntr_code"]], score_desc, on="cntr_code", how="left")
    df = df[["cntr_code", "gtmi_group", "gtmi_id", "score", "indicator_name"]].copy()
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    return gdf, df


def gtmi_country_data(region: str, pillar: str = "PIMS") -> list:
    """
    "PIMS" -> special 3-status view of indicator I-14 (Public Investment
    Management System), with its 8 sub-indicators (I-14.1 ... I-14.7.1) in the
    popup. Any other pillar -> average score (0-1) of that pillar's top-level
    indicator, with its detail indicators (same gtmi_group, excluding itself)
    in the popup.
    """
    _, df = gtmi_load(region)
    names = get_country_name_map()
    out = []

    if pillar == "PIMS":
        pims_scores = df[df["gtmi_id"] == "I-14"]
        pims_sub = df[df["gtmi_id"].isin(PIMS_SUB_IDS)]

        for _, s in pims_scores.iterrows():
            score_val = _nan_to_none(s["score"])
            name = names.get(s["cntr_code"], s["cntr_code"])
            if score_val == 0:
                status = "Not yet implemented"
            elif score_val == 1:
                status = "PIMS under implementation"
            elif score_val is not None:
                status = "PIMS Implemented"
            else:
                status = "N/A"
            sub_rows = pims_sub[pims_sub["cntr_code"] == s["cntr_code"]]
            out.append({
                "cntrCode": s["cntr_code"],
                "score": score_val,
                "tooltip": f"Country: {name}<br>Current PIMS Status: {status}",
                "popupRows": [
                    {"indicator": r["indicator_name"], "score": _nan_to_none(r["score"]) or "N/A"}
                    for _, r in sub_rows.iterrows()
                ],
            })
    else:
        pillar_scores = df[df["gtmi_id"] == pillar]
        detail_scores = df[(df["gtmi_group"] == pillar) & (df["gtmi_id"] != pillar)]

        for _, s in pillar_scores.iterrows():
            score_val = _nan_to_none(s["score"])
            name = names.get(s["cntr_code"], s["cntr_code"])
            details = detail_scores[detail_scores["cntr_code"] == s["cntr_code"]]
            out.append({
                "cntrCode": s["cntr_code"],
                "score": score_val,
                "tooltip": (
                    f"Country: {name}<br>Average {pillar} Score: "
                    f"{'N/A' if score_val is None else f'{score_val:.2f}'}"
                ),
                "popupRows": [
                    {"indicator": r["indicator_name"], "score": _nan_to_none(r["score"]) or "N/A"}
                    for _, r in details.iterrows()
                ],
            })

    return out


# ── PIIAG ──────────────────────────────────────────────────────────────────────

def piiag_load(region: str):
    gdf = region_query(region)
    c_grp = load_csv("country_group")
    c_grp = c_grp[c_grp["grp_name"] == region]

    score = load_csv("piiag_score")
    desc = load_csv("piiag_desc")

    score_desc = pd.merge(score, desc, on="piiag_id", how="inner")
    df = pd.merge(c_grp[["cntr_code"]], score_desc, on="cntr_code", how="inner")
    df = df[["cntr_code", "piiag_section", "piiag_id", "score", "status", "indicator_name"]].copy()
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    return gdf, df


def piiag_sections() -> list:
    desc = load_csv("piiag_desc")
    return sorted(desc["piiag_section"].dropna().unique().tolist())


def piiag_country_data(region: str, section: str = "Overall") -> list:
    """Same "Overall vs specific" pattern as CCIA, but grouped by piiag_section."""
    _, df = piiag_load(region)
    names = get_country_name_map()
    out = []

    if section == "Overall":
        for code, items in df.groupby("cntr_code"):
            sect_avgs = items.groupby("piiag_section")["score"].mean(numeric_only=True).dropna()
            if sect_avgs.empty:
                continue
            overall = float(sect_avgs.mean())
            name = names.get(code, code)
            out.append({
                "cntrCode": code,
                "score": round(overall, 2),
                "tooltip": f"Country: {name}<br>Overall PIIAG Score: {overall:.2f}",
                "popupRows": [{"indicator": s, "score": round(float(v), 2)} for s, v in sect_avgs.items()],
            })
    else:
        filtered = df[df["piiag_section"] == section]
        for code, items in filtered.groupby("cntr_code"):
            scores = items["score"].fillna(0)
            avg = float(scores.mean()) if len(scores) else 0.0
            name = names.get(code, code)
            out.append({
                "cntrCode": code,
                "score": round(avg, 2),
                "tooltip": f"Country: {name}<br>Average {section} Score: {avg:.2f}",
                "popupRows": [
                    {"indicator": r["indicator_name"], "score": _nan_to_none(r["score"]) or 0}
                    for _, r in items.iterrows()
                ],
            })

    return out


# ── EF (Infrastructure Efficient Frontier) ───────────────────────────────────

EF_INPUT_VAR = "INF.INP1.GEX.ICS.GQII.ALL"
EF_OUTPUT_VAR = "INF.OUT.GQII"
EF_VALUE_COL = "2019-2023"

EF_SHORT_NAME_ORDER = [
    "Average Score",
    "Global Quality of Infrastructure Index",
    "Logistics Performance Index",
    "Overall Infrastructure",
    "Transport Infrastructure",
    "Road Infrastructure",
    "Rail Infrastructure",
    "Port Infrastructure",
    "Air Transport",
    "Electricity Supply",
]


def _load_ef_raw() -> pd.DataFrame:
    # Was: pd.read_csv(os.path.join(DATA_DIR, "Infra_eff_app_clean.csv"))
    # Now: cbd_infra_eff_app_clean, via the same cached load_csv() every other
    # table goes through (no separate @lru_cache needed here - load_csv already
    # caches by name).
    return load_csv("infra_eff_app_clean")


def _build_ef_wide() -> pd.DataFrame:
    ef = _load_ef_raw()
    frontier_rows = ef[ef["varname"].isin([EF_INPUT_VAR, EF_OUTPUT_VAR])].copy()
    df_wide = frontier_rows.pivot_table(
        index="ISO", columns="varname", values=EF_VALUE_COL, aggfunc="first"
    ).reset_index()
    df_wide = df_wide.dropna(subset=[EF_INPUT_VAR, EF_OUTPUT_VAR])
    return df_wide


def _compute_dea_frontier(df_wide: pd.DataFrame) -> pd.DataFrame:
    """VRS input-oriented DEA. Adds a 'theta' efficiency column."""
    x_vec = df_wide[EF_INPUT_VAR].values
    y_vec = df_wide[EF_OUTPUT_VAR].values
    n = len(x_vec)

    theta_scores = []
    for i in range(n):
        c = [1] + [0] * n
        A_ub = [[-x_vec[i]] + list(x_vec), [0] + list(-y_vec)]
        b_ub = [0, -y_vec[i]]
        A_eq = [[0] + [1] * n]
        b_eq = [1]
        bounds = [(0, None)] * (n + 1)
        res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
        theta_scores.append(res.x[0] if res.success else np.nan)

    df_wide = df_wide.copy()
    df_wide["theta"] = theta_scores
    return df_wide


@lru_cache(maxsize=None)
def _get_ef_wide_with_theta() -> pd.DataFrame:
    df_wide = _build_ef_wide()
    if df_wide.empty:
        return df_wide
    return _compute_dea_frontier(df_wide)


def ef_get_frontier() -> dict:
    """DEA (VRS) frontier points + FDH (skyline) frontier points + full scatter."""
    df = _get_ef_wide_with_theta()
    if df.empty:
        return {"dea": [], "fdh": [], "scatter": []}

    vrs_frontier = df[df["theta"] >= 0.9999].sort_values(by=EF_INPUT_VAR)

    sorted_data = df.sort_values(by=EF_INPUT_VAR)
    fdh_points, current_max_y = [], -np.inf
    for _, row in sorted_data.iterrows():
        if row[EF_OUTPUT_VAR] >= current_max_y:
            fdh_points.append(row)
            current_max_y = row[EF_OUTPUT_VAR]
    fdh_frontier = pd.DataFrame(fdh_points)

    return {
        "dea": [{"x": r[EF_INPUT_VAR], "y": r[EF_OUTPUT_VAR], "iso": r["ISO"]} for _, r in vrs_frontier.iterrows()],
        "fdh": [{"x": r[EF_INPUT_VAR], "y": r[EF_OUTPUT_VAR], "iso": r["ISO"]} for _, r in fdh_frontier.iterrows()],
        "scatter": [
            {"iso": r["ISO"], "x": r[EF_INPUT_VAR], "y": r[EF_OUTPUT_VAR], "theta": r["theta"] if pd.notna(r["theta"]) else None}
            for _, r in df.iterrows()
        ],
    }


def ef_get_scores(method: Optional[str] = None, sample: Optional[str] = None, isos: Optional[list[str]] = None) -> pd.DataFrame:
    """Per-country, per-indicator efficiency score rows (excludes the raw input/output vars)."""
    df = _load_ef_raw().copy()
    exclude = {EF_INPUT_VAR, EF_OUTPUT_VAR}
    df = df[~df["varname"].isin(exclude)]

    if method:
        df = df[df["method"] == method]
    if sample:
        df = df[df["sample"] == sample]
    if isos:
        df = df[df["ISO"].isin(isos)]

    df = df[["ISO", "short_name", "method", "sample", EF_VALUE_COL]].copy()
    df = df.rename(columns={EF_VALUE_COL: "score"})
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df = df.dropna(subset=["score"])
    return df


def ef_get_filters() -> dict:
    df = _load_ef_raw()
    return {
        "methods": sorted(df["method"].dropna().unique().tolist()),
        "samples": sorted(df["sample"].dropna().unique().tolist()),
        "countries": sorted(df["ISO"].dropna().unique().tolist()),
        "shortNames": EF_SHORT_NAME_ORDER,
    }


# ── PEFA ───────────────────────────────────────────────────────────────────────

PEFA_INDICATORS = ["PI-11", "PI-11.3", "PI-11.4", "PI-12", "PI-16"]

SCORE_COLOR_MAP = {
    "A": "#2E8B57",
    "B+": "#5FB3A5",
    "B": "#008080",
    "C+": "#F9A95D",
    "C": "#F28C28",
    "D+": "#DA6E9A",
    "D": "#B03060",
    "D*": "#B03060",
    "NU": "#000000",
}

GRADE_ORDER = ["A", "B+", "B", "C+", "C", "D+", "D", "D*", "NU"]
GRADE_INDEX = {g: i for i, g in enumerate(GRADE_ORDER)}


def _load_pefa_master() -> pd.DataFrame:
    # Was: pd.read_csv(os.path.join(DATA_DIR, "pefa_master.csv"))
    # Now: cbd_pefa_master, via the shared cached load_csv().
    df = load_csv("pefa_master").copy()
    if "id" not in df.columns:
        df["id"] = df["Economy"] + " (" + df["Year"].astype(str) + ")"
    return df


def pefa_get_map(indicator: str = "PI-11", framework: str = "Annex 2011") -> list:
    """One record per country (latest assessment), with grade index + popup rows."""
    df = _load_pefa_master().copy()
    df = df[df["Framework"] == framework]

    if indicator not in df.columns:
        return []

    df = df.sort_values("Year", ascending=False).drop_duplicates(subset=["Economy"])

    records = []
    for _, row in df.iterrows():
        code = row.get("Code")
        if not code or str(code) == "nan":
            continue

        grade = str(row.get(indicator, "") or "").strip()
        idx = GRADE_INDEX.get(grade)

        popup_rows = []
        for ind in PEFA_INDICATORS:
            if ind in df.columns:
                g = str(row.get(ind, "") or "").strip()
                if g and g not in ("nan", "NA", "NR"):
                    popup_rows.append({"indicator": ind, "score": g})

        economy = str(row.get("Economy", ""))
        year = str(row.get("Year", ""))
        tooltip = f"<b>{economy}</b> ({year})<br>{indicator}: {grade if grade else 'N/A'}"

        records.append({
            "cntrCode": code,
            "score": idx if idx is not None else None,
            "tooltip": tooltip,
            "popupRows": popup_rows,
        })

    return records


def pefa_get_color_map() -> dict:
    return SCORE_COLOR_MAP


def pefa_get_grade_order() -> list:
    return GRADE_ORDER


def pefa_country_data(indicator: str = "PI-11", framework: str = "Annex 2011") -> list:
    """Alias kept for naming symmetry with the other *_country_data() builders."""
    return pefa_get_map(indicator=indicator, framework=framework)