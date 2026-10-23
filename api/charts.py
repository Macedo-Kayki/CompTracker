from __future__ import annotations

import io
import threading
from functools import lru_cache

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator, PercentFormatter

from matplotlib.image import imread
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from api import logos, stats
from api.store import Filters, store

THEMES = {
    "dark": {
        "surface": "#1c1b1a", "text": "#f9f9f9", "text2": "#c5c5c3", "muted": "#8a8887",
        "grid": "#2b2a29", "axis": "#403f3e", "main": "#dbd9d6",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
        "atk": "#e66767", "def": "#3987e5",
        "seq": ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
    },
    "light": {
        "surface": "#f9f9f9", "text": "#0a0a0a", "text2": "#656462", "muted": "#8a8887",
        "grid": "#e7e6e3", "axis": "#adacaa", "main": "#2b2a29",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
        "atk": "#e34948", "def": "#2a78d6",
        "seq": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    },
}
EVENT_ORDER = ["Champions", "Masters", "Liga", "Qualificatória", "Ascension", "Kickoff", "Challengers", "Outros"]
EVENT_COLORS = {
    "light": dict(zip(EVENT_ORDER, ["#c28f2c", "#7c4ddb", "#d1363a", "#2a78d6", "#c2418f", "#e8743b", "#16a085", "#8a8887"])),
    "dark": dict(zip(EVENT_ORDER, ["#b8892a", "#9a7cf0", "#e05558", "#3d8ae8", "#d2509b", "#d9622a", "#13997f", "#8a8887"])),
}
for _mode, _theme in THEMES.items():
    _theme["events"] = EVENT_COLORS[_mode]

FONT = ["Segoe UI", "DejaVu Sans", "Arial", "sans-serif"]
DPI = 110
_lock = threading.Lock()
pct = PercentFormatter(1.0, decimals=0)


def _short(name, n=24):
    """Encurta um nome longo, preferindo o texto entre parênteses quando cabe."""
    name = str(name)
    if len(name) <= n:
        return name
    if name.endswith(")") and "(" in name:
        inner = name[name.rfind("(") + 1:-1]
        if len(inner) <= n:
            return inner
    return name[: n - 1].rstrip() + "…"


def _compact(v, _pos=None):
    """Formata números grandes de forma compacta (K, M) para eixos."""
    v = float(v)
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M".replace(".0M", "M")
    if abs(v) >= 1e3:
        return f"{v / 1e3:.1f}K".replace(".0K", "K")
    return f"{v:.0f}"


_render = threading.local()


def _fig(t, w=8.0, h=4.2):
    """Cria uma figura matplotlib com o fundo do tema, mais larga se pedido."""
    if getattr(_render, "wide", False):
        w *= 1.55
    fig = Figure(figsize=(w, h), dpi=DPI, facecolor=t["surface"])
    FigureCanvasAgg(fig)
    return fig


def _titles(fig, t, title=None, subtitle=None):
    """Escreve título e subtítulo no topo da figura."""
    h = fig.get_figheight()
    texts = []
    if title:
        texts.append(fig.text(0, 1 - 0.08 / h, title.upper(), ha="left", va="top", fontsize=13,
                              fontweight="heavy", color=t["text"]))
    if subtitle:
        texts.append(fig.text(0, 1 - 0.40 / h, subtitle, ha="left", va="top", fontsize=9.5, color=t["text2"]))
    fig._ct_texts = texts


def _ax(fig, t, title=None, subtitle=None):
    """Cria o eixo principal estilizado conforme o tema, com título."""
    _titles(fig, t, title, subtitle)
    ax = fig.add_subplot(111)
    ax.set_facecolor(t["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["axis"])
        ax.spines[side].set_linewidth(1)
    ax.tick_params(colors=t["muted"], labelsize=9, length=0, pad=6)
    ax.grid(True, color=t["grid"], linewidth=1, linestyle="-")
    ax.set_axisbelow(True)
    return ax


def _png(fig, legend=False, top=None, legend_rows=1) -> bytes:
    """Ajusta margens, alinha os títulos e renderiza a figura em PNG."""
    h = fig.get_figheight()
    fig.subplots_adjust(top=top if top is not None else 1 - (0.74 + (0.30 * legend_rows if legend else 0)) / h)
    texts = getattr(fig, "_ct_texts", [])
    if texts and fig.axes:
        renderer = fig.canvas.get_renderer()
        x0 = min(ax.get_tightbbox(renderer).x0 for ax in fig.axes) / fig.bbox.width
        for txt in texts:
            txt.set_x(x0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.18)
    return buf.getvalue()


def _empty(t, msg="Sem dados para o filtro atual") -> bytes:
    """Renderiza uma imagem PNG com a mensagem de sem dados."""
    fig = _fig(t, 8, 2.2)
    fig.text(0.5, 0.5, msg, ha="center", va="center", fontsize=11, color=t["text2"])
    return _png(fig, top=1.0)


def _legend(ax, t, handles=None, labels=None, ncol=4):
    """Adiciona a legenda estilizada acima do eixo."""
    kw = dict(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=ncol, frameon=False, fontsize=9,
              labelcolor=t["text2"], handlelength=1.0, handleheight=1.0, columnspacing=1.4, borderaxespad=0.3)
    leg = ax.legend(handles, labels, **kw) if handles else ax.legend(**kw)
    return leg


def _barh(ax, t, labels, values, colors, fmt, xmax=None, extra=None):
    """Desenha barras horizontais com rótulos de valor ao lado."""
    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, height=0.62, color=colors, linewidth=0)
    ax.set_yticks(y, labels, color=t["text2"], fontsize=9.5)
    ax.grid(axis="y", visible=False)
    vmax = xmax or (np.nanmax(values) if len(values) else 1)
    ax.set_xlim(0, vmax * 1.16 if vmax > 0 else 1)
    for i, v in enumerate(values):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        txt = fmt(v) + (f"  {extra[i]}" if extra is not None else "")
        ax.text(v + vmax * 0.012, y[i], txt, va="center", ha="left", fontsize=8.5, color=t["text2"])
    ax.spines["left"].set_visible(False)


def _team_logos(ax, y, team_ids, size_px=16):
    """Desenha os logos dos times ao lado dos rótulos do eixo Y."""
    ax.tick_params(axis="y", pad=size_px + 10)
    for yi, tid in zip(y, team_ids):
        path = logos.team_logo_path(tid, getattr(_render, "theme", None))
        if not path:
            continue
        try:
            img = imread(path)
        except Exception:
            continue
        zoom = size_px / max(img.shape[0], img.shape[1]) * 72 / DPI
        box = AnnotationBbox(OffsetImage(img, zoom=zoom), (0, yi), xycoords=("axes fraction", "data"),
                             xybox=(-(size_px / 2 + 4), 0), boxcoords="offset points", frameon=False, pad=0)
        ax.add_artist(box)


def _ramp(t):
    """Cria o colormap sequencial do tema."""
    return LinearSegmentedColormap.from_list("seq", t["seq"])


def _ink_on(color_rgb, t):
    """Escolhe texto claro ou escuro conforme a luminância da cor de fundo."""
    r, g, b = color_rgb[:3]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#0b0b0b" if lum > 0.55 else "#f6f6f4"


def _pct_label(v):
    """Formata uma fração como porcentagem, usando "<1%" para valores pequenos."""
    return "<1%" if 0 < v < 0.005 else f"{v:.0%}"


def _annotate_sparse(ax, xs, ys, labels, t, max_labels=10):
    """Anota pontos do gráfico de dispersão evitando rótulos sobrepostos."""
    placed = []
    to_axes = ax.transData + ax.transAxes.inverted()
    for x, y, lab in list(zip(xs, ys, labels))[:max_labels * 3]:
        ax_x, ax_y = to_axes.transform((x, y))
        if any(abs(ax_x - px) < 0.16 and abs(ax_y - py) < 0.045 for px, py in placed):
            continue
        placed.append((ax_x, ax_y))
        ax.annotate(lab, (x, y), xytext=(5, 4), textcoords="offset points", fontsize=8, color=t["text2"])
        if len(placed) >= max_labels:
            break


def _heatmap(fig, ax, t, pivot: pd.DataFrame):
    """Desenha um mapa de calor com seaborn e porcentagens em cada célula."""
    ax.set_facecolor(t["surface"])
    cmap = _ramp(t)
    sns.heatmap(pivot, ax=ax, cmap=cmap, cbar=False, linewidths=2, linecolor=t["surface"], annot=False)
    vmin, vmax = np.nanmin(pivot.values), np.nanmax(pivot.values)
    for (i, j), v in np.ndenumerate(pivot.values):
        if np.isnan(v):
            continue
        rgb = cmap((v - vmin) / (vmax - vmin) if vmax > vmin else 0.5)
        ax.text(j + 0.5, i + 0.5, _pct_label(v), ha="center", va="center", fontsize=8, color=_ink_on(rgb, t))
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(colors=t["text2"], labelsize=9, length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)


def matches_by_year(f, t, **_):
    """Desenha o gráfico de partidas por ano."""
    mf = f.apply(store["matches_fact"])
    if mf.empty:
        return _empty(t)
    s = mf.groupby("year").size()
    fig = _fig(t, 8, 3.8)
    ax = _ax(fig, t, "Partidas por ano", "Partidas concluídas no filtro atual")
    ax.bar(s.index.astype(str), s.values, width=0.55, color=t["main"], linewidth=0)
    for x, v in zip(s.index.astype(str), s.values):
        ax.text(x, v, f"{v:,}".replace(",", "."), ha="center", va="bottom", fontsize=9, color=t["text2"])
    ax.set_ylim(0, s.max() * 1.14)
    ax.yaxis.set_major_formatter(FuncFormatter(_compact))
    ax.grid(axis="x", visible=False)
    return _png(fig)


def matches_by_tier(f, t, **_):
    """Desenha o gráfico de partidas por ano empilhadas por tier."""
    mf = f.apply(store["matches_fact"])
    if mf.empty:
        return _empty(t)
    p = mf.groupby(["year", "tier"]).size().unstack(fill_value=0).reindex(columns=[1, 2, 3], fill_value=0)
    fig = _fig(t, 8, 3.8)
    ax = _ax(fig, t, "Partidas por ano e tier", "Tier 1 = VCT · Tier 2 = Challengers/Ascension · Tier 3 = prêmio ≥ US$ 5 mil")
    x = p.index.astype(str)
    bottom = np.zeros(len(p))
    gap = p.sum(axis=1).max() * 0.006
    for i, tier in enumerate(p.columns):
        vals = p[tier].to_numpy(dtype=float)
        ax.bar(x, vals, bottom=bottom, width=0.55, color=t["series"][i], label=f"Tier {tier}", linewidth=0)
        bottom = bottom + vals + np.where(vals > 0, gap, 0)
    for xi, tot, top in zip(x, p.sum(axis=1), bottom):
        ax.text(xi, top, f"{int(tot):,}".replace(",", "."), ha="center", va="bottom", fontsize=9, color=t["text2"])
    ax.set_ylim(0, bottom.max() * 1.14)
    ax.yaxis.set_major_formatter(FuncFormatter(_compact))
    ax.grid(axis="x", visible=False)
    _legend(ax, t, ncol=3)
    return _png(fig, legend=True)


def side_by_year(f, t, **_):
    """Desenha a linha de % de rounds vencidos por ataque e defesa a cada ano."""
    mc = f.apply(store["map_cube"])
    if mc.empty:
        return _empty(t)
    g = mc.groupby("year")[["atk_won", "def_won"]].sum()
    g["atk"] = g["atk_won"] / (g["atk_won"] + g["def_won"])
    g["def"] = 1 - g["atk"]
    fig = _fig(t, 8, 3.8)
    ax = _ax(fig, t, "Lado que mais vence rounds", "% dos rounds do tempo regulamentar vencidos por lado")
    x = g.index.astype(str)
    for key, label in (("atk", "Ataque"), ("def", "Defesa")):
        ax.plot(x, g[key], color=t[key], linewidth=2, marker="o", markersize=7,
                markeredgecolor=t["surface"], markeredgewidth=2, label=label, solid_capstyle="round")
        ax.text(len(x) - 1 + 0.12, g[key].iloc[-1], f"{label} {g[key].iloc[-1]:.1%}", va="center",
                fontsize=9, color=t["text2"])
    ax.axhline(0.5, color=t["axis"], linewidth=1)
    lo = min(g["atk"].min(), g["def"].min())
    hi = max(g["atk"].max(), g["def"].max())
    ax.set_ylim(min(0.44, lo - 0.01), max(0.56, hi + 0.01))
    ax.set_xlim(-0.3, len(x) - 1 + 0.9)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(axis="x", visible=False)
    _legend(ax, t, ncol=2)
    return _png(fig, legend=True)


def win_types(f, t, **_):
    """Desenha a participação de cada tipo de vitória de round por lado."""
    rc = f.apply(store["round_cube"])
    if rc.empty:
        return _empty(t)
    names = {("atk", "elim"): "Ataque · eliminação", ("atk", "boom"): "Ataque · spike detonada",
             ("def", "elim"): "Defesa · eliminação", ("def", "defuse"): "Defesa · spike desarmada",
             ("def", "time"): "Defesa · tempo esgotado"}
    g = rc.groupby(["winner_side", "win_type"])["rounds"].sum()
    total = g.sum()
    rows = [(names[k], g.get(k, 0) / total, k[0]) for k in names]
    fig = _fig(t, 8, 3.4)
    ax = _ax(fig, t, "Como os rounds são vencidos", "Participação de cada tipo de vitória no total de rounds")
    _barh(ax, t, [r[0] for r in rows], [r[1] for r in rows], [t[r[2]] for r in rows], lambda v: f"{v:.1%}")
    ax.xaxis.set_major_formatter(pct)
    from matplotlib.patches import Patch
    _legend(ax, t, [Patch(color=t["atk"]), Patch(color=t["def"])], ["Ataque", "Defesa"], ncol=2)
    return _png(fig, legend=True)


def titles_top(f, t, limit=15, **_):
    """Desenha o ranking dos times com mais títulos, por tipo de evento."""
    ti = stats.titles(f)
    if ti.empty:
        return _empty(t, "Nenhum título no filtro atual")
    g = ti.groupby(["champion_name", "event_type"]).size().unstack(fill_value=0)
    types = [c for c in EVENT_ORDER if c in g.columns]
    g["total"] = g[types].sum(axis=1)
    intl = [c for c in ("Champions", "Masters") if c in g.columns]
    g["_intl"] = g[intl].sum(axis=1) if intl else 0
    g = g.sort_values(["total", "_intl"], ascending=False).head(int(limit))
    fig = _fig(t, 8, 0.36 * len(g) + 1.6)
    ax = _ax(fig, t, "Times com mais títulos", "Campeão de cada evento concluído (1º lugar), por tipo de evento")
    y = np.arange(len(g))[::-1]
    tmax = g["total"].max()
    left = np.zeros(len(g))
    gap = tmax * 0.004
    for ty in types:
        vals = g[ty].to_numpy(dtype=float)
        ax.barh(y, vals, left=left, height=0.62, color=t["events"][ty], label=ty, linewidth=0)
        left = left + vals + np.where(vals > 0, gap, 0)
    for yi, tot, end in zip(y, g["total"], left):
        ax.text(end + tmax * 0.012, yi, str(int(tot)), va="center", fontsize=8.5, color=t["text2"])
    ax.set_xlim(0, left.max() * 1.1)
    ax.set_yticks(y, [_short(n) for n in g.index], color=t["text2"], fontsize=9.5)
    ids = ti.drop_duplicates("champion_name").set_index("champion_name")["champion_id"]
    _team_logos(ax, y, [ids.get(n) for n in g.index])
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    _legend(ax, t, ncol=4)
    return _png(fig, legend=True, legend_rows=(len(types) + 3) // 4)


def intl_titles_region(f, t, **_):
    """Desenha os títulos internacionais (Masters/Champions) por região."""
    ti = stats.titles(f)
    ti = ti[ti["event_type"].isin(stats.INTERNATIONAL_TYPES)]
    if ti.empty:
        return _empty(t, "Nenhum título internacional no filtro atual")
    reg = store["dim_teams"].set_index("team_id")["team_region"]
    g = (ti.assign(team_region=ti["champion_id"].map(reg).fillna("Outros"))
           .groupby(["team_region", "event_type"]).size().unstack(fill_value=0))
    types = [c for c in ("Champions", "Masters") if c in g.columns]
    g["total"] = g[types].sum(axis=1)
    g = g.sort_values("total", ascending=False)
    fig = _fig(t, 8, 0.4 * len(g) + 1.6)
    ax = _ax(fig, t, "Títulos internacionais por região", "Masters e Champions, pela região do time campeão")
    y = np.arange(len(g))[::-1]
    left = np.zeros(len(g))
    tmax = g["total"].max()
    for ty in types:
        vals = g[ty].to_numpy(dtype=float)
        ax.barh(y, vals, left=left, height=0.62, color=t["events"][ty], label=ty, linewidth=0)
        left = left + vals + np.where(vals > 0, tmax * 0.004, 0)
    for yi, tot, end in zip(y, g["total"], left):
        ax.text(end + tmax * 0.012, yi, str(int(tot)), va="center", fontsize=8.5, color=t["text2"])
    ax.set_yticks(y, list(g.index), color=t["text2"], fontsize=9.5)
    ax.set_xlim(0, left.max() * 1.12)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    _legend(ax, t, ncol=2)
    return _png(fig, legend=True)


def team_winrate(f, t, min_maps=40, team_region=None, limit=20, **_):
    """Desenha o ranking de win rate de mapas dos melhores times."""
    df = stats.team_table(f, team_region=team_region, min_maps=int(min_maps))
    if df.empty:
        return _empty(t, "Nenhum time com o mínimo de mapas")
    df = df.sort_values("map_wr", ascending=False).head(int(limit))
    fig = _fig(t, 8, 0.34 * len(df) + 1.3)
    ax = _ax(fig, t, "Win rate de mapas — melhores times", f"Mínimo de {min_maps} mapas no filtro atual")
    _barh(ax, t, [_short(n) for n in df["team_name"]], list(df["map_wr"]), t["main"], lambda v: f"{v:.1%}",
          xmax=1, extra=[f"({int(m)} mapas)" for m in df["maps"]])
    _team_logos(ax, np.arange(len(df))[::-1], df["team_id"])
    ax.xaxis.set_major_formatter(pct)
    return _png(fig)


def team_sides(f, t, min_maps=40, team_region=None, **_):
    """Desenha o gráfico de dispersão de rounds vencidos no ataque versus defesa por time."""
    df = stats.team_table(f, team_region=team_region, min_maps=int(min_maps)).dropna(subset=["atk_wr", "def_wr"])
    if df.empty:
        return _empty(t, "Nenhum time com o mínimo de mapas")
    fig = _fig(t, 8, 5.4)
    ax = _ax(fig, t, "Força no ataque × defesa", f"% de rounds vencidos em cada lado · times com {min_maps}+ mapas")
    sns.scatterplot(data=df, x="atk_wr", y="def_wr", ax=ax, s=55, color=t["main"],
                    edgecolor=t["surface"], linewidth=1.5, alpha=0.9)
    lo = min(df["atk_wr"].min(), df["def_wr"].min()) - 0.02
    hi = max(df["atk_wr"].max(), df["def_wr"].max()) + 0.02
    ax.plot([lo, hi], [lo, hi], color=t["axis"], linewidth=1)
    ax.text(hi, hi, " ataque = defesa", fontsize=8, color=t["muted"], va="bottom", ha="right")
    fig.canvas.draw()
    top = df.assign(score=df["atk_wr"] + df["def_wr"]).sort_values("score", ascending=False)
    _annotate_sparse(ax, top["atk_wr"], top["def_wr"], [_short(n, 18) for n in top["team_name"]], t, max_labels=10)
    ax.set_xlabel("Rounds vencidos no ataque", color=t["muted"], fontsize=9)
    ax.set_ylabel("Rounds vencidos na defesa", color=t["muted"], fontsize=9)
    ax.xaxis.set_major_formatter(pct)
    ax.yaxis.set_major_formatter(pct)
    return _png(fig)


def team_year(f, t, team_id=None, **_):
    """Desenha o win rate de séries e mapas de um time por ano."""
    if team_id is None:
        return _empty(t, "Selecione um time")
    d = stats.team_detail(int(team_id), f)
    by = pd.DataFrame(d.get("by_year", []))
    if by.empty:
        return _empty(t)
    fig = _fig(t, 8, 3.6)
    ax = _ax(fig, t, "Desempenho por ano", "Win rate de séries (partidas) e de mapas")
    x = np.arange(len(by))
    w = 0.34
    ax.bar(x - w / 2 - 0.01, by["match_wr"], width=w, color=t["series"][0], label="Partidas", linewidth=0)
    ax.bar(x + w / 2 + 0.01, by["map_wr"], width=w, color=t["series"][1], label="Mapas", linewidth=0)
    for xi, a, b in zip(x, by["match_wr"], by["map_wr"]):
        ax.text(xi - w / 2, a, f"{a:.0%}", ha="center", va="bottom", fontsize=8, color=t["text2"])
        ax.text(xi + w / 2, b, f"{b:.0%}", ha="center", va="bottom", fontsize=8, color=t["text2"])
    ax.set_xticks(x, by["year"].astype(int).astype(str))
    ax.set_ylim(0, 1.08)
    ax.yaxis.set_major_formatter(pct)
    ax.grid(axis="x", visible=False)
    _legend(ax, t, ncol=2)
    return _png(fig, legend=True)


def team_maps(f, t, team_id=None, **_):
    """Desenha os rounds vencidos por mapa e lado de um time."""
    if team_id is None:
        return _empty(t, "Selecione um time")
    by = pd.DataFrame(stats.team_detail(int(team_id), f).get("by_map", []))
    if by.empty:
        return _empty(t)
    by = by[by["maps"] >= 1].sort_values("maps", ascending=False).head(12)
    fig = _fig(t, 8, 0.5 * len(by) + 1.4)
    ax = _ax(fig, t, "Rounds vencidos por mapa e lado", "Rótulo: win rate do mapa e número de mapas jogados")
    y = np.arange(len(by))[::-1]
    h = 0.34
    ax.barh(y + h / 2 + 0.01, by["atk_wr"], height=h, color=t["atk"], label="Ataque", linewidth=0)
    ax.barh(y - h / 2 - 0.01, by["def_wr"], height=h, color=t["def"], label="Defesa", linewidth=0)
    for yi, r in zip(y, by.itertuples()):
        m = max(r.atk_wr if not pd.isna(r.atk_wr) else 0, r.def_wr if not pd.isna(r.def_wr) else 0)
        ax.text(m + 0.01, yi, f"mapa {r.map_wr:.0%} · {int(r.maps)}", va="center", fontsize=8, color=t["text2"])
    ax.set_yticks(y, by["map_name"], color=t["text2"], fontsize=9.5)
    ax.set_xlim(0, 1)
    ax.axvline(0.5, color=t["axis"], linewidth=1)
    ax.xaxis.set_major_formatter(pct)
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    _legend(ax, t, ncol=2)
    return _png(fig, legend=True)


def team_players(f, t, team_id=None, min_maps=5, **_):
    """Desenha o ranking de rating dos jogadores de um time."""
    if team_id is None:
        return _empty(t, "Selecione um time")
    df = stats.player_table(f, team_id=int(team_id), min_maps=int(min_maps)).dropna(subset=["rating"]).head(12)
    if df.empty:
        return _empty(t)
    fig = _fig(t, 8, 0.36 * len(df) + 1.3)
    ax = _ax(fig, t, "Melhores jogadores do time", f"Rating médio por round · mínimo de {min_maps} mapas pelo time")
    _barh(ax, t, list(df["player_name"]), list(df["rating"]), t["main"], lambda v: f"{v:.2f}",
          extra=[f"({int(m)} mapas)" for m in df["maps"]])
    return _png(fig)


def h2h_maps(f, t, team_a=None, team_b=None, **_):
    """Desenha o placar de vitórias no confronto direto entre dois times."""
    if team_a is None or team_b is None:
        return _empty(t, "Selecione dois times")
    a, b = int(team_a), int(team_b)
    pair = pd.DataFrame(stats.head_to_head(a, b, f)["matches"])
    if pair.empty:
        return _empty(t, "Os times não se enfrentaram no filtro atual")
    dim = store["dim_teams"].set_index("team_id")["team_name"]
    s = pd.Series({dim.get(a, a): int((pair["winner_id"] == a).sum()), dim.get(b, b): int((pair["winner_id"] == b).sum())})
    fig = _fig(t, 8, 2.0)
    ax = _ax(fig, t, "Confronto direto", f"{len(pair)} séries no filtro atual")
    _barh(ax, t, list(s.index), list(s.values), [t["series"][0], t["series"][1]], lambda v: f"{int(v)} vitórias")
    _team_logos(ax, np.arange(2)[::-1], [a, b])
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    return _png(fig)


def player_top(f, t, metric="rating", min_maps=20, team_region=None, limit=20, **_):
    """Desenha o ranking de jogadores pela métrica escolhida."""
    label, col = stats.PLAYER_METRICS.get(metric, stats.PLAYER_METRICS["rating"])
    df = stats.player_ranking(f, metric, int(min_maps), team_region=team_region, limit=int(limit)).dropna(subset=[col])
    if df.empty:
        return _empty(t, "Nenhum jogador com o mínimo de mapas")
    is_pct = col in ("hs", "kast")
    is_float = col in ("rating", "kd", "kpr")
    fmt = (lambda v: f"{v:.1f}%") if is_pct else (lambda v: f"{v:.2f}") if is_float else (lambda v: f"{v:,.0f}".replace(",", "."))
    names = [f"{p}  ·  {_short(tm, 20)}" if isinstance(tm, str) else p for p, tm in zip(df["player_name"], df["team_name"])]
    fig = _fig(t, 8, 0.34 * len(df) + 1.3)
    ax = _ax(fig, t, f"Top {len(df)} — {label}", f"Mínimo de {min_maps} mapas no filtro atual · time onde mais jogou")
    _barh(ax, t, names, list(df[col]), t["main"], fmt)
    _team_logos(ax, np.arange(len(df))[::-1], df["team_id"], size_px=14)
    if not (is_pct or is_float):
        ax.xaxis.set_major_formatter(FuncFormatter(_compact))
    return _png(fig)


def _stacked_players(f, t, cols, labels, title, subtitle, min_maps, team_region, team_id, limit):
    """Desenha barras empilhadas por jogador somando as colunas informadas."""
    df = stats.player_table(f, team_id=team_id, team_region=team_region, min_maps=int(min_maps))
    if df.empty:
        return _empty(t)
    df = df.assign(_tot=df[cols].sum(axis=1)).sort_values("_tot", ascending=False).head(int(limit))
    df = df[df["_tot"] > 0]
    if df.empty:
        return _empty(t, "Sem dados de performance para o filtro atual")
    fig = _fig(t, 8, 0.36 * len(df) + 1.4)
    ax = _ax(fig, t, title, subtitle)
    y = np.arange(len(df))[::-1]
    left = np.zeros(len(df))
    gap = df["_tot"].max() * 0.004
    for i, (c, lab) in enumerate(zip(cols, labels)):
        vals = df[c].to_numpy(dtype=float)
        ax.barh(y, vals, left=left, height=0.62, color=t["series"][i], label=lab, linewidth=0)
        left = left + vals + np.where(vals > 0, gap, 0)
    for yi, tot, end in zip(y, df["_tot"], left):
        ax.text(end + df["_tot"].max() * 0.01, yi, f"{int(tot):,}".replace(",", "."), va="center", fontsize=8.5, color=t["text2"])
    names = [f"{p}  ·  {_short(tm, 20)}" if isinstance(tm, str) else p for p, tm in zip(df["player_name"], df["team_name"])]
    ax.set_yticks(y, names, color=t["text2"], fontsize=9.5)
    _team_logos(ax, y, df["team_id"], size_px=14)
    ax.set_xlim(0, left.max() * 1.1)
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    _legend(ax, t, ncol=len(cols))
    return _png(fig, legend=True)


def player_multikills(f, t, min_maps=0, team_region=None, team_id=None, limit=15, **_):
    """Desenha o ranking de multikills (2K a 5K) por jogador."""
    return _stacked_players(f, t, ["k2", "k3", "k4", "k5"], ["2K (duas)", "3K (triple)", "4K (quadra)", "5K (ace)"],
                            "Multikills", "Rounds com 2+ abates do mesmo jogador", min_maps, team_region,
                            None if team_id is None else int(team_id), limit)


def player_clutches(f, t, min_maps=0, team_region=None, team_id=None, limit=15, **_):
    """Desenha o ranking de clutches vencidos (1v1 a 1v5) por jogador."""
    return _stacked_players(f, t, ["c1v1", "c1v2", "c1v3", "c1v4", "c1v5"], ["1v1", "1v2", "1v3", "1v4", "1v5"],
                            "Clutches vencidos", "Rounds vencidos como último vivo do time, por situação",
                            min_maps, team_region, None if team_id is None else int(team_id), limit)


def hs_distribution(f, t, min_maps=20, team_region=None, **_):
    """Desenha o histograma com KDE da taxa de headshot dos jogadores."""
    df = stats.player_table(f, team_region=team_region, min_maps=int(min_maps)).dropna(subset=["hs"])
    if len(df) < 5:
        return _empty(t, "Poucos jogadores para a distribuição")
    fig = _fig(t, 8, 3.8)
    ax = _ax(fig, t, "Distribuição da taxa de headshot", f"{len(df)} jogadores com {min_maps}+ mapas · HS% ponderado por kills")
    sns.histplot(df["hs"], ax=ax, bins=30, color=t["main"], edgecolor=t["surface"], linewidth=1.5,
                 kde=True, line_kws={"linewidth": 2})
    med = df["hs"].median()
    ax.axvline(med, color=t["text2"], linewidth=1)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    ax.text(med, ax.get_ylim()[1] * 0.97, f" mediana {med:.1f}% ", fontsize=9, color=t["text"], va="top", ha="left",
            bbox=dict(boxstyle="square,pad=0.25", facecolor=t["surface"], edgecolor="none"))
    best = df.nlargest(3, "hs")
    lines = ["MAIORES HS%"] + [f"{i}. {r['player_name']} ({_short(r['team_name'], 16) if isinstance(r['team_name'], str) else '—'})"
                               f"  {r['hs']:.1f}%" for i, (_, r) in enumerate(best.iterrows(), 1)]
    ax.text(0.99, 0.97, "\n".join(lines), transform=ax.transAxes, ha="right", va="top", fontsize=9, linespacing=1.5,
            color=t["text"], bbox=dict(boxstyle="square,pad=0.6", facecolor=t["surface"], edgecolor=t["grid"]))
    for _, r in best.iterrows():
        ax.plot([r["hs"]], [0], marker="v", markersize=7, color=t["text2"], clip_on=False, zorder=5)
    ax.set_xlabel("HS %", color=t["muted"], fontsize=9)
    ax.set_ylabel("Jogadores", color=t["muted"], fontsize=9)
    ax.grid(axis="x", visible=False)
    return _png(fig)


def rating_vs_hs(f, t, min_maps=20, team_region=None, **_):
    """Desenha o gráfico de dispersão rating × headshot com regressão e correlação."""
    df = stats.player_table(f, team_region=team_region, min_maps=int(min_maps)).dropna(subset=["hs", "rating"])
    if len(df) < 5:
        return _empty(t, "Poucos jogadores para comparar")
    fig = _fig(t, 8, 5.0)
    ax = _ax(fig, t, "Rating × headshot", f"Cada ponto é um jogador com {min_maps}+ mapas")
    sns.regplot(data=df, x="hs", y="rating", ax=ax, scatter_kws={"s": 28, "color": t["main"], "alpha": 0.75,
                "edgecolor": t["surface"], "linewidths": 1}, line_kws={"color": t["text2"], "linewidth": 2}, ci=None)
    corr = np.corrcoef(df["hs"], df["rating"])[0, 1]
    ax.text(0.99, 0.02, f"correlação de Pearson r = {corr:.2f}", transform=ax.transAxes, ha="right",
            fontsize=8.5, color=t["text2"])
    fig.canvas.draw()
    top = df.sort_values("rating", ascending=False)
    _annotate_sparse(ax, top["hs"], top["rating"], top["player_name"], t, max_labels=8)
    ax.set_xlabel("HS %", color=t["muted"], fontsize=9)
    ax.set_ylabel("Rating", color=t["muted"], fontsize=9)
    return _png(fig)


def player_year(f, t, player_id=None, **_):
    """Desenha a linha de rating por ano de um jogador."""
    if player_id is None:
        return _empty(t, "Selecione um jogador")
    by = pd.DataFrame(stats.player_detail(int(player_id), f).get("by_year", []))
    if by.empty:
        return _empty(t)
    fig = _fig(t, 8, 3.4)
    ax = _ax(fig, t, "Rating por ano", "Média ponderada por rounds jogados")
    x = by["year"].astype(int).astype(str)
    ax.plot(x, by["rating"], color=t["main"], linewidth=2, marker="o", markersize=7,
            markeredgecolor=t["surface"], markeredgewidth=2)
    for xi, v, m in zip(x, by["rating"], by["maps"]):
        if not pd.isna(v):
            ax.annotate(f"{v:.2f}", (xi, v), xytext=(0, 8), textcoords="offset points", ha="center",
                        fontsize=8.5, color=t["text2"])
    ax.axhline(1.0, color=t["axis"], linewidth=1)
    ax.grid(axis="x", visible=False)
    return _png(fig)


def player_agents(f, t, player_id=None, **_):
    """Desenha os agentes mais jogados por um jogador com seu rating."""
    if player_id is None:
        return _empty(t, "Selecione um jogador")
    ag = pd.DataFrame(stats.player_detail(int(player_id), f).get("agents", []))
    if ag.empty:
        return _empty(t)
    ag = ag.head(10)
    fig = _fig(t, 8, 0.36 * len(ag) + 1.3)
    ax = _ax(fig, t, "Agentes mais jogados", "Mapas por agente · rótulo com o rating no agente")
    _barh(ax, t, [stats.agent_name(a) for a in ag["agent"]], list(ag["maps"]), t["main"], lambda v: f"{int(v)}",
          extra=[f"(rating {r:.2f})" if not pd.isna(r) else "" for r in ag["rating"]])
    return _png(fig)


def map_side_bias(f, t, min_maps=20, **_):
    """Desenha o quanto cada mapa favorece ataque ou defesa em pontos percentuais."""
    df = stats.map_table(f)
    df = df[df["maps"] >= int(min_maps)].sort_values("atk_wr")
    if df.empty:
        return _empty(t)
    diff = df["atk_wr"] - 0.5
    fig = _fig(t, 8, 0.4 * len(df) + 1.4)
    ax = _ax(fig, t, "Lado favorecido em cada mapa", "Quanto o ataque vence acima (+) ou abaixo (−) de 50% dos rounds, em pontos percentuais (pp)")
    y = np.arange(len(df))
    colors = [t["atk"] if d > 0 else t["def"] for d in diff]
    ax.barh(y, diff, height=0.62, color=colors, linewidth=0)
    span = max(0.02, diff.abs().max())
    for yi, d, wr, m in zip(y, diff, df["atk_wr"], df["maps"]):
        side = "ataque" if d > 0 else "defesa"
        ax.text(d + (span * 0.03 if d >= 0 else -span * 0.03), yi, f"{max(wr, 1 - wr):.1%} {side} · {int(m)} mapas",
                va="center", ha="left" if d >= 0 else "right", fontsize=8, color=t["text2"])
    ax.set_yticks(y, df["map_name"], color=t["text2"], fontsize=9.5)
    ax.set_xlim(-span * 1.9, span * 1.9)
    ax.axvline(0, color=t["muted"], linewidth=1)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: "0" if abs(v) < 1e-9 else f"{v * 100:+.0f} pp"))
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    from matplotlib.patches import Patch
    _legend(ax, t, [Patch(color=t["def"]), Patch(color=t["atk"])], ["Favorece a defesa", "Favorece o ataque"], ncol=2)
    return _png(fig, legend=True)


def map_heatmap(f, t, **_):
    """Desenha o mapa de calor da presença de cada mapa no pool por ano."""
    mc = f.apply(store["map_cube"])
    if mc.empty:
        return _empty(t)
    p = mc.groupby(["map_name", "year"])["maps"].sum().unstack(fill_value=0)
    share = p / p.sum(axis=0)
    share = share.loc[share.sum(axis=1).sort_values(ascending=False).index].replace(0, np.nan)
    fig = _fig(t, 8, 0.36 * len(share) + 1.4)
    ax = fig.add_subplot(111)
    _titles(fig, t, "Map pool ao longo dos anos", "% dos mapas jogados em cada ano (vazio = fora do pool)")
    _heatmap(fig, ax, t, share)
    ax.set_xticklabels([str(int(c)) for c in share.columns])
    return _png(fig)


def agent_heatmap(f, t, limit=20, **_):
    """Desenha o mapa de calor do pick rate dos agentes por ano."""
    ac = f.apply(store["agent_cube"])
    if ac.empty:
        return _empty(t)
    p = ac.groupby(["agent", "year"])["picks"].sum().unstack(fill_value=0)
    maps_per_year = p.sum(axis=0) / 10
    rate = p / maps_per_year
    rate = rate.loc[rate.sum(axis=1).sort_values(ascending=False).index[: int(limit)]].replace(0, np.nan)
    rate.index = [stats.agent_name(a) for a in rate.index]
    fig = _fig(t, 8, 0.32 * len(rate) + 1.4)
    ax = fig.add_subplot(111)
    _titles(fig, t, "Meta de agentes por ano", "Pick rate: % das composições que usaram o agente")
    _heatmap(fig, ax, t, rate / 2)
    ax.set_xticklabels([str(int(c)) for c in rate.columns])
    return _png(fig)


def agent_pickrate(f, t, map_name=None, limit=15, **_):
    """Desenha o ranking de pick rate dos agentes, opcionalmente por mapa."""
    df = stats.agent_table(f, map_name=map_name).head(int(limit))
    if df.empty:
        return _empty(t)
    fig = _fig(t, 8, 0.34 * len(df) + 1.3)
    sub = f"Mapa: {map_name}" if map_name else "Todos os mapas"
    ax = _ax(fig, t, "Agentes mais escolhidos", f"{sub} · % das composições · rótulo com a win rate")
    rate = df["pick_rate"] / 2
    _barh(ax, t, [stats.agent_name(a) for a in df["agent"]], list(rate), t["main"], lambda v: f"{v:.0%}",
          extra=[f"(vence {w:.0%})" for w in df["win_rate"]])
    ax.xaxis.set_major_formatter(pct)
    return _png(fig)


CHARTS = {
    "matches_by_year": matches_by_year, "matches_by_tier": matches_by_tier, "side_by_year": side_by_year, "win_types": win_types,
    "titles_top": titles_top, "intl_titles_region": intl_titles_region,
    "team_winrate": team_winrate, "team_sides": team_sides, "team_year": team_year, "team_maps": team_maps,
    "team_players": team_players, "h2h_maps": h2h_maps,
    "player_top": player_top, "player_multikills": player_multikills, "player_clutches": player_clutches,
    "hs_distribution": hs_distribution, "rating_vs_hs": rating_vs_hs, "player_year": player_year,
    "player_agents": player_agents,
    "map_side_bias": map_side_bias, "map_heatmap": map_heatmap, "agent_heatmap": agent_heatmap,
    "agent_pickrate": agent_pickrate,
}


@lru_cache(maxsize=512)
def render(name: str, f: Filters, theme: str, params: tuple, version: int) -> bytes:
    """Renderiza (com cache) o gráfico pedido em PNG no tema escolhido."""
    t = THEMES.get(theme, THEMES["dark"])
    kwargs = dict(params)
    _render.wide = bool(kwargs.pop("wide", False))
    _render.theme = theme
    with _lock:
        with matplotlib.rc_context({"font.family": FONT, "axes.unicode_minus": False}):
            return CHARTS[name](f, t, **kwargs)
