"use strict";

const MX_PAGE = 10;
const WIN_TYPES = {
  elim: { label: "eliminação", icon: '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>' },
  boom: { label: "spike detonada", icon: '<circle cx="8" cy="8" r="2.6" fill="currentColor"/><path d="M8 1.5v2.4M8 12.1v2.4M1.5 8h2.4M12.1 8h2.4M3.4 3.4l1.7 1.7M10.9 10.9l1.7 1.7M3.4 12.6l1.7-1.7M10.9 5.1l1.7-1.7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' },
  defuse: { label: "spike desarmada", icon: '<path d="M8 2l4 6-4 6-4-6z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M3 13L13 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' },
  time: { label: "tempo esgotado", icon: '<circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8 4.6V8l2.4 1.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' },
};
const X1_KINDS = [["all", "Todos os abates"], ["fk", "First kills"], ["op", "Operator"]];
const SIDE = { atk: "ataque", def: "defesa" };

// Cria a lista paginada de partidas, com botão "Ver mais".
function matchList(el, loader, focus = null, openId = null, openTab = null) {
  let offset = 0, total = 0;
  el.innerHTML = `<div class="mx-list"></div><div class="mx-more"></div>`;
  const list = $(".mx-list", el), more = $(".mx-more", el);
  // Carrega a próxima página de partidas e a adiciona à lista.
  const load = async () => {
    more.innerHTML = `<span class="mx-loading">Carregando…</span>`;
    let page;
    try { page = await loader(offset, MX_PAGE); } catch (e) { more.innerHTML = `<div class="error">${esc(e.message)}</div>`; return; }
    total = page.total;
    if (!total) { list.innerHTML = `<div class="empty">Nenhuma partida no filtro atual.</div>`; more.innerHTML = ""; return; }
    list.insertAdjacentHTML("beforeend", page.matches.map((m) => matchRow(m, focus)).join(""));
    offset += page.matches.length;
    more.innerHTML = offset < total
      ? `<button type="button" class="btn-more">Ver mais <small>${fmt.int(offset)} de ${fmt.int(total)}</small></button>`
      : `<span class="mx-end">${fmt.int(total)} partida${total === 1 ? "" : "s"} · fim da lista</span>`;
    const btn = $(".btn-more", more);
    if (btn) btn.onclick = load;
    const target = openId && $(`details.mx[data-match="${openId}"]`, list);
    if (target && !target.open) { target.dataset.tab = openTab || ""; target.open = true; openId = null; }
  };
  list.addEventListener("toggle", (e) => {
    const d = e.target;
    if (d.matches && d.matches("details.mx") && d.open && !d.dataset.loaded) { d.dataset.loaded = "1"; loadMatch(d); }
  }, true);
  load();
}

// Gera o HTML de uma partida na lista, com placar, resultado e MVP.
function matchRow(m, focus) {
  focus = focus || m.team_id || null;
  const won = focus ? m.winner_id === Number(focus) : null;
  const res = focus && m.winner_id ? `<span class="mx-res ${won ? "w" : "l"}">${won ? "V" : "D"}</span>` : "";
  const side = (id, name) => `<span class="mx-team${m.winner_id === id ? " win" : ""}">${teamLogo(id, name)}${teamText(id, name)}</span>`;
  const team = m.mvp_kind === "team";
  const mvp = m.game_id ? `<span class="mx-mvp"><b class="mvp-tag${team ? " team" : ""}" title="${team ? "MVP do time: maior rating entre os 5 jogadores do time" : "MVP do mapa: maior rating entre os 10 jogadores"}">${team ? "MVP time" : "MVP"}</b><span><strong>${esc(m.map_name || "")}</strong>
      <small>${esc(agentName(m.agent))} · ${fmt.int(m.k)}/${fmt.int(m.d)}/${fmt.int(m.a)} · ACS ${fmt.int(m.acs)}</small></span><em>${fmt.n2(m.rating)}</em></span>` : "";
  return `<details class="mx${mvp ? " has-mvp" : ""}" data-match="${m.match_id}"${m.game_id ? ` data-game="${m.game_id}"` : ""}>
    <summary>
      <span class="mx-date">${fmt.date(m.match_date)}</span>
      <span class="mx-ev">${tierTag(m.tier)}<span>${evName(m.event_name, m.event_type, m.event_id)}<small>${esc(m.round_label || m.stage_label || "")}</small></span></span>
      ${mvp}
      <span class="mx-teams">${side(m.team1_id, m.team1_name)}<b class="mx-score">${m.team1_score ?? "-"}<i>:</i>${m.team2_score ?? "-"}</b>${side(m.team2_id, m.team2_name)}</span>
      ${res}<span class="mx-caret" aria-hidden="true"></span>
    </summary>
    <div class="mx-body"><div class="mx-loading">Carregando partida…</div></div>
  </details>`;
}

// Carrega os detalhes de uma partida e monta as abas de mapas.
async function loadMatch(det) {
  const body = $(".mx-body", det);
  let d;
  try { d = await fetch(`/api/matches/${det.dataset.match}`).then((r) => (r.ok ? r.json() : Promise.reject(new Error("Partida não encontrada")))); } catch (e) {
    body.innerHTML = `<div class="error">${esc(e.message)}</div>`;
    return;
  }
  const m = d.match;
  const tabs = [{ key: "total", label: "Todos os mapas", sub: `${m.team1_score ?? "-"} : ${m.team2_score ?? "-"}` },
    ...d.maps.map((g, i) => ({ key: String(i), label: g.map_name, sub: `${g.team1_score ?? "-"} : ${g.team2_score ?? "-"}` }))];
  body.innerHTML = `<div class="mx-tabs" role="tablist">${tabs.map((t, i) => `<button type="button" role="tab" data-k="${t.key}" aria-selected="${i === 0}">${esc(t.label)}<small>${esc(t.sub)}</small></button>`).join("")}</div>
    ${d.veto ? `<p class="mx-veto">${esc(d.veto)}</p>` : ""}<div class="mx-pane"></div>`;
  const pane = $(".mx-pane", body);
  // Exibe a aba escolhida (série inteira ou um mapa).
  const show = (key) => {
    body.querySelectorAll(".mx-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.k === key)));
    pane.innerHTML = "";
    if (key === "total") renderTotal(pane, d); else renderMap(pane, d, d.maps[Number(key)]);
  };
  $(".mx-tabs", body).onclick = (e) => { const b = e.target.closest("button[data-k]"); if (b) show(b.dataset.k); };
  const gi = det.dataset.game ? d.maps.findIndex((g) => String(g.game_id) === det.dataset.game) : -1;
  const start = gi >= 0 ? String(gi + 1) : det.dataset.tab;
  show(start && (start === "total" || d.maps[Number(start) - 1]) ? (start === "total" ? start : String(Number(start) - 1)) : d.maps.length === 1 ? "0" : "total");
}

// Retorna id e nome do time 1 ou 2 da partida.
const teamOf = (d, n) => (n === 1 ? { id: d.team1_id, name: d.match.team1_name } : { id: d.team2_id, name: d.match.team2_name });

// Mostra o resumo da série com placares, tabelas e X1.
function renderTotal(pane, d) {
  const maps = d.maps.map((g) => {
    const w = g.team1_score > g.team2_score ? 1 : g.team2_score > g.team1_score ? 2 : 0;
    return `<div class="mx-mapsum"><b>${esc(g.map_name)}</b><span class="${w === 1 ? "win" : ""}">${g.team1_score ?? "-"}</span><i>:</i><span class="${w === 2 ? "win" : ""}">${g.team2_score ?? "-"}</span>
      ${g.picked_by ? `<small>pick de ${esc(teamOf(d, g.picked_by === d.team1_id ? 1 : 2).name)}</small>` : "<small>decider</small>"}</div>`;
  }).join("");
  pane.innerHTML = `<div class="mx-mapsums">${maps}</div><div class="mx-boards"></div><div class="mx-x1"></div>`;
  scoreboards($(".mx-boards", pane), d, d.total.players);
  x1($(".mx-x1", pane), d, d.total.matrix, "na série");
}

// Mostra os detalhes de um mapa com placar, cronologia, tabelas e X1.
function renderMap(pane, d, g) {
  // Gera o placar de ataque, defesa e prorrogação de um time.
  const half = (n) => {
    const atk = g[`team${n}_atk`], dfn = g[`team${n}_def`], ot = g[`team${n}_ot`];
    return `<span class="side-atk">${atk ?? "-"}</span> · <span class="side-def">${dfn ?? "-"}</span>${ot ? ` · <span>${ot} OT</span>` : ""}`;
  };
  const t1 = teamOf(d, 1), t2 = teamOf(d, 2);
  const dur = g.duration_sec ? `${Math.floor(g.duration_sec / 60)}:${String(g.duration_sec % 60).padStart(2, "0")}` : "";
  const pick = g.picked_by ? `pick de ${esc(g.picked_by === t1.id ? t1.name : t2.name)}` : "decider";
  pane.innerHTML = `<div class="mx-maphead">
      <div class="mx-mh-team${g.winner_id === t1.id ? " win" : ""}">${teamLogo(t1.id, t1.name, "md")}<div><b>${esc(t1.name)}</b><small>${half(1)}</small></div><strong>${g.team1_score ?? "-"}</strong></div>
      <div class="mx-mh-map"><b>${esc(g.map_name)}</b><small>${pick}${dur ? ` · ${dur}` : ""}</small></div>
      <div class="mx-mh-team r${g.winner_id === t2.id ? " win" : ""}"><strong>${g.team2_score ?? "-"}</strong><div><b>${esc(t2.name)}</b><small>${half(2)}</small></div>${teamLogo(t2.id, t2.name, "md")}</div>
    </div>
    <div class="mx-tl"></div><div class="mx-boards"></div><div class="mx-x1"></div>`;
  timeline($(".mx-tl", pane), d, g);
  scoreboards($(".mx-boards", pane), d, g.players);
  x1($(".mx-x1", pane), d, g.matrix, `em ${g.map_name}`);
}

// Desenha a cronologia de rounds vencidos por cada time.
function timeline(el, d, g) {
  if (!g.rounds.length) { el.innerHTML = `<p class="hint">Cronologia de rounds indisponível para este mapa.</p>`; return; }
  // Gera as células de rounds de um time.
  const cells = (n) => g.rounds.map((r) => {
    const gap = r.n === 13 || (r.n > 24 && r.n % 2 === 1) ? " gap" : "";
    if (r.winner !== n) return `<span class="tl-c${gap}"></span>`;
    const wt = WIN_TYPES[r.type] || WIN_TYPES.elim;
    const who = teamOf(d, n).name;
    return `<span class="tl-c won ${r.side}${gap}" title="Round ${r.n} · ${esc(who)} venceu no ${SIDE[r.side] || r.side} por ${wt.label} · placar ${esc(r.score || "")}"><svg viewBox="0 0 16 16" aria-hidden="true">${wt.icon}</svg></span>`;
  }).join("");
  const nums = g.rounds.map((r) => `<span class="tl-c num${r.n === 13 || (r.n > 24 && r.n % 2 === 1) ? " gap" : ""}">${r.n}</span>`).join("");
  const label = (n) => { const t = teamOf(d, n); return `<span class="tl-team">${teamLogo(t.id, t.name)}<b>${esc(t.name)}</b></span>`; };
  el.innerHTML = `<div class="mx-sub"><h4>Cronologia dos rounds</h4>
      <span class="tl-legend"><i class="atk"></i>vencido no ataque <i class="def"></i>vencido na defesa ${Object.values(WIN_TYPES).map((w) => `<svg viewBox="0 0 16 16" aria-hidden="true">${w.icon}</svg>${w.label}`).join(" ")}</span></div>
    <div class="tl-scroll"><div class="tl-grid">
      ${label(1)}<div class="tl-row">${cells(1)}</div>
      ${label(2)}<div class="tl-row">${cells(2)}</div>
      <span></span><div class="tl-row">${nums}</div>
    </div></div>`;
}

// Monta as tabelas de abates dos dois times.
function scoreboards(el, d, players) {
  const cols = [
    { key: "player_name", label: "Jogador", l: true, html: (r) => playerLink(r.player_id, r.player_name) },
    { key: "agent", label: "Agente", l: true, html: (r) => esc((r.agents || [r.agent]).filter(Boolean).map(agentName).join(", ") || "—") },
    { key: "rating", label: "Rating", fmt: fmt.n2 }, { key: "acs", label: "ACS", fmt: fmt.int },
    { key: "k", label: "K", fmt: fmt.int }, { key: "d", label: "D", fmt: fmt.int }, { key: "a", label: "A", fmt: fmt.int },
    { key: "pm", label: "+/–", html: (r) => { const v = (r.k || 0) - (r.d || 0); return `<span class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${v > 0 ? "+" : ""}${v}</span>`; } },
    { key: "kast", label: "KAST", fmt: fmt.hs }, { key: "adr", label: "ADR", fmt: fmt.int }, { key: "hs", label: "HS%", fmt: fmt.hs },
    { key: "fk", label: "FK", fmt: fmt.int, title: "First kills" }, { key: "fd", label: "FD", fmt: fmt.int, title: "First deaths" },
  ];
  el.innerHTML = `<div class="mx-sub"><h4>Tabela de abates</h4></div><div class="mx-board-grid"></div>`;
  const grid = $(".mx-board-grid", el);
  for (const n of [1, 2]) {
    const t = teamOf(d, n);
    const rows = players.filter((p) => p.team_id === t.id).map((p) => ({ ...p, pm: (p.k || 0) - (p.d || 0) }));
    const box = document.createElement("div");
    box.className = "mx-board";
    box.innerHTML = `<div class="mx-board-head">${teamLogo(t.id, t.name)}<b>${esc(t.name)}</b></div>`;
    box.append(table(cols, rows, { rank: false, sortKey: "acs" }));
    grid.append(box);
  }
}

// Monta a matriz de X1 entre os jogadores dos dois times.
function x1(el, d, matrix, where) {
  const kinds = X1_KINDS.filter(([k]) => matrix && matrix[k]);
  if (!kinds.length) { el.innerHTML = `<div class="mx-sub"><h4>X1 entre jogadores</h4></div><p class="hint">Matriz de abates indisponível para esta partida.</p>`; return; }
  const t1 = teamOf(d, 1), t2 = teamOf(d, 2);
  el.innerHTML = `<div class="mx-sub"><h4>X1 entre jogadores</h4>
      <div class="segmented sm" role="group" aria-label="Tipo de abate">${kinds.map(([k, l], i) => `<button type="button" data-k="${k}" class="${i ? "" : "on"}">${l}</button>`).join("")}</div></div>
    <p class="hint">Cada célula: abates do jogador da linha (${esc(t1.name)}) sobre o da coluna (${esc(t2.name)}) e, embaixo, quantas vezes morreu para ele ${esc(where)}. O saldo colore a célula.</p>
    <div class="x1-wrap"></div>`;
  // Desenha a matriz para o tipo de abate escolhido.
  const draw = (k) => {
    const mx = matrix[k];
    const nm = (p) => (p.player_id ? `<a href="#/jogador/${p.player_id}">${esc(p.name)}</a>` : esc(p.name));
    const peak = Math.max(1, ...mx.kills.flatMap((row, i) => row.map((v, j) => Math.abs(v - mx.deaths[i][j]))));
    $(".x1-wrap", el).innerHTML = `<table class="x1"><thead><tr><th class="x1-corner">${teamLogo(t1.id, t1.name)}<span>×</span>${teamLogo(t2.id, t2.name)}</th>${mx.cols.map((c) => `<th>${nm(c)}</th>`).join("")}<th class="x1-tot">Saldo</th></tr></thead>
      <tbody>${mx.rows.map((r, i) => {
        let net = 0;
        const tds = mx.cols.map((c, j) => {
          const kv = mx.kills[i][j], dv = mx.deaths[i][j], diff = kv - dv;
          net += diff;
          const a = Math.round((Math.abs(diff) / peak) * 38);
          const bg = diff ? `style="--x1:${diff > 0 ? "var(--good)" : "var(--red)"};--x1a:${a}%"` : "";
          return `<td class="x1-c${diff > 0 ? " pos" : diff < 0 ? " neg" : ""}" ${bg} title="${esc(r.name)} matou ${esc(c.name)} ${kv} ${kv === 1 ? "vez" : "vezes"} e morreu para ele ${dv} ${dv === 1 ? "vez" : "vezes"}"><b>${kv}</b><small>${dv}</small><i>${diff > 0 ? "+" : ""}${diff}</i></td>`;
        }).join("");
        return `<tr><th>${nm(r)}</th>${tds}<td class="x1-tot ${net > 0 ? "pos" : net < 0 ? "neg" : ""}">${net > 0 ? "+" : ""}${net}</td></tr>`;
      }).join("")}</tbody></table>`;
  };
  $(".segmented", el).onclick = (e) => {
    const b = e.target.closest("button[data-k]");
    if (!b) return;
    el.querySelectorAll(".segmented button").forEach((x) => x.classList.toggle("on", x === b));
    draw(b.dataset.k);
  };
  draw(kinds[0][0]);
}
