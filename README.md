# Country Benchmarking Dashboard (PFM4CA) — Dash Edition

A Python/Dash port of the PIMPAM Country Benchmarking Tool. No FastAPI
server in front — Dash callbacks call straight into `queries.py`, which reads
its tables from **Databricks Unity Catalog** (previously local CSVs).

## What changed in the redesign

The app used to be seven separate pages (one per dataset), each with its own
sidebar, plus a home page that was a table. It is now three pages:

| Page | URL | What it is |
|------|-----|------------|
| **Overview** | `/` | Plain-language introduction, "How it works" in three steps, the seven benchmarks grouped as *Global* and *Regional*, how to read the scores, and **Launch Tool** and **Country-wise analysis** buttons |
| **Dashboard** | `/?page=dashboard#gccii` | Everything on one page (see below). The text after `#` is the active tab, so every view has a shareable link |
| **Country-wise analysis** | `/?page=country-wise-cbd-analysis#country=KHM&peers=VNM,THA` | Pick one country and see every benchmark for it on one page (see below). The text after `#` holds the country and peers, so every view has a shareable link |

Old links such as `?page=gtmi` still work and open the matching tab.

**Dashboard anatomy**

1. **Tab switcher**: the seven benchmarks, grouped Global / Regional deep-dives.
2. **Title + question**: what this benchmark answers, "How to read this", and an *About this data* popover.
3. **Filter strip**: Region / Topic / Method etc. (depends on the tab) beside four **headline numbers** for the current filters.
4. **Map** with a legend underneath that also counts the countries in each band.
5. **Dynamic detail pane**: a ranked list of countries by default; click a country (map, list or search box) and it becomes a profile with the score, rank, comparison to the average and the indicators behind it. The selected country stays selected when you switch tabs. On the efficiency tab the pane compares up to five countries and a *Frontier | Component scores* switch toggles the two charts.

**Country-wise analysis anatomy** (`country_page.py`)

It is reached from the **Country-wise analysis** button on the Overview page (and a link in the header). It is a separate page, not a tab.

1. **Selection bar** (stays at the top while you scroll): *Country* and *Compare with peers* (up to 3), plus a colour key. The selected country is always **red**; each peer gets its own colour; every other country is shown light.
2. **Country header**: name, region and which of the seven benchmarks have data for it.
3. **Panels in a grid, two across**: Infrastructure (efficiency | gap), Public investment management (PEFA | GovTech), Climate readiness (climate institutions | climate assessment), Regional deep-dive (PIM tracker, full width).
4. Each map panel has a one-line summary for the selected country, a map framed on the country's region (selected country outlined in red, peers in their colour, everyone else faded), the legend, and a table with the selected country and peers side by side across the indicators behind the score. The efficiency panel shows the frontier (selected country as a large red dot) and the component scores of the selected country and peers.
5. Climate assessment and PIM tracker only cover a few countries. For any other country the panel says so and lists the countries that were assessed, each one a button.

Country-wise analysis never changes the data layer: it calls the same `datasets.py` resolvers and `queries.py` functions as the dashboard.

Design choices worth knowing: the map palette runs orange (low) to indigo (high) so it works for
red-green colour-blind users; Fira Sans is self-hosted in `assets/fonts` (SIL OFL licence) so it
loads even where Google Fonts is blocked.

## Project layout

```
app.py            Dash app: routing + every callback (tab, filters, data, selection)
pages.py          Layouts: Overview page and the one-page Dashboard
country_page.py   Country-wise analysis page: layout + all of its callbacks (every id starts with 'cw-')
country_data.py   Data side of that page: country list, URL state, caches, peer/region scoping,
                    thinned map shapes and map framing (no Dash, no figures)
country_figures.py  Plotly figures for that page: faded map + highlighted overlay, frontier, components
datasets.py       Registry of the 7 benchmarks: plain-language copy, filters, and the
                    adapters that call queries.py and return one common "view model"
utils.py          Colours, Plotly figure builders, header/footer, legend, KPI strip,
                    ranking list and country-profile components
queries.py        All data access (Unity Catalog, DEA/FDH frontier ...) - UNCHANGED
assets/           style.css (auto-loaded), fonts/, logos, favicon, hero_dotmap.svg
dev/run_mock.py   Run the whole UI on synthetic data, no Databricks needed
dev/make_hero_dotmap.py   Regenerates the decorative dot map on the Overview page
```

### Adding or changing a benchmark

Everything about a benchmark lives in `datasets.py`: add a `_resolve_xxx(filter_values)`
function that returns the view model described at the top of that file, add its filters to
`FILTERS`, add an entry to `DATASETS` (title, the question it answers, how to read it, about
text) and put its key in `TAB_ORDER`. No new page, layout or callback is needed.

### Running the UI without Databricks

```bash
python dev/run_mock.py     # http://127.0.0.1:8050
```

This imports the real `queries.py` but replaces the two network calls with synthetic tables, so
the scoring, popups and efficiency frontier are the real code running on **random numbers**.
A "Demo data" badge is shown on every page. If the basemap tiles are blocked on your network,
set `CBD_MAP_STYLE=white-bg` (or `carto-positron`); the default is `open-street-map`.
The Country-wise page uses the same basemap; `CBD_COUNTRY_MAP_STYLE=carto-positron` gives it a quieter one
that lets the faded fills stand out more. `CBD_GEOM_TOL_CONTEXT` and `CBD_GEOM_TOL_FOCUS` (degrees,
default 0.03 and 0.008) set how much country outlines are simplified on that page.

## Setup

```bash
pip install -r requirements.txt
```

Key dependencies added for the Databricks migration:
```
databricks-sql-connector
databricks-sdk
python-dotenv
```
(`pandas`, `numpy`, `scipy` were already required.)

## Data source: Databricks Unity Catalog

Every table that used to be a CSV in `./data` now lives in Unity Catalog,
prefixed `cbd_` (e.g. `ccia_score.csv` → `cbd_ccia_score`). World boundaries will be from the 
official World Bank portal which is stored in UC Table `cdb_world_boundaries_dissolved`. It also geospatially
joins all the territories of countries lik Spain, France, etc. ISO A3-coded country 
boundaries used for every choropleth. Score/desc/master tables now live in Databricks.

Set these environment variables (a `.env` file in the project root is picked
up automatically via `python-dotenv`; see `.env.example`):

```bash
DATABRICKS_SERVER_HOSTNAME=adb-xxxx.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abc123
DATABRICKS_CLIENT_ID=your-client-id
DATABRICKS_CLIENT_SECRET=your-client-secret

CBD_CATALOG=prd_mega   # catalog holding the cbd_* tables
CBD_SCHEMA=sgpbpi163     # schema holding the cbd_* tables
```

`queries.py` fails fast at import time with a clear error listing exactly
which of these are missing.

**Column names matter.** The code references some columns by exact case
(`"Code"`, `"Economy"`, `"Year"`, `"Framework"`, `"ISO"`, `"varname"`,
`"method"`, `"sample"`, `"short_name"`, `"2019-2023"`) alongside snake_case
ones (`cntr_code`, `grp_name`, `gccii_id`, `score`, `indicator_name`, ...).
Make sure the Unity Catalog tables preserve these exact names.

## Mapbox

The maps use Plotly's `Choroplethmapbox` trace. To get the exact
`mapbox://styles/mapbox/light-v11` look from the original app, set a Mapbox
access token before running:

```bash
export MAPBOX_TOKEN=pk.your_token_here   # macOS/Linux
set MAPBOX_TOKEN=pk.your_token_here      # Windows (cmd)
```

Without a token the app still runs fine — maps fall back to the free
"carto-positron" basemap style automatically.

Note: Mapbox's `light-v11` style renders its own place labels (city/country
names) on top of the choropleth fill, which can look illegible over a solid
highlight color. `build_map_figure()` sets `below=""` on the trace so the
fill draws above the label layer, hiding labels inside highlighted regions
rather than clashing with them.

## Run

```bash
python app.py
```

Then open http://127.0.0.1:8050

## Notes on the port

- **Region/pillar dropdowns** are `dcc.Dropdown` (Dash's raw `html.Select`
  has no bindable `value` prop), themed via CSS in `assets/style.css` to
  match the original's compact native-select look.
- **Choropleth colors** are computed the same way as the original
  `getScoreColor5` / categorical logic in `constants.ts`: continuous scores
  are bucketed into 5 bands (Low → High); PIMS and PEFA use their own fixed
  categorical color sets. Countries with no data render at low opacity gray.
- **Click-to-see-detail** replaces the original's map-anchored Mapbox popup
  with a floating panel pinned to the top-right of the map (same table
  layout: Country / Indicator / Score). Hover tooltips use Plotly's native
  hover label.
- **Sidebar info blocks** (`utils.info_block`) accept either a string
  (rendered as a paragraph) or a list of strings (rendered as a bulleted
  list) — see the PEFA page's "Indicators" block for an example.
- **PEFA's region dropdown** only re-centers the map (as in the original) —
  it does not filter the data, since PEFA scores aren't tied to World Bank
  regions in the source data.
- The world boundary file is Natural Earth data (public domain), simplified
  and reduced to ISO A3 + name only to keep the app fast.