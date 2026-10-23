"use strict";

const CT = {
  charts: new Set(),
  logos: new Map(),
  nf: new Intl.NumberFormat("pt-BR"),
  reduceMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
};

// Troca o ponto decimal por vírgula.
const comma = (s) => s.replace(".", ",");
// Prefixa o texto com o sinal do valor.
const signed = (v, s) => (v > 0 ? "+" : v < 0 ? "−" : "") + s;
// Formatadores usados nos eixos, rótulos e tooltips dos gráficos.
const CF = {
  int: (v) => CT.nf.format(Math.round(v)),
  compact: (v) => (Math.abs(v) >= 1e6 ? comma((v / 1e6).toFixed(1)) + " mi" : Math.abs(v) >= 1e4 ? comma((v / 1e3).toFixed(0)) + " mil" : CT.nf.format(v)),
  pct0: (v) => Math.round(v * 100) + "%",
  pct1: (v) => comma((v * 100).toFixed(1)) + "%",
  n2: (v) => comma(Number(v).toFixed(2)),
  hs: (v) => comma(Number(v).toFixed(1)) + "%",
  hs0: (v) => Math.round(v) + "%",
  pp: (v) => signed(v, comma(Math.abs(v * 100).toFixed(1)) + " pp"),
  pp0: (v) => (Math.abs(v) < 1e-9 ? "0" : signed(v, Math.abs(Math.round(v * 100)) + " pp")),
};
// Formata um valor do gráfico com o formatador indicado.
const cfmt = (key, v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : (CF[key] || CF.n2)(v));

// Retorna as cores do gráfico para o tema atual.
function chartTheme() {
  const mode = theme();
  const t = (state.meta && state.meta.chart_themes && state.meta.chart_themes[mode]) || {};
  return { ...t, events: (state.meta && state.meta.event_colors[mode]) || {}, mode };
}
// Converte um token de cor da API na cor real do tema.
function tokenColor(T, tok) {
  if (!tok) return T.main;
  if (tok.startsWith("ev:")) return T.events[tok.slice(3)] || T.muted;
  if (/^s\d$/.test(tok)) return T.series[Number(tok.slice(1))];
  return T[tok] || tok;
}

// Gera o HTML do contêiner de um gráfico, com título e botões.
function chart(name, extra = {}, alt = "") {
  const png = `/api/chart/${name}.png?${qs({ ...extra, theme: theme() })}`;
  return `<figure class="chart" data-chart="${name}" data-q="${esc(qs(extra))}" data-alt="${esc(alt || name)}">
    <figcaption class="chart-head"><div class="chart-titles"><h3 class="chart-title">${esc(alt)}</h3><p class="chart-sub"></p></div>
      <div class="chart-tools"><button type="button" class="chart-btn" data-act="table" aria-pressed="false" hidden>Tabela</button><a class="chart-btn" href="${esc(png)}" download="${name}.png" title="Versão estática gerada com matplotlib/seaborn">Baixar PNG</a></div></figcaption>
    <div class="chart-body is-loading"></div></figure>`;
}

// Carrega todos os gráficos ainda não inicializados na página.
function hydrateCharts(root = document) {
  root.querySelectorAll("figure.chart[data-chart]:not([data-state])").forEach(loadChart);
}
// Busca os dados de um gráfico na API e o renderiza.
async function loadChart(fig) {
  fig.dataset.state = "loading";
  const body = $(".chart-body", fig);
  let spec;
  try {
    const r = await fetch(`/api/chart-data/${fig.dataset.chart}?${fig.dataset.q}`);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    spec = await r.json();
  } catch (e) {
    body.classList.remove("is-loading");
    body.innerHTML = `<div class="chart-empty">Não foi possível carregar o gráfico: ${esc(e.message)}</div>`;
    fig.dataset.state = "error";
    return;
  }
  if (!fig.isConnected) return;
  fig.dataset.state = "ready";
  body.classList.remove("is-loading");
  if (spec.title) $(".chart-title", fig).textContent = spec.title;
  $(".chart-sub", fig).textContent = spec.subtitle || "";
  if (spec.kind === "empty") {
    body.innerHTML = `<div class="chart-empty">${esc(spec.message)}</div>`;
    return;
  }
  if (spec.kind === "heatmap") {
    body.append(heatmap(spec, chartTheme()));
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "chart-canvas";
  wrap.style.height = chartHeight(spec) + "px";
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", [spec.title, spec.subtitle].filter(Boolean).join(". "));
  wrap.append(canvas);
  if (spec.callout) wrap.insertAdjacentHTML("beforeend", `<div class="chart-callout"><b>${esc(spec.callout[0])}</b>${spec.callout.slice(1).map((l) => `<span>${esc(l)}</span>`).join("")}</div>`);
  body.append(wrap);
  CT.charts.add(new Chart(canvas, buildConfig(spec, chartTheme())));
  const btn = $('[data-act="table"]', fig);
  btn.hidden = false;
  btn.onclick = () => {
    const on = btn.getAttribute("aria-pressed") !== "true";
    btn.setAttribute("aria-pressed", String(on));
    btn.textContent = on ? "Gráfico" : "Tabela";
    wrap.hidden = on;
    let tbl = $(".chart-table", body);
    if (on && !tbl) {
      tbl = document.createElement("div");
      tbl.className = "chart-table";
      tbl.append(specTable(spec));
      body.append(tbl);
    }
    if (tbl) tbl.hidden = !on;
  };
}

// Calcula a altura do gráfico conforme o tipo e a quantidade de itens.
function chartHeight(spec) {
  if (spec.height) return spec.height;
  const legend = legendShown(spec) ? 30 : 0;
  const grouped = spec.datasets.length > 1 && !spec.stacked;
  if (spec.kind === "bar" && spec.horizontal) return Math.max(150, spec.labels.length * (grouped ? 36 : 27) + 46 + legend);
  return 300 + legend;
}
// Indica se a legenda deve ser exibida.
const legendShown = (spec) => spec.datasets.filter((d) => d.role !== "ref").length >= 2;

// Monta a configuração do Chart.js a partir da especificação da API.
function buildConfig(spec, T) {
  const horiz = Boolean(spec.horizontal);
  const valAx = horiz ? "x" : "y", catAx = horiz ? "y" : "x";
  const scatter = spec.kind === "scatter";
  const font = getComputedStyle(document.documentElement).getPropertyValue("--font").trim() || "Inter, sans-serif";
  Chart.defaults.font.family = font;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = T.muted;

  const datasets = spec.datasets.map((d, j) => dataset(spec, d, j, T, horiz));
  const axisFmt = (ax) => (spec[ax] && spec[ax].fmt) || (spec.fmt === "int" ? "compact" : spec.fmt);
  // Monta a configuração de um eixo numérico.
  const linearAxis = (ax) => {
    const o = spec[ax] || {};
    const fixedMax = o.max !== undefined;
    return {
      type: "linear", min: o.min, max: o.max, beginAtZero: o.min === undefined && spec.kind === "bar",
      grace: fixedMax ? 0 : spec.end && horiz ? (spec.notes ? "26%" : "14%") : spec.end ? "12%" : "4%",
      grid: { color: T.grid, drawTicks: false }, border: { display: false },
      ticks: { color: T.muted, padding: 6, maxTicksLimit: 8, callback: (v) => cfmt(axisFmt(ax), v),
               precision: spec.fmt === "int" ? 0 : undefined, stepSize: o.step },
      title: o.title ? { display: true, text: o.title, color: T.muted, font: { size: 11.5 } } : undefined,
    };
  };
  const scales = {};
  if (scatter || spec.linear_x) {
    scales.x = { ...linearAxis("x"), beginAtZero: false, offset: false };
    scales.y = linearAxis("y");
    if (spec.linear_x) scales.y.beginAtZero = true;
  } else {
    scales[valAx] = { ...linearAxis(valAx), stacked: Boolean(spec.stacked) };
    scales[catAx] = {
      type: "category", stacked: Boolean(spec.stacked), grid: { display: false },
      border: { color: T.axis }, offset: true,
      ticks: { color: T.text2, padding: spec.logos ? 28 : 8, autoSkip: !horiz, font: { size: horiz ? 12.5 : 12 } },
    };
  }

  const tipItems = (items) => items.filter((it) => it.raw !== null && it.raw !== undefined && !["ref", "fit"].includes(spec.datasets[it.datasetIndex].role)
    && spec.datasets[it.datasetIndex].tip !== "none");
  const tooltip = {
    backgroundColor: T.surface, borderColor: T.axis, borderWidth: 1, titleColor: T.text, bodyColor: T.text2,
    footerColor: T.muted, padding: 10, cornerRadius: 4, boxWidth: 10, boxHeight: 10, boxPadding: 4,
    titleFont: { weight: "700" }, footerFont: { weight: "500" }, caretSize: 5,
    filter: (it) => tipItems([it]).length > 0,
    callbacks: {},
  };
  if (scatter) {
    const xf = spec.x_fmt || spec.x.fmt, yf = spec.y.fmt || spec.fmt;
    Object.assign(tooltip.callbacks, {
      title: (items) => (items[0] ? items[0].raw.name : ""),
      label: (it) => [`${spec.x.title}: ${cfmt(xf === "pct0" ? "pct1" : xf, it.raw.x)}`, `${spec.y.title}: ${cfmt(yf === "pct0" ? "pct1" : yf, it.raw.y)}`],
      footer: (items) => (items[0] && items[0].raw.note) || "",
    });
  } else if (spec.linear_x) {
    const w = spec.bin_width / 2;
    Object.assign(tooltip.callbacks, {
      title: (items) => (items[0] ? `HS entre ${CF.hs(items[0].raw.x - w)} e ${CF.hs(items[0].raw.x + w)}` : ""),
      label: (it) => ` ${it.raw.y} jogador${it.raw.y === 1 ? "" : "es"}`,
    });
  } else {
    Object.assign(tooltip.callbacks, {
      title: (items) => (items[0] ? spec.labels[items[0].dataIndex] : ""),
      label: (it) => ` ${spec.datasets[it.datasetIndex].label}: ${cfmt(spec.fmt, it.raw)}`,
      footer: (items) => {
        if (!items[0]) return "";
        const i = items[0].dataIndex, out = [];
        if (spec.stacked && spec.end === "total" && items.length > 1) out.push(`Total: ${cfmt(spec.fmt, items.reduce((s, it) => s + (it.raw || 0), 0))}`);
        if (spec.notes && spec.notes[i]) out.push(spec.notes[i].replace(/^\((.*)\)$/, "$1"));
        return out;
      },
    });
  }

  // Retorna o link do item clicado no gráfico, se houver.
  const linkAt = (evt, els) => {
    if (els.length) {
      const el = els[0], ds = spec.datasets[el.datasetIndex];
      if (scatter) return ds.role ? null : ds.data[el.index].link;
      return spec.links ? spec.links[el.index] : null;
    }
    return null;
  };
  return {
    type: scatter ? "scatter" : spec.kind === "line" ? "line" : "bar",
    data: { labels: spec.labels, datasets },
    options: {
      indexAxis: horiz ? "y" : "x",
      responsive: true, maintainAspectRatio: false,
      animation: CT.reduceMotion ? false : { duration: 450 },
      layout: { padding: { top: spec.end && !horiz ? 18 : 4, right: spec.end === "last" ? 112 : 8 } },
      interaction: scatter ? { mode: "nearest", intersect: true } : { mode: "index", axis: horiz ? "y" : "x", intersect: false },
      scales,
      plugins: {
        legend: {
          display: legendShown(spec), position: "top", align: "start",
          labels: { color: T.text2, boxWidth: 10, boxHeight: 10, padding: 14, font: { size: 12 }, usePointStyle: false,
                    filter: (item) => spec.datasets[item.datasetIndex].role !== "ref",
                    sort: (a, b) => a.datasetIndex - b.datasetIndex },
        },
        tooltip,
      },
      onHover: (evt, els, ch) => { ch.canvas.style.cursor = linkAt(evt, els) || axisLink(ch, spec, evt) ? "pointer" : "default"; },
      onClick: (evt, els, ch) => { const to = linkAt(evt, els) || axisLink(ch, spec, evt); if (to) location.hash = to.replace(/^#/, ""); },
    },
    plugins: [legendGapPlugin, refsPlugin(spec, T), endLabelsPlugin(spec, T), logosPlugin(spec, T), pointLabelsPlugin(spec, T)],
  };
}

// Monta a configuração de uma série do gráfico conforme o tipo.
function dataset(spec, d, j, T, horiz) {
  const color = Array.isArray(d.color) ? d.color.map((c) => tokenColor(T, c)) : tokenColor(T, d.color);
  const type = d.type || (spec.kind === "scatter" ? (d.role ? "line" : "scatter") : spec.kind === "line" ? "line" : "bar");
  const base = { label: d.label, data: d.data, type, backgroundColor: color, borderColor: color };
  if (type === "scatter") {
    const dense = d.data.length > 300;
    return { ...base, backgroundColor: color + (dense ? "70" : "c8"), borderColor: T.surface, borderWidth: dense ? 0.5 : 1,
             pointRadius: dense ? 3 : 4, pointHoverRadius: 6, pointHoverBorderWidth: 2, pointHoverBackgroundColor: color, order: 1 };
  }
  if (type === "line") {
    const ref = d.role === "ref", fit = d.role === "fit", kde = spec.linear_x;
    return { ...base, borderWidth: ref ? 1 : 2, pointRadius: ref || fit || kde ? 0 : 4, pointHoverRadius: ref || fit || kde ? 0 : 6,
             pointBackgroundColor: color, pointBorderColor: T.surface, pointBorderWidth: 2, tension: kde ? 0.35 : 0,
             fill: false, order: 0, spanGaps: true, showLine: true, borderDash: ref ? [4, 4] : undefined };
  }
  if (spec.linear_x) {
    return { ...base, barPercentage: 1, categoryPercentage: 1, borderColor: T.surface, borderWidth: { left: 1, right: 1 },
             borderRadius: { topLeft: 2, topRight: 2 }, borderSkipped: "bottom", order: 1, grouped: false };
  }
  const multi = spec.datasets.length > 1 && !spec.stacked;
  const out = {
    ...base, order: 1,
    maxBarThickness: horiz ? (multi ? 11 : 18) : 46,
    categoryPercentage: multi ? 0.76 : 0.8, barPercentage: multi ? 0.94 : 0.9,
    borderSkipped: "start", borderRadius: 4,
  };
  if (spec.stacked) {
    out.borderSkipped = false;
    out.borderColor = T.surface;
    out.borderWidth = horiz ? { right: 2 } : { top: 2 };
    out.borderRadius = (ctx) => (isOuterSegment(ctx) ? (horiz ? { topRight: 4, bottomRight: 4 } : { topLeft: 4, topRight: 4 }) : 0);
    if (spec.datasets.some((x) => x.data.some((v) => v !== null && v < 0))) {
      out.borderWidth = 0;
      out.borderSkipped = "start";
      out.borderRadius = 4;
    }
  }
  return out;
}
// Indica se o segmento é o último visível da pilha (para arredondar).
function isOuterSegment(ctx) {
  const ch = ctx.chart, i = ctx.dataIndex;
  for (let j = ch.data.datasets.length - 1; j > ctx.datasetIndex; j--) {
    const v = ch.data.datasets[j].data[i];
    if (ch.isDatasetVisible(j) && v !== null && v !== undefined && v !== 0) return false;
  }
  return true;
}

// Retorna o link do rótulo do eixo Y sob o cursor, se houver.
function axisLink(ch, spec, evt) {
  if (!spec.links || !spec.horizontal || !ch.scales.y || ch.scales.y.type !== "category") return null;
  const { left } = ch.chartArea;
  if (evt.x >= left || evt.x < 0) return null;
  const i = Math.round(ch.scales.y.getValueForPixel(evt.y));
  return i >= 0 && i < spec.links.length ? spec.links[i] : null;
}

// Escreve um texto no canvas com alinhamento definido.
function label(ctx, T, text, x, y, align = "left", base = "middle") {
  ctx.fillStyle = T.text2;
  ctx.textAlign = align;
  ctx.textBaseline = base;
  ctx.fillText(text, x, y);
}

// Plugin que adiciona espaço entre a legenda e o gráfico.
const legendGapPlugin = {
  id: "ctLegendGap",
  beforeInit(ch) {
    if (!ch.legend) return;
    const fit = ch.legend.fit;
    ch.legend.fit = function fitWithGap() {
      fit.call(this);
      this.height += 12;
    };
  },
};

// Plugin que desenha linhas de referência e a guia do cursor.
function refsPlugin(spec, T) {
  return {
    id: "ctRefs",
    beforeDatasetsDraw(ch) {
      const { ctx, chartArea: a } = ch;
      ctx.save();
      for (const r of spec.refs || []) {
        const sc = ch.scales[r.axis];
        if (!sc) continue;
        const p = sc.getPixelForValue(r.value);
        ctx.strokeStyle = r.strong ? T.muted : T.axis;
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (r.axis === "y") { ctx.moveTo(a.left, p); ctx.lineTo(a.right, p); } else { ctx.moveTo(p, a.top); ctx.lineTo(p, a.bottom); }
        ctx.stroke();
        if (r.label) {
          ctx.font = `600 11.5px ${Chart.defaults.font.family}`;
          const w = ctx.measureText(r.label).width + 10;
          ctx.fillStyle = T.surface;
          ctx.fillRect(p + 4, a.top + 2, w, 18);
          ctx.fillStyle = T.text;
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(r.label, p + 9, a.top + 11);
        }
      }
      const act = ch.tooltip && ch.tooltip.getActiveElements();
      if (spec.kind === "line" && act && act.length) {
        const x = act[0].element.x;
        ctx.strokeStyle = T.axis;
        ctx.beginPath(); ctx.moveTo(x, a.top); ctx.lineTo(x, a.bottom); ctx.stroke();
      }
      ctx.restore();
    },
  };
}

// Plugin que escreve valores e notas na ponta das barras e linhas.
function endLabelsPlugin(spec, T) {
  return {
    id: "ctEnd",
    afterDatasetsDraw(ch) {
      if (!spec.end) return;
      const { ctx } = ch, horiz = Boolean(spec.horizontal), f = spec.end_fmt || spec.fmt;
      const visible = spec.datasets.map((_d, j) => j).filter((j) => ch.isDatasetVisible(j) && !spec.datasets[j].role);
      const notes = spec.notes || [];
      ctx.save();
      ctx.font = `500 11.5px ${Chart.defaults.font.family}`;
      // Posiciona o rótulo conforme o tipo e a orientação do gráfico.
      const place = (el, v, text) => {
        if (spec.kind === "line") return label(ctx, T, text, el.x, el.y - 10, "center", "bottom");
        if (horiz) return label(ctx, T, text, el.x + (v < 0 ? -6 : 6), el.y, v < 0 ? "right" : "left");
        return label(ctx, T, text, el.x, el.y - 4, "center", "bottom");
      };
      if (spec.end === "last") {
        for (const j of visible) {
          const meta = ch.getDatasetMeta(j), data = spec.datasets[j].data, i = data.length - 1;
          if (meta.data[i] && data[i] !== null) label(ctx, T, `${spec.datasets[j].label} ${cfmt(f, data[i])}`, meta.data[i].x + 10, meta.data[i].y);
        }
      } else if (spec.end === "value") {
        const one = visible.length === 1;
        for (const j of visible) {
          const meta = ch.getDatasetMeta(j);
          spec.datasets[j].data.forEach((v, i) => {
            if (v === null || !meta.data[i]) return;
            place(meta.data[i], v, cfmt(f, v) + (one && notes[i] ? `  ${notes[i]}` : ""));
          });
        }
      } else {
        spec.labels.forEach((_l, i) => {
          let tip = null, total = 0, sign = 1;
          for (const j of visible) {
            const v = spec.datasets[j].data[i], el = ch.getDatasetMeta(j).data[i];
            if (v === null || v === undefined || !el) continue;
            total += v;
            sign = v < 0 ? -1 : 1;
            const end = horiz ? el.x : -el.y;
            if (!tip || (sign > 0 ? end > tip.end : end < tip.end)) tip = { el, end };
          }
          if (!tip) return;
          const text = spec.end === "total" ? cfmt(f, total) + (notes[i] ? `  ${notes[i]}` : "") : notes[i] || "";
          const cat = ch.scales[horiz ? "y" : "x"].getPixelForValue(i);
          const at = horiz ? { x: tip.el.x, y: cat } : { x: cat, y: tip.el.y };
          if (text && (spec.end !== "total" || total !== 0)) place(at, sign, text);
        });
      }
      ctx.restore();
    },
  };
}

// Carrega e guarda em cache o logo de um time para o canvas.
function logoImage(id, mode, ch) {
  const key = `${id}:${mode}`;
  let img = CT.logos.get(key);
  if (!img) {
    img = new Image();
    img.decoding = "async";
    img.src = `/api/logo/team/${id}?theme=${mode}`;
    img.onerror = () => { img.failed = true; };
    img.waiting = new Set();
    img.onload = () => { img.waiting.forEach((c) => c.canvas && c.draw()); img.waiting.clear(); };
    CT.logos.set(key, img);
  }
  if (!img.complete) img.waiting.add(ch);
  return img;
}

// Plugin que desenha os logos dos times ao lado do eixo Y.
function logosPlugin(spec, T) {
  return {
    id: "ctLogos",
    afterDraw(ch) {
      if (!spec.logos || !spec.horizontal) return;
      const sc = ch.scales.y, { ctx } = ch, size = 18;
      const x = ch.chartArea.left - 8 - size;
      spec.logos.forEach((id, i) => {
        if (!id) return;
        const img = logoImage(id, T.mode, ch);
        if (!img.complete || img.failed || !img.naturalWidth) return;
        const k = size / Math.max(img.naturalWidth, img.naturalHeight);
        const w = img.naturalWidth * k, h = img.naturalHeight * k, y = sc.getPixelForValue(i);
        ctx.drawImage(img, x + (size - w) / 2, y - h / 2, w, h);
      });
    },
  };
}

// Plugin que escreve nomes nos pontos da dispersão, sem sobreposição.
function pointLabelsPlugin(spec, T) {
  return {
    id: "ctPointLabels",
    afterDatasetsDraw(ch) {
      if (spec.kind !== "scatter" || !spec.label_top || !ch.isDatasetVisible(0)) return;
      const { ctx, chartArea: a } = ch, meta = ch.getDatasetMeta(0), placed = [];
      ctx.save();
      ctx.font = `500 11.5px ${Chart.defaults.font.family}`;
      for (let i = 0; i < meta.data.length && placed.length < spec.label_top && i < spec.label_top * 4; i++) {
        const el = meta.data[i], name = spec.datasets[0].data[i].name;
        const w = ctx.measureText(name).width;
        const right = el.x + 7 + w < a.right;
        const box = { x0: (right ? el.x + 6 : el.x - 6 - w) - 3, x1: (right ? el.x + 6 + w : el.x - 6) + 3, y0: el.y - 19, y1: el.y - 1 };
        if (placed.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0)) continue;
        placed.push(box);
        ctx.fillStyle = T.surface + "cc";
        ctx.fillRect(box.x0, el.y - 17, box.x1 - box.x0, 14);
        label(ctx, T, name, right ? box.x0 + 3 : box.x1 - 3, el.y - 10, right ? "left" : "right");
      }
      ctx.restore();
    },
  };
}

// Interpola a cor da escala sequencial para um valor entre 0 e 1.
function heatColor(T, t) {
  const seq = T.seq, p = Math.min(Math.max(t, 0), 1) * (seq.length - 1), i = Math.min(Math.floor(p), seq.length - 2), k = p - i;
  const hex = (h) => [1, 3, 5].map((o) => parseInt(h.slice(o, o + 2), 16));
  const a = hex(seq[i]), b = hex(seq[i + 1]);
  return a.map((c, n) => Math.round(c + (b[n] - c) * k));
}
// Cria o mapa de calor em tabela, com escala de cores e tooltip.
function heatmap(spec, T) {
  const flat = spec.values.flat().filter((v) => v !== null);
  const lo = Math.min(...flat), hi = Math.max(...flat);
  const wrap = document.createElement("div");
  wrap.className = "heat-wrap";
  // Gera a célula colorida do mapa de calor.
  const cell = (v, r, c) => {
    if (v === null) return `<td class="heat-empty" data-tip="${esc(`${r} · ${c}: fora do pool / sem picks`)}"></td>`;
    const rgb = heatColor(T, hi > lo ? (v - lo) / (hi - lo) : 0.5);
    const lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
    return `<td style="background:rgb(${rgb});color:${lum > 0.55 ? "#0b0b0b" : "#f6f6f4"}" data-tip="${esc(`${r} · ${c}: ${cfmt("pct1", v)}`)}">${v > 0 && v < 0.005 ? "&lt;1%" : cfmt(spec.fmt, v)}</td>`;
  };
  const stops = [0, 0.25, 0.5, 0.75, 1].map((s) => `rgb(${heatColor(T, s)}) ${s * 100}%`).join(",");
  wrap.innerHTML = `<div class="heat-scroll"><table class="heat"><thead><tr><th class="l">${esc(spec.row_label || "")}</th>${spec.cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${spec.rows.map((r, i) => `<tr><th class="l">${esc(r)}</th>${spec.values[i].map((v, j) => cell(v, r, spec.cols[j])).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="heat-scale"><span>${cfmt(spec.fmt, lo)}</span><i style="background:linear-gradient(90deg,${stops})"></i><span>${cfmt(spec.fmt, hi)}</span></div>
    <div class="chart-tip" hidden></div>`;
  const tip = $(".chart-tip", wrap);
  wrap.addEventListener("mousemove", (e) => {
    const td = e.target.closest("td[data-tip]");
    if (!td) { tip.hidden = true; return; }
    tip.textContent = td.dataset.tip;
    tip.hidden = false;
    const box = wrap.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX - box.left + 12, box.width - tip.offsetWidth - 4) + "px";
    tip.style.top = e.clientY - box.top + 14 + "px";
  });
  wrap.addEventListener("mouseleave", () => { tip.hidden = true; });
  return wrap;
}

// Converte a especificação do gráfico em uma tabela de dados.
function specTable(spec) {
  if (spec.kind === "scatter") {
    const rows = spec.datasets[0].data.map((p) => ({ name: p.name, x: p.x, y: p.y, note: p.note || "" }));
    const xf = spec.x_fmt || (spec.x.fmt === "pct0" ? "pct1" : spec.x.fmt), yf = spec.y.fmt === "pct0" ? "pct1" : spec.y.fmt;
    return table([{ key: "name", label: "Nome", l: true }, { key: "x", label: esc(spec.x.title), fmt: (v) => cfmt(xf, v) },
      { key: "y", label: esc(spec.y.title), fmt: (v) => cfmt(yf, v) }, { key: "note", label: "Detalhe", l: true }], rows,
      { rank: false, scroll: true, sortKey: "y" });
  }
  if (spec.linear_x) {
    const w = spec.bin_width / 2;
    const rows = spec.datasets[0].data.map((p) => ({ bin: `${CF.hs(p.x - w)} – ${CF.hs(p.x + w)}`, n: p.y }));
    return table([{ key: "bin", label: "Faixa de HS%", l: true }, { key: "n", label: "Jogadores", fmt: CF.int }], rows, { rank: false, scroll: true });
  }
  const sets = spec.datasets.filter((d) => !d.role);
  const rows = spec.labels.map((l, i) => {
    const r = { label: l, note: spec.notes ? spec.notes[i] : "" };
    sets.forEach((d, j) => { r["d" + j] = d.data[i]; });
    if (spec.stacked && sets.length > 1) r.total = sets.reduce((s, d) => s + (d.data[i] || 0), 0);
    return r;
  });
  const cols = [{ key: "label", label: "Item", l: true },
    ...sets.map((d, j) => ({ key: "d" + j, label: esc(d.label), fmt: (v) => cfmt(spec.fmt, v) }))];
  if (spec.stacked && sets.length > 1 && spec.end === "total") cols.push({ key: "total", label: "Total", fmt: (v) => cfmt(spec.fmt, v) });
  if (spec.notes) cols.push({ key: "note", label: "Detalhe", l: true });
  return table(cols, rows, { rank: false, scroll: true });
}

new MutationObserver(() => {
  for (const c of CT.charts) if (!c.canvas || !c.canvas.isConnected) { c.destroy(); CT.charts.delete(c); }
  hydrateCharts(document.getElementById("app") || document);
}).observe(document.getElementById("app"), { childList: true, subtree: true });
