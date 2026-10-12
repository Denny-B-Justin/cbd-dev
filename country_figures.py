"""
country_figures.py
------------------
Plotly figures for the country-wise page. One idea runs through all of them:

    the selected country is RED, up to three peers get their own colour,
    and every other country is shown light, as quiet context.

Colours (checked with a colour-blind simulation, see PEER_COLORS) and the context
styling live here so every chart on the page agrees.

All builders take plain view-model dicts from country_data.py and return a Plotly
figure (or, for map overlays, plain dicts that app callbacks can send with Patch()
so that changing the peers never re-sends any boundary geometry).
"""

import os

import plotly.graph_objects as go

import utils as u

# ══════════════════════════════════════════════════════════════════════════
# Colours
# ══════════════════════════════════════════════════════════════════════════

FOCUS_COLOR = "#D62839"        # the selected country, on every chart
FOCUS_TINT = "#FDECEE"         # its column / row background in tables
# Peers, in the order they were picked. With the red above these four pass the
# colour-blind and normal-vision separation checks even when any two touch (maps,
# scatter), which is why peers are capped at three (country_data.MAX_PEERS).
PEER_COLORS = ["#2A78D6", "#1BAF7A", "#C98500"]

CONTEXT_DOT = "#C5CEDB"                # other countries on the scatter
CONTEXT_FILL_OPACITY = 0.36            # other countries on the maps: same palette, faded
CONTEXT_NODATA_OPACITY = 0.30

_HOVER = dict(bgcolor="white", font_size=13, font_family=u.FONT_STACK, align="left", bordercolor="#D5DCE6")
_AXIS_FONT = dict(family=u.FONT_STACK, size=12, color="#44546A")
_TRANSPARENT = [[0, "rgba(255,255,255,0)"], [1, "rgba(255,255,255,0)"]]


def role_colors(focus, peers):
    """{iso: colour}. The selected country is red, peers take PEER_COLORS in the order picked."""
    out = {focus: FOCUS_COLOR} if focus else {}
    for i, iso in enumerate(peers or []):
        out[iso] = PEER_COLORS[i % len(PEER_COLORS)]
    return out


def map_style():
    """Basemap for the country maps: the same one the dashboard uses (CBD_MAP_STYLE, default
    'open-street-map'), so the page works wherever the dashboard does. Set CBD_COUNTRY_MAP_STYLE
    to 'carto-positron' for a quieter basemap that lets the faded fills stand out more."""
    return os.environ.get("CBD_COUNTRY_MAP_STYLE") or u.get_map_style()


def _discrete(colors):
    n = len(colors)
    scale = []
    for i, c in enumerate(colors):
        scale += [[i / n, c], [(i + 1) / n, c]]
    return scale


def empty_figure(message=None):
    fig = go.Figure()
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      margin=dict(l=0, r=0, t=0, b=0))
    if message:
        fig.add_annotation(text=message, showarrow=False, font=dict(family=u.FONT_STACK, size=14, color="#6B7A90"))
    return fig


# ══════════════════════════════════════════════════════════════════════════
# Maps: faded context + highlighted country and peers
# ══════════════════════════════════════════════════════════════════════════
# Trace 0  every country in the view, faded            (rebuilt when country/filters change)
# Trace 1  white halo under the peers                  (replaced via Patch when peers change)
# Trace 2  peers: full colour, outlined in their colour
# Trace 3  white halo under the selected country
# Trace 4  selected country: full colour, red outline
# The selected country is its own pair of traces, drawn LAST, so its red outline stays
# complete even along a border it shares with a peer.

EMPTY_OVERLAY = {
    "type": "choroplethmap",
    "geojson": {"type": "FeatureCollection", "features": []},
    "locations": [], "z": [], "featureidkey": "properties.ISO_A3", "showscale": False, "hoverinfo": "skip",
}


def _halo_and_fill(vm, isos, colors, geojson, names, width):
    """(halo, fill) traces for the countries in `isos` that have a shape in `geojson`."""
    present = {f["properties"]["ISO_A3"] for f in geojson.get("features", [])}
    isos = [i for i in isos if i in present]
    if not isos:
        return [EMPTY_OVERLAY, EMPTY_OVERLAY]
    rows = {r["iso"]: r for r in vm["rows"]}
    palette = list(vm["colors"])
    n = len(palette)
    z, lines, custom = [], [], []
    for iso in isos:
        r = rows.get(iso)
        z.append((r["band"] if r and r["band"] is not None else n) + 0.5)   # last band = no data
        lines.append(colors[iso])
        custom.append([iso, r["tooltip"] if r else f"{names.get(iso, iso)}: no data in this view"])
    halo = {
        "type": "choroplethmap", "geojson": geojson, "locations": isos, "z": [1] * len(isos),
        "featureidkey": "properties.ISO_A3", "colorscale": _TRANSPARENT, "showscale": False,
        "marker": {"opacity": 1, "line": {"width": width + 4.5, "color": "#ffffff"}}, "hoverinfo": "skip",
    }
    fill = {
        "type": "choroplethmap", "geojson": geojson, "locations": isos, "z": z,
        "featureidkey": "properties.ISO_A3",
        "colorscale": _discrete(palette + [u.NO_DATA_COLOR]), "zmin": 0, "zmax": n + 1, "showscale": False,
        "marker": {"opacity": 0.97, "line": {"width": width, "color": lines}},
        "customdata": custom, "hovertemplate": "%{customdata[1]}<extra></extra>",
    }
    return [halo, fill]


def overlay_traces(vm, members, colors, geojson, names):
    """
    Traces 1-4 as plain dicts (for Patch). members[0] is the selected country, the rest are peers;
    geojson holds the shapes of exactly those countries. A member with no score (or not in the
    view's table at all) is still outlined, in the 'no data' grey, so you can see where it is.
    """
    peers = _halo_and_fill(vm, list(members[1:]), colors, geojson, names, 2.8)
    focus = _halo_and_fill(vm, list(members[:1]), colors, geojson, names, 3.8)
    return peers + focus


def build_map(vm, members, colors, geo_context, geo_focus, frame, uirevision, names):
    """Faded choropleth of the whole view with the selected country and peers drawn on top."""
    palette = list(vm["colors"])
    n = len(palette)
    locations, z, opacity, custom = [], [], [], []
    for r in vm["rows"]:
        scored = r["band"] is not None
        locations.append(r["iso"])
        z.append((r["band"] if scored else n) + 0.5)
        opacity.append(CONTEXT_FILL_OPACITY if scored else CONTEXT_NODATA_OPACITY)
        custom.append([r["iso"], r["tooltip"]])

    fig = go.Figure()
    fig.add_trace(go.Choroplethmap(
        geojson=geo_context, locations=locations, z=z, featureidkey="properties.ISO_A3",
        colorscale=_discrete(palette + [u.NO_DATA_COLOR]), zmin=0, zmax=n + 1, showscale=False,
        marker=dict(opacity=opacity, line=dict(width=0.6, color="#ffffff")),
        customdata=custom, hovertemplate="%{customdata[1]}<extra></extra>",
    ))
    for trace in overlay_traces(vm, members, colors, geo_focus, names):
        fig.add_trace(go.Choroplethmap(**{k: v for k, v in trace.items() if k != "type"}))

    lat, lon, zoom = frame
    fig.update_layout(
        map=dict(style=map_style(), center={"lat": lat, "lon": lon}, zoom=zoom),
        margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)", hoverlabel=_HOVER,
        font=dict(family=u.FONT_STACK), uirevision=uirevision, showlegend=False,
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
# Infrastructure efficiency
# ══════════════════════════════════════════════════════════════════════════

_FRONTIER_HOVER = ("<b>%{customdata[1]}</b><br>Public investment: %{x:.2f}"
                   "<br>Infrastructure quality: %{y:.2f}<extra></extra>")


def build_frontier(vm, focus, peers, colors, names):
    """Efficiency frontier. Everyone else is a light dot; the selected country is a large red dot."""
    rows = vm["rows"]
    members = ([focus] if focus else []) + list(peers or [])
    others = [p for p in rows if p["iso"] not in members]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[p["x"] for p in others], y=[p["y"] for p in others], mode="markers", name="Other countries",
        marker=dict(color=CONTEXT_DOT, size=7, opacity=0.8),
        customdata=[[p["iso"], p["name"]] for p in others], hovertemplate=_FRONTIER_HOVER,
    ))
    dea, fdh = vm["frontier"]["dea"], vm["frontier"]["fdh"]
    if dea:
        pts = sorted(dea, key=lambda p: p["x"])
        fig.add_trace(go.Scatter(x=[p["x"] for p in pts], y=[p["y"] for p in pts], mode="lines",
                                 name="DEA frontier", line=dict(color=u.INDIGO, width=2), opacity=0.7,
                                 hoverinfo="skip"))
    if fdh:
        pts = sorted(fdh, key=lambda p: p["x"])
        fig.add_trace(go.Scatter(x=[p["x"] for p in pts], y=[p["y"] for p in pts], mode="lines",
                                 name="FDH frontier", line=dict(color=u.ORANGE, width=2, dash="dash"),
                                 opacity=0.7, hoverinfo="skip"))

    by_iso = {p["iso"]: p for p in rows}
    for iso in list(peers or []) + ([focus] if focus else []):        # focus last = on top
        p = by_iso.get(iso)
        if not p:
            continue
        is_focus = iso == focus
        fig.add_trace(go.Scatter(
            x=[p["x"]], y=[p["y"]], mode="markers+text", showlegend=False, name=p["name"],
            text=[f"<b>{p['name']}</b>" if is_focus else p["name"]],
            textposition="top center" if is_focus else "bottom center",
            textfont=dict(family=u.FONT_STACK, size=13 if is_focus else 12, color=u.NAVY),
            marker=dict(color=colors[iso], size=17 if is_focus else 12, line=dict(width=2, color="#ffffff")),
            customdata=[[p["iso"], p["name"]]], hovertemplate=_FRONTIER_HOVER,
        ))

    if focus and focus not in by_iso:
        fig.add_annotation(
            xref="paper", yref="paper", x=0.01, y=0.99, xanchor="left", yanchor="top", showarrow=False,
            text=f"{names.get(focus, focus)} is not in the efficiency analysis",
            font=dict(family=u.FONT_STACK, size=13, color=FOCUS_COLOR),
            bgcolor="rgba(255,255,255,.9)", bordercolor=FOCUS_COLOR, borderwidth=1, borderpad=5)

    fig.update_layout(
        margin=dict(l=64, r=20, t=40, b=52),
        font=dict(family=u.FONT_STACK, color="#44546A"),
        xaxis=dict(title=dict(text="Public investment per person (log scale)", font=_AXIS_FONT),
                   gridcolor="#E8EDF3", zeroline=False, tickfont=_AXIS_FONT),
        yaxis=dict(title=dict(text="Infrastructure quality (GQII)", font=_AXIS_FONT),
                   gridcolor="#E8EDF3", zeroline=False, tickfont=_AXIS_FONT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(family=u.FONT_STACK, size=12)),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)", hoverlabel=_HOVER,
        uirevision=f"frontier|{focus}", clickmode="event",
    )
    return fig


def build_components(df, focus, peers, colors, names, order):
    """Grouped bars: the efficiency score of each component for the selected country and its peers."""
    members = ([focus] if focus else []) + list(peers or [])
    if df is None or df.empty or not members:
        return empty_figure("No component scores for this method and sample")
    by_var = {}
    for _, row in df.iterrows():
        by_var.setdefault(row["short_name"] or "", {})[row["ISO"]] = row["score"]
    labels = sorted(by_var, key=lambda n: order.index(n) if n in order else 999)

    fig = go.Figure()
    for iso in members:
        fig.add_trace(go.Bar(
            x=labels, y=[by_var[n].get(iso) for n in labels], name=names.get(iso, iso),
            marker_color=colors[iso],
            hovertemplate="<b>" + names.get(iso, iso).replace("<", "") + "</b><br>%{x}: %{y:.2f}<extra></extra>",
        ))
    fig.update_layout(
        barmode="group", bargap=0.28, bargroupgap=0.08, margin=dict(l=56, r=16, t=40, b=96),
        font=dict(family=u.FONT_STACK, color="#44546A"),
        yaxis=dict(title=dict(text="Score", font=_AXIS_FONT), gridcolor="#E8EDF3", tickfont=_AXIS_FONT),
        xaxis=dict(tickfont=dict(family=u.FONT_STACK, size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(family=u.FONT_STACK, size=12)),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)", hoverlabel=_HOVER,
    )
    return fig
