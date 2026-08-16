/* GeoPilot dashboard.
 *
 * Draws SVG from the data embedded in the page. No network, no libraries: the
 * page has to work from a USB stick, an email attachment, or a laptop with no
 * connection in a mechanical room.
 *
 * It renders what the generator computed and nothing else. In particular it
 * never interpolates across a hole: an interval with no data is a break in the
 * line, because that is what the recording says.
 */

(function () {
  "use strict";

  const data = window.GEOPILOT;
  if (!data) return;

  const WIDTH = 720;
  const PAD = { top: 12, right: 10, bottom: 22, left: 46 };

  // The viewBox scales uniformly, so its shape decides how tall a chart lands
  // once the card narrows. A wide, flat box that reads well on a laptop becomes
  // an unreadable 80-pixel strip on a phone, so a narrow card gets a taller box.
  const NARROW = 480;

  function heightFor(width) {
    return width < NARROW ? 320 : 200;
  }

  const svgns = "http://www.w3.org/2000/svg";

  function el(name, attributes) {
    const node = document.createElementNS(svgns, name);
    for (const key in attributes) node.setAttribute(key, attributes[key]);
    return node;
  }

  function niceNumber(value, digits) {
    if (value === null || value === undefined) return "—";
    return Number(value).toFixed(digits === undefined ? 2 : digits);
  }

  function shortDate(iso) {
    // The generator already resolved these to the local wall clock where the
    // readings were taken. Slicing beats re-parsing into the viewer's zone.
    return iso.slice(5, 16).replace("T", " ");
  }

  function extent(series, kind) {
    // Bars count occurrences, which start at zero. Padding below the smallest
    // one would put a negative number on the axis of a quantity that cannot be
    // negative, and an axis that does not start at zero exaggerates a bar chart.
    if (kind === "bars") {
      let most = 0;
      for (const point of series) most = Math.max(most, point.count);
      return [0, most === 0 ? 1 : most * 1.08];
    }

    let low = Infinity;
    let high = -Infinity;
    for (const point of series) {
      if (point.min < low) low = point.min;
      if (point.max > high) high = point.max;
    }
    if (low === Infinity) return [0, 1];
    if (low === high) return [low - 0.5, high + 0.5];
    const margin = (high - low) * 0.08;
    return [low - margin, high + margin];
  }

  function scales(series, kind, height) {
    const [low, high] = extent(series, kind);
    const innerWidth = WIDTH - PAD.left - PAD.right;
    const innerHeight = height - PAD.top - PAD.bottom;
    const span = Math.max(series.length - 1, 1);
    return {
      low: low,
      high: high,
      x: (index) => PAD.left + (index / span) * innerWidth,
      y: (value) => PAD.top + (1 - (value - low) / (high - low)) * innerHeight,
    };
  }

  function drawAxes(svg, series, scale, height) {
    const axis = el("g", { class: "axis" });

    for (let step = 0; step <= 3; step += 1) {
      const value = scale.low + ((scale.high - scale.low) * step) / 3;
      const y = scale.y(value);
      axis.appendChild(el("line", { x1: PAD.left, y1: y, x2: WIDTH - PAD.right, y2: y }));
      const label = el("text", { x: PAD.left - 6, y: y + 3, "text-anchor": "end" });
      label.textContent = niceNumber(value, 1);
      axis.appendChild(label);
    }

    const first = el("text", { x: PAD.left, y: height - 6 });
    first.textContent = shortDate(series[0].at);
    axis.appendChild(first);

    if (series.length > 1) {
      const last = el("text", { x: WIDTH - PAD.right, y: height - 6, "text-anchor": "end" });
      last.textContent = shortDate(series[series.length - 1].at);
      axis.appendChild(last);
    }

    svg.appendChild(axis);
  }

  function drawBand(svg, series, scale) {
    if (series.length < 2) return;
    const upper = series.map((point, index) => `${scale.x(index)},${scale.y(point.max)}`);
    const lower = series
      .map((point, index) => `${scale.x(index)},${scale.y(point.min)}`)
      .reverse();
    svg.appendChild(el("polygon", { class: "band", points: upper.concat(lower).join(" ") }));
  }

  function drawLine(svg, series, scale) {
    const commands = series
      .map((point, index) => `${index === 0 ? "M" : "L"}${scale.x(index)},${scale.y(point.mean)}`)
      .join("");
    svg.appendChild(el("path", { class: "line", d: commands }));
  }

  function drawBars(svg, series, scale) {
    const innerWidth = WIDTH - PAD.left - PAD.right;
    const width = Math.max(2, (innerWidth / Math.max(series.length, 1)) * 0.62);
    const base = scale.y(scale.low);
    series.forEach((point, index) => {
      const y = scale.y(point.count);
      svg.appendChild(
        el("rect", {
          class: "bar",
          x: scale.x(index) - width / 2,
          y: Math.min(y, base),
          width: width,
          height: Math.max(1, Math.abs(base - y)),
        }),
      );
    });
  }

  function plot(container, series, kind, unit) {
    container.textContent = "";

    if (!series || series.length === 0) {
      const empty = document.createElement("p");
      empty.className = "note";
      empty.textContent = "nothing recorded in this view";
      container.appendChild(empty);
      return;
    }

    const height = heightFor(container.clientWidth || WIDTH);
    const svg = el("svg", { viewBox: `0 0 ${WIDTH} ${height}`, role: "img" });
    const scale = scales(series, kind, height);

    drawAxes(svg, series, scale, height);
    if (kind === "bars") {
      drawBars(svg, series, scale);
    } else {
      drawBand(svg, series, scale);
      drawLine(svg, series, scale);
    }

    container.appendChild(svg);

    const readout = document.createElement("div");
    readout.className = "readout";
    container.appendChild(readout);

    svg.addEventListener("pointermove", (event) => {
      const box = svg.getBoundingClientRect();
      const fraction = (event.clientX - box.left) / box.width;
      const index = Math.round(fraction * WIDTH - PAD.left) / (WIDTH - PAD.left - PAD.right);
      const at = Math.min(
        series.length - 1,
        Math.max(0, Math.round(index * Math.max(series.length - 1, 1))),
      );
      const point = series[at];
      readout.textContent =
        kind === "bars"
          ? `${shortDate(point.at)} · ${point.count} cycles · shortest ${niceNumber(point.min, 0)}s · mean ${niceNumber(point.mean, 0)}s · longest ${niceNumber(point.max, 0)}s`
          : `${shortDate(point.at)} · mean ${niceNumber(point.mean)} ${unit} · min ${niceNumber(point.min)} · max ${niceNumber(point.max)} · n=${point.count}`;
    });

    svg.addEventListener("pointerleave", () => {
      readout.textContent = "";
    });
  }

  function wire(panel) {
    const figure = panel.querySelector(".figure");
    const spec = data.panels[panel.dataset.panel];
    if (!spec) return null;

    let current = spec.initial;
    const buttons = panel.querySelectorAll("button[data-view]");

    const show = (view) => {
      current = view;
      buttons.forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.view === view));
      });
      plot(figure, spec.views[view], spec.kind, spec.unit);
    };

    buttons.forEach((button) => {
      button.addEventListener("click", () => show(button.dataset.view));
    });

    show(current);
    return () => show(current);
  }

  const redraws = [];
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    const redraw = wire(panel);
    if (redraw) redraws.push(redraw);
  });

  // Crossing the narrow threshold changes the viewBox, so the charts have to be
  // drawn again. Debounced, because a phone rotating fires this repeatedly.
  let pending = 0;
  let lastWidth = window.innerWidth;
  window.addEventListener("resize", () => {
    const crossed =
      (lastWidth < NARROW) !== (window.innerWidth < NARROW) || Math.abs(window.innerWidth - lastWidth) > 80;
    lastWidth = window.innerWidth;
    if (!crossed) return;
    clearTimeout(pending);
    pending = setTimeout(() => redraws.forEach((redraw) => redraw()), 150);
  });
})();
