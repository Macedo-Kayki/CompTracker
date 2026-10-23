"use strict";

// Atalho para document.querySelector, com raiz opcional.
const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const NF = new Intl.NumberFormat("pt-BR");
const EMPTY_FILTERS = { tier: "1", year: "", region: "", event_type: "", event_id: "" };
const state = { filters: { ...EMPTY_FILTERS }, meta: null };

// Lê e grava valores em JSON no localStorage, ignorando erros.
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {  } },
};
// Escapa caracteres especiais de HTML de um texto.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Indica se o valor pode ser tratado como número.
const isNum = (v) => v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v));
// Formatadores de números, porcentagens, moedas e datas no padrão pt-BR.
const fmt = {
  int: (v) => (isNum(v) ? NF.format(Math.round(v)) : "—"),
  pct: (v) => (isNum(v) ? (v * 100).toFixed(1).replace(".", ",") + "%" : "—"),
  pct0: (v) => (isNum(v) ? Math.round(v * 100) + "%" : "—"),
  hs: (v) => (isNum(v) ? Number(v).toFixed(1).replace(".", ",") + "%" : "—"),
  n2: (v) => (isNum(v) ? Number(v).toFixed(2).replace(".", ",") : "—"),
  n1: (v) => (isNum(v) ? Number(v).toFixed(1).replace(".", ",") : "—"),
  usd: (v) => (isNum(v) ? "US$ " + NF.format(Math.round(v)) : "—"),
  usdShort: (v) => {
    if (!isNum(v)) return "—";
    if (v >= 1e6) return "US$ " + (v / 1e6).toFixed(2).replace(".", ",") + " mi";
    if (v >= 1e4) return "US$ " + Math.round(v / 1e3) + " mil";
    return "US$ " + NF.format(Math.round(v));
  },
  date: (v) => (v ? new Date(v).toLocaleDateString("pt-BR", { timeZone: "UTC" }) : "—"),
  compact: (v) => {
    if (!isNum(v)) return "—";
    if (v >= 1e6) return (v / 1e6).toFixed(1).replace(".", ",") + " mi";
    if (v >= 1e4) return (v / 1e3).toFixed(1).replace(".", ",") + " mil";
    return NF.format(v);
  },
};
// Retorna o tema atual (claro ou escuro), salvo ou do sistema.
const theme = () => document.documentElement.dataset.theme ||
  (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");

// Monta a query string com os filtros globais e parâmetros extras.
function qs(extra = {}, withFilters = true) {
  const p = new URLSearchParams();
  const all = withFilters ? { ...state.filters, ...extra } : extra;
  for (const [k, v] of Object.entries(all)) if (v !== "" && v !== null && v !== undefined) p.set(k, v);
  return p.toString();
}
// Faz uma requisição GET à API com os filtros e retorna o JSON.
async function api(path, extra = {}) {
  const r = await fetch(`/api/${path}?${qs(extra)}`);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {  }
    throw new Error(msg);
  }
  return r.json();
}
// Gera o HTML de um card com título, dica e conteúdo.
const card = (title, body, hint = "") => `<div class="card">${title ? `<h2>${title}</h2>` : ""}${hint ? `<p class="hint">${hint}</p>` : ""}${body}</div>`;
// Gera o HTML de um indicador (KPI) com rótulo, valor e subtítulo.
const kpi = (label, value, sub = "", hero = false, cls = "") => `<div class="kpi${hero ? " hero" : ""}${cls ? ` ${cls}` : ""}"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;

// Gera a imagem do logo do time ou um selo com as iniciais.
const teamLogo = (id, name, size = "", onTheme = null) => (id
  ? `<img class="tlogo ${size}" src="/api/logo/team/${id}?theme=${onTheme || theme()}" alt="" loading="lazy" data-n="${esc(name || "")}" onerror="logoFail(this)">`
  : `<span class="tlogo tlogo-empty ${size}">${esc(initials(name))}</span>`);
// Extrai até duas iniciais de um nome.
const initials = (name) => String(name || "?").replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
// Troca um logo que falhou ao carregar pelo selo com as iniciais.
window.logoFail = (img) => {
  const span = document.createElement("span");
  span.className = `${img.className} tlogo-empty`;
  span.textContent = initials(img.dataset.n);
  img.replaceWith(span);
};

// Retorna o país de um time a partir dos metadados.
const teamCountry = (id) => ((state.meta && state.meta.team_countries) || {})[id] || "";
// Gera o nome do time acompanhado do país.
const teamText = (id, name) => {
  const c = teamCountry(id);
  return `<span class="team-txt"><span class="team-nm">${esc(name ?? id)}</span>${c ? `<small class="team-ct">${esc(c)}</small>` : ""}</span>`;
};
// Gera o link para a página do time, com logo e nome.
const teamLink = (id, name) => (id
  ? `<a class="team" href="#/time/${id}">${teamLogo(id, name)}${teamText(id, name)}</a>`
  : (name ? `<span class="team">${teamLogo(null, name)}${teamText(null, name)}</span>` : "—"));
// Gera o link para a página do jogador.
const playerLink = (id, name) => (id ? `<a href="#/jogador/${id}">${esc(name ?? id)}</a>` : esc(name ?? "—"));
const AGENT_NAMES = { kayo: "KAY/O" };
// Formata o nome de um agente para exibição.
const agentName = (a) => (a ? AGENT_NAMES[a] || a.charAt(0).toUpperCase() + a.slice(1) : "—");
// Gera a célula colorida de lado (Ataque ou Defesa).
const sideCell = (s) => (s === "Ataque" ? `<span class="side-atk">Ataque</span>` : s === "Defesa" ? `<span class="side-def">Defesa</span>` : "—");

// Cria uma tabela ordenável a partir de colunas e linhas.
function table(columns, rows, { id = "t" + Math.random().toString(36).slice(2), rank = true, sortKey = null, desc = true, scroll = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = scroll ? "table-wrap scroll" : "table-wrap";
  let key = sortKey, dir = desc ? -1 : 1;
  // Desenha a tabela na ordem atual e liga a ordenação nos cabeçalhos.
  const render = () => {
    const data = key ? [...rows].sort((a, b) => {
      const va = a[key], vb = b[key];
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir;
    }) : rows;
    wrap.innerHTML = `<table class="data" id="${id}"><thead><tr>${rank ? '<th class="l rank">#</th>' : ""}${columns.map((c) =>
      `<th class="${c.l ? "l" : ""} ${c.key === key ? "sorted" + (dir > 0 ? " asc" : "") : ""}" data-k="${c.key}" title="${esc(c.title || "")}">${c.label}</th>`).join("")}</tr></thead>
      <tbody>${data.length ? data.map((r, i) => `<tr>${rank ? `<td class="l rank${i < 3 ? ` r${i + 1}` : ""}">${i + 1}</td>` : ""}${columns.map((c) =>
        `<td class="${c.l ? "l" : ""}${c.key === key ? " sorted-col" : ""}">${c.html ? c.html(r) : (c.fmt || esc)(r[c.key])}</td>`).join("")}</tr>`).join("")
        : `<tr><td colspan="${columns.length + 1}" class="empty">Sem dados para o filtro atual</td></tr>`}</tbody></table>`;
    wrap.querySelectorAll("th[data-k]").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.k;
      if (k === key) dir = -dir; else { key = k; dir = -1; }
      render();
    }));
  };
  render();
  return wrap;
}
const filtersBar = $("#filters");

// Renderiza o HTML da página e reposiciona a barra de filtros.
function mount(html) {
  document.body.append(filtersBar);
  app.innerHTML = html;
  const head = $(".page-head", app);
  if (head) head.after(filtersBar); else app.prepend(filtersBar);
}
// Gera o cabeçalho padrão da página com sobretítulo, título e subtítulo.
const hero = (eyebrow, title, sub, side = "") => `<div class="page-head"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${sub ? `<p>${sub}</p>` : ""}</div>${side}</div>`;
// Gera a etiqueta do tier (T1, T2, T3).
const tierTag = (t) => (t ? `<span class="tier-tag t${t}">T${t}</span>` : "—");

// Retorna a cor associada ao tipo de evento no tema atual.
const evColor = (type) => ((state.meta && state.meta.event_colors[theme()]) || {})[type] || "var(--muted)";
// Gera o selo colorido do tipo de evento.
const evBadge = (type) => (type ? `<span class="ev-badge" style="--ev:${evColor(type)}">${esc(type)}</span>` : "—");
// Gera o nome do evento colorido, com link para os detalhes quando houver id.
const evName = (name, type, id = null) => (id
  ? `<a class="ev-name ev-link" href="#" data-event="${id}" style="--ev:${evColor(type)}" title="${esc(type || "")} · ver detalhes">${esc(name ?? "—")}</a>`
  : `<span class="ev-name" style="--ev:${evColor(type)}" title="${esc(type || "")}">${esc(name ?? "—")}</span>`);
const EV_DESC = {
  Champions: "Mundial do ano, o título mais importante", Masters: "Torneios internacionais da temporada",
  Liga: "Ligas do VCT (Stages e VCT CN)", "Qualificatória": "Last Chance Qualifiers e promoções",
  Ascension: "Acesso do Tier 2 para as ligas", Kickoff: "Abertura da temporada do VCT",
  Challengers: "Circuito regional (Tier 1 em 2021–22, Tier 2 a partir de 2023)", Outros: "Torneios independentes (Tier 3) e outros circuitos, como Oceania Tour e Strike Arabia",
};
// Substitui o conteúdo de um elemento por um nó.
function put(sel, node) { const el = $(sel); if (!el) return; el.innerHTML = ""; el.append(node); }
// Exibe a página de erro com a mensagem recebida.
function fail(err) { mount(hero("Erro", "Não foi possível carregar", "") + `<div class="error">${esc(err.message)}</div>`); }

const COUNT_METRICS = new Set(["kills", "clutches", "aces", "k4", "k3", "k2", "assists", "fk"]);
// Define o mínimo automático de mapas conforme o filtro atual.
function autoMinMaps() {
  const f = state.filters;
  return f.event_id ? 1 : f.event_type ? 5 : f.year ? 20 : 40;
}
// Retorna o mínimo de mapas efetivo (informado ou automático).
const effMinMaps = (raw, metric = null) => (raw === "" || raw === null || raw === undefined
  ? (metric && COUNT_METRICS.has(metric) ? 1 : autoMinMaps()) : Number(raw));

const PLAYER_COLS = [
  { key: "player_name", label: "Jogador", l: true, html: (r) => playerLink(r.player_id, r.player_name) },
  { key: "team_name", label: "Time", l: true, html: (r) => teamLink(r.team_id, r.team_name) },
  { key: "maps", label: "Mapas", fmt: fmt.int },
  { key: "rating", label: "Rating", fmt: fmt.n2 },
  { key: "acs", label: "ACS", fmt: fmt.n1 },
  { key: "kd", label: "K/D", fmt: fmt.n2 },
  { key: "adr", label: "ADR", fmt: fmt.n1 },
  { key: "kast", label: "KAST", fmt: fmt.hs },
  { key: "hs", label: "HS%", fmt: fmt.hs, title: "Taxa de headshot ponderada pelas kills" },
  { key: "k", label: "Kills", fmt: fmt.int },
  { key: "fk", label: "FK", fmt: fmt.int, title: "First kills" },
  { key: "clutches", label: "Clutches", fmt: fmt.int },
  { key: "k5", label: "Aces", fmt: fmt.int },
  { key: "k4", label: "4K", fmt: fmt.int },
  { key: "k3", label: "3K", fmt: fmt.int },
  { key: "k2", label: "2K", fmt: fmt.int },
];
const TEAM_COLS = [
  { key: "team_name", label: "Time", l: true, html: (r) => teamLink(r.team_id, r.team_name) },
  { key: "team_region", label: "Região", l: true },
  { key: "matches", label: "Séries", fmt: fmt.int },
  { key: "match_wr", label: "WR séries", fmt: fmt.pct },
  { key: "maps", label: "Mapas", fmt: fmt.int },
  { key: "map_wr", label: "WR mapas", fmt: fmt.pct },
  { key: "round_wr", label: "WR rounds", fmt: fmt.pct },
  { key: "atk_wr", label: "Ataque", fmt: fmt.pct, title: "% dos rounds de ataque vencidos" },
  { key: "def_wr", label: "Defesa", fmt: fmt.pct, title: "% dos rounds de defesa vencidos" },
  { key: "best_side", label: "Melhor lado", l: true, html: (r) => sideCell(r.best_side) },
  { key: "pistol_wr", label: "Pistols", fmt: fmt.pct },
  { key: "titles", label: "Títulos", fmt: fmt.int },
  { key: "intl_titles", label: "Internac.", fmt: fmt.int, title: "Masters + Champions" },
];
const MATCH_COLS = [
  { key: "match_date", label: "Data", l: true, fmt: fmt.date },
  { key: "tier", label: "Tier", l: true, html: (r) => tierTag(r.tier) },
  { key: "event_name", label: "Evento", l: true, html: (r) => evName(r.event_name, r.event_type, r.event_id) },
  { key: "round_label", label: "Fase", l: true },
  { key: "team1_name", label: "Time 1", l: true, html: (r) => `<span class="${r.winner_id === r.team1_id ? "win" : ""}">${teamLink(r.team1_id, r.team1_name)}</span>` },
  { key: "score", label: "Placar", html: (r) => `${r.team1_score ?? "-"} : ${r.team2_score ?? "-"}` },
  { key: "team2_name", label: "Time 2", l: true, html: (r) => `<span class="${r.winner_id === r.team2_id ? "win" : ""}">${teamLink(r.team2_id, r.team2_name)}</span>` },
];

// Monta a página Visão geral com KPIs, gráficos e destaques.
async function pageOverview() {
  const ovMin = autoMinMaps();
  mount(`<header class="page-head team-hero overview-hero">
      <div class="th-visual"><img class="tv-photo" src="/static/img/banners/allcamps.jpg?v=${(state.meta && state.meta.banner_version) || 0}" fetchpriority="high" decoding="async" alt="Arena de VALORANT lotada, com o troféu no palco e as bandeiras dos times" onerror="this.closest('.overview-hero').classList.add('no-photo');this.remove()"></div>
      <div class="th-shade"></div>
      <div class="th-content">
        <div class="eyebrow">VALORANT · cenário competitivo masculino</div>
        <h1 class="th-name"><span>Visão geral do cenário</span></h1>
        <p class="ov-sub">Tier 1 (VCT), Tier 2 (Challengers e Ascension) e Tier 3, de 2021 a 20/10/2026 · fonte: VLR.gg</p>
      </div>
    </header>
    <div class="kpis" id="kpis"></div>
    <div class="grid cols-2">
      ${card("", chart("side_by_year", {}, "Lado que mais vence por ano"))}
      ${card("", chart("matches_by_tier", { tier: "" }, "Partidas por ano e tier"))}
      ${card("", chart("win_types", {}, "Tipos de vitória de round"))}
      ${card("", chart("map_side_bias", {}, "Lado favorecido por mapa"))}
    </div>
    <h3 class="section-title">Destaques do filtro atual</h3>
    <div class="grid cols-2">
      ${card(`Melhores times (WR de mapas, ${ovMin}+ mapas)`, '<div id="ov-teams"></div>')}
      ${card(`Melhores jogadores (rating, ${ovMin}+ mapas)`, '<div id="ov-players"></div>')}
    </div>
    <div class="grid cols-2 mt">
      ${card("", chart("titles_top", { limit: 12 }, "Times com mais títulos"))}
      ${card("Campeões mais recentes", '<div id="ov-titles"></div>')}
    </div>`);
  const [ov, teams, players, titles] = await Promise.all([
    api("overview"), api("teams", { min_maps: ovMin, limit: 10 }), api("players", { min_maps: ovMin, limit: 10 }), api("titles"),
  ]);
  const s = ov.sides;
  $("#kpis").innerHTML = [
    `<div class="kpi hero"><div class="label">Lado que mais vence</div><div class="value">${s.atk_wr >= 0.5 ? "Ataque" : "Defesa"} ${fmt.pct(Math.max(s.atk_wr, 1 - s.atk_wr))}</div>
      <div class="side-meter"><div class="atk" style="flex:${s.atk_rounds}"></div><div class="def" style="flex:${s.def_rounds}"></div></div>
      <div class="legend-inline"><span><i class="dot" style="background:var(--atk)"></i>Ataque ${fmt.compact(s.atk_rounds)}</span><span><i class="dot" style="background:var(--def)"></i>Defesa ${fmt.compact(s.def_rounds)}</span></div></div>`,
    kpi("Eventos", fmt.int(ov.events), `${fmt.usd(ov.prize_usd)} distribuídos`),
    kpi("Partidas", fmt.int(ov.matches), `${fmt.int(ov.maps)} mapas`),
    kpi("Rounds", fmt.compact(ov.rounds)),
    kpi("Times / jogadores", `${fmt.int(ov.teams)} / ${fmt.int(ov.players)}`),
    kpi("Kills", fmt.compact(ov.kills)),
    kpi("Aces", fmt.int(ov.aces), `${fmt.int(ov.clutches)} clutches`),
  ].join("");
  put("#ov-teams", table(TEAM_COLS.filter((c) => ["team_name", "maps", "map_wr", "atk_wr", "def_wr", "titles"].includes(c.key)), teams));
  put("#ov-players", table(PLAYER_COLS.filter((c) => ["player_name", "team_name", "maps", "rating", "acs", "hs", "clutches"].includes(c.key)), players));
  put("#ov-titles", table([
    { key: "tier", label: "Tier", l: true, html: (r) => tierTag(r.tier) },
    { key: "name", label: "Evento", l: true, html: (r) => evName(r.name, r.event_type, r.event_id) },
    { key: "champion_name", label: "Campeão", l: true, html: (r) => teamLink(r.champion_id, r.champion_name) },
    { key: "runner_up_name", label: "Vice", l: true, html: (r) => teamLink(r.runner_up_id, r.runner_up_name) },
  ], titles.slice(0, 12), { rank: false }));
}

// Monta a página Times com gráficos e ranking filtrável.
async function pageTeams() {
  const saved = store.get("teams-opts2", { team_region: "", min_maps: "" });
  const opts = { team_region: saved.team_region, min_maps: effMinMaps(saved.min_maps) };
  mount(`<div class="page-head"><div><div class="eyebrow">Ranking</div><h1>Times</h1><p>Win rate de séries, mapas e rounds, força por lado, pistols e títulos</p></div>
    <div class="filters-local">
      <div class="field"><label>Região do time</label><select id="t-region"><option value="">Todas</option>${["Americas", "EMEA", "Pacific", "China", "Outros"].map((r) => `<option ${opts.team_region === r ? "selected" : ""}>${r}</option>`).join("")}</select></div>
      <div class="field"><label>Mín. de mapas</label><input id="t-min" type="number" min="0" value="${saved.min_maps}" placeholder="auto: ${opts.min_maps}" title="Vazio = automático pelo filtro atual"></div>
    </div></div>
    <div class="grid cols-2">
      ${card("", chart("team_winrate", opts, "Win rate de mapas"))}
      ${card("", chart("team_sides", opts, "Ataque x defesa"))}
    </div>
    <div class="mt">${card("Ranking de times", '<div id="t-table"></div>', `Mínimo de ${opts.min_maps} mapas · clique no cabeçalho para ordenar · clique no time para ver detalhes`)}</div>`);
  const upd = () => { store.set("teams-opts2", { team_region: $("#t-region").value, min_maps: $("#t-min").value }); pageTeams(); };
  $("#t-region").onchange = upd; $("#t-min").onchange = upd;
  const rows = await api("teams", { ...opts, limit: 1000 });
  put("#t-table", table(TEAM_COLS, rows, { sortKey: "map_wr", scroll: true }));
}

// Monta a página de detalhes de um time.
async function pageTeam(id) {
  mount(`<div class="empty">Carregando time…</div>`);
  const [d, featured] = await Promise.all([api(`teams/${id}`), api(`teams/${id}/featured-title`).catch(() => ({}))]);
  const s = d.summary, t = d.team;
  const country = teamCountry(id);
  const plainHead = hero(`Time · ${esc(t.team_region)}`, `<span class="hero-team">${teamLogo(id, t.team_name, "xl", "dark")}${esc(t.team_name)}</span>`,
    `${country ? `${esc(country)} · ` : ""}Ativo de ${t.first_year} a ${t.last_year} · números do filtro atual`,
    `<a class="btn" href="#/confronto?a=${id}">Confronto direto</a>`);
  mount(`${featured && featured.event_id ? teamHero(id, t, featured) : plainHead}
    <div class="kpis">
      ${kpi("Títulos", fmt.int(d.titles.length), `${d.finals_lost.length} vice-campeonatos`, true)}
      ${kpi("Séries", fmt.int(s.matches), `WR ${fmt.pct(s.match_wr)}`)}
      ${kpi("Mapas", fmt.int(s.maps), `WR ${fmt.pct(s.map_wr)}`)}
      ${kpi("Rounds de ataque", fmt.pct(s.atk_wr), `${fmt.int(s.atk_won)} de ${fmt.int(s.atk_played)}`)}
      ${kpi("Rounds de defesa", fmt.pct(s.def_wr), `${fmt.int(s.def_won)} de ${fmt.int(s.def_played)}`)}
      ${kpi("Melhor lado", s.atk_wr > s.def_wr ? "Ataque" : "Defesa")}
      ${kpi("Pistols", fmt.pct(s.pistol_wr), `${fmt.int(s.pistols_won)} vencidos`)}
      ${kpi("Prêmios conquistados", fmt.usdShort(s.prize_won_usd), `${fmt.usd(s.prize_won_usd)} · ${fmt.int(s.prize_events)} eventos`, false, "wide")}
    </div>
    <div class="grid cols-2">
      ${card("", chart("team_year", { team_id: id }, "Desempenho por ano"))}
      ${card("", chart("team_maps", { team_id: id }, "Ataque e defesa por mapa"))}
      ${card("", chart("team_players", { team_id: id, min_maps: 5 }, "Melhores jogadores"))}
      ${card("", chart("player_clutches", { team_id: id, limit: 10 }, "Clutches do time"))}
    </div>
    <div class="mt">${card("Jogadores do time", '<div id="tm-players"></div>', "Estatísticas apenas dos mapas jogados por este time")}</div>
    <div class="grid cols-2 mt">
      ${card("Títulos", '<div id="tm-titles"></div>')}
      ${card("Partidas recentes", '<div id="tm-recent"></div>')}
    </div>
    <div class="mt">${card("", chart("player_multikills", { team_id: id, limit: 10, wide: 1 }, "Multikills do time"))}</div>`);
  put("#tm-players", table(PLAYER_COLS.filter((c) => c.key !== "team_name"), d.players, { sortKey: "rating" }));
  put("#tm-titles", table([
    { key: "tier", label: "Tier", l: true, html: (r) => tierTag(r.tier) },
    { key: "name", label: "Evento", l: true, html: (r) => evName(r.name, r.event_type, r.event_id) }, { key: "year", label: "Ano" },
    { key: "event_type", label: "Tipo", l: true, html: (r) => evBadge(r.event_type) },
    { key: "champion_prize_usd", label: "Prêmio do time", fmt: fmt.usd, title: "Quanto o time recebeu pelo título" },
    { key: "prize_usd", label: "Premiação total", fmt: fmt.usd, title: "Total distribuído entre todos os times do evento" },
  ], d.titles, { rank: false }));
  put("#tm-recent", table(MATCH_COLS.filter((c) => c.key !== "event_name"), d.recent, { rank: false }));
}

// Monta o banner da página Jogadores com os líderes de cada gráfico.
function playersHero(leaders, filtersHtml) {
  const intro = `<div><div class="eyebrow">Ranking · líderes</div><h1>Jogadores</h1><p>Rating, ACS, kills, HS%, clutches, aces, quadras, triples e double kills</p></div>`;
  if (!leaders || !leaders.length) return `<div class="page-head">${intro}${filtersHtml}</div>`;
  const n = leaders.length, slant = n > 1 ? 7 : 0;
  const top = (k) => (k <= 0 ? 0 : k >= n ? 100 : (k / n) * 100 + slant / 2);
  const bot = (k) => (k <= 0 ? 0 : k >= n ? 100 : (k / n) * 100 - slant / 2);
  const pct = (v) => `${v.toFixed(3)}%`;
  const slices = leaders.map((p, k) => {
    const l1 = top(k), r1 = top(k + 1), l2 = bot(k), r2 = bot(k + 1);
    const box = `left:${pct(Math.min(l1, l2))};width:${pct(Math.max(r1, r2) - Math.min(l1, l2))}`;
    const clip = `clip-path:polygon(${pct(l1)} 0,${pct(r1)} 0,${pct(r2)} 100%,${pct(l2)} 100%)`;
    const pos = p.focus ? `object-position:${p.focus[0]}% ${Math.max(0, p.focus[1] - 8)}%" data-fx="${p.focus[0]}" data-fy="${p.focus[1]}` : "";
    const visual = p.photo_url
      ? `<img class="mh-photo" src="${esc(p.photo_url)}" style="${box};${pos}" alt="${esc(p.player_name)}" ${k === 0 ? 'fetchpriority="high"' : 'loading="lazy"'} decoding="async">`
      : `<div class="mh-nophoto" style="${box}">${teamLogo(p.team_id, p.team_name, "hero", "dark")}</div>`;
    return `<div class="mh-slice" style="${clip}" data-g="${[l1, r1, l2, r2].map((v) => v.toFixed(3)).join(",")}">${visual}</div>`;
  }).join("");
  const cuts = leaders.slice(1).map((_p, i) => `<div class="mh-cut" style="--t:${pct(top(i + 1))};--b:${pct(bot(i + 1))}"></div>`).join("");
  const caps = leaders.map((p, k) => {
    const at = (y) => ((top(k) + top(k + 1)) / 2) * (1 - y) + ((bot(k) + bot(k + 1)) / 2) * y;
    const center = at(0.86);
    return `<a class="mh-cap" href="#/jogador/${p.player_id}" data-k="${k}" style="left:${pct(center)};width:${pct(100 / n - slant)}">
      <span class="mh-leads">${p.leads.map((l) => `<span><small>${esc(l.title)}</small><b>${esc(l.value)}</b></span>`).join("")}</span>
      <strong>${esc(p.player_name)}</strong>
      ${p.team_name ? `<span class="mh-team">${teamLogo(p.team_id, p.team_name, "", "dark")}${esc(p.team_name)}</span>` : ""}
    </a>`;
  }).join("");
  return `<header class="page-head team-hero multi-hero">
    <div class="th-visual">${slices}${cuts}</div>
    <div class="th-shade"></div>
    <div class="mh-content"><div class="mh-top">${intro}${filtersHtml}</div><div class="mh-caps">${caps}</div></div>
    ${leaders.some((p) => p.photo_url) ? `<div class="tb-credit">Fotos: ${esc([...new Set(leaders.filter((p) => p.photo_url).map((p) => (p.photo_source === "flickr" ? "Riot Games (Flickr)" : "Liquipedia")))].join(" e "))}</div>` : ""}
  </header>`;
}

// Alinha fotos, logos e legendas às fatias inclinadas do banner de líderes.
function alignLeaders(root = document) {
  const hero = $(".multi-hero", root);
  if (!hero) return;
  const hr = hero.getBoundingClientRect(), W = hr.width, H = hr.height;
  const slices = [...hero.querySelectorAll(".mh-slice")];
  // Calcula as bordas esquerda e direita de uma fatia em dada altura.
  const span = (k, t) => {
    const [l1, r1, l2, r2] = slices[k].dataset.g.split(",").map(Number);
    return [(l1 + (l2 - l1) * t) / 100 * W, (r1 + (r2 - r1) * t) / 100 * W];
  };
  slices.forEach((slice, k) => {
    const img = $(".mh-photo", slice);
    if (img && img.dataset.fx) {
      // Posiciona a foto para centralizar o rosto do jogador na fatia.
      const place = () => {
        const cw = img.clientWidth, ch = img.clientHeight, iw = img.naturalWidth, ih = img.naturalHeight;
        if (!cw || !iw) return;
        const scale = Math.max(cw / iw, ch / ih), rw = iw * scale, rh = ih * scale;
        const y = Math.min(0, Math.max(ch - rh, ch * 0.3 - (Number(img.dataset.fy) / 100) * rh));
        const faceT = (y + (Number(img.dataset.fy) / 100) * rh) / H;
        const [a, b] = span(k, Math.min(1, Math.max(0, faceT)));
        const target = (a + b) / 2 - img.offsetLeft;
        const x = Math.min(0, Math.max(cw - rw, target - (Number(img.dataset.fx) / 100) * rw));
        img.style.objectPosition = `${x.toFixed(1)}px ${y.toFixed(1)}px`;
      };
      if (img.complete) place(); else img.addEventListener("load", place, { once: true });
    }
    const piece = $(".mh-nophoto .tlogo", slice);
    if (piece) {
      const box = piece.closest(".mh-nophoto");
      piece.style.transform = "";
      const pr = piece.getBoundingClientRect();
      const [a, b] = span(k, (pr.top + pr.height / 2 - hr.top) / H);
      const dx = (a + b) / 2 - (pr.left - hr.left + pr.width / 2);
      piece.style.transform = `translateX(${dx.toFixed(1)}px)`;
      if (box) box.style.overflow = "hidden";
    }
  });
  hero.querySelectorAll(".mh-cap[data-k]").forEach((cap) => {
    const parent = cap.offsetParent.getBoundingClientRect();
    const cr = cap.getBoundingClientRect();
    const [a, b] = span(Number(cap.dataset.k), (cr.top + cr.height / 2 - hr.top) / H);
    cap.style.left = `${((a + b) / 2 - (parent.left - hr.left)).toFixed(1)}px`;
    cap.style.width = `${Math.max(80, b - a - 16).toFixed(1)}px`;
  });
  fitNames(hero);
}

// Reduz a fonte dos nomes do banner até caberem na largura.
function fitNames(root = document) {
  root.querySelectorAll(".mh-cap strong").forEach((el) => {
    el.style.fontSize = "";
    const max = el.parentElement.clientWidth - 12;
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollWidth > max && size > 11) {
      size -= 1;
      el.style.fontSize = `${size}px`;
    }
  });
}
window.addEventListener("resize", () => alignLeaders());

// Monta a página Jogadores com líderes, gráficos e rankings.
async function pagePlayers() {
  const metrics = await api("players/metrics");
  const saved = store.get("players-opts2", { metric: "rating", min_maps: "", team_region: "" });
  const opts = { metric: saved.metric, team_region: saved.team_region, min_maps: effMinMaps(saved.min_maps, saved.metric) };
  const rateMin = effMinMaps(saved.min_maps), countMin = effMinMaps(saved.min_maps, "kills");
  const leaders = await api("players/featured", { metric: opts.metric, min_maps: opts.min_maps, count_min: countMin, rate_min: rateMin,
    team_region: opts.team_region }).catch(() => []);
  mount(`${playersHero(leaders, `
    <div class="filters-local">
      <div class="field"><label>Métrica</label><select id="p-metric">${Object.entries(metrics).map(([k, v]) => `<option value="${k}" ${opts.metric === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="field"><label>Região do time</label><select id="p-region"><option value="">Todas</option>${["Americas", "EMEA", "Pacific", "China", "Outros"].map((r) => `<option ${opts.team_region === r ? "selected" : ""}>${r}</option>`).join("")}</select></div>
      <div class="field"><label>Mín. de mapas</label><input id="p-min" type="number" min="0" value="${saved.min_maps}" placeholder="auto: ${opts.min_maps}" title="Vazio = automático: sem mínimo para contagens (aces, kills, clutches…), ${rateMin} mapas para taxas"></div>
    </div>`)}
    <div class="grid cols-2">
      ${card("", chart("player_top", opts, "Ranking de jogadores"))}
      ${card("", chart("player_clutches", { min_maps: countMin, team_region: opts.team_region }, "Clutches"))}
      ${card("", chart("player_multikills", { min_maps: countMin, team_region: opts.team_region }, "Multikills"))}
      <div class="grid">
        ${card("", chart("hs_distribution", { min_maps: rateMin, team_region: opts.team_region }, "Distribuição de HS%"))}
        ${card("", chart("rating_vs_hs", { min_maps: rateMin, team_region: opts.team_region }, "Rating x HS%"))}
      </div>
    </div>
    <div class="mt">${card("Ranking completo", '<div id="p-table"></div>', `Top 300 pela métrica escolhida · mínimo de ${opts.min_maps} mapas · ordene por qualquer coluna`)}</div>
    <div class="mt">${card("Maiores performances em um único mapa", '<div id="p-top"></div>')}</div>`);
  alignLeaders();
  if (document.fonts) document.fonts.ready.then(() => alignLeaders());
  const upd = () => { store.set("players-opts2", { metric: $("#p-metric").value, min_maps: $("#p-min").value, team_region: $("#p-region").value }); pagePlayers(); };
  ["#p-metric", "#p-region", "#p-min"].forEach((s) => ($(s).onchange = upd));
  const [rows, top] = await Promise.all([api("players", { ...opts, limit: 300 }), api("top-performances", { metric: "k", limit: 25 })]);
  const metricCol = { kills: "k", aces: "k5", assists: "a" }[opts.metric] || opts.metric;
  put("#p-table", table(PLAYER_COLS, rows, { sortKey: PLAYER_COLS.some((c) => c.key === metricCol) ? metricCol : "rating", scroll: true }));
  put("#p-top", table([
    { key: "player_name", label: "Jogador", l: true, html: (r) => playerLink(r.player_id, r.player_name) },
    { key: "team_name", label: "Time", l: true, html: (r) => teamLink(r.team_id, r.team_name) },
    { key: "opp_name", label: "Adversário", l: true, html: (r) => teamLink(r.opp_id, r.opp_name) },
    { key: "map_name", label: "Mapa", l: true },
    { key: "agent", label: "Agente", l: true, html: (r) => esc(agentName(r.agent)) },
    { key: "k", label: "K", fmt: fmt.int }, { key: "d", label: "D", fmt: fmt.int }, { key: "a", label: "A", fmt: fmt.int },
    { key: "acs", label: "ACS", fmt: fmt.int }, { key: "rating", label: "Rating", fmt: fmt.n2 },
    { key: "rounds", label: "Rounds", fmt: fmt.int },
    { key: "event_name", label: "Evento", l: true, html: (r) => evName(r.event_name, r.event_type, r.event_id) }, { key: "match_date", label: "Data", l: true, fmt: fmt.date },
  ], top, { sortKey: "k" }));
}

// Monta a página de detalhes de um jogador.
async function pagePlayer(id) {
  mount(`<div class="empty">Carregando jogador…</div>`);
  const [d, heroInfo] = await Promise.all([api(`players/${id}`), api(`players/${id}/hero`).catch(() => ({}))]);
  const s = d.summary, p = d.player;
  const plainHead = hero(`Jogador · ${esc(p.country || "")}`, esc(p.player_name), `Time atual: ${teamLink(p.current_team_id, p.current_team_name)} · números do filtro atual`);
  mount(`${heroInfo && heroInfo.photo_url ? playerHero(id, p, heroInfo) : plainHead}
    <div class="kpis">
      ${kpi("Rating", fmt.n2(s.rating), `${fmt.int(s.maps)} mapas · ${fmt.int(s.rounds)} rounds`, true)}
      ${kpi("ACS", fmt.n1(s.acs))}
      ${kpi("K / D / A", `${fmt.int(s.k)} / ${fmt.int(s.d)} / ${fmt.int(s.a)}`, `K/D ${fmt.n2(s.kd)}`, false, "wide")}
      ${kpi("HS%", fmt.hs(s.hs))}
      ${kpi("Clutches", fmt.int(s.clutches), `1v1 ${fmt.int(s.c1v1)} · 1v2 ${fmt.int(s.c1v2)} · 1v3+ ${fmt.int((s.c1v3 || 0) + (s.c1v4 || 0) + (s.c1v5 || 0))}`)}
      ${kpi("Aces / 4K", `${fmt.int(s.k5)} / ${fmt.int(s.k4)}`, `3K ${fmt.int(s.k3)} · 2K ${fmt.int(s.k2)}`)}
      ${kpi("First kills", fmt.int(s.fk), `saldo ${s.fk_diff >= 0 ? "+" : ""}${fmt.int(s.fk_diff)}`)}
    </div>
    <div class="grid cols-2">
      ${card("", chart("player_year", { player_id: id }, "Rating por ano"))}
      ${card("", chart("player_agents", { player_id: id }, "Agentes"))}
    </div>
    <div class="grid cols-2 mt">
      ${card("Por ano", '<div id="pl-year"></div>')}
      ${card("Por time", '<div id="pl-team"></div>')}
    </div>
    <div class="mt">${card("Melhores mapas · MVP", '<div id="pl-best"></div>', `<span class="mvp-tag">MVP</span> maior rating entre os 10 jogadores do mapa · <span class="mvp-tag team">MVP time</span> maior rating do time dele · do mais recente para o mais antigo, seguindo os filtros · clique para ver a partida`)}</div>`);
  const yearCols = [{ key: "year", label: "Ano", l: true }, ...PLAYER_COLS.filter((c) => !["player_name", "team_name"].includes(c.key))];
  put("#pl-year", table(yearCols, d.by_year, { rank: false }));
  put("#pl-team", table([{ key: "team_name", label: "Time", l: true, html: (r) => teamLink(r.team_id, r.team_name) },
    ...PLAYER_COLS.filter((c) => ["maps", "rating", "acs", "kd", "hs", "clutches", "k5"].includes(c.key))], d.by_team, { rank: false }));
  matchList($("#pl-best"), (offset, limit) => api(`players/${id}/mvp-maps`, { offset, limit }));
}

// Monta o banner da página Mapas com o mapa e o agente mais jogados.
function mapAgentHero(fe) {
  if (!fe || !fe.map) return hero("Meta", "Mapas &amp; agentes", "Lado favorecido, map pool e meta de agentes ao longo do tempo");
  const m = fe.map, a = fe.agent;
  const asset = (kind, name, field) => `/api/asset/${kind}/${encodeURIComponent(name)}/${field}`;
  const cols = (a.colors || []).slice(0, 3).map((c) => "#" + c.slice(0, 6));
  const grad = cols.length ? `style="--ag1:${cols[0]};--ag2:${cols[1] || cols[0]};--ag3:${cols[2] || cols[0]}"` : "";
  return `<header class="page-head team-hero duo-hero">
    <div class="th-visual">
      <div class="duo-map"><img class="tv-photo" src="${asset("map", m.name, "splash")}" fetchpriority="high" decoding="async" alt="Mapa ${esc(m.name)}"></div>
      <div class="duo-agent" ${grad}>
        <img class="duo-agent-bg" src="${asset("agent", a.name, "background")}" alt="" aria-hidden="true" onerror="this.remove()">
        <img class="duo-agent-art" src="${asset("agent", a.name, "fullPortrait")}" decoding="async" alt="Agente ${esc(a.display_name)}">
      </div>
      <div class="duo-cut" aria-hidden="true"></div>
    </div>
    <div class="th-shade"></div>
    <div class="duo-content">
      <div class="duo-side">
        <div class="eyebrow">Mapa mais jogado</div>
        <h1 class="th-name"><span>${esc(m.name)}</span></h1>
        <p class="duo-meta">${fmt.int(m.maps)} mapas · ${fmt.pct(m.share)} do total</p>
        <div class="duo-chip"><small>Agente mais escolhido neste mapa</small><b>${esc(m.top_agent.display_name)}</b><span>${fmt.pct0(m.top_agent.rate)} das composições · ${fmt.int(m.top_agent.picks)} picks</span></div>
      </div>
      <div class="duo-side r">
        <div class="eyebrow">Agente mais escolhido</div>
        <h1 class="th-name"><span>${esc(a.display_name)}</span></h1>
        <p class="duo-meta">${fmt.int(a.picks)} picks · ${fmt.pct0(a.rate)} das composições</p>
        <div class="duo-chip"><small>Mapa em que foi mais escolhido</small><b>${esc(a.best_map.name)}</b><span>${fmt.int(a.best_map.picks)} picks · ${fmt.pct0(a.best_map.rate)} das composições</span></div>
      </div>
    </div>
  </header>`;
}

// Monta a página Mapas com gráficos e tabelas de mapas e agentes.
async function pageMaps() {
  const mapSel = store.get("map-sel", "");
  const [maps, featured] = await Promise.all([api("maps"), api("maps/featured").catch(() => ({}))]);
  mount(`${mapAgentHero(featured)}
    <div class="grid cols-2">
      ${card("", chart("map_side_bias", { min_maps: 10 }, "Lado favorecido por mapa"))}
      ${card("", chart("map_heatmap", {}, "Map pool por ano"))}
      ${card("", chart("agent_heatmap", {}, "Meta de agentes"))}
      <div class="card"><div class="field" style="margin-bottom:8px"><label>Mapa</label><select id="m-sel"><option value="">Todos</option>${maps.map((m) => `<option ${m.map_name === mapSel ? "selected" : ""}>${esc(m.map_name)}</option>`).join("")}</select></div>
        ${chart("agent_pickrate", { map_name: mapSel }, "Agentes mais escolhidos")}</div>
    </div>
    <div class="grid cols-2 mt">
      ${card("Mapas", '<div id="m-table"></div>')}
      ${card("Agentes", '<div id="a-table"></div>')}
    </div>`);
  $("#m-sel").onchange = (e) => { store.set("map-sel", e.target.value); pageMaps(); };
  put("#m-table", table([
    { key: "map_name", label: "Mapa", l: true }, { key: "maps", label: "Jogos", fmt: fmt.int }, { key: "play_rate", label: "% do total", fmt: fmt.pct },
    { key: "atk_wr", label: "Ataque", fmt: fmt.pct }, { key: "def_wr", label: "Defesa", fmt: fmt.pct },
    { key: "side", label: "Favorece", l: true, html: (r) => sideCell(r.atk_wr > 0.5 ? "Ataque" : "Defesa") },
    { key: "ot_rate", label: "Prorrogação", fmt: fmt.pct }, { key: "avg_duration_min", label: "Duração (min)", fmt: fmt.n1 },
  ], maps, { sortKey: "maps" }));
  const agents = await api("agents", { map_name: mapSel });
  put("#a-table", table([
    { key: "agent", label: "Agente", l: true, html: (r) => esc(agentName(r.agent)) },
    { key: "picks", label: "Picks", fmt: fmt.int }, { key: "pick_rate", label: "Pick rate", fmt: (v) => fmt.pct(v / 2), title: "% das composições" },
    { key: "win_rate", label: "Win rate", fmt: fmt.pct }, { key: "kd", label: "K/D", fmt: fmt.n2 },
  ], agents, { sortKey: "picks" }));
}

// Monta o banner da página Títulos com o campeão mais recente do Tier 1.
function titlesHero(f) {
  if (!f || !f.event_id) return hero("Hall da fama", "Títulos", "Campeão e vice de cada evento concluído (colocação oficial do VLR.gg; na falta dela, a grande final)");
  const meta = [f.runner_up_name ? `Vice: ${esc(f.runner_up_name)}` : "", f.champion_prize_usd ? `Prêmio do campeão: ${fmt.usdShort(f.champion_prize_usd)}` : "",
    f.end_date ? `Final em ${fmt.date(f.end_date)}` : "", f.location ? esc(f.location) : ""].filter(Boolean).join(" · ");
  return `<header class="page-head team-hero title-hero${f.photo_url ? "" : " no-photo"}" style="--ev:${evColor(f.event_type)}">
    <div class="th-visual">${titleVisual(f)}</div>
    <div class="th-shade"></div>
    <div class="th-content">
      <div class="eyebrow">Hall da fama · título mais recente do Tier 1 · ${esc(f.event_type)}</div>
      <h1 class="th-name">${teamLogo(f.champion_id, f.champion_name, "hero", "dark")}<span>${esc(f.champion_name)}</span></h1>
      <button type="button" class="th-title" data-event="${f.event_id}">${TROPHY}
        <span><small>Campeão · ${esc(f.year)}</small>${esc(f.name)}</span><b>Ver detalhes →</b></button>
      <div class="th-actions">${f.has_bracket ? `<button type="button" class="btn" id="ti-bracket">Ver chaveamento</button>` : ""}
        <span class="th-meta">${meta}</span></div>
    </div>
    ${f.photo_credit ? `<div class="tb-credit">Foto: ${esc(f.photo_credit)}</div>` : ""}
  </header>`;
}

// Monta a página Títulos com gráficos, legenda de eventos e campeões.
async function pageTitles() {
  const featured = await api("featured-title").catch(() => ({}));
  mount(`${titlesHero(featured)}
    <div class="grid cols-2">
      ${card("", chart("titles_top", { limit: 20 }, "Times com mais títulos"))}
      ${card("", chart("intl_titles_region", {}, "Títulos internacionais por região"))}
    </div>
    <div class="mt">${card("Cores dos eventos", `<div class="ev-legend">${state.meta.event_order.map((ty) =>
      `<div class="ev-legend-item" style="--ev:${evColor(ty)}"><b>${esc(ty)}</b><span>${esc(EV_DESC[ty] || "")}</span></div>`).join("")}</div>`,
      "Cada tipo de evento tem uma cor fixa, igual nas tabelas e nos gráficos")}</div>
    <div class="mt">${card("Todos os campeões", '<div id="ti-table"></div>')}</div>`);
  const bk = $("#ti-bracket");
  if (bk) bk.onclick = () => openEvent(featured.event_id, { bracket: true });
  const rows = await api("titles");
  put("#ti-table", table([
    { key: "end_date", label: "Data", l: true, fmt: fmt.date },
    { key: "tier", label: "Tier", l: true, html: (r) => tierTag(r.tier) },
    { key: "name", label: "Evento", l: true, html: (r) => evName(r.name, r.event_type, r.event_id) },
    { key: "event_type", label: "Tipo", l: true, html: (r) => evBadge(r.event_type) }, { key: "region", label: "Região", l: true },
    { key: "champion_name", label: "Campeão", l: true, html: (r) => teamLink(r.champion_id, r.champion_name) },
    { key: "runner_up_name", label: "Vice", l: true, html: (r) => teamLink(r.runner_up_id, r.runner_up_name) },
    { key: "champion_prize_usd", label: "Prêmio do campeão", fmt: fmt.usd, title: "Quanto o campeão recebeu (1º lugar)" },
    { key: "runner_up_prize_usd", label: "Prêmio do vice", fmt: fmt.usd },
    { key: "prize_usd", label: "Premiação total", fmt: fmt.usd, title: "Total distribuído entre todos os times do evento" },
  ], rows, { rank: false, scroll: true }));
}

// Monta o banner do confronto direto com os dois times escolhidos.
function h2hHero(a, b, colors, names) {
  // Gera o lado de um time no banner, ou o aviso para escolhê-lo.
  const side = (id, cls) => {
    if (!id) return `<div class="vs-side ${cls} empty"><span>Escolha o time ${cls === "l" ? "A" : "B"}</span></div>`;
    const c = colors[id];
    return `<div class="vs-side ${cls}${c ? "" : " neutral"}" style="${c ? `--tc:${c}` : ""}">
      ${teamLogo(id, names[id], "hero", "dark")}<b>${esc(names[id] || "")}</b></div>`;
  };
  return `<header class="page-head vs-hero">
    <div class="vs-bg">${side(a, "l")}${side(b, "r")}<div class="vs-mark">VS</div></div>
    <div class="vs-content">
      <div><div class="eyebrow">Head to head</div><h1>Confronto direto</h1><p>Histórico entre dois times</p></div>
      <div class="filters-local"><div class="field"><label>Time A</label><select id="h-a"></select></div>
        <div class="field"><label>Time B</label><select id="h-b"></select></div></div>
    </div>
  </header>`;
}

// Monta a página Confronto com o histórico entre dois times.
async function pageH2H(params) {
  const a = params.get("a") || "", b = params.get("b") || "";
  const ids = [a, b].filter(Boolean);
  const [teams, colors] = await Promise.all([api("teams", { min_maps: 10, limit: 1000, sort: "maps" }),
    ids.length ? fetch(`/api/team-colors?ids=${ids.join(",")}`).then((r) => r.json()).catch(() => ({})) : {}]);
  const names = Object.fromEntries(teams.map((t) => [String(t.team_id), t.team_name]));
  mount(`${h2hHero(a, b, colors, names)}<div id="h2h-body"></div>`);
  teams.sort((x, y) => x.team_name.localeCompare(y.team_name));
  const opt = (sel) => `<option value="">—</option>` + teams.map((t) => `<option value="${t.team_id}" ${String(t.team_id) === sel ? "selected" : ""}>${esc(t.team_name)}</option>`).join("");
  $("#h-a").innerHTML = opt(a); $("#h-b").innerHTML = opt(b);
  const go = () => { location.hash = `#/confronto?a=${$("#h-a").value}&b=${$("#h-b").value}`; };
  $("#h-a").onchange = go; $("#h-b").onchange = go;
  const one = a || b;
  if (!one) { $("#h2h-body").innerHTML = `<div class="empty">Escolha um time para ver as últimas partidas dele, ou dois times para o confronto direto.</div>`; return; }
  if (!a || !b) {
    const t = teams.find((x) => String(x.team_id) === one);
    $("#h2h-body").innerHTML = card(`Últimas partidas · ${esc(t ? t.team_name : "")}`, '<div id="h2h-list"></div>',
      "Da mais recente para a mais antiga, seguindo os filtros · clique numa partida para ver mapas, placar por mapa, cronologia dos rounds, tabela de abates e X1 · escolha o Time B para o confronto direto");
    matchList($("#h2h-list"), (offset, limit) => api(`teams/${one}/matches`, { offset, limit }), one, params.get("partida"), params.get("mapa"));
    return;
  }
  const d = await api("h2h", { team_a: a, team_b: b });
  $("#h2h-body").innerHTML = `<div class="grid cols-2">
      ${card("", `<div class="h2h-score"><div><div class="n">${d.team_a.wins}</div><div class="name">${teamLink(a, d.team_a.name)}</div></div>
        <div class="vs">vitórias<br>em séries</div><div><div class="n">${d.team_b.wins}</div><div class="name">${teamLink(b, d.team_b.name)}</div></div></div>`)}
      ${card("", chart("h2h_maps", { team_a: a, team_b: b }, "Confronto direto"))}
    </div><div class="mt">${card("Séries", '<div id="h2h-list"></div>', "Da mais recente para a mais antiga · clique numa série para ver os detalhes")}</div>`;
  matchList($("#h2h-list"), async (offset, limit) => ({ total: d.matches.length, matches: d.matches.slice(offset, offset + limit) }), a, params.get("partida"), params.get("mapa"));
}

const LAYERS = [
  ["01 Scraping", "Páginas do VLR.gg", "Descobre os eventos e as partidas e baixa cada página em paralelo (4 threads), com limite de requisições por segundo, retentativas e cache: nada é baixado duas vezes", "Arquivos HTML compactados", "requests, BeautifulSoup, ThreadPoolExecutor"],
  ["02 Bronze", "HTML baixado", "Guarda o dado bruto sem nenhuma alteração, compactado em gzip e particionado por ano (<code>year=AAAA</code>). É a fonte da verdade: dá para reprocessar tudo sem baixar de novo", "86 mil arquivos <code>.html.gz</code>", "Sistema de arquivos do Hadoop"],
  ["03 Silver", "HTML da bronze", "Lê os arquivos em paralelo, extrai os dados do HTML (placar, mapas, rounds, estatísticas de cada jogador, prêmios) e padroniza tipos, datas e moedas. Só as partidas novas são processadas", "Tabelas limpas em Parquet", "PySpark (<code>binaryFile</code>, <code>mapPartitions</code>, broadcast)"],
  ["04 Gold", "Tabelas da silver", "Junta as tabelas num modelo estrela (dimensões de times, jogadores e eventos) e agrega em cubos com somas por time, jogador, mapa, agente, evento e ano. Também define campeões, tiers e regiões", "Cubos agregados em Parquet", "Spark SQL (<code>groupBy</code>, window functions, joins)"],
  ["05 Serving", "Cubos da gold", "Exporta os cubos em CSV e carrega na memória da API. Cada filtro do site vira uma soma das linhas filtradas, e as médias são calculadas no final, já ponderadas", "Respostas JSON e gráficos", "pandas, FastAPI, matplotlib/seaborn"],
  ["06 Sob demanda", "HTML de uma partida na bronze", "Quando alguém abre uma partida, lê o HTML dela na hora e monta rounds, tabela de abates e X1, sem passar pelo Spark", "Detalhe da partida em JSON", "BeautifulSoup, cache em memória"],
  ["07 Visualização", "JSON da API", "Monta as páginas, os banners e as tabelas no navegador e desenha os gráficos interativos", "O site", "HTML, CSS, JavaScript, Chart.js"],
];

const CREDIT_GROUPS = [
  ["Dados", [
    ["VLR.gg", "https://www.vlr.gg", "Eventos, partidas, mapas, rounds, estatísticas dos jogadores, matriz de abates, premiações e logos de times e eventos"],
    ["Liquipedia", "https://liquipedia.net/valorant", "Fotos dos jogadores (ficha de cada jogador, via API MediaWiki), com link para a página de origem"],
  ]],
  ["Imagens", [
    ["VALORANT Esports (Flickr)", "https://www.flickr.com/photos/valorantesports/", "Fotos dos títulos de Masters e Champions e de jogadores"],
    ["VCT Americas (Flickr)", "https://www.flickr.com/photos/vctamericas/", "Fotos dos títulos das ligas, Kickoffs e LCQs das Américas e de jogadores"],
    ["VCT EMEA (Flickr)", "https://www.flickr.com/photos/vctemea/", "Fotos dos títulos das ligas, Kickoffs e LCQs da EMEA"],
    ["VCT Pacific (Flickr)", "https://www.flickr.com/photos/vctpacific/", "Fotos dos títulos das ligas do Pacífico"],
    ["valorant-api.com", "https://valorant-api.com", "Artes oficiais dos mapas (splash) e dos agentes (retrato e fundo) do banner de Mapas & agentes"],
    ["Banner da Visão geral", "", "Imagem fornecida pelo autor do projeto (web/img/banners/allcamps)"],
  ]],
  ["Fontes tipográficas", [
    ["Inter e Inter Tight (Google Fonts)", "https://fonts.google.com/specimen/Inter", "Rasmus Andersson · SIL Open Font License 1.1"],
  ]],
  ["Bibliotecas", [
    ["Apache Spark / PySpark", "https://spark.apache.org", "ETL do data lake · Apache License 2.0"],
    ["Apache Hadoop", "https://hadoop.apache.org", "FileSystem do data lake (winutils no Windows) · Apache License 2.0"],
    ["pandas", "https://pandas.pydata.org", "Camada de serving · BSD 3-Clause"],
    ["NumPy", "https://numpy.org", "Cálculos numéricos · BSD 3-Clause"],
    ["matplotlib", "https://matplotlib.org", "Gráficos em PNG · licença matplotlib (PSF)"],
    ["seaborn", "https://seaborn.pydata.org", "Gráficos estatísticos em PNG · BSD 3-Clause"],
    ["FastAPI", "https://fastapi.tiangolo.com", "API REST · MIT"],
    ["Uvicorn", "https://www.uvicorn.org", "Servidor da API · BSD 3-Clause"],
    ["Requests", "https://requests.readthedocs.io", "Coleta HTTP · Apache License 2.0"],
    ["Beautiful Soup 4", "https://www.crummy.com/software/BeautifulSoup/", "Parsing do HTML · MIT"],
    ["Pillow", "https://python-pillow.org", "Redimensionamento das fotos e cores dos logos · MIT-CMU (HPND)"],
    ["Chart.js 4.4.1", "https://www.chartjs.org", "Gráficos interativos no navegador · MIT"],
  ]],
];

// Monta o HTML da seção de créditos: fontes, fotógrafos, tipografia, bibliotecas e aviso de marca.
function creditsHtml(cr) {
  const link = (name, url) => (url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(name)}</a>` : esc(name));
  const groups = CREDIT_GROUPS.map(([title, items]) => `<div class="cr-group"><h4>${esc(title)}</h4><ul>${items.map(([name, url, desc]) =>
    `<li><b>${link(name, url)}</b><span>${esc(desc)}</span></li>`).join("")}</ul></div>`).join("");
  const people = (list) => (list && list.length
    ? list.map((p) => `<li><b>${esc(p.credit.replace(/ \/ Riot Games$/, ""))}</b><span>${fmt.int(p.photos)} foto${p.photos === 1 ? "" : "s"}</span></li>`).join("")
    : `<li><span>—</span></li>`);
  return `<div class="credits">${groups}
    <div class="cr-group"><h4>Fotógrafos · títulos</h4><ul>${people(cr.title_photographers)}</ul></div>
    <div class="cr-group"><h4>Fotógrafos · jogadores (Flickr)</h4><ul>${people(cr.player_photographers)}</ul></div>
  </div>
  <p class="cr-note">Fotos de títulos, de jogadores, artes de mapas e de agentes: © Riot Games, todos os direitos reservados, usadas apenas para fins acadêmicos.
    VALORANT e VALORANT Champions Tour são marcas da Riot Games, Inc. Este projeto não tem vínculo com a Riot Games, o VLR.gg ou a Liquipedia.
    O crédito de cada foto aparece sobre a imagem; os detalhes estão em <code>web/img/titulos/creditos.json</code> e <code>data/bronze/catalog</code>.</p>`;
}

// Monta a página Dados com o pipeline, a cobertura, as fontes e o tamanho das tabelas.
async function pageData() {
  const m = (state.meta && state.meta.manifest) || {};
  const L = m.layers || {};
  const mb = (k) => (L[k] ? (L[k].bytes / 2 ** 20).toFixed(1).replace(".", ",") + " MB" : "—");
  const files = (k) => (L[k] ? NF.format(L[k].files) + " arquivos" : "");
  const rows = (o) => Object.entries(o || {}).map(([k, v]) => ({ table: k, rows: v }));
  const [cov, cr] = await Promise.all([api("coverage", { tier: "" }).catch(() => ({})),
    fetch("/api/credits").then((r) => r.json()).catch(() => ({}))]);
  const n = (k) => fmt.int(cov[k]);
  const part = (a, b) => (isNum(cov[a]) && cov[b] ? `${n(a)} de ${n(b)} · ${fmt.pct0(cov[a] / cov[b])}` : "—");
  mount(`${hero("Big Data", "Dados &amp; pipeline", "Arquitetura medallion num data lake local acessado pelo Hadoop FileSystem")}
    <div class="card"><div class="pipeline">
      <div class="stage"><b><span>01</span> Coleta</b><small>Scraper Python (requests + BeautifulSoup) no VLR.gg, com limite de taxa e cache</small><div class="big">VLR.gg</div></div>
      <div class="stage"><b><span>02</span> Bronze</b><small>HTML bruto em gzip, particionado em <code>year=AAAA</code></small><div class="big">${mb("bronze")}</div><small>${files("bronze")}</small></div>
      <div class="stage"><b><span>03</span> Silver</b><small>Spark lê com <code>binaryFile</code>, faz o parsing em paralelo e grava Parquet</small><div class="big">${mb("silver")}</div><small>${files("silver")}</small></div>
      <div class="stage"><b><span>04</span> Gold</b><small>Spark SQL: cubos com medidas aditivas por time, jogador, mapa e agente</small><div class="big">${mb("gold")}</div><small>${files("gold")}</small></div>
      <div class="stage"><b><span>05</span> Serving</b><small>CSV lido pelo pandas na API FastAPI; gráficos interativos em Chart.js e PNG em matplotlib/seaborn</small><div class="big">${mb("serving")}</div><small>${files("serving")}</small></div>
      <div class="stage"><b><span>06</span> Sob demanda</b><small>Detalhe de cada partida (rounds, tabela de abates e X1) lido do bronze na hora, com cache em memória</small><div class="big">${n("matches")}</div><small>partidas inspecionáveis</small></div>
    </div></div>
    <div class="mt">${card("O que acontece em cada camada", `<div class="table-wrap"><table class="data layers"><thead><tr>
        <th class="l">Camada</th><th class="l">Entrada</th><th class="l">O que é feito</th><th class="l">Saída</th><th class="l">Tecnologia</th></tr></thead><tbody>
      ${LAYERS.map(([name, input, work, output, tech]) => `<tr><td class="l"><b>${name}</b></td><td class="l">${input}</td><td class="l">${work}</td><td class="l">${output}</td><td class="l">${tech}</td></tr>`).join("")}
      </tbody></table></div>`, "Do site do VLR.gg até o gráfico na tela, cada etapa pega o resultado da anterior")}</div>
    <div class="kpis mt">
      ${kpi("Spark", esc(m.spark_version || "—"))}${kpi("Hadoop", esc(m.hadoop_version || "—"))}
      ${kpi("Período", m.period ? `${fmt.date(m.period[0])} – ${fmt.date(m.period[1])}` : "—")}${kpi("Gerado em", esc(m.generated_at || "—"))}
    </div>
    <div class="kpis">
      ${kpi("Eventos", n("events"), "Tier 1, 2 e 3")}${kpi("Partidas", n("matches"))}${kpi("Mapas", n("maps"))}
      ${kpi("Rounds", n("rounds"))}${kpi("Times", n("teams"))}${kpi("Jogadores", n("players"))}
    </div>
    <div class="grid cols-2">
      ${card("Cobertura", `<table class="data cov"><tbody>
        <tr><td class="l">Títulos com premiação total</td><td>${part("titles_prize", "titles")}</td></tr>
        <tr><td class="l">Títulos com prêmio do campeão</td><td>${part("titles_champion_prize", "titles")}</td></tr>
        <tr><td class="l">Títulos do Tier 1 com foto da vitória</td><td>${part("tier1_title_photos", "tier1_titles")}</td></tr>
        <tr><td class="l">Jogadores do VCT com foto</td><td>${part("vct_photos", "vct_players")}</td></tr>
        <tr><td class="l">Líderes do banner de Jogadores com foto</td><td>${part("leader_photos", "leaders")}</td></tr>
        <tr><td class="l">Partidas com aba de performance (X1, multikills)</td><td>${part("matrix_matches", "matches")}</td></tr>
      </tbody></table>`, "Quanto de cada informação foi encontrado nas fontes")}
      ${card("Fontes", `<table class="data cov"><tbody>
        <tr><td class="l"><b>VLR.gg</b></td><td class="l">eventos, partidas, mapas, rounds, estatísticas, premiações e logos</td></tr>
        <tr><td class="l"><b>Liquipedia</b></td><td class="l">fotos dos jogadores (API MediaWiki, ${n("liquipedia_photos")} fotos)</td></tr>
        <tr><td class="l"><b>Flickr oficial da Riot</b></td><td class="l">fotos dos títulos (${n("title_photos")}) e de jogadores sem foto na Liquipedia (${n("flickr_photos")})</td></tr>
        <tr><td class="l"><b>valorant-api.com</b></td><td class="l">artes oficiais de mapas e agentes</td></tr>
      </tbody></table>`, "Tudo é guardado em cache local; nada é pedido de novo sem necessidade")}
    </div>
    <div class="mt">${card("Créditos", creditsHtml(cr), "Todas as fontes de dados, imagens, fontes tipográficas e bibliotecas usadas no projeto")}</div>
    <div class="grid cols-2">
      ${card("Tabelas silver (Parquet)", '<div id="d-silver"></div>')}
      ${card("Tabelas gold (Parquet + CSV)", '<div id="d-gold"></div>')}
    </div>`);
  const cols = [{ key: "table", label: "Tabela", l: true }, { key: "rows", label: "Linhas", fmt: fmt.int }];
  put("#d-silver", table(cols, rows(m.silver_rows), { rank: false }));
  put("#d-gold", table(cols, rows(m.gold_rows), { rank: false }));
}

const ROUTES = [
  [/^\/?$/, "overview", () => pageOverview()],
  [/^\/times$/, "teams", () => pageTeams()],
  [/^\/time\/(\d+)$/, "teams", (m) => pageTeam(m[1])],
  [/^\/jogadores$/, "players", () => pagePlayers()],
  [/^\/jogador\/(\d+)$/, "players", (m) => pagePlayer(m[1])],
  [/^\/mapas$/, "maps", () => pageMaps()],
  [/^\/titulos$/, "titles", () => pageTitles()],
  [/^\/confronto$/, "h2h", (_m, p) => pageH2H(p)],
  [/^\/dados$/, "data", () => pageData()],
];
// Lê a rota da URL, ativa a aba e renderiza a página correspondente.
async function route() {
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  for (const [re, tab, fn] of ROUTES) {
    const m = path.match(re);
    if (!m) continue;
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
    const params = new URLSearchParams(query || "");
    try { await fn(m, params); } catch (e) { fail(e); }
    document.body.classList.toggle("hero-on", Boolean($(".team-hero, .vs-hero")));

    if (params.get("evento")) openEvent(params.get("evento"), { bracket: params.get("chave") === "1" });
    return;
  }
  location.hash = "#/";
}

// Preenche o seletor de eventos conforme os filtros escolhidos.
function fillEvents() {
  const sel = $("#f-event"), f = state.filters;
  const evs = state.meta.events.filter((e) => (!f.tier || e.tier == f.tier) && (!f.year || e.year == f.year)
    && (!f.region || e.region === f.region) && (!f.event_type || e.event_type === f.event_type));
  sel.innerHTML = `<option value="">Todos (${evs.length})</option>` + evs.map((e) => `<option value="${e.event_id}">${esc(e.name)}</option>`).join("");
  if (!evs.some((e) => String(e.event_id) === String(f.event_id))) f.event_id = "";
  sel.value = f.event_id;
  paintEventFilters();
}
// Aplica a cor do tipo de evento aos seletores de filtro.
function paintEventFilters() {
  const f = state.filters;
  const ev = state.meta.events.find((e) => String(e.event_id) === String(f.event_id));
  const type = ev ? ev.event_type : f.event_type;
  const paint = (el, color) => { el.classList.toggle("has-ev", Boolean(color)); if (color) el.style.setProperty("--ev", color); };
  paint($("#f-type"), f.event_type ? evColor(f.event_type) : null);
  paint($("#f-event"), ev ? evColor(type) : null);
}
// Gera os botões de seleção de tier.
function fillTiers() {
  const opts = [{ tier: "", label: "Todos", desc: "Todos os tiers" }, ...state.meta.tiers];
  $("#f-tier").innerHTML = opts.map((t) => `<button type="button" data-tier="${t.tier}" title="${esc(t.desc)}"
    class="${String(t.tier) === String(state.filters.tier) ? "on" : ""}">${esc(t.label)}</button>`).join("");
}
// Carrega os metadados e configura a barra de filtros globais.
async function initFilters() {
  state.filters = { ...state.filters, ...store.get("filters", {}) };
  state.meta = await api("meta", { tier: "" });
  const add = (sel, vals) => { $(sel).innerHTML += vals.map((v) => `<option>${esc(v)}</option>`).join(""); };
  add("#f-year", state.meta.years); add("#f-region", state.meta.regions); add("#f-type", state.meta.event_types);
  // Sincroniza os campos de filtro com o estado atual.
  const sync = () => {
    $("#f-year").value = state.filters.year; $("#f-region").value = state.filters.region; $("#f-type").value = state.filters.event_type;
    fillTiers(); fillEvents();
  };
  const commit = () => { fillTiers(); fillEvents(); store.set("filters", state.filters); route(); };
  sync();
  ["#f-year", "#f-region", "#f-type", "#f-event"].forEach((s) => ($(s).onchange = () => {
    Object.assign(state.filters, { year: $("#f-year").value, region: $("#f-region").value, event_type: $("#f-type").value, event_id: $("#f-event").value });
    commit();
  }));
  $("#f-tier").onclick = (e) => {
    const b = e.target.closest("button[data-tier]");
    if (!b) return;
    state.filters.tier = b.dataset.tier;
    commit();
  };
  $("#f-reset").onclick = () => { state.filters = { ...EMPTY_FILTERS }; sync(); store.set("filters", state.filters); route(); };
}
// Aplica o tema salvo e configura o botão de alternar tema.
function initTheme() {
  const saved = store.get("theme", null);
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-toggle").onclick = () => {
    const next = theme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("theme", next);
    route();
  };
}

// Mostra um aviso flutuante no canto da tela, que some sozinho depois de alguns segundos.
function notify(message, kind = "info") {
  let stack = $("#toasts");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toasts";
    stack.setAttribute("role", "status");
    stack.setAttribute("aria-live", "polite");
    document.body.append(stack);
  }
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<b aria-hidden="true">${kind === "warn" ? "!" : "i"}</b><span>${esc(message)}</span><i class="toast-bar" aria-hidden="true"></i>`;
  const close = () => { el.classList.add("out"); setTimeout(() => el.remove(), 220); };
  el.onclick = close;
  stack.querySelectorAll(".toast").forEach((t, i, all) => { if (i < all.length - 2) t.remove(); });
  stack.append(el);
  setTimeout(close, 3500);
}

// Configura a busca de times e jogadores: resultados instantâneos e Enter para abrir o mais relevante.
function initSearch() {
  const input = $("#search"), box = $("#search-results");
  let timer;
  const lookup = (q) => fetch(`/api/search?${qs({ q }, false)}`).then((x) => x.json()).catch(() => ({ teams: [], players: [] }));
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { box.classList.remove("open"); input.blur(); return; }
    if (e.key !== "Enter") return;
    e.preventDefault();
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) return;
    if (q.length < 2) { notify(`Digite pelo menos 2 caracteres para buscar.`, "warn"); return; }
    const r = await lookup(q);
    const pick = r.players.find((p) => p.exact) ? { href: `#/jogador/${r.players.find((p) => p.exact).player_id}` }
      : r.teams.find((t) => t.exact) ? { href: `#/time/${r.teams.find((t) => t.exact).team_id}` }
      : r.players[0] || r.teams[0] ? { href: r.players[0] && (!r.teams[0] || r.players[0].maps >= r.teams[0].maps) ? `#/jogador/${r.players[0].player_id}` : `#/time/${r.teams[0].team_id}` }
      : null;
    if (!pick) { notify(`Nenhum time ou jogador encontrado para “${q}”.`, "warn"); return; }
    box.classList.remove("open");
    input.value = "";
    input.blur();
    location.hash = pick.href;
  });
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { box.classList.remove("open"); return; }
    timer = setTimeout(async () => {
      const r = await lookup(q);
      if (input.value.trim() !== q) return;
      box.innerHTML = (r.teams.length ? "<h6>Times</h6>" + r.teams.map((t) => `<a href="#/time/${t.team_id}">${teamLogo(t.team_id, t.team_name)}${esc(t.team_name)}<span>${esc(teamCountry(t.team_id) || t.team_region || "")} · ${fmt.int(t.maps)} mapas</span></a>`).join("") : "")
        + (r.players.length ? "<h6>Jogadores</h6>" + r.players.map((p) => `<a href="#/jogador/${p.player_id}">${esc(p.player_name)}<span>${esc(p.current_team_name || "")} · ${fmt.int(p.maps)} mapas</span></a>`).join("") : "")
        || `<div class="empty">Nada encontrado</div>`;
      box.classList.add("open");
    }, 200);
  });
  box.addEventListener("click", () => { box.classList.remove("open"); input.value = ""; });
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) box.classList.remove("open"); });
}

// Inicializa tema, busca, filtros e o roteamento da aplicação.
(async function main() {
  initTheme();
  initSearch();
  try { await initFilters(); } catch (e) { fail(e); return; }
  window.addEventListener("hashchange", route);
  route();
})();

const TROPHY = `<svg class="trophy" viewBox="0 0 64 64" aria-hidden="true"><path fill="currentColor" d="M18 6h28v6h10v6c0 8-6 14-13 15-2 6-6 10-9 11v7h9v7H21v-7h9v-7c-3-1-7-5-9-11C14 32 8 26 8 18v-6h10V6zm-4 12c0 4 3 7 6 8-1-3-2-6-2-9v-1h-4v2zm32-2v1c0 3-1 6-2 9 3-1 6-4 6-8v-2h-4z"/></svg>`;

// Gera o visual do título: foto do campeão ou card com troféu e logos.
function titleVisual(d) {
  if (d.photo_url) return `<img class="tv-photo" src="${esc(d.photo_url)}" fetchpriority="high" decoding="async" alt="${esc(d.champion_name || "")} com o troféu do ${esc(d.name)}">`;
  const champ = d.champion_id ? teamLogo(d.champion_id, d.champion_name, "hero", "dark") : "";
  const evLogo = d.event_id ? `<img class="tv-evlogo" src="/api/logo/event/${d.event_id}?theme=dark" alt="" onerror="this.remove()">` : "";
  return `<div class="tv-card">${evLogo}<div class="tv-center">${TROPHY}${champ}</div></div>`;
}

// Fecha o modal aberto.
function closeModal() {
  const m = $("#modal");
  if (m) m.remove();
  document.body.classList.remove("modal-open");
}

// Abre o modal com os detalhes de um evento e o chaveamento.
async function openEvent(id, { bracket: autoBracket = false } = {}) {
  closeModal();
  const wrap = document.createElement("div");
  wrap.id = "modal";
  wrap.className = "modal-backdrop";
  wrap.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="Detalhes do evento"><div class="empty">Carregando…</div></div>`;
  document.body.append(wrap);
  document.body.classList.add("modal-open");
  wrap.addEventListener("click", (e) => { if (e.target === wrap || e.target.closest(".modal-close")) closeModal(); });
  let d;
  try { d = await api(`events/${id}`); } catch (e) { wrap.querySelector(".modal").innerHTML = `<div class="error">${esc(e.message)}</div>`; return; }
  const fact = (label, value) => `<div class="fact"><div class="label">${label}</div><div class="value">${value}</div></div>`;
  const status = d.champion_name ? "" : `<p class="muted">Evento sem campeão definido (em andamento ou sem playoffs).</p>`;
  wrap.querySelector(".modal").innerHTML = `
    <button type="button" class="modal-close" aria-label="Fechar">×</button>
    <div class="modal-hero" style="--ev:${evColor(d.event_type)}">
      <div class="tb-visual">${titleVisual(d)}</div>
      <div class="tb-overlay">
        <div class="tb-eyebrow">${tierTag(d.tier)} ${evBadge(d.event_type)}</div>
        <div class="tb-title">${esc(d.name)}</div>
        <div class="tb-meta"><span>${esc(d.year)}</span>${d.champion_name ? `<span class="tb-champ">${TROPHY}${teamLogo(d.champion_id, d.champion_name, "md", "dark")}${esc(d.champion_name)}</span>` : ""}</div>
      </div>${d.photo_credit ? `<div class="tb-credit">Foto: ${esc(d.photo_credit)}</div>` : ""}
    </div>
    <div class="modal-body">
      ${status}
      <div class="facts">
        ${fact("Campeão", d.champion_id ? `${teamLink(d.champion_id, d.champion_name)}<small>${fmt.usd(d.champion_prize_usd)}</small>` : "—")}
        ${fact("Vice", d.runner_up_id ? `${teamLink(d.runner_up_id, d.runner_up_name)}<small>${fmt.usd(d.runner_up_prize_usd)}</small>` : "—")}
        ${fact("Período", `${fmt.date(d.start_date)} – ${fmt.date(d.end_date)}`)}
        ${fact("Local", esc(d.location || "—"))}
        ${fact("Premiação total", fmt.usd(d.prize_usd))}
        ${fact("Partidas", fmt.int(d.matches))}
      </div>
      <div class="modal-actions">
        ${d.has_bracket ? `<button type="button" class="btn" id="show-bracket">Ver chaveamento</button>`
          : `<span class="muted">${d.tier === 1 ? "Este evento não tem playoffs registrados." : "Chaveamento disponível apenas para eventos do Tier 1."}</span>`}
      </div>
      <div id="bracket"></div>
    </div>`;
  const btn = $("#show-bracket");
  if (btn) btn.onclick = async () => {
    btn.disabled = true;
    $("#bracket").innerHTML = `<div class="empty">Montando o chaveamento…</div>`;
    try { $("#bracket").innerHTML = renderBracket(await api(`events/${id}/bracket`)); btn.remove(); }
    catch (e) { $("#bracket").innerHTML = `<div class="error">${esc(e.message)}</div>`; btn.disabled = false; }
  };
  if (btn && autoBracket) btn.click();
}

const BK_MATCH_H = 74, BK_GAP = 12, BK_LABEL_H = 24;
// Gera o HTML do chaveamento de playoffs de um evento.
function renderBracket(b) {
  // Gera a linha de um time numa partida do chaveamento.
  const side = (m, n) => {
    const tid = m[`team${n}_id`], name = m[`team${n}_name`], score = m[`team${n}_score`];
    const won = m.winner_id && m.winner_id === tid;
    return `<div class="bk-team ${won ? "won" : ""}">${teamLogo(tid, name)}<span class="bk-name">${esc(name || "TBD")}</span><span class="bk-score">${score ?? "-"}</span></div>`;
  };
  if (!b.sections.length) return `<div class="empty">Sem partidas de playoffs.</div>`;

  const SLOT = BK_MATCH_H + BK_GAP;
  return b.sections.map((sec) => {
    const n0 = Math.max(...sec.rounds.map((r) => r.matches.length));
    return `<div class="bk-section"><h3 class="bk-title">${esc(sec.name)}</h3>
    <div class="bk-cols">${sec.rounds.map((r) => {
      const k = n0 / r.matches.length;
      const top = ((k - 1) * SLOT) / 2, gap = (k - 1) * SLOT + BK_GAP;
      return `<div class="bk-col" style="padding-top:${top + BK_LABEL_H}px;gap:${gap}px">
        <div class="bk-round" style="top:${top}px">${esc(r.label)}</div>
        ${r.matches.map((m) => `<div class="bk-match" title="${fmt.date(m.match_date)}">${side(m, 1)}${side(m, 2)}</div>`).join("")}</div>`;
    }).join("")}</div></div>`;
  }).join("");
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-event]");
  if (!el) return;
  e.preventDefault();
  openEvent(el.dataset.event);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
window.addEventListener("hashchange", closeModal);

// Monta o banner do time com o título mais recente.
function teamHero(id, t, f) {
  const country = teamCountry(id);
  return `<header class="page-head team-hero${f.photo_url ? "" : " no-photo"}" style="--ev:${evColor(f.event_type)}">
    <div class="th-visual">${titleVisual(f)}</div>
    <div class="th-shade"></div>
    <div class="th-content">
      <div class="eyebrow">Time · ${esc(t.team_region)}${country ? ` · ${esc(country)}` : ""}</div>
      <h1 class="th-name">${teamLogo(id, t.team_name, "hero", "dark")}<span>${esc(t.team_name)}</span></h1>
      <button type="button" class="th-title" data-event="${f.event_id}">${TROPHY}
        <span><small>Título mais recente no Tier 1</small>Campeão do ${esc(f.name)}</span><b>Ver detalhes →</b></button>
      <div class="th-actions"><a class="btn" href="#/confronto?a=${id}">Confronto direto</a>
        <span class="th-meta">Ativo de ${t.first_year} a ${t.last_year} · números abaixo seguem os filtros</span></div>
    </div>
    ${f.photo_credit ? `<div class="tb-credit">Foto: ${esc(f.photo_credit)}</div>` : ""}
  </header>`;
}

window.addEventListener("scroll", () => document.body.classList.toggle("scrolled", window.scrollY > 40), { passive: true });

// Monta o banner do jogador com foto e time atual.
function playerHero(id, p, h) {
  const tid = p.current_team_id, tname = p.current_team_name;
  const bg = h.photo_portrait ? `<img class="tv-bg" src="${esc(h.photo_url)}" alt="" aria-hidden="true">` : "";
  return `<header class="page-head team-hero player-hero${h.photo_portrait ? " portrait" : ""}">
    <div class="th-visual">${bg}<img class="tv-photo" src="${esc(h.photo_url)}" fetchpriority="high" decoding="async" alt="${esc(p.player_name)}"></div>
    <div class="th-shade"></div>
    <div class="th-content">
      <div class="eyebrow">Jogador · Tier 1${p.country ? ` · ${esc(p.country)}` : ""}</div>
      <h1 class="th-name"><span>${esc(p.player_name)}</span></h1>
      ${tid ? `<a class="th-title" href="#/time/${tid}">${teamLogo(tid, tname, "md", "dark")}
        <span><small>Time atual</small>${esc(tname)}</span><b>Ver time →</b></a>` : ""}
      <div class="th-actions"><span class="th-meta">${fmt.int(h.tier1_maps)} mapas no Tier 1 · números abaixo seguem os filtros</span></div>
    </div>
    ${h.photo_credit ? `<a class="tb-credit" href="${esc(h.photo_page || "#")}" target="_blank" rel="noopener">Foto: ${esc(h.photo_credit)}</a>` : ""}
  </header>`;
}
