/*
 * export.js - "Save PNG" for the charts (Dashboard and Country-wise analysis).
 *
 * Dash loads every .js file in assets/ by itself. One click handler on the document picks up any
 * button that carries data-png-graph, so it keeps working when a page re-renders. Nothing here
 * talks to the server: the chart is turned into an image with Plotly, then a title, the colour key
 * and the legend are drawn around it so the picture makes sense on its own in a slide or a report.
 *
 * Button attributes (set in exports.py):
 *   data-png-graph       id of the dcc.Graph to capture
 *   data-png-title       heading (or data-png-title-sel: CSS selector of an element that holds it)
 *   data-png-file        start of the file name (default: made from the heading)
 *   data-png-sub-sel     CSS selector of an element whose text is the subtitle
 *   data-png-sub-mode    "filters" = the visible filter values of the Dashboard
 *   data-png-legend-sel  CSS selector of the map legend
 *   data-png-key-sel     CSS selector of the colour key (selected country and peers)
 */
(function () {
  "use strict";

  var FONT = '"Fira Sans", "Helvetica Neue", Arial, sans-serif';
  var INK = "#0B2B4B", SOFT = "#44546A", MUTE = "#6B7A90", LINE = "#D5DCE6";
  var SCALE = 2;       // 2x the on-screen size, so the picture stays sharp when it is pasted into a slide

  function clean(s) { return (s || "").replace(/\s+/g, " ").trim(); }

  function plotDiv(id) {
    var host = document.getElementById(id);
    if (!host) return null;
    return host.classList.contains("js-plotly-plot") ? host : host.querySelector(".js-plotly-plot");
  }

  // Text of an element. A block made of several lines (the country summary strip) is joined with " | "
  // so "Albania B+" and "4 of 32 countries share this result" do not run into each other.
  function textOf(sel) {
    var el = sel ? document.querySelector(sel) : null;
    if (!el) return "";
    var parts = [];
    Array.prototype.forEach.call(el.children, function (c) {
      var t = clean(c.innerText || c.textContent);
      if (t) parts.push(t);
    });
    return parts.length > 1 ? parts.join("  |  ") : clean(el.innerText || el.textContent);
  }

  // The Dashboard's visible filters, e.g. "Region: Europe and Central Asia | Method: Bootstrapped DEA".
  function filterText() {
    var out = [];
    document.querySelectorAll(".filterbar .field").forEach(function (f) {
      if (f.offsetParent === null) return;
      var label = clean((f.querySelector(".field-label") || {}).innerText);
      var value = clean((f.querySelector(".Select-value-label, .dash-dropdown-value, .dash-dropdown-trigger") || {}).innerText);
      if (label && value) out.push(label + ": " + value);
    });
    return out.join("  |  ");
  }

  // [{color, label}] from a legend or colour key.
  function readLegend(sel) {
    var root = sel ? document.querySelector(sel) : null;
    if (!root) return [];
    var items = [];
    root.querySelectorAll(".legend-item").forEach(function (li) {
      var sw = li.querySelector(".legend-swatch");
      var label = clean((li.querySelector(".legend-label") || {}).innerText);
      var range = clean((li.querySelector(".legend-range") || {}).innerText);
      if (sw && label) items.push({ color: getComputedStyle(sw).backgroundColor, label: label + (range ? " (" + range + ")" : "") });
    });
    return items;
  }

  function readKey(sel) {
    var root = sel ? document.querySelector(sel) : null;
    if (!root) return [];
    var items = [];
    root.querySelectorAll(".cw-key").forEach(function (li) {
      var dot = li.querySelector(".cw-dot");
      if (dot) items.push({ color: getComputedStyle(dot).backgroundColor, label: clean(li.innerText), ring: dot.classList.contains("is-light") });
    });
    return items;
  }

  function wrap(ctx, text, maxWidth) {
    var words = text.split(" "), lines = [], line = "";
    words.forEach(function (w) {
      var test = line ? line + " " + w : w;
      if (ctx.measureText(test).width > maxWidth && line) { lines.push(line); line = w; } else { line = test; }
    });
    if (line) lines.push(line);
    return lines;
  }

  // Lay swatch + label pairs out left to right, wrapping to new rows. Returns the height used.
  function drawItems(ctx, items, x, y, maxWidth, size, draw) {
    var gap = 18 * SCALE, sw = 11 * SCALE, rowH = size * 1.7, cx = x, cy = y;
    ctx.font = size + "px " + FONT;
    items.forEach(function (it) {
      var w = sw + 6 * SCALE + ctx.measureText(it.label).width;
      if (cx > x && cx + w > x + maxWidth) { cx = x; cy += rowH; }
      if (draw) {
        ctx.fillStyle = it.color;
        ctx.beginPath(); ctx.arc(cx + sw / 2, cy + size * 0.55, sw / 2, 0, Math.PI * 2); ctx.fill();
        if (it.ring) { ctx.strokeStyle = "#B8C3D3"; ctx.lineWidth = 1 * SCALE; ctx.stroke(); }
        ctx.fillStyle = SOFT; ctx.textBaseline = "alphabetic";
        ctx.fillText(it.label, cx + sw + 6 * SCALE, cy + size * 0.9);
      }
      cx += w + gap;
    });
    return items.length ? cy - y + rowH : 0;
  }

  function loadImage(src) {
    return new Promise(function (ok, fail) {
      var img = new Image();
      img.onload = function () { ok(img); };
      img.onerror = fail;
      img.src = src;
    });
  }

  function stamp() {
    var d = new Date();
    return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
  }

  function countryFromUrl() {
    var m = /country=([A-Za-z]{3})/.exec(window.location.hash || "");
    return m ? m[1].toUpperCase() : "";
  }

  async function savePng(btn) {
    var d = btn.dataset;
    var gd = plotDiv(d.pngGraph);
    if (!gd || !window.Plotly) throw new Error("chart not ready");

    var w = Math.max(320, Math.round(gd.offsetWidth)), h = Math.max(200, Math.round(gd.offsetHeight));
    var chart = await loadImage(await window.Plotly.toImage(gd, { format: "png", width: w, height: h, scale: SCALE }));

    var title = d.pngTitle || textOf(d.pngTitleSel);
    var sub = d.pngSubMode === "filters" ? filterText() : textOf(d.pngSubSel);
    var key = readKey(d.pngKeySel), legend = readLegend(d.pngLegendSel);
    var legendTitle = textOf(d.pngLegendSel ? d.pngLegendSel + " .legend-title" : "");

    var pad = 24 * SCALE, inner = chart.width, W = inner + 2 * pad;
    var probe = document.createElement("canvas").getContext("2d");

    // First pass measures, second pass draws, so the canvas is exactly as tall as it needs to be.
    function layout(ctx, draw) {
      var y = pad;
      ctx.textBaseline = "alphabetic";
      ctx.font = "600 " + 22 * SCALE + "px " + FONT;
      if (draw) { ctx.fillStyle = INK; ctx.fillText(title, pad, y + 22 * SCALE); }
      y += 22 * SCALE * 1.35;
      if (sub) {
        ctx.font = 14 * SCALE + "px " + FONT;
        wrap(ctx, sub, inner).forEach(function (line) {
          if (draw) { ctx.fillStyle = SOFT; ctx.fillText(line, pad, y + 14 * SCALE); }
          y += 14 * SCALE * 1.5;
        });
      }
      y += 8 * SCALE;
      if (key.length) { y += drawItems(ctx, key, pad, y, inner, 13 * SCALE, draw) + 6 * SCALE; }
      var chartTop = y;
      if (draw) {
        ctx.strokeStyle = LINE; ctx.lineWidth = 1 * SCALE;
        ctx.strokeRect(pad - 0.5, chartTop - 0.5, chart.width + 1, chart.height + 1);
        ctx.drawImage(chart, pad, chartTop);
      }
      y += chart.height + 12 * SCALE;
      if (legend.length) {
        if (legendTitle) {
          ctx.font = "600 " + 13 * SCALE + "px " + FONT;
          if (draw) { ctx.fillStyle = INK; ctx.fillText(legendTitle, pad, y + 13 * SCALE); }
          y += 13 * SCALE * 1.6;
        }
        y += drawItems(ctx, legend, pad, y, inner, 12.5 * SCALE, draw);
      }
      y += 10 * SCALE;
      ctx.font = 11.5 * SCALE + "px " + FONT;
      if (draw) {
        ctx.fillStyle = MUTE;
        ctx.fillText("Source: World Bank, Country Benchmarking Dashboard. Saved " + stamp() + ".", pad, y + 11.5 * SCALE);
      }
      y += 11.5 * SCALE * 1.4 + pad;
      return Math.ceil(y);
    }

    var H = layout(probe, false);
    var canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, W, H);
    layout(ctx, true);

    var blob = await new Promise(function (ok) { canvas.toBlob(ok, "image/png"); });
    if (!blob) throw new Error("could not encode the image");
    var base = d.pngFile || title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    var name = ["cbd", base, countryFromUrl(), stamp()].filter(Boolean).join("_") + ".png";
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  // The button's text belongs to React, so progress and errors are shown with classes (see style.css).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-png-graph]") : null;
    if (!btn || btn.classList.contains("is-busy")) return;
    btn.classList.remove("is-error");
    btn.classList.add("is-busy");
    var fonts = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
    fonts.then(function () { return savePng(btn); })
      .catch(function (err) {
        console.error("Save PNG failed:", err);
        btn.classList.add("is-error");
        setTimeout(function () { btn.classList.remove("is-error"); }, 3000);
      })
      .then(function () { btn.classList.remove("is-busy"); });
  });
})();