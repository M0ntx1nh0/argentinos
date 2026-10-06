"""
Club Argentino — Dashboard de Análisis
Desarrollado por Ramón Codesido · Sport Data Campus
"""

import base64
import io
import json
import os
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv
from fpdf import FPDF
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from plotly.subplots import make_subplots
from data_loader import load_all
from video_loader import load_longomatch_events

# ── Colores del club ──────────────────────────────────────────────────────────
AZUL_OSCURO  = "#1B2A4A"
AZUL_CELESTE = "#6AAFE6"
AZUL_MEDIO   = "#2E4B7A"
AZUL_CLARO   = "#3D6B9E"
DORADO       = "#C9A84C"
BLANCO       = "#FFFFFF"
GRIS_MEDIO   = "#C8D6E5"
VERDE        = "#4CAF82"
ROJO         = "#E85D75"

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
TRAMO_ORDER = ["0-15", "16-30", "31-45", "45+", "46-60", "61-75", "76-90", "90+"]

load_dotenv(Path(__file__).parent / ".env")


def _streamlit_secret(name: str) -> str:
    """Obtiene secretos en Cloud sin exigir un secrets.toml en desarrollo local."""
    try:
        return str(st.secrets.get(name, "")).strip()
    except FileNotFoundError:
        return ""


TOKEN_FILE = Path(__file__).parent / "token_google.json"
SERVICE_ACCOUNT_FILE = Path(os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    Path(__file__).parent / "titan-argentinos-503811-67466c1aab4b.json",
))
GOOGLE_SEASON_FOLDER_ID = (
    _streamlit_secret("GOOGLE_SEASON_FOLDER_ID")
    or os.getenv("GOOGLE_SEASON_FOLDER_ID", "").strip()
)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]


# ── Helper: template de plotly con profundidad ────────────────────────────────
# Color del área de plot ligeramente más claro que el paper para crear profundidad
PLOT_BG  = "#253F6B"   # azul medio más cálido para el área de datos
PAPER_BG = "#1B2A4A"   # azul oscuro del fondo general

HOVER = dict(bgcolor="#0F1B33", bordercolor=DORADO,
             font=dict(family="Inter, Arial, sans-serif", color=BLANCO, size=12))


def t(fig: go.Figure, height=380, margin=None, **extra) -> go.Figure:
    m = margin or dict(t=36, b=36, l=48, r=36)
    if isinstance(extra.get("title"), str):
        # Títulos de gráfico alineados a la izquierda, como en un informe.
        extra["title"] = dict(text=f"<b>{extra['title']}</b>", x=0.012, xanchor="left",
                              font=dict(size=13, color=BLANCO))
    fig.update_layout(
        height=height,
        margin=m,
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO, size=12),
        hoverlabel=HOVER,
        barcornerradius=7,  # cabecera de barra redondeada (Plotly ≥ 5.19)
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLANCO, size=11),
                    orientation="h", y=1.08),
        # Borde sutil alrededor del área de plot (conserva líneas/zonas ya añadidas)
        shapes=list(fig.layout.shapes) + [dict(
            type="rect", xref="paper", yref="paper",
            x0=0, y0=0, x1=1, y1=1,
            line=dict(color="rgba(106,175,230,0.12)", width=1),
            fillcolor="rgba(0,0,0,0)", layer="above",
        )],
        **extra,
    )
    fig.update_xaxes(
        gridcolor="rgba(200,214,229,0.07)",
        zeroline=False,
        color=BLANCO,
        tickfont=dict(color=GRIS_MEDIO, size=11),
        linecolor="rgba(200,214,229,0.15)",
        linewidth=1,
    )
    fig.update_yaxes(
        gridcolor="rgba(200,214,229,0.07)",
        zeroline=False,
        color=BLANCO,
        tickfont=dict(color=GRIS_MEDIO, size=11),
        linecolor="rgba(200,214,229,0.15)",
        linewidth=1,
    )
    return fig


def depth_bar(color: str, name: str, x, y, text=None, pos="outside",
              secondary_y=False, opacity=1.0) -> go.Bar:
    """Barra con gradiente vertical para dar sensación de profundidad."""
    # Color base y versión más clara para el highlight superior
    return go.Bar(
        name=name, x=x, y=y,
        marker=dict(
            color=color,
            opacity=opacity,
            line=dict(color="rgba(0,0,0,0.25)", width=1),
            # Gradiente: más claro arriba, más oscuro abajo
            pattern=dict(shape=""),  # sin pattern, solo color sólido con borde
        ),
        # Si no se pasa texto, cada barra muestra su valor.
        text=text if text is not None else [f"{v:g}" if v else "" for v in y],
        textposition=pos,
        textfont=dict(color=BLANCO, size=12, family="Inter"),
        cliponaxis=False,
    )


def chart(fig):
    """Renderiza un plotly chart."""
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def img_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ── Sistema de diseño: componentes HTML (estilos en inject_css) ───────────────
TONE_COLORS = {"pos": VERDE, "neg": ROJO, "warn": DORADO, "info": AZUL_CELESTE}
TONE_LABELS = {"pos": "Fortaleza", "neg": "Alerta", "warn": "A vigilar", "info": "Contexto"}
TONE_GROUPS = {"pos": "Fortalezas", "warn": "A vigilar", "neg": "Alertas", "info": "Contexto"}
TONE_ICONS = {"pos": "▲", "warn": "●", "neg": "▼", "info": "◆"}
TONE_ORDER = ["pos", "warn", "neg", "info"]
RESULT_COLORS = {"V": VERDE, "E": DORADO, "D": ROJO}


def metric_card(label: str, value, suffix: str = "", delta: tuple[str, str] | None = None,
                hint: str = "", accent: str = DORADO) -> str:
    """Tarjeta KPI. `delta` = (texto, tono) para comparar con una referencia."""
    delta_html = ""
    if delta:
        text, tone = delta
        delta_html = (f'<div class="cadf-kpi-delta" style="color:{TONE_COLORS.get(tone, GRIS_MEDIO)}">'
                      f'{text}</div>')
    hint_html = f'<div class="cadf-kpi-hint">{hint}</div>' if hint else ""
    return (f'<div class="cadf-kpi" style="--accent:{accent}">'
            f'<div class="cadf-kpi-label">{label}</div>'
            f'<div class="cadf-kpi-value">{value}<span>{suffix}</span></div>'
            f'{delta_html}{hint_html}</div>')


def page_header(title: str, subtitle: str = "", kicker: str = "", aside: str = ""):
    """Cabecera de página con degradado del club."""
    aside_html = f'<div class="cadf-hero-aside">{aside}</div>' if aside else ""
    st.markdown(
        f'<div class="cadf-hero"><div><div class="cadf-hero-kicker">{kicker}</div>'
        f'<h1>{title}</h1><p>{subtitle}</p></div>{aside_html}</div>',
        unsafe_allow_html=True,
    )


def section(title: str, subtitle: str = ""):
    """Cabecera de capítulo: el subtítulo dice qué pregunta responde el bloque."""
    sub = f'<div class="cadf-section-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="cadf-section"><div class="cadf-section-title">{title}</div>{sub}</div>',
                unsafe_allow_html=True)


def insight_panel(items: list[tuple[str, str, str]], heading: str = "Lectura técnica"):
    """Conclusiones automáticas: lista de (tono, titular, explicación)."""
    if not items:
        return
    # Una columna por tipo para identificar de un vistazo fortalezas, riesgos y contexto.
    groups = []
    for tone in TONE_ORDER:
        tone_items = [(title, body) for t_, title, body in items if t_ == tone]
        if not tone_items:
            continue
        cards = "".join(f'<div class="cadf-insight"><div class="cadf-insight-title">{title}</div>'
                        f'<div class="cadf-insight-body">{body}</div></div>' for title, body in tone_items)
        groups.append(
            f'<div class="cadf-insight-group" style="--tone:{TONE_COLORS[tone]}">'
            f'<div class="cadf-insight-group-head"><span>{TONE_ICONS[tone]}</span>{TONE_GROUPS[tone]}'
            f'<b>{len(tone_items)}</b></div>{cards}</div>'
        )
    st.markdown(f'<div class="cadf-insights-head">{heading}</div>'
                f'<div class="cadf-insights">{"".join(groups)}</div>', unsafe_allow_html=True)


def result_chip(res: str, text: str = "") -> str:
    return (f'<span class="cadf-chip" style="--chip:{RESULT_COLORS.get(res, GRIS_MEDIO)}">'
            f'{text or res}</span>')


def vs_ref(value, ref, decimals: int = 1, suffix: str = "", higher_better: bool = True,
           label: str = "media temp.") -> tuple[str, str] | None:
    """Delta frente a una referencia, coloreado según si mejora o empeora."""
    if value is None or ref is None or pd.isna(value) or pd.isna(ref):
        return None
    diff = float(value) - float(ref)
    if abs(diff) < 10 ** -decimals / 2:
        return (f"= {label}", "info")
    arrow = "▲" if diff > 0 else "▼"
    good = (diff > 0) == higher_better
    return (f"{arrow} {abs(diff):.{decimals}f}{suffix} vs {label}", "pos" if good else "neg")


# ── Datos de temporada: tabla de partidos y conclusiones automáticas ───────────
TRAMO_BLOQUES = [
    ("0-15'", ["0-15"]), ("16-30'", ["16-30"]), ("31-45+'", ["31-45", "45+"]),
    ("46-60'", ["46-60"]), ("61-75'", ["61-75"]), ("76-90+'", ["76-90", "90+"]),
]
TRAMOS_REGULARES = ["0-15", "16-30", "31-45", "46-60", "61-75", "76-90"]


def season_label(df: pd.DataFrame) -> str:
    seasons = df.loc[df["nivel"] == "temporada", "tramo_raw"].astype(str).str.extract(r"(\d{4})-(\d{4})")
    seasons = seasons.dropna()
    return f"{seasons.iloc[0, 0]}–{seasons.iloc[0, 1]}" if not seasons.empty else ""


def matches_table(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por partido, en orden cronológico, con resultado y puntos."""
    sort_col = "orden" if "orden" in df.columns else ("jornada" if "jornada" in df.columns else "partido")
    m = df[df["nivel"] == "temporada"].sort_values(sort_col).copy()
    if "jornada" not in m.columns:
        m["jornada"] = range(1, len(m) + 1)
    if "condicion" not in m.columns:
        m["condicion"] = "Local"
    if "competicion" not in m.columns:
        m["competicion"] = "Oficial"
    m["gf"] = m["goles"].fillna(0).astype(int)
    m["gc"] = m["goles_enc"].fillna(0).astype(int)
    m["res"] = ["V" if a > b else "D" if a < b else "E" for a, b in zip(m["gf"], m["gc"])]
    m["pts"] = m["res"].map({"V": 3, "E": 1, "D": 0})
    m["jlabel"] = [f"J{j}" if c == "Oficial" else "Amistoso" for j, c in zip(m["jornada"], m["competicion"])]
    m["etiqueta"] = [f"{j} · {r}" for j, r in zip(m["jlabel"], m["rival"])]
    m["cond"] = m["condicion"].map({"Local": "L", "Visitante": "V"}).fillna("")
    return m.reset_index(drop=True)


def official_matches(m: pd.DataFrame) -> pd.DataFrame:
    """Filtra los amistosos; si aún no hay oficiales, devuelve todo para no dejar la vista vacía."""
    official = m[m["competicion"] == "Oficial"]
    return official if not official.empty else m


def split_friendlies(df: pd.DataFrame, video_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Datos de competición oficial (HUDL y vídeo) sin los amistosos de pretemporada."""
    if "competicion" not in df.columns or not (df["competicion"] == "Amistoso").any():
        return df, video_df
    official = df[df["competicion"] == "Oficial"]
    if official.empty:
        return df, video_df
    friendly_keys = {_tactical_rival_key(r) for r in df.loc[df["competicion"] == "Amistoso", "rival"].unique()}
    if not video_df.empty:
        video_df = video_df[~video_df["rival"].map(_tactical_rival_key).isin(friendly_keys)]
    return official, video_df


def goals_by_block(df: pd.DataFrame, rival: str | None = None) -> pd.DataFrame:
    """Goles a favor y en contra por bloques de 15' (el añadido va con su tramo)."""
    tramos = df[df["nivel"] == "tramo"]
    if rival is not None:
        tramos = tramos[tramos["rival"] == rival]
    rows = []
    for label, raws in TRAMO_BLOQUES:
        sel = tramos[tramos["tramo_raw"].isin(raws)]
        rows.append({"bloque": label, "gf": int(sel["goles"].fillna(0).sum()),
                     "gc": int(sel["goles_enc"].fillna(0).sum())})
    return pd.DataFrame(rows).set_index("bloque")


GOAL_TYPES = [
    "Apertura de marcador", "Victoria (1-0)", "Ampliar ventaja", "Ponerse por delante",
    "Remontada", "Igualar marcador", "Reducir distancia",
]
BLOQUE_DE_TRAMO = {raw: label for label, raws in TRAMO_BLOQUES for raw in raws}


def _classify_goals(seq: list[tuple[str, str]]) -> list[dict]:
    """Clasifica cada gol según el marcador previo. `seq` = [(equipo, tramo_raw), ...] en orden."""
    final = {"propio": sum(1 for e, _ in seq if e == "propio"), "rival": sum(1 for e, _ in seq if e == "rival")}
    winner = max(final, key=final.get) if final["propio"] != final["rival"] else None
    score = {"propio": 0, "rival": 0}
    trailed = {"propio": False, "rival": False}
    goals = []
    for team, raw in seq:
        other = "rival" if team == "propio" else "propio"
        mine, theirs = score[team], score[other]
        if len(seq) == 1:
            tipo = "Victoria (1-0)"
        elif mine == 0 and theirs == 0:
            tipo = "Apertura de marcador"
        elif mine > theirs:
            tipo = "Ampliar ventaja"
        elif mine == theirs:
            tipo = "Ponerse por delante"
        elif mine == theirs - 1:
            tipo = "Igualar marcador"
        else:
            tipo = "Reducir distancia"
        score[team] += 1
        goals.append({"equipo": team, "tramo_raw": raw, "tipo": tipo, "had_trailed": trailed[team],
                      "marcador": f"{score['propio']}-{score['rival']}"})
        for side, opp in [("propio", "rival"), ("rival", "propio")]:
            trailed[side] = trailed[side] or score[side] < score[opp]
    # Remontada: quien iba perdiendo se pone por delante con el último gol del partido y gana.
    if winner and goals:
        last = goals[-1]
        if last["equipo"] == winner and last["tipo"] == "Ponerse por delante" and last["had_trailed"]:
            last["tipo"] = "Remontada"
    return goals


def goal_sequence(df: pd.DataFrame, video_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Goles de la temporada en orden, con tramo (HUDL) y tipo de gol.

    HUDL fija el tramo de cada gol; si ambos equipos marcan en el mismo tramo, el orden
    se toma de los eventos de gol de LongoMatch (reloj de vídeo)."""
    rows, notes = [], []
    tramos = df[df["nivel"] == "tramo"]
    for _, match in matches_table(df).iterrows():
        tr = tramos[tramos["rival"] == match["rival"]].copy()
        tr["orden"] = tr["tramo_raw"].map({raw: i for i, raw in enumerate(TRAMO_ORDER)})
        tr = tr.sort_values("orden")
        ev = _video_events_for_rival(video_df, match["rival"]) if not video_df.empty else video_df
        lm_order = (ev[ev["fase"] == "gol"].sort_values("time_seconds")["equipo"].tolist()
                    if not ev.empty else [])
        seq = []
        for _, r in tr.iterrows():
            a, b = int(pd.Series([r["goles"]]).fillna(0).iloc[0]), int(pd.Series([r["goles_enc"]]).fillna(0).iloc[0])
            order = ["propio"] * a + ["rival"] * b
            if a and b:
                chunk = lm_order[len(seq):len(seq) + a + b]
                if sorted(chunk) == sorted(order):
                    order = chunk
                else:
                    notes.append(f"J{match['jornada']} · {match['rival']}: orden estimado en el tramo {r['tramo_raw']}")
            seq += [(team, r["tramo_raw"]) for team in order]
        if len(seq) != match["gf"] + match["gc"]:
            notes.append(f"J{match['jornada']} · {match['rival']}: {match['gf'] + match['gc'] - len(seq)} gol(es) sin tramo en HUDL")
        for goal in _classify_goals(seq):
            goal.update(jornada=match["jornada"], rival=match["rival"],
                        bloque=BLOQUE_DE_TRAMO.get(goal["tramo_raw"], goal["tramo_raw"]))
            rows.append(goal)
    cols = ["jornada", "rival", "equipo", "tramo_raw", "bloque", "tipo", "marcador"]
    return (pd.DataFrame(rows)[cols] if rows else pd.DataFrame(columns=cols)), notes


def _goal_types_chart(goals: pd.DataFrame, title: str, rgb: str) -> go.Figure:
    """Matriz tramo × tipo de gol: el tamaño y la intensidad del círculo indican cuántos."""
    blocks = [label for label, _ in TRAMO_BLOQUES]
    counts = (pd.crosstab(goals["tipo"], goals["bloque"]) if not goals.empty else pd.DataFrame()
              ).reindex(index=GOAL_TYPES, columns=blocks, fill_value=0)
    maximum = max(int(counts.to_numpy().max()), 1)
    fig = go.Figure()
    t(fig, height=440, title=title, margin=dict(t=64, b=44, l=150, r=56))

    # Columnas sin goles: sombreadas y rotuladas.
    for xi, block in enumerate(blocks):
        if counts[block].sum() == 0:
            fig.add_vrect(x0=xi - 0.45, x1=xi + 0.45, fillcolor="rgba(200,214,229,0.06)",
                          line=dict(color="rgba(200,214,229,0.18)", width=1, dash="dot"), layer="below")
            fig.add_annotation(x=xi, y=len(GOAL_TYPES) - 0.35, text="sin goles", showarrow=False,
                               font=dict(color="rgba(200,214,229,0.6)", size=10, family="Inter"))
    fig.add_vline(x=2.5, line_color="rgba(255,255,255,0.25)", line_dash="dash", line_width=1.2)

    # Rejilla de puntos tenue para leer la matriz.
    gx, gy = zip(*[(xi, yi) for xi in range(len(blocks)) for yi in range(len(GOAL_TYPES))])
    fig.add_trace(go.Scatter(x=gx, y=gy, mode="markers", hoverinfo="skip", showlegend=False,
                             marker=dict(size=5, color="rgba(200,214,229,0.14)")))

    xs, ys, sizes, colors, texts, hovers = [], [], [], [], [], []
    for yi, tipo in enumerate(GOAL_TYPES):
        for xi, block in enumerate(blocks):
            n = int(counts.loc[tipo, block])
            if not n:
                continue
            detail = goals[(goals["tipo"] == tipo) & (goals["bloque"] == block)]
            xs.append(xi); ys.append(yi); texts.append(str(n))
            sizes.append(26 + 20 * (n - 1) / max(maximum - 1, 1) if maximum > 1 else 30)
            colors.append(f"rgba({rgb},{0.45 + 0.55 * n / maximum:.2f})")
            hovers.append(f"<b>{tipo}</b> · {block}<br>" + "<br>".join(
                f"J{r.jornada} · {r.rival} (→ {r.marcador})" for r in detail.itertuples()))
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=texts, showlegend=False,
        textfont=dict(color=BLANCO, size=13, family="Inter"),
        marker=dict(size=sizes, color=colors, line=dict(color="rgba(255,255,255,0.75)", width=1.5)),
        hovertext=hovers, hoverinfo="text",
    ))

    # Totales: por tipo a la derecha y por tramo arriba.
    for yi, tipo in enumerate(GOAL_TYPES):
        total = int(counts.loc[tipo].sum())
        fig.add_annotation(x=len(blocks) - 0.35, y=yi, xanchor="left", showarrow=False,
                           text=f"<b>{total}</b>" if total else "·",
                           font=dict(color=BLANCO if total else GRIS_MEDIO, size=12, family="Inter"))
    for xi, block in enumerate(blocks):
        total = int(counts[block].sum())
        fig.add_annotation(x=xi, y=-0.75, showarrow=False, text=f"<b>{total}</b>",
                           font=dict(color=f"rgb({rgb})" if total else GRIS_MEDIO, size=12, family="Inter"))

    fig.update_xaxes(tickvals=list(range(len(blocks))), ticktext=blocks, range=[-0.6, len(blocks) - 0.1],
                     showgrid=False, side="bottom")
    fig.update_yaxes(tickvals=list(range(len(GOAL_TYPES))), ticktext=GOAL_TYPES,
                     range=[len(GOAL_TYPES) - 0.2, -1.1], showgrid=False, tickfont=dict(color=BLANCO, size=12))
    return fig


def _goal_type_insights(goals: pd.DataFrame, n_matches: int) -> list[tuple[str, str, str]]:
    if goals.empty:
        return []
    items = []
    first = goals.groupby("jornada").head(1)
    scored_first = int((first["equipo"] == "propio").sum())
    conceded_first = int((first["equipo"] == "rival").sum())
    own = goals[goals["equipo"] == "propio"]
    remontadas = int((own["tipo"] == "Remontada").sum())
    items.append(("pos" if scored_first >= conceded_first else "warn", "¿Quién marca primero?",
                  f"CAdF abre el marcador en <b>{scored_first}</b> de {n_matches} partidos y el rival en "
                  f"<b>{conceded_first}</b>."))
    if conceded_first:
        items.append(("pos" if remontadas else "neg", "Reacción tras encajar primero",
                      f"<b>{remontadas}</b> remontada(s) en {conceded_first} partido(s) en los que el rival marcó "
                      f"primero. " + ("El equipo no se descompone cuando va por detrás." if remontadas else
                                      "Cuando el rival golpea primero, el equipo no ha dado la vuelta al marcador.")))
    rival = goals[goals["equipo"] == "rival"]
    key = rival["tipo"].value_counts()
    # Solo si un tipo destaca (≥2 goles y más que el siguiente); si no, no hay patrón.
    if len(key) and key.iloc[0] >= 2 and (len(key) == 1 or key.iloc[0] > key.iloc[1]):
        items.append(("warn", f"Goles encajados: sobre todo «{key.index[0]}»",
                      f"{key.iloc[0]} de {len(rival)} goles en contra son de este tipo. " +
                      ("El rival nos ha empatado tras ir ganando: gestionar mejor las ventajas."
                       if key.index[0] == "Igualar marcador" else "")))
    ampliar = int((own["tipo"] == "Ampliar ventaja").sum())
    if ampliar:
        items.append(("pos", "Instinto para cerrar partidos",
                      f"<b>{ampliar}</b> gol{'es' if ampliar > 1 else ''} para ampliar ventaja: con el marcador a favor el equipo sigue atacando."))
    return items


def _half_totals(df: pd.DataFrame, col: str, rival: str | None = None) -> tuple[float, float]:
    partes = df[df["nivel"] == "parte"]
    if rival is not None:
        partes = partes[partes["rival"] == rival]
    first = partes.loc[partes["tramo_raw"] == "1º mitad", col].fillna(0).sum()
    second = partes.loc[partes["tramo_raw"] == "2º mitad", col].fillna(0).sum()
    return float(first), float(second)


def _recovery_conversion(video_df: pd.DataFrame) -> tuple[int, int]:
    """(recuperaciones, cuántas acaban en finalización o gol en 20 s)."""
    total = converted = 0
    for _, events in video_df.groupby("partido"):
        outcomes = _tactical_20_second_outcomes(events, "recuperacion")
        total += int(outcomes.sum())
        converted += int(outcomes.get("Gol", 0) + outcomes.get("Finalización", 0))
    return total, converted


def season_insights(df: pd.DataFrame, video_df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Convierte los datos acumulados en las conclusiones que interesan al cuerpo técnico."""
    m = matches_table(df)
    items = []
    gf, gc = int(m["gf"].sum()), int(m["gc"].sum())

    # 1. Cuándo marcamos
    gf1, gf2 = _half_totals(df, "goles")
    blocks = goals_by_block(df)
    late = int(blocks.loc["76-90+'", "gf"])
    if gf:
        share2 = gf2 / gf
        if share2 >= 0.6:
            items.append(("pos", "Equipo de segundas partes",
                          f"<b>{gf2:.0f} de {gf}</b> goles llegan tras el descanso y <b>{late}</b> en el "
                          f"último cuarto de hora. El equipo termina los partidos más fuerte que el rival."))
        elif share2 <= 0.4:
            items.append(("warn", "Golpeamos pronto, ¿y después?",
                          f"<b>{gf1:.0f} de {gf}</b> goles llegan en la 1ª parte. Revisar si el equipo "
                          f"sostiene la intensidad ofensiva tras el descanso."))
        else:
            items.append(("info", "Gol repartido en los 90'",
                          f"{gf1:.0f} goles en la 1ª parte y {gf2:.0f} en la 2ª: amenaza constante."))

    # 2. Tramo crítico de control
    tr = df[(df["nivel"] == "tramo") & df["tramo_raw"].isin(TRAMOS_REGULARES)]
    pos_tramo = tr.groupby("tramo_raw")["pct_posesion"].mean().reindex(TRAMOS_REGULARES).dropna()
    if len(pos_tramo) >= 3:
        worst, best = pos_tramo.idxmin(), pos_tramo.idxmax()
        items.append(("neg" if pos_tramo[worst] < 47 else "warn", f"Tramo crítico: {worst}'",
                      f"Posesión media del <b>{pos_tramo[worst]:.0f}%</b>, la más baja del partido tipo. "
                      f"El mejor tramo es el {best}' ({pos_tramo[best]:.0f}%). Preparar ese momento "
                      f"(salida, distancias, pausa) es una palanca clara."))

    # 3. Qué separa ganar de no ganar
    wins, rest = m[m["res"] == "V"], m[m["res"] != "V"]
    if len(wins) and len(rest):
        pw, pr = wins["pct_pases"].mean(), rest["pct_pases"].mean()
        posw, posr = wins["pct_posesion"].mean(), rest["pct_posesion"].mean()
        if abs(pw - pr) >= 5:
            items.append(("pos" if pw > pr else "warn", "La precisión marca el resultado",
                          f"Con victoria pasamos al <b>{pw:.0f}%</b> de acierto; sin ella, al <b>{pr:.0f}%</b>. "
                          f"La posesión apenas cambia ({posw:.0f}% vs {posr:.0f}%): no es cuánto tenemos el "
                          f"balón, sino qué hacemos con él."))

    # 4. Eficacia
    sot = int(m["tiros_puerta"].fillna(0).sum())
    if sot:
        dry = m[(m["tiros_puerta"].fillna(0) >= 3) & (m["gf"] == 0)]
        body = f"<b>{gf}</b> goles con <b>{sot}</b> tiros a puerta: conversión del <b>{gf / sot * 100:.0f}%</b>."
        if not dry.empty:
            r = dry.iloc[0]
            body += (f" Ante {r['rival']} fueron {int(r['tiros_puerta'])} a puerta sin premio: "
                     f"el partido perdido se explica más por el acierto que por la producción.")
        items.append(("warn" if not dry.empty else "info", "Eficacia de cara a puerta", body))

    # 5. Defensa: cuándo encajamos
    if gc:
        gc1, gc2 = _half_totals(df, "goles_enc")
        clean = int((m["gc"] == 0).sum())
        items.append(("pos" if gc / len(m) <= 1 else "neg", f"{gc} goles encajados en {len(m)} partidos",
                      f"{gc1:.0f} en la 1ª parte y {gc2:.0f} en la 2ª; <b>{clean}</b> portería(s) a cero. "
                      f"Media de {gc / len(m):.1f} por partido."))

    # 6. Transición tras robo (LongoMatch)
    if not video_df.empty:
        own = video_df[video_df["equipo"] == "propio"]
        rec = own[own["fase"] == "recuperacion"]
        total, converted = _recovery_conversion(video_df)
        if total:
            high = rec["zona"].isin(["Zona 2", "Zona 3"]).mean() * 100
            items.append(("warn" if converted / total < 0.2 else "pos", "Robamos arriba, finalizamos poco",
                          f"<b>{high:.0f}%</b> de las recuperaciones son en campo medio o rival, pero solo el "
                          f"<b>{converted / total * 100:.0f}%</b> acaba en finalización en los 20 s siguientes. "
                          f"Hay margen en la primera decisión tras robo."))
    return items


# ── Sidebar ───────────────────────────────────────────────────────────────────
NAV_ITEMS = [
    ("🏠", "Inicio"),
    ("📋", "Temporada"),
    ("🎮", "Partido"),
    ("⚔️", "Rivales"),
    ("💪", "Física"),
]

def render_sidebar(temporada: str = ""):
    if "page" not in st.session_state:
        st.session_state.page = "Inicio"

    logo_arg = img_to_b64(os.path.join(ASSETS, "logo_argentino.png"))
    logo_sdc = img_to_b64(os.path.join(ASSETS, "sport data campus.png"))

    st.sidebar.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:center;
                gap:14px;padding:20px 8px 16px 8px;">
        <img src="data:image/png;base64,{logo_arg}"
             style="width:68px;height:68px;object-fit:contain;border-radius:50%;
                    border:2px solid {DORADO};">
        <img src="data:image/png;base64,{logo_sdc}"
             style="width:68px;height:68px;object-fit:contain;border-radius:8px;">
    </div>
    <div style="text-align:center;color:{AZUL_CELESTE};font-size:0.78rem;
                font-weight:600;letter-spacing:0.06em;margin-bottom:16px;">
        ANÁLISIS DE RENDIMIENTO<br>
        <span style="color:{DORADO};font-size:0.85rem;">Temporada {temporada}</span>
    </div>
    """, unsafe_allow_html=True)

    # Cajitas de navegación
    for icon, label in NAV_ITEMS:
        active = st.session_state.page == label
        # Wrapper div con clase activa/inactiva para que el CSS la pille
        st.sidebar.markdown(
            f'<div class="nav-item-{"active" if active else "inactive"}">',
            unsafe_allow_html=True,
        )
        if st.sidebar.button(f"{icon}  {label}", key=f"nav_{label}",
                             use_container_width=True):
            st.session_state.page = label
            st.rerun()
        st.sidebar.markdown("</div>", unsafe_allow_html=True)

    if st.sidebar.button("🔄  Actualizar datos", key="refresh_drive_data", use_container_width=True):
        # Permite ver un archivo recién subido sin esperar al vencimiento de la caché.
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown(f"<hr style='border-color:{AZUL_CLARO};margin:20px 0 12px'>",
                        unsafe_allow_html=True)
    st.sidebar.markdown(f"""
    <div style="text-align:center;color:{GRIS_MEDIO};font-size:0.67rem;
                line-height:1.7;padding-bottom:8px;">
        Desarrollado por<br>
        <span style="color:{DORADO};font-weight:700;font-size:0.78rem;">Ramón Codesido</span><br>
        <span style="color:{AZUL_CELESTE};font-size:0.72rem;">Sport Data Campus</span>
    </div>
    """, unsafe_allow_html=True)

    return st.session_state.page


# ── Página: Inicio ────────────────────────────────────────────────────────────
def _goals_timing_chart(blocks: pd.DataFrame, height: int = 300) -> go.Figure:
    """Goles a favor (arriba) y en contra (abajo) por bloque de 15'."""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=blocks.index, y=blocks["gf"], name="Goles a favor",
        marker=dict(color=VERDE, line=dict(width=0)),
        text=[str(v) if v else "" for v in blocks["gf"]], textposition="outside",
        textfont=dict(color=VERDE, size=13, family="Inter"),
        hovertemplate="%{x}<br>A favor: <b>%{y}</b><extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=blocks.index, y=-blocks["gc"], name="Goles en contra",
        marker=dict(color=ROJO, line=dict(width=0)),
        text=[str(v) if v else "" for v in blocks["gc"]], textposition="outside",
        textfont=dict(color=ROJO, size=13, family="Inter"),
        customdata=blocks["gc"], hovertemplate="%{x}<br>En contra: <b>%{customdata}</b><extra></extra>",
    ))
    top = max(int(blocks["gf"].max()), int(blocks["gc"].max()), 1) + 1
    fig.add_vline(x=2.5, line_color="rgba(255,255,255,0.25)", line_dash="dash", line_width=1.2)
    fig.add_annotation(x=2.5, y=top, text="DESCANSO", showarrow=False, yanchor="top",
                       font=dict(color=GRIS_MEDIO, size=9, family="Inter"))
    # Tramos sin goles: se marcan en gris para que el vacío también se lea.
    for label, gf, gc in zip(blocks.index, blocks["gf"], blocks["gc"]):
        if not gf:
            fig.add_annotation(x=label, y=0.15, text="0", showarrow=False, yanchor="bottom",
                               font=dict(color="rgba(200,214,229,0.45)", size=11, family="Inter"))
        if not gc:
            fig.add_annotation(x=label, y=-0.15, text="0", showarrow=False, yanchor="top",
                               font=dict(color="rgba(200,214,229,0.45)", size=11, family="Inter"))
    t(fig, height=height, barmode="relative", bargap=0.35, margin=dict(t=40, b=30, l=36, r=16))
    fig.update_yaxes(range=[-top, top], zeroline=True, zerolinecolor="rgba(255,255,255,0.35)",
                     tickvals=list(range(-top, top + 1)),
                     ticktext=[str(abs(v)) for v in range(-top, top + 1)])
    fig.update_layout(legend=dict(y=1.12, x=0))
    return fig


def _points_chart(m: pd.DataFrame) -> go.Figure:
    """Puntos acumulados frente al máximo posible, jornada a jornada."""
    acum = m["pts"].cumsum()
    maximo = [3 * (i + 1) for i in range(len(m))]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=m["etiqueta"], y=maximo, name="Máximo posible", mode="lines",
        line=dict(color="rgba(200,214,229,0.35)", width=1.5, dash="dot"),
        hovertemplate="Máximo: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=m["etiqueta"], y=acum, name="Puntos acumulados", mode="lines+markers+text",
        line=dict(color=DORADO, width=3.5),
        fill="tozeroy", fillcolor="rgba(201,168,76,0.10)", cliponaxis=False,
        marker=dict(size=16, color=[RESULT_COLORS[r] for r in m["res"]], line=dict(color=BLANCO, width=2)),
        text=[f"<b>{v}</b>" for v in acum], textposition="top center",
        textfont=dict(color=DORADO, size=12),
        customdata=[f"{r} {a}-{b}" for r, a, b in zip(m["res"], m["gf"], m["gc"])],
        hovertemplate="%{x}<br>%{customdata}<br>Acumulado: <b>%{y}</b><extra></extra>",
    ))
    t(fig, height=300, margin=dict(t=40, b=30, l=36, r=16))
    fig.update_yaxes(rangemode="tozero", range=[0, max(maximo) + 1.5], dtick=3)
    fig.update_xaxes(range=[-0.3, len(m) - 0.7])
    fig.update_layout(legend=dict(y=1.12, x=0))
    return fig


def page_inicio(df: pd.DataFrame, video_df: pd.DataFrame):
    m = matches_table(df)
    n = len(m)
    temporada = season_label(df)
    v, e, d = (m["res"] == "V").sum(), (m["res"] == "E").sum(), (m["res"] == "D").sum()
    pts = int(m["pts"].sum())
    gf, gc = int(m["gf"].sum()), int(m["gc"].sum())

    racha = "".join(result_chip(r) for r in m["res"])
    page_header(
        "Club Argentino",
        f"Panel de rendimiento · {n} partidos analizados · {v}V {e}E {d}D",
        kicker=f"Temporada {temporada}",
        aside=f'<div class="cadf-hero-stat"><span>{pts}</span>puntos de {3 * n}</div>'
              f'<div class="cadf-form">{racha}</div>',
    )

    # ── KPIs de temporada ──
    cols = st.columns(5)
    for col, html in zip(cols, [
        metric_card("Puntos por partido", f"{pts / max(n, 1):.2f}", "",
                    hint=f"{pts / max(3 * n, 1) * 100:.0f}% de los puntos en juego", accent=DORADO),
        metric_card("Goles a favor / en contra", f"{gf}", f" / {gc}",
                    hint=f"Diferencia {gf - gc:+d} · {gf / max(n, 1):.1f} marcados por partido", accent=VERDE),
        metric_card("Posesión media", f"{m['pct_posesion'].mean():.1f}", "%",
                    hint=f"Rango {m['pct_posesion'].min():.0f}–{m['pct_posesion'].max():.0f}%", accent=AZUL_CELESTE),
        metric_card("Precisión de pase", f"{m['pct_pases'].mean():.0f}", "%",
                    hint=f"Rango {m['pct_pases'].min():.0f}–{m['pct_pases'].max():.0f}%", accent=AZUL_CELESTE),
        metric_card("Tiros a puerta / partido", f"{m['tiros_puerta'].fillna(0).mean():.1f}", "",
                    hint=f"de {m['tiros'].fillna(0).mean():.1f} tiros totales", accent=DORADO),
    ]):
        col.markdown(html, unsafe_allow_html=True)

    # ── La temporada en claves ──
    insight_panel(season_insights(df, video_df), heading="La temporada en claves")

    # ── Evolución y momentos ──
    c1, c2 = st.columns(2)
    with c1:
        section("¿Cómo vamos?", "Puntos acumulados frente al máximo posible, jornada a jornada.")
        chart(_points_chart(m))
    with c2:
        section("¿Cuándo marcamos y cuándo encajamos?",
                "Goles de toda la temporada por bloques de 15'. Arriba a favor, abajo en contra.")
        chart(_goals_timing_chart(goals_by_block(df)))

    # ── Resultados ──
    section("Resultados", "Cada partido con su resultado y los tres indicadores de control del juego.")
    avg_pos, avg_pas = m["pct_posesion"].mean(), m["pct_pases"].mean()
    rows = []
    for _, r in m.iterrows():
        pos_c = AZUL_CELESTE if r["pct_posesion"] >= avg_pos else GRIS_MEDIO
        pas_c = VERDE if r["pct_pases"] >= avg_pas else ROJO
        rows.append(
            f'<div class="cadf-row" style="--res:{RESULT_COLORS[r["res"]]}">'
            f'<div class="cadf-row-j">J{r["jornada"]}</div>'
            f'<div class="cadf-row-rival">{r["rival"]}<span class="cadf-tag">'
            f'{"Local" if r["cond"] == "L" else "Visitante"}</span></div>'
            f'<div class="cadf-row-score">{r["gf"]}<span>–</span>{r["gc"]}</div>'
            f'<div>{result_chip(r["res"])}</div>'
            f'<div class="cadf-row-stat" style="color:{pos_c}">{r["pct_posesion"]:.0f}%<small>posesión</small></div>'
            f'<div class="cadf-row-stat" style="color:{pas_c}">{r["pct_pases"]:.0f}%<small>pase</small></div>'
            f'<div class="cadf-row-stat">{int(r["tiros_puerta"] or 0)}/{int(r["tiros"] or 0)}'
            f'<small>a puerta/tiros</small></div></div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.caption("Precisión de pase en verde/rojo según esté por encima o por debajo de la media de temporada.")


# ── Página: Temporada ─────────────────────────────────────────────────────────
def _cell_color(val):
    if val >= 60: return "rgba(106,175,230,0.9)", AZUL_OSCURO
    if val >= 50: return "rgba(106,175,230,0.5)", BLANCO
    if val >= 45: return "rgba(201,168,76,0.55)", BLANCO
    return "rgba(232,93,117,0.75)", BLANCO


def _timeline_chart(m: pd.DataFrame):
    """Diferencia de goles por partido + acumulado, en orden cronológico."""
    dif = (m["gf"] - m["gc"]).tolist()
    acum = pd.Series(dif).cumsum().tolist()
    etiquetas = [f"{lbl}<br><b>{gf}–{gc}</b>" for lbl, gf, gc in zip(m["etiqueta"], m["gf"], m["gc"])]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=etiquetas, y=dif, name="Diferencia por partido",
        marker=dict(color=[VERDE if d > 0 else (ROJO if d < 0 else DORADO) for d in dif],
                    line=dict(width=0), opacity=0.9),
        text=[f"{d:+d}" for d in dif], textposition="outside", textfont=dict(color=BLANCO, size=13),
        hovertemplate="%{x}<br>Diferencia: %{y:+d}<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=etiquetas, y=acum, name="Acumulado temporada", mode="lines+markers+text",
        line=dict(color=DORADO, width=3),
        marker=dict(size=12, color=[VERDE if v > 0 else (ROJO if v < 0 else DORADO) for v in acum],
                    line=dict(color=BLANCO, width=2)),
        text=[f"{v:+d}" for v in acum], textposition="top center", textfont=dict(color=DORADO, size=11),
        hovertemplate="Acumulado: %{y:+d}<extra></extra>",
    ), secondary_y=True)
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.25)", line_width=1.2, line_dash="dot",
                  secondary_y=False)
    t(fig, height=350, bargap=0.4, margin=dict(t=64, b=30, l=44, r=56),
      title="Diferencia de goles y acumulado")
    span = max(max(abs(v) for v in dif + acum), 1) + 1
    fig.update_yaxes(title_text="Diferencia", range=[-span, span], secondary_y=False)
    fig.update_yaxes(title_text="Acumulado", range=[-span, span], showgrid=False,
                     tickfont=dict(color=DORADO), color=DORADO, secondary_y=True)
    fig.update_layout(legend=dict(y=1.13, x=0.42))
    return fig


def _halves_chart(first, second, names=("1ª parte", "2ª parte")) -> go.Figure:
    """Compara mitades separando porcentajes y volúmenes (no comparten escala)."""
    pct_metrics = [("Posesión", "pct_posesion"), ("Precisión pase", "pct_pases")]
    vol_metrics = [("Tiros", "tiros"), ("A puerta", "tiros_puerta"), ("Centros", "centros")]
    fig = make_subplots(rows=1, cols=2, column_widths=[0.42, 0.58], horizontal_spacing=0.09,
                        subplot_titles=("Control con balón (%)", "Producción ofensiva"))
    vol_max = 1
    for name, data, color in [(names[0], first, AZUL_CELESTE), (names[1], second, DORADO)]:
        pct = [float(data.get(c) or 0) for _, c in pct_metrics]
        vol = [float(data.get(c) or 0) for _, c in vol_metrics]
        vol_max = max(vol_max, *vol)
        fig.add_trace(go.Bar(name=name, x=[l for l, _ in pct_metrics], y=pct, marker_color=color,
                             legendgroup=name, text=[f"{v:.0f}%" for v in pct], textposition="outside",
                             textfont=dict(color=BLANCO, size=12)), row=1, col=1)
        fig.add_trace(go.Bar(name=name, x=[l for l, _ in vol_metrics], y=vol, marker_color=color,
                             legendgroup=name, showlegend=False,
                             text=[f"{v:.1f}".rstrip("0").rstrip(".") for v in vol], textposition="outside",
                             textfont=dict(color=BLANCO, size=12)), row=1, col=2)
    t(fig, height=320, barmode="group", bargap=0.3, margin=dict(t=56, b=30, l=40, r=20))
    fig.update_yaxes(range=[0, 112], ticksuffix="%", row=1, col=1)
    fig.update_yaxes(range=[0, vol_max * 1.25], row=1, col=2)
    fig.update_annotations(font=dict(color=GRIS_MEDIO, size=12, family="Inter"))
    fig.update_layout(legend=dict(y=1.2, x=0))
    return fig


SCORE_METRICS = [
    ("pct_posesion", "Posesión", "{:.0f}%", True),
    ("pct_pases", "Pase", "{:.0f}%", True),
    ("pct_pases_atq", "Pase últ. tercio", "{:.0f}%", True),
    ("cadenas_6mas", "Cadenas 6+", "{:.0f}", True),
    ("tiros", "Tiros", "{:.0f}", True),
    ("tiros_puerta", "A puerta", "{:.0f}", True),
    ("centros", "Centros", "{:.0f}", None),
    ("faltas", "Faltas", "{:.0f}", False),
]


def _scorecard(m: pd.DataFrame):
    """Tabla de rendimiento: cada celda coloreada contra la media de temporada."""
    cols = "56px minmax(150px,1.6fr) 74px " + " ".join(["minmax(70px,1fr)"] * len(SCORE_METRICS))
    head = "".join(f"<div>{label}</div>" for _, label, _, _ in SCORE_METRICS)
    html = [f'<div class="cadf-score-wrap"><div class="cadf-score" style="grid-template-columns:{cols}">'
            f'<div class="cadf-score-h">J</div><div class="cadf-score-h">Rival</div>'
            f'<div class="cadf-score-h">Result.</div>'
            + head.replace("<div>", '<div class="cadf-score-h">')]
    means = {c: m[c].mean() for c, _, _, _ in SCORE_METRICS if c in m}
    for _, r in m.iterrows():
        html.append(f'<div class="cadf-score-j">J{r["jornada"]}</div>'
                    f'<div class="cadf-score-rival">{r["rival"]} <span class="cadf-tag">{r["cond"]}</span></div>'
                    f'<div>{result_chip(r["res"], f"{r["gf"]}-{r["gc"]}")}</div>')
        for col, _, fmt, higher in SCORE_METRICS:
            val, mean = r.get(col), means.get(col)
            if val is None or pd.isna(val):
                html.append('<div class="cadf-score-c">—</div>')
                continue
            bg = "transparent"
            if higher is not None and mean:
                rel = (val - mean) / mean
                if abs(rel) >= 0.08:
                    good = (rel > 0) == higher
                    alpha = min(0.18 + abs(rel) * 0.6, 0.55)
                    bg = f"rgba(76,175,130,{alpha:.2f})" if good else f"rgba(232,93,117,{alpha:.2f})"
            html.append(f'<div class="cadf-score-c" style="background:{bg}">{fmt.format(val)}</div>')
    html.append('<div class="cadf-score-j"></div><div class="cadf-score-rival"><b>Media</b></div><div></div>')
    for col, _, fmt, _ in SCORE_METRICS:
        mean = means.get(col)
        html.append(f'<div class="cadf-score-c cadf-score-mean">{fmt.format(mean) if pd.notna(mean) else "—"}</div>')
    html.append("</div></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _performance_insights(m: pd.DataFrame) -> list[tuple[str, str, str]]:
    items = []
    if len(m) >= 2:
        best = m.loc[m["pct_pases"].idxmax()]
        worst = m.loc[m["pct_pases"].idxmin()]
        items.append(("pos", f"Mejor partido con balón: {best['etiqueta']}",
                      f"{best['pct_pases']:.0f}% de pase, {int(best.get('cadenas_6mas') or 0)} cadenas de 6+ pases y "
                      f"{int(best['tiros_puerta'] or 0)} tiros a puerta. Es el modelo de juego a replicar."))
        items.append(("neg" if worst["res"] != "V" else "warn", f"Partido más impreciso: {worst['etiqueta']}",
                      f"{worst['pct_pases']:.0f}% de pase y {worst['pct_pases_atq'] or 0:.0f}% en el último tercio "
                      f"({result_chip(worst['res'], f'{worst.gf}-{worst.gc}')}). Cuando el pase cae, el equipo "
                      f"no instala el juego en campo rival."))
    if len(m) >= 4:
        half = len(m) // 2
        early, recent = m.iloc[:half], m.iloc[half:]
        d_pas = recent["pct_pases"].mean() - early["pct_pases"].mean()
        d_sot = recent["tiros_puerta"].fillna(0).mean() - early["tiros_puerta"].fillna(0).mean()
        tone = "pos" if d_pas >= 0 and d_sot >= 0 else ("neg" if d_pas < 0 and d_sot < 0 else "info")
        items.append((tone, "Tendencia reciente",
                      f"Últimos {len(recent)} partidos frente a los {len(early)} primeros: pase "
                      f"<b>{d_pas:+.0f} pts</b> y tiros a puerta <b>{d_sot:+.1f}</b> por partido."))
    return items


def page_temporada(df: pd.DataFrame, video_df: pd.DataFrame):
    m = matches_table(df)
    temporada = m
    rivales = m["etiqueta"].tolist()
    n_partidos = max(len(m), 1)
    page_header("Temporada", f"Evolución del equipo jornada a jornada · {len(m)} partidos",
                kicker=f"Temporada {season_label(df)}")

    # ── 1: Rendimiento partido a partido ──
    section("1 · Rendimiento partido a partido",
            "Cada celda comparada con la media de temporada: verde mejora, rojo empeora. "
            "Así se ve qué cambió en cada resultado.")
    _scorecard(m)
    chart(_timeline_chart(m))
    insight_panel(_performance_insights(m))

    # ── 2: Control del juego por tramos ──
    section("2 · Control del juego",
            "¿En qué momentos del partido mandamos con balón y en cuáles lo cedemos al rival?")
    tramos_df = df[df["nivel"] == "tramo"].copy()
    pivot = (
        tramos_df.pivot_table(index="rival", columns="tramo_raw", values="pct_posesion")
        .reindex(index=m["rival"], columns=TRAMO_ORDER)
    )
    promedios = pivot.mean()
    n_rivales = len(pivot.index)
    n_tramos  = len(TRAMO_ORDER)
    prom_y    = n_rivales + 0.3
    added = {"45+", "90+"}

    fig_hm = go.Figure()
    for r_idx, rival in enumerate(pivot.index):
        for t_idx, tramo in enumerate(TRAMO_ORDER):
            val = pivot.loc[rival, tramo] if tramo in pivot.columns else None
            if pd.isna(val): continue
            bg, tc = _cell_color(val)
            fig_hm.add_shape(type="rect",
                x0=t_idx-0.45, x1=t_idx+0.45, y0=r_idx-0.4, y1=r_idx+0.4,
                fillcolor=bg, opacity=0.45 if tramo in added else 1,
                line=dict(color="rgba(255,255,255,0.06)", width=1))
            fig_hm.add_annotation(x=t_idx, y=r_idx, text=f"<b>{val:.0f}%</b>",
                showarrow=False, font=dict(color=tc if tramo not in added else GRIS_MEDIO,
                                           size=13, family="Inter"))
    for t_idx, tramo in enumerate(TRAMO_ORDER):
        pval = promedios.get(tramo)
        if pd.isna(pval): continue
        bg, tc = _cell_color(pval)
        fig_hm.add_shape(type="rect",
            x0=t_idx-0.45, x1=t_idx+0.45,
            y0=prom_y-0.38, y1=prom_y+0.38,
            fillcolor=bg, opacity=0.45 if tramo in added else 1, line=dict(color=DORADO, width=1.5))
        fig_hm.add_annotation(x=t_idx, y=prom_y, text=f"<b>{pval:.0f}%</b>",
            showarrow=False, font=dict(color=tc if tramo not in added else GRIS_MEDIO,
                                       size=12, family="Inter"))
    fig_hm.add_vline(x=3.5, line_color="rgba(255,255,255,0.3)", line_dash="dash", line_width=1.2)

    fig_hm.update_layout(
        paper_bgcolor=PAPER_BG, plot_bgcolor=PAPER_BG, hoverlabel=HOVER,
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO),
        height=max(220, (n_rivales + 1) * 72 + 90),
        margin=dict(t=20, b=50, l=150, r=20),
        xaxis=dict(tickvals=list(range(n_tramos)),
                   ticktext=[f"<i>{tr}*</i>" if tr in added else tr for tr in TRAMO_ORDER],
                   showgrid=False, zeroline=False, tickfont=dict(color=GRIS_MEDIO, size=11)),
        yaxis=dict(tickvals=list(range(n_rivales)) + [prom_y],
                   ticktext=m["etiqueta"].tolist() + ["<b>Promedio</b>"],
                   showgrid=False, zeroline=False, tickfont=dict(color=BLANCO, size=11),
                   autorange="reversed"),
    )
    for color, label in [("rgba(106,175,230,0.9)", "≥60%"),("rgba(106,175,230,0.5)", "50–60%"),
                          ("rgba(201,168,76,0.55)", "45–50%"),("rgba(232,93,117,0.75)", "<45%")]:
        fig_hm.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
            marker=dict(size=11, color=color, symbol="square"), name=label, showlegend=True))
    fig_hm.update_layout(legend=dict(orientation="h", y=-0.12, x=0,
        font=dict(color=GRIS_MEDIO, size=10), bgcolor="rgba(0,0,0,0)"))
    chart(fig_hm)
    st.caption("Nota · tiempo añadido (45+* y 90+*): pocos minutos de juego, porcentajes muy volátiles; "
               "se muestran atenuados y no se usan en las conclusiones.")

    regular = promedios.reindex(TRAMOS_REGULARES).dropna()
    control_items = []
    if len(regular) >= 3:
        first_half = regular.reindex(["0-15", "16-30", "31-45"]).mean()
        second_half = regular.reindex(["46-60", "61-75", "76-90"]).mean()
        dominated = (pivot[TRAMOS_REGULARES] >= 50).sum().sum()
        total_cells = pivot[TRAMOS_REGULARES].notna().sum().sum()
        control_items.append(("neg" if regular.min() < 47 else "warn",
                              f"Tramo crítico: {regular.idxmin()}'",
                              f"Posesión media del <b>{regular.min():.0f}%</b>. Es el momento en que el rival "
                              f"nos quita el balón con más frecuencia."))
        control_items.append(("pos", f"Tramo fuerte: {regular.idxmax()}'",
                              f"Posesión media del <b>{regular.max():.0f}%</b>: el equipo instala su juego."))
        control_items.append(("info", "Patrón por mitades",
                              f"1ª parte {first_half:.0f}% · 2ª parte {second_half:.0f}%. Dominamos con balón en "
                              f"<b>{dominated} de {total_cells}</b> tramos regulares jugados."))

    # ── Posesión + Pases % ──
    fig_ctrl = go.Figure()
    fig_ctrl.add_trace(go.Scatter(
        x=rivales, y=temporada["pct_posesion"], name="Posesión %",
        mode="lines+markers",
        line=dict(color=AZUL_CELESTE, width=3),
        marker=dict(size=11, color=AZUL_CELESTE, line=dict(color=BLANCO, width=2)),
        fill="tozeroy", fillcolor="rgba(106,175,230,0.08)",
    ))
    fig_ctrl.add_trace(go.Scatter(
        x=rivales, y=temporada["pct_pases"], name="Precisión pases %",
        mode="lines+markers",
        line=dict(color=DORADO, width=3, dash="dot"),
        marker=dict(size=11, color=DORADO, line=dict(color=BLANCO, width=2)),
    ))
    fig_ctrl.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,255,0.2)", line_width=1)
    for rv, pos, pas in zip(rivales, temporada["pct_posesion"], temporada["pct_pases"]):
        fig_ctrl.add_annotation(x=rv, y=pos, text=f"{pos:.1f}%", showarrow=False,
                                yshift=-18, font=dict(color=AZUL_CELESTE, size=10))
        fig_ctrl.add_annotation(x=rv, y=pas, text=f"{pas:.0f}%", showarrow=False,
                                yshift=16, font=dict(color=DORADO, size=10))
    t(fig_ctrl, height=340, title="Posesión y precisión de pase por partido",
      margin=dict(t=48, b=36, l=48, r=24),
      yaxis=dict(range=[30, 105], ticksuffix="%"))
    fig_ctrl.update_layout(legend=dict(y=1.14, x=0.55))
    chart(fig_ctrl)
    insight_panel(control_items)

    # ── 3: Momentos del partido ──
    section("3 · Primera y segunda parte",
            "¿Cómo cambia el equipo tras el descanso? Promedio por partido en cada mitad y goles por tramo.")
    partes_df = df[df["nivel"] == "parte"]
    p1m = partes_df[partes_df["tramo_raw"] == "1º mitad"].mean(numeric_only=True)
    p2m = partes_df[partes_df["tramo_raw"] == "2º mitad"].mean(numeric_only=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        chart(_halves_chart(p1m, p2m))
    with c2:
        fig_goals = _goals_timing_chart(goals_by_block(df), height=320)
        fig_goals.update_layout(title=dict(text="<b>Goles por tramo</b>", x=0.02, font=dict(size=13)),
                                margin=dict(t=56, b=72, l=36, r=16), legend=dict(orientation="h", yanchor="top", y=-0.1, x=0))
        chart(fig_goals)
    half_items = []
    d_tiros = (p2m.get("tiros") or 0) - (p1m.get("tiros") or 0)
    d_pos = (p2m.get("pct_posesion") or 0) - (p1m.get("pct_posesion") or 0)
    gf1, gf2 = _half_totals(df, "goles")
    half_items.append(("pos" if d_tiros > 0 else "warn",
                       "Tras el descanso" + (" crecemos" if d_tiros > 0 else " bajamos"),
                       f"Tiros por partido: {p1m.get('tiros') or 0:.1f} → <b>{p2m.get('tiros') or 0:.1f}</b> "
                       f"({d_tiros:+.1f}). Posesión {d_pos:+.0f} pts. Goles: {gf1:.0f} en la 1ª y "
                       f"<b>{gf2:.0f}</b> en la 2ª."))
    insight_panel(half_items)

    # ── Tipos de gol por tramo ──
    section("Tipos de gol por tramo",
            "Qué significó cada gol para el marcador y en qué momento llegó. Círculo más grande e intenso = "
            "más goles. Pasa el ratón por un círculo para ver los partidos.")
    goals, goal_notes = goal_sequence(df, video_df)
    chart(_goal_types_chart(goals[goals["equipo"] == "propio"], "Goles a favor", "76,175,130"))
    chart(_goal_types_chart(goals[goals["equipo"] == "rival"], "Goles en contra", "232,93,117"))
    st.caption("Tramo de cada gol según HUDL; cuando ambos equipos marcan en el mismo tramo, el orden sale "
               "del reloj de LongoMatch. Criterios completos en el desplegable inferior."
               + (" · " + " · ".join(goal_notes) if goal_notes else ""))
    insight_panel(_goal_type_insights(goals, n_partidos))

    with st.expander("Criterios de clasificación y detalle gol a gol (para revisión)"):
        st.markdown(
            "| Tipo de gol | Criterio |\n|---|---|\n"
            "| **Apertura de marcador** | Primer gol del partido (0-0 → 1-0), salvo que el partido acabe 1-0. |\n"
            "| **Victoria (1-0)** | Único gol de un partido que termina 1-0. |\n"
            "| **Ampliar ventaja** | Marca el equipo que ya iba ganando. |\n"
            "| **Ponerse por delante** | Deshace un empate (que no sea 0-0) y pone al equipo por delante. |\n"
            "| **Remontada** | El equipo había ido perdiendo, se pone por delante con el **último gol del partido** "
            "y gana. Si después hay más goles, ese gol cuenta como *Ponerse por delante*. |\n"
            "| **Igualar marcador** | Marca el equipo que perdía por un gol y empata. |\n"
            "| **Reducir distancia** | Marca el equipo que perdía por dos o más goles, sin llegar a empatar. |\n\n"
            "Los amistosos de pretemporada no se incluyen. Tramo de cada gol según HUDL; si los dos equipos "
            "marcan en el mismo tramo, el orden se toma del reloj de LongoMatch."
        )
        if not goals.empty:
            detail = goals.merge(matches_table(df)[["jornada", "jlabel", "condicion"]], on="jornada", how="left")
            detail["orden"] = detail.groupby("jornada").cumcount() + 1
            st.dataframe(
                detail.assign(equipo=detail["equipo"].map({"propio": "CAdF", "rival": "Rival"}))[
                    ["jlabel", "rival", "condicion", "orden", "equipo", "bloque", "marcador", "tipo"]
                ].rename(columns={
                    "jlabel": "Jornada", "rival": "Rival", "condicion": "Condición", "orden": "Nº gol",
                    "equipo": "Marca", "bloque": "Tramo", "marcador": "Marcador (CAdF-Rival)", "tipo": "Tipo de gol",
                }),
                use_container_width=True, hide_index=True,
            )

    # ── 4: Ataque ──
    section("4 · Ataque: producir y acertar",
            "Volumen de tiro, precisión por zonas y eficacia de cara a puerta.")
    st.markdown("<div class='cadf-sublabel'>Pases por tercio del campo · precisión y volumen</div>", unsafe_allow_html=True)
    modo = st.radio("Modo", ["Promedio por partido", "Total temporada"],
                    horizontal=True, label_visibility="collapsed")

    tercios_data = [
        ("Zona defensiva\n(1er tercio)",   "def_intentados",  "def_completados",  "pct_pases_def"),
        ("Zona media\n(mitad campo)",       "mid_intentados",  "mid_completados",  "pct_pases_mid"),
        ("Zona de ataque\n(último tercio)", "atq_intentados",  "atq_completados",  "pct_pases_atq"),
    ]

    fig_pitch = go.Figure()
    pitch_w, pitch_h = 105, 68

    # Campo
    fig_pitch.add_shape(type="rect", x0=0, y0=0, x1=pitch_w, y1=pitch_h,
                        fillcolor="#2D5A1B", line=dict(color="white", width=2))
    fig_pitch.add_shape(type="line", x0=pitch_w/2, y0=0, x1=pitch_w/2, y1=pitch_h,
                        line=dict(color="white", width=1.5, dash="dot"))
    fig_pitch.add_shape(type="circle",
                        x0=pitch_w/2-9.15, y0=pitch_h/2-9.15,
                        x1=pitch_w/2+9.15, y1=pitch_h/2+9.15,
                        line=dict(color="white", width=1.5))
    for x0, x1 in [(0, 16.5), (pitch_w-16.5, pitch_w)]:
        fig_pitch.add_shape(type="rect", x0=x0, y0=pitch_h/2-20.16,
                            x1=x1, y1=pitch_h/2+20.16,
                            fillcolor="rgba(0,0,0,0)", line=dict(color="white", width=1.5))

    zone_colors = ["rgba(232,93,117,{a})", "rgba(201,168,76,{a})", "rgba(106,175,230,{a})"]
    zone_w = pitch_w / 3

    for i, (zona, ip_col, pc_col, pct_col) in enumerate(tercios_data):
        total_int  = temporada[ip_col].fillna(0).sum()
        total_comp = temporada[pc_col].fillna(0).sum()
        total_perd = total_int - total_comp
        # % real por partido (media de los % individuales, no calculado del total)
        avg_pct = temporada[pct_col].fillna(0).mean()

        if modo == "Promedio por partido":
            vi = total_int / n_partidos
            vc = total_comp / n_partidos
            vp = total_perd / n_partidos
            lbl_c, lbl_p, lbl_i = f"{vc:.1f}", f"{vp:.1f}", f"{vi:.1f}"
        else:
            vi, vc, vp = total_int, total_comp, total_perd
            lbl_c, lbl_p, lbl_i = str(int(vc)), str(int(vp)), str(int(vi))

        x0 = i * zone_w
        x1 = (i + 1) * zone_w
        cx = (x0 + x1) / 2
        alpha = 0.15 + (avg_pct / 100) * 0.35
        fig_pitch.add_shape(type="rect", x0=x0+1, y0=1, x1=x1-1, y1=pitch_h-1,
                            fillcolor=zone_colors[i].format(a=round(alpha, 2)),
                            line=dict(color="rgba(255,255,255,0.12)", width=1))

        pct_color = VERDE if avg_pct >= 80 else (DORADO if avg_pct >= 70 else ROJO)
        r = 9
        fig_pitch.add_shape(type="circle",
                            x0=cx-r, y0=pitch_h/2-r, x1=cx+r, y1=pitch_h/2+r,
                            fillcolor=AZUL_OSCURO, line=dict(color=pct_color, width=2.5))
        fig_pitch.add_annotation(x=cx, y=pitch_h/2, text=f"<b>{avg_pct:.0f}%</b>",
                                  showarrow=False,
                                  font=dict(color=pct_color, size=14, family="Inter"))
        fig_pitch.add_annotation(x=cx, y=pitch_h-5,
                                  text=f"<b>{zona.replace(chr(10),'<br>')}</b>",
                                  showarrow=False,
                                  font=dict(color="white", size=9, family="Inter"),
                                  align="center")
        fig_pitch.add_annotation(x=cx, y=8,
                                  text=f"✅ {lbl_c}   ❌ {lbl_p}",
                                  showarrow=False,
                                  font=dict(color=BLANCO, size=11, family="Inter"))

    fig_pitch.update_layout(
        paper_bgcolor=AZUL_OSCURO, plot_bgcolor=AZUL_OSCURO,
        height=360, margin=dict(t=10, b=10, l=10, r=10),
        xaxis=dict(range=[0, pitch_w], showgrid=False, zeroline=False,
                   showticklabels=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[0, pitch_h], showgrid=False, zeroline=False,
                   showticklabels=False),
        showlegend=False,
    )
    chart(fig_pitch)

    # ── Tiros, a puerta, goles y % a puerta ──
    fig_tir = make_subplots(specs=[[{"secondary_y": True}]])
    tiros_tot = temporada["tiros"].fillna(0).astype(int).tolist()
    tiros_prt = temporada["tiros_puerta"].fillna(0).astype(int).tolist()
    goles_t   = temporada["gf"].tolist()
    pct_efic  = [round(tp/tt*100) if tt > 0 else 0 for tt, tp in zip(tiros_tot, tiros_prt)]
    fig_tir.add_trace(go.Bar(
        name="Tiros totales", x=rivales, y=tiros_tot,
        marker=dict(color=AZUL_CELESTE, opacity=0.55, line=dict(width=0)),
        text=tiros_tot, textposition="outside", textfont=dict(color=AZUL_CELESTE, size=12),
    ), secondary_y=False)
    fig_tir.add_trace(go.Bar(
        name="Tiros a puerta", x=rivales, y=tiros_prt,
        marker=dict(color=DORADO, line=dict(width=0)),
        text=tiros_prt, textposition="outside", textfont=dict(color=DORADO, size=12),
    ), secondary_y=False)
    fig_tir.add_trace(go.Bar(
        name="Goles", x=rivales, y=goles_t,
        marker=dict(color=VERDE, line=dict(width=0)),
        text=goles_t, textposition="outside", textfont=dict(color=VERDE, size=12),
    ), secondary_y=False)
    fig_tir.add_trace(go.Scatter(
        name="% tiros a puerta", x=rivales, y=pct_efic, mode="lines+markers",
        line=dict(color=BLANCO, width=1.5, dash="dot"),
        marker=dict(size=8, color=BLANCO),
        hovertemplate="%{x}<br>%{y}% de los tiros van a puerta<extra></extra>",
    ), secondary_y=True)
    t(fig_tir, height=360, barmode="group", bargap=0.25, bargroupgap=0.06,
      title="Del tiro al gol, partido a partido", margin=dict(t=48, b=36, l=44, r=56))
    fig_tir.update_yaxes(title_text="Nº", secondary_y=False, rangemode="tozero")
    fig_tir.update_yaxes(title_text="% a puerta", secondary_y=True, showgrid=False,
                         range=[0, 110], ticksuffix="%")
    fig_tir.update_layout(legend=dict(y=1.14, x=0.3))
    chart(fig_tir)

    attack_items = []
    sot, gf = sum(tiros_prt), sum(goles_t)
    if sot:
        conv = [g / s * 100 if s else 0 for g, s in zip(goles_t, tiros_prt)]
        low = int(pd.Series(conv).idxmin())
        attack_items.append(("info", f"Conversión: {gf / sot * 100:.0f}% de los tiros a puerta",
                             f"{gf} goles con {sot} tiros a puerta. El partido de menor acierto fue "
                             f"{rivales[low]} ({goles_t[low]} de {tiros_prt[low]})."))
    wins, rest = temporada[temporada["res"] == "V"], temporada[temporada["res"] != "V"]
    if len(wins) and len(rest) and temporada["pct_pases_atq"].notna().any():
        attack_items.append(("warn", "El último tercio decide",
                             f"Precisión en el último tercio: <b>{wins['pct_pases_atq'].mean():.0f}%</b> en victorias "
                             f"frente a <b>{rest['pct_pases_atq'].mean():.0f}%</b> en el resto. Llegar no basta: "
                             f"hay que dar el último pase con ventaja."))
    insight_panel(attack_items)

    # ── 5: Defensa y balón parado ──
    section("5 · Defensa y balón parado",
            "Cuánto exige el rival a nuestra portería y cómo gestionamos faltas y córners.")
    par_t  = temporada["paradas"].fillna(0).astype(int).tolist()
    tap_t  = temporada["tap"].fillna(0).astype(int).tolist()
    ge_t   = temporada["gc"].tolist()
    fal_t  = temporada["faltas"].fillna(0).astype(int).tolist()
    sch_t  = temporada["jugadas_set"].fillna(0).astype(int).tolist()

    c1, c2 = st.columns(2)
    with c1:
        fig_def_t = go.Figure()
        for name, values, color in [("Paradas portero", par_t, AZUL_CELESTE),
                                    ("Disparos bloqueados", tap_t, DORADO),
                                    ("Goles encajados", ge_t, ROJO)]:
            fig_def_t.add_trace(go.Bar(name=name, x=rivales, y=values,
                                       marker=dict(color=color, line=dict(width=0)),
                                       text=values, textposition="outside",
                                       textfont=dict(color=color, size=11)))
        t(fig_def_t, height=320, barmode="group", bargap=0.25, title="Portería y bloqueos",
          margin=dict(t=48, b=36, l=36, r=16))
        fig_def_t.update_yaxes(rangemode="tozero")
        fig_def_t.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.14, x=0), margin=dict(b=72))
        chart(fig_def_t)
    with c2:
        fig_je = go.Figure()
        fig_je.add_trace(go.Bar(
            name="Saques de esquina", x=rivales, y=sch_t,
            marker=dict(color=AZUL_CELESTE, line=dict(width=0)),
            text=sch_t, textposition="outside", textfont=dict(color=AZUL_CELESTE, size=11),
        ))
        fig_je.add_trace(go.Bar(
            name="Faltas cometidas", x=rivales, y=fal_t,
            marker=dict(color=ROJO, opacity=0.85, line=dict(width=0)),
            text=fal_t, textposition="outside", textfont=dict(color=ROJO, size=11),
        ))
        t(fig_je, height=320, barmode="group", bargap=0.3, title="Córners a favor y faltas",
          margin=dict(t=48, b=36, l=36, r=16))
        fig_je.update_yaxes(rangemode="tozero")
        fig_je.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.14, x=0), margin=dict(b=72))
        chart(fig_je)

    def_items = []
    saves = sum(par_t) + sum(tap_t)
    if saves or sum(ge_t):
        def_items.append(("info", f"{sum(ge_t)} goles encajados · {sum(par_t)} paradas · {sum(tap_t)} bloqueos",
                          f"El rival llega a portería ~{(sum(par_t) + sum(ge_t)) / n_partidos:.1f} veces por "
                          f"partido entre paradas y goles."))
    if fal_t:
        worst = int(pd.Series(fal_t).idxmax())
        def_items.append(("warn" if fal_t[worst] >= 18 else "info", "Faltas cometidas",
                          f"Media de {sum(fal_t) / n_partidos:.1f} por partido; pico ante {rivales[worst]} "
                          f"({fal_t[worst]}). Más faltas = más balón parado en contra."))
    insight_panel(def_items)

    # ── 6: Táctico (LongoMatch) ──
    _render_tactical_season_summary(video_df, len(temporada))


# ── Página: Partido ───────────────────────────────────────────────────────────
def _block_list(blocks: pd.Series) -> str:
    minutes = [label for label, count in blocks.items() for _ in range(int(count))]
    return ", ".join(minutes) if minutes else "—"


def match_insights(df: pd.DataFrame, rival: str, video_df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Las 4-6 claves que explican un partido concreto."""
    m_all = matches_table(df)
    row = m_all[m_all["rival"] == rival].iloc[0]
    m = official_matches(m_all)
    items = []

    # Momentos del marcador
    blocks = goals_by_block(df, rival)
    if row["gf"] or row["gc"]:
        tone = "pos" if row["gf"] > row["gc"] else ("neg" if row["gf"] < row["gc"] else "warn")
        items.append((tone, "Cuándo se decidió",
                      f"Goles a favor: <b>{_block_list(blocks['gf'])}</b>. "
                      f"En contra: <b>{_block_list(blocks['gc'])}</b>."))

    # Dominio por tramos
    tr = (df[(df["nivel"] == "tramo") & (df["rival"] == rival) & df["tramo_raw"].isin(TRAMOS_REGULARES)]
          .set_index("tramo_raw")["pct_posesion"].dropna())
    if len(tr):
        dom = int((tr >= 50).sum())
        items.append(("pos" if dom > len(tr) / 2 else "warn", f"Mandamos en {dom} de {len(tr)} tramos",
                      f"Mejor tramo {tr.idxmax()}' ({tr.max():.0f}% de posesión); el peor, "
                      f"{tr.idxmin()}' ({tr.min():.0f}%)."))

    # Mitades
    partes = df[(df["nivel"] == "parte") & (df["rival"] == rival)].set_index("tramo_raw")
    if {"1º mitad", "2º mitad"} <= set(partes.index):
        p1, p2 = partes.loc["1º mitad"], partes.loc["2º mitad"]
        t1, t2 = p1.get("tiros") or 0, p2.get("tiros") or 0
        better = "2ª" if t2 > t1 else "1ª"
        items.append(("info", f"Mejor {better} parte en ataque",
                      f"Tiros {t1:.0f} → {t2:.0f}, a puerta {p1.get('tiros_puerta') or 0:.0f} → "
                      f"{p2.get('tiros_puerta') or 0:.0f}, pase {p1.get('pct_pases') or 0:.0f}% → "
                      f"{p2.get('pct_pases') or 0:.0f}%."))

    # Frente a la media de temporada
    if len(m) > 1:
        d_pas = row["pct_pases"] - m["pct_pases"].mean()
        d_sot = (row["tiros_puerta"] or 0) - m["tiros_puerta"].fillna(0).mean()
        tone = "pos" if d_pas >= 0 and d_sot >= 0 else ("neg" if d_pas < 0 and d_sot < 0 else "info")
        items.append((tone, "Frente a nuestra media",
                      f"Precisión de pase <b>{d_pas:+.0f} pts</b> y tiros a puerta <b>{d_sot:+.1f}</b> respecto a "
                      f"la media de temporada."))
        sot = int(row["tiros_puerta"] or 0)
        if sot >= 3 and row["gf"] == 0:
            items.append(("neg", "Sin premio de cara a puerta",
                          f"{sot} tiros a puerta y ningún gol: el resultado no refleja la producción ofensiva."))

    # Vídeo: cómo nos atacó el rival
    ev = _video_events_for_rival(video_df, rival)
    if not ev.empty:
        opp_fin = ev[(ev["equipo"] == "rival") & (ev["fase"] == "finalizacion")]
        if len(opp_fin) >= 3:
            tipo = opp_fin["tipo_llegada"].value_counts()
            carril = opp_fin["carril"].value_counts()
            if not tipo.empty:
                items.append(("warn" if tipo.iloc[0] / len(opp_fin) >= 0.5 else "info",
                              f"Así nos atacó {rival}",
                              f"<b>{tipo.iloc[0]} de {len(opp_fin)}</b> finalizaciones rivales llegaron por "
                              f"<b>{tipo.index[0].lower()}</b>"
                              + (f", sobre todo por el carril {carril.index[0].lower()}." if not carril.empty else ".")))
        total, converted = _recovery_conversion(ev)
        if total:
            items.append(("warn" if converted / total < 0.2 else "pos", "Tras recuperar",
                          f"{total} recuperaciones; <b>{converted}</b> terminan en finalización o gol en 20 s "
                          f"({converted / total * 100:.0f}%)."))
    return items


def page_partido(df: pd.DataFrame, video_df: pd.DataFrame):
    m_all = matches_table(df)
    m = official_matches(m_all)  # referencia "media temp.": solo partidos oficiales
    labels = {r["rival"]: f"{r['jlabel']} · CAdF vs {r['rival']} ({r['condicion']})" for _, r in m_all.iterrows()}
    rivales = m_all["rival"].tolist()
    rival_sel = st.selectbox("Partido", rivales, index=len(rivales) - 1,
                             format_func=lambda r: labels[r], key="partido_sel")

    pdata    = df[df["rival"] == rival_sel]
    temp_row = pdata[pdata["nivel"] == "temporada"].iloc[0]
    tramos   = pdata[pdata["nivel"] == "tramo"].set_index("tramo_raw").reindex(TRAMO_ORDER).reset_index()
    partes   = pdata[pdata["nivel"] == "parte"]
    mrow     = m_all[m_all["rival"] == rival_sel].iloc[0]

    gf, gc = int(mrow["gf"]), int(mrow["gc"])
    res_text = {"V": "Victoria", "E": "Empate", "D": "Derrota"}[mrow["res"]]

    # ── Cabecera: marcador ──
    page_header(
        f"CAdF <span class='cadf-score-big'>{gf}<em>–</em>{gc}</span> {rival_sel}",
        f"{res_text} · {mrow['condicion']} · "
        + (f"Jornada {mrow['jornada']}" if mrow["competicion"] == "Oficial" else "Amistoso de pretemporada"),
        kicker=f"Análisis de partido · Temporada {season_label(df)}",
        aside=result_chip(mrow["res"], res_text),
    )

    cols = st.columns(5)
    for col, html in zip(cols, [
        metric_card("Posesión", f"{mrow['pct_posesion']:.1f}", "%",
                    delta=vs_ref(mrow["pct_posesion"], m["pct_posesion"].mean(), 1, " pts"), accent=AZUL_CELESTE),
        metric_card("Precisión de pase", f"{mrow['pct_pases']:.0f}", "%",
                    delta=vs_ref(mrow["pct_pases"], m["pct_pases"].mean(), 0, " pts"), accent=AZUL_CELESTE),
        metric_card("Tiros / a puerta", f"{int(mrow['tiros'] or 0)}", f" / {int(mrow['tiros_puerta'] or 0)}",
                    delta=vs_ref(mrow["tiros_puerta"], m["tiros_puerta"].mean(), 1, " a puerta"), accent=DORADO),
        metric_card("Pase último tercio", f"{mrow['pct_pases_atq'] or 0:.0f}", "%",
                    delta=vs_ref(mrow["pct_pases_atq"], m["pct_pases_atq"].mean(), 0, " pts"), accent=DORADO),
        metric_card("Cadenas de 6+ pases", f"{int(mrow['cadenas_6mas'] or 0)}", "",
                    delta=vs_ref(mrow["cadenas_6mas"], m["cadenas_6mas"].mean(), 1), accent=VERDE),
    ]):
        col.markdown(html, unsafe_allow_html=True)

    insight_panel(match_insights(df, rival_sel, video_df), heading="Claves del partido")

    # ── Match Momentum ──
    section("La historia del partido",
            "Posesión por tramo de 15': arriba manda CAdF, abajo el rival. ⚽ gol a favor · 🔴 gol en contra.")

    tramos_mm   = tramos.dropna(subset=["pct_posesion"])
    tramo_labels_mm = tramos_mm["tramo_raw"].tolist()
    pos_vals_mm = tramos_mm["pct_posesion"].tolist()
    goles_mm    = tramos_mm["goles"].tolist()
    goles_enc_mm = tramos_mm["goles_enc"].tolist()
    pases_mm    = tramos_mm["pct_pases"].tolist()

    # Valor CAdF: pos - 50 (>0 domina CAdF, <0 domina rival)
    diff_vals   = [p - 50 for p in pos_vals_mm]
    colors_mm   = [AZUL_CELESTE if d >= 0 else GRIS_MEDIO for d in diff_vals]

    fig_mm = go.Figure()

    # Zona de fondo: arriba CAdF, abajo rival
    fig_mm.add_hrect(y0=0,   y1=50,  fillcolor="rgba(106,175,230,0.05)", line_width=0)
    fig_mm.add_hrect(y0=-50, y1=0,   fillcolor="rgba(200,214,229,0.04)", line_width=0)
    fig_mm.add_hline(y=0, line_color="rgba(255,255,255,0.35)", line_width=1.5)

    # Barras CAdF (arriba) — usando Bar trace real
    fig_mm.add_trace(go.Bar(
        x=tramo_labels_mm,
        y=[max(d, 0) for d in diff_vals],
        marker=dict(
            color=[AZUL_CELESTE if d >= 0 else "rgba(0,0,0,0)" for d in diff_vals],
            line=dict(width=0),
        ),
        base=0,
        showlegend=False,
        hovertemplate="%{x}<br>Posesión CAdF: <b>%{customdata[0]:.0f}%</b>"
                      "<br>Precisión de pase: %{customdata[1]:.0f}%<extra></extra>",
        customdata=list(zip(pos_vals_mm, pases_mm)),
    ))
    # Barras rival (abajo) — invertidas
    fig_mm.add_trace(go.Bar(
        x=tramo_labels_mm,
        y=[min(d, 0) for d in diff_vals],
        marker=dict(
            color=[GRIS_MEDIO if d < 0 else "rgba(0,0,0,0)" for d in diff_vals],
            opacity=0.7,
            line=dict(width=0),
        ),
        base=0,
        showlegend=False,
        hovertemplate="%{x}<br>Posesión rival: <b>%{customdata:.0f}%</b><extra></extra>",
        customdata=[100 - p for p in pos_vals_mm],
    ))

    # Etiquetas % posesión CAdF
    for lbl, d, pos in zip(tramo_labels_mm, diff_vals, pos_vals_mm):
        yshift = 8 if d >= 0 else -8
        yanchor = "bottom" if d >= 0 else "top"
        fig_mm.add_annotation(
            x=lbl, y=max(d, 0) if d >= 0 else min(d, 0),
            text=f"<b>{pos if d >= 0 else 100 - pos:.0f}%</b>",
            showarrow=False, yshift=yshift,
            yanchor=yanchor,
            font=dict(color=AZUL_CELESTE if d >= 0 else GRIS_MEDIO,
                      size=10, family="Inter"),
        )

    # ⚽ goles
    for lbl, d, g in zip(tramo_labels_mm, diff_vals, goles_mm):
        if pd.notna(g) and g > 0:
            for k in range(int(g)):
                fig_mm.add_annotation(
                    x=lbl, y=max(d, 0) + 10 + k * 10,
                    text="⚽", showarrow=False, font=dict(size=15),
                )
    for lbl, d, g in zip(tramo_labels_mm, diff_vals, goles_enc_mm):
        if pd.notna(g) and g > 0:
            for k in range(int(g)):
                fig_mm.add_annotation(
                    x=lbl, y=min(d, 0) - 10 - k * 10,
                    text="🔴", showarrow=False, font=dict(size=13),
                )

    # Separador descanso
    if "45+" in tramo_labels_mm and "46-60" in tramo_labels_mm:
        fig_mm.add_vline(
            x=tramo_labels_mm.index("45+") + 0.5,
            line_color="rgba(255,255,255,0.25)", line_width=1.5, line_dash="dash",
        )
        fig_mm.add_annotation(
            x=tramo_labels_mm.index("45+") + 0.5, y=56,
            text="DESCANSO", showarrow=False,
            font=dict(color=GRIS_MEDIO, size=10, family="Inter"),
        )

    # Etiquetas CAdF / Rival
    fig_mm.add_annotation(x=tramo_labels_mm[0], y=56, text="<b>▲ CAdF</b>",
                          showarrow=False, xanchor="left",
                          font=dict(color=AZUL_CELESTE, size=11, family="Inter"))
    fig_mm.add_annotation(x=tramo_labels_mm[0], y=-56, text=f"<b>▼ {rival_sel}</b>",
                          showarrow=False, xanchor="left",
                          font=dict(color=GRIS_MEDIO, size=11, family="Inter"))

    fig_mm.update_layout(
        paper_bgcolor=PAPER_BG, plot_bgcolor=PLOT_BG, hoverlabel=HOVER,
        height=360, margin=dict(t=20, b=30, l=60, r=20),
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO),
        barmode="overlay", bargap=0.25, barcornerradius=7,
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False,
                   tickfont=dict(color=GRIS_MEDIO, size=11)),
        yaxis=dict(
            range=[-62, 62],
            tickvals=[-50, -25, 0, 25, 50],
            ticktext=["100%", "75%", "50%", "75%", "100%"],
            showgrid=False, zeroline=False,
            tickfont=dict(color=GRIS_MEDIO, size=10),
        ),
    )
    chart(fig_mm)

    # ── Comparativa 1ª vs 2ª mitad ──
    section("Primera y segunda parte", "¿Qué cambió tras el descanso? Porcentajes y volúmenes por separado.")
    p1 = partes[partes["tramo_raw"] == "1º mitad"].iloc[0] if len(partes) >= 1 else {}
    p2 = partes[partes["tramo_raw"] == "2º mitad"].iloc[0] if len(partes) >= 2 else {}
    chart(_halves_chart(p1, p2))

    # ── Campograma de pases por tercio ──
    section("Pases por tercio del campo",
            "Dónde se juega el balón (burbuja = pases intentados) y con qué acierto en cada zona.")

    tercios_data = [
        ("DEF", "def_intentados", "def_completados", "pct_pases_def"),
        ("MED", "mid_intentados", "mid_completados", "pct_pases_mid"),
        ("ATQ", "atq_intentados", "atq_completados", "pct_pases_atq"),
    ]

    # Recoger datos
    zonas_vals = []
    for label, ip, pc, pct_col in tercios_data:
        intentados  = int(temp_row.get(ip) or 0)
        completados = int(temp_row.get(pc) or 0)
        perdidos    = intentados - completados
        pct         = temp_row.get(pct_col) or 0
        zonas_vals.append((label, intentados, completados, perdidos, pct))

    total_intentados = sum(v[1] for v in zonas_vals) or 1

    # ── Campograma + Barras: un único figura con subplots compartiendo eje X ──
    _, col_main, _ = st.columns([1, 7, 1])
    with col_main:
        pitch_w, pitch_h = 105, 68
        zone_w  = pitch_w / 3
        max_int = max(v[1] for v in zonas_vals) or 1

        # Centros de cada zona en coordenadas del campo
        zone_cx = [zone_w/2, zone_w + zone_w/2, 2*zone_w + zone_w/2]  # 17.5, 52.5, 87.5

        fig_cp = make_subplots(
            rows=2, cols=1,
            row_heights=[0.62, 0.38],
            vertical_spacing=0.03,
            shared_xaxes=True,
        )

        # ── Shapes del campo: layer="below" para que las burbujas queden encima ──
        def ps(shape_dict):
            """Añade layer=below a un shape del campo."""
            shape_dict["layer"] = "below"
            shape_dict.setdefault("xref", "x")
            shape_dict.setdefault("yref", "y")
            return shape_dict

        pitch_shapes = []
        # Césped
        for i in range(6):
            pitch_shapes.append(ps(dict(type="rect",
                x0=i*(pitch_w/6), y0=0, x1=(i+1)*(pitch_w/6), y1=pitch_h,
                fillcolor="#1E3D14" if i%2==0 else "#243D18",
                line=dict(width=0))))
        # Borde
        pitch_shapes.append(ps(dict(type="rect", x0=0, y0=0, x1=pitch_w, y1=pitch_h,
            fillcolor="rgba(0,0,0,0)", line=dict(color="white", width=2))))
        # Línea central
        pitch_shapes.append(ps(dict(type="line", x0=pitch_w/2, y0=0,
            x1=pitch_w/2, y1=pitch_h, line=dict(color="white", width=1.5))))
        # Círculo central
        pitch_shapes.append(ps(dict(type="circle",
            x0=pitch_w/2-9.15, y0=pitch_h/2-9.15,
            x1=pitch_w/2+9.15, y1=pitch_h/2+9.15,
            fillcolor="rgba(0,0,0,0)", line=dict(color="white", width=1.5))))
        # Áreas
        for ax0, ax1 in [(0, 16.5), (pitch_w-16.5, pitch_w)]:
            pitch_shapes.append(ps(dict(type="rect", x0=ax0, y0=pitch_h/2-20.16,
                x1=ax1, y1=pitch_h/2+20.16, fillcolor="rgba(0,0,0,0)",
                line=dict(color="white", width=1.5))))
            px0 = ax0 if ax0==0 else pitch_w-5.5
            px1 = 5.5 if ax0==0 else pitch_w
            pitch_shapes.append(ps(dict(type="rect", x0=px0, y0=pitch_h/2-9.16,
                x1=px1, y1=pitch_h/2+9.16, fillcolor="rgba(0,0,0,0)",
                line=dict(color="white", width=1))))
        # Divisores de tercio
        for xi in [zone_w, 2*zone_w]:
            pitch_shapes.append(ps(dict(type="line", x0=xi, y0=0, x1=xi, y1=pitch_h,
                line=dict(color="rgba(255,255,255,0.35)", width=1.5, dash="dash"))))

        # ── Row 1: burbujas (trace, siempre encima de shapes) ──
        bubble_sizes, bubble_texts = [], []
        for i, (label, intentados, completados, perdidos, pct) in enumerate(zonas_vals):
            pct_total = intentados / total_intentados * 100
            size_px = 55 + int((intentados / max_int) * 85)
            bubble_sizes.append(size_px)
            bubble_texts.append(str(intentados))
            # % total arriba del campo
            fig_cp.add_annotation(x=zone_cx[i], y=pitch_h+5,
                text=f"<b>{pct_total:.0f}%</b>", showarrow=False,
                font=dict(color=AZUL_CELESTE, size=12, family="Inter"),
                xref="x", yref="y")

        fig_cp.add_trace(go.Scatter(
            x=zone_cx, y=[pitch_h/2]*3,
            mode="markers+text",
            marker=dict(size=bubble_sizes, sizemode="diameter",
                        color="rgba(15,25,50,0.88)",
                        line=dict(color=AZUL_CELESTE, width=2.5)),
            text=bubble_texts,
            textposition="middle center",
            textfont=dict(color=BLANCO, size=20, family="Inter", weight=700),
            showlegend=False, hoverinfo="skip",
        ), row=1, col=1)

        # Flecha dirección ataque
        fig_cp.add_annotation(x=10, y=6, ax=2, ay=6,
            xref="x", yref="y", axref="x", ayref="y",
            text="", showarrow=True, arrowhead=2, arrowsize=1.2,
            arrowwidth=2, arrowcolor="rgba(255,255,255,0.4)")

        # ── Row 2: barras apiladas ──
        completados_vals = [v[2] for v in zonas_vals]
        perdidos_vals    = [v[3] for v in zonas_vals]
        pct_vals         = [v[4] for v in zonas_vals]
        max_bar = max(c+p for c, p in zip(completados_vals, perdidos_vals)) or 1

        fig_cp.add_trace(go.Bar(
            name="Pases completados", x=zone_cx, y=completados_vals,
            marker=dict(color=AZUL_CELESTE, line=dict(color=AZUL_OSCURO, width=1)),
            text=completados_vals, textposition="inside",
            textfont=dict(color=BLANCO, size=13, family="Inter"),
            insidetextanchor="middle", width=22,
        ), row=2, col=1)
        fig_cp.add_trace(go.Bar(
            name="Pases perdidos", x=zone_cx, y=perdidos_vals,
            marker=dict(color=GRIS_MEDIO, opacity=0.55,
                        line=dict(color=AZUL_OSCURO, width=1)),
            text=perdidos_vals, textposition="inside",
            textfont=dict(color=AZUL_OSCURO, size=12, family="Inter"),
            insidetextanchor="middle", width=22,
        ), row=2, col=1)

        # % bajo las barras y etiquetas DEF/MED/ATQ
        for i, (label, pct) in enumerate(zip(["DEF","MED","ATQ"], pct_vals)):
            pct_color = VERDE if pct >= 80 else (DORADO if pct >= 70 else ROJO)
            fig_cp.add_annotation(x=zone_cx[i], y=-max_bar*0.12,
                text=f"<b>{pct:.0f}%</b>", showarrow=False,
                font=dict(color=pct_color, size=13, family="Inter"),
                xref="x2", yref="y2")
            fig_cp.add_annotation(x=zone_cx[i], y=-max_bar*0.28,
                text=f"<b>{label}</b>", showarrow=False,
                font=dict(color=GRIS_MEDIO, size=11, family="Inter"),
                xref="x2", yref="y2")

        # ── Layout global ──
        fig_cp.update_layout(
            paper_bgcolor=PAPER_BG,
            height=540,
            margin=dict(t=30, b=50, l=10, r=10),
            font=dict(family="Inter, Arial, sans-serif", color=BLANCO),
            barmode="stack", barcornerradius=6,
            showlegend=True,
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLANCO, size=11),
                        orientation="h", y=-0.08, x=0.25),
            shapes=pitch_shapes,
            # Eje X compartido (coordenadas del campo 0-105)
            xaxis=dict(range=[-3, pitch_w+3], showgrid=False, zeroline=False,
                       showticklabels=False, fixedrange=True),
            xaxis2=dict(range=[-3, pitch_w+3], showgrid=False, zeroline=False,
                        showticklabels=False, fixedrange=True),
            # Eje Y fila 1: campo
            yaxis=dict(range=[-5, pitch_h+12], showgrid=False, zeroline=False,
                       showticklabels=False, fixedrange=True),
            # Eje Y fila 2: barras
            yaxis2=dict(range=[-max_bar*0.35, max_bar*1.15],
                        showgrid=False, zeroline=False,
                        showticklabels=False, fixedrange=True),
            plot_bgcolor=PAPER_BG,
        )
        st.plotly_chart(fig_cp, use_container_width=True,
                        config={"displayModeBar": False})

    # ── Cadenas de pase ──
    section("Juego asociativo: cadenas de pase",
            "¿Somos capaces de enlazar pases? Comparado con la media de temporada.")
    cad_cols = st.columns(5)
    for col, (label, key, dec, accent) in zip(cad_cols, [
        ("Cadenas totales", "cadenas_total", 0, AZUL_CELESTE),
        ("De 3 a 5 pases", "cadenas_3_5", 0, AZUL_CELESTE),
        ("De 6 o más pases", "cadenas_6mas", 0, DORADO),
        ("Pases por cadena", "cadenas_prom", 1, BLANCO),
        ("Cadena más larga", "cadena_max", 0, VERDE),
    ]):
        val = temp_row.get(key)
        col.markdown(metric_card(label, f"{val or 0:.{dec}f}", "",
                                 delta=vs_ref(val, m[key].mean(), 1), accent=accent),
                     unsafe_allow_html=True)

    # ── Defensa y balón parado ──
    section("Defensa y balón parado",
            "Qué nos exigió el rival y cuándo; faltas cometidas por tramo.")
    d_cols = st.columns(5)
    pa0 = int(temp_row.get("pa0") or 0)
    for col, html in zip(d_cols, [
        metric_card("Goles encajados", gc, "", delta=vs_ref(gc, m["gc"].mean(), 1, higher_better=False),
                    hint="Portería a cero" if pa0 or gc == 0 else "", accent=ROJO),
        metric_card("Paradas del portero", int(temp_row.get("paradas") or 0), "",
                    delta=vs_ref(temp_row.get("paradas"), m["paradas"].mean(), 1, higher_better=False),
                    accent=AZUL_CELESTE),
        metric_card("Disparos bloqueados", int(temp_row.get("tap") or 0), "",
                    delta=vs_ref(temp_row.get("tap"), m["tap"].mean(), 1), accent=DORADO),
        metric_card("Faltas cometidas", int(temp_row.get("faltas") or 0), "",
                    delta=vs_ref(temp_row.get("faltas"), m["faltas"].mean(), 1, higher_better=False),
                    accent=ROJO),
        metric_card("Córners / centros", int(temp_row.get("jugadas_set") or 0),
                    f" / {int(temp_row.get('centros') or 0)}",
                    hint=f"Penaltis: {int(temp_row.get('pl') or 0)}", accent=GRIS_MEDIO),
    ]):
        col.markdown(html, unsafe_allow_html=True)

    tr_labels = tramos["tramo_raw"].tolist()
    par_vals = tramos["paradas"].fillna(0).tolist()
    tap_vals = tramos["tap"].fillna(0).tolist()
    faltas_tramo = tramos["faltas"].fillna(0).tolist()
    c1, c2 = st.columns(2)
    for column, title, series in [
        (c1, "Paradas y bloqueos por tramo",
         [("Paradas portero", par_vals, AZUL_CELESTE), ("Disparos bloqueados", tap_vals, DORADO)]),
        (c2, "Faltas cometidas por tramo", [("Faltas", faltas_tramo, ROJO)]),
    ]:
        if not any(v > 0 for _, values, _ in series for v in values):
            continue
        fig = go.Figure()
        for name, values, color in series:
            fig.add_trace(go.Bar(name=name, x=tr_labels, y=values, marker=dict(color=color, line=dict(width=0)),
                                 text=[str(int(v)) if v > 0 else "" for v in values],
                                 textposition="outside", textfont=dict(color=color, size=11)))
        if "45+" in tr_labels and "46-60" in tr_labels:
            fig.add_vline(x=tr_labels.index("45+") + 0.5, line_color="rgba(255,255,255,0.2)",
                          line_width=1.2, line_dash="dash")
        t(fig, height=280, barmode="group", bargap=0.25, title=title,
          margin=dict(t=48, b=30, l=30, r=16), showlegend=len(series) > 1)
        fig.update_yaxes(rangemode="tozero", dtick=1 if max(max(v) for _, v, _ in series) <= 5 else None)
        fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.14, x=0), margin=dict(b=72))
        with column:
            chart(fig)

    _render_tactical_match_summary(video_df, rival_sel)


# ── Página: Rivales ───────────────────────────────────────────────────────────
def _share(series: pd.Series, value: str) -> float:
    series = series.dropna()
    return float((series == value).mean() * 100) if len(series) else float("nan")


def rival_insights(df: pd.DataFrame, rival: str, video_df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Lo que el cuerpo técnico necesita recordar del rival para la vuelta."""
    items = []
    ev = _video_events_for_rival(video_df, rival)
    if not ev.empty:
        opp = ev[ev["equipo"] == "rival"]
        starts = opp.loc[opp["fase"] == "inicio", "inicio_tipo"]
        if starts.notna().sum() >= 5:
            largo = _share(starts, "Largo")
            if largo >= 50:
                items.append(("warn", f"Salida en largo ({largo:.0f}%)",
                              "El rival evita construir desde atrás: preparar duelo aéreo, vigilancia de "
                              "segunda jugada y bloque que no se parta."))
            else:
                items.append(("info", f"Salida en corto ({100 - largo:.0f}%)",
                              "El rival intenta construir desde atrás: hay opción de presión alta con "
                              "disparadores claros para robar en zona de finalización."))
        prog = opp.loc[opp["fase"] == "progresion", "progresion_tipo"]
        if prog.notna().sum() >= 5:
            directo = _share(prog, "Directo")
            items.append(("warn" if directo >= 50 else "info",
                          f"Progresa {'en directo' if directo >= 50 else 'de forma organizada'} "
                          f"({max(directo, 100 - directo):.0f}%)",
                          "Ataca rápido a la espalda: cuidar la altura de la línea y las coberturas."
                          if directo >= 50 else
                          "Prefiere juntar pases: cerrar dentro y orientar su circulación hacia banda."))
        fin = opp[opp["fase"] == "finalizacion"]
        if len(fin) >= 3:
            tipo = fin["tipo_llegada"].value_counts()
            carril = fin["carril"].value_counts()
            items.append(("neg" if tipo.iloc[0] / len(fin) >= 0.5 else "warn",
                          f"Su vía de gol: {tipo.index[0].lower()}",
                          f"{tipo.iloc[0]} de {len(fin)} finalizaciones llegaron por {tipo.index[0].lower()}"
                          + (f"; carril más usado: {carril.index[0].lower()} ({carril.iloc[0]})." if len(carril) else ".")))
        set_rival = int(opp["fase"].isin(["corner", "tiro_libre"]).sum())
        set_own = int(ev[(ev["equipo"] == "propio") & ev["fase"].isin(["corner", "tiro_libre"])].shape[0])
        items.append(("info", "Balón parado",
                      f"Acciones a balón parado: CAdF {set_own} · {rival} {set_rival}."))

    tr = (df[(df["nivel"] == "tramo") & (df["rival"] == rival) & df["tramo_raw"].isin(TRAMOS_REGULARES)]
          .set_index("tramo_raw")["pct_posesion"].dropna())
    weak = tr[tr < 45]
    if len(weak):
        items.append(("neg", "Momentos en los que nos quitó el balón",
                      ", ".join(f"{k}' ({v:.0f}%)" for k, v in weak.items())
                      + ". Anticipar ajustes o cambios antes de esos tramos."))
    elif len(tr):
        items.append(("pos", "Control sostenido",
                      f"No hubo ningún tramo regular por debajo del 45% de posesión (mínimo {tr.min():.0f}%)."))
    return items


def _rivals_overview(m: pd.DataFrame, video_df: pd.DataFrame):
    """Tabla comparativa de todos los rivales con datos HUDL y de vídeo."""
    cols = "56px minmax(150px,1.6fr) 74px " + " ".join(["minmax(78px,1fr)"] * 6)
    heads = ["Posesión", "Pase", "Tiros (puerta)", "Finaliz. CAdF", "Finaliz. rival", "Recup. / pérd."]
    html = [f'<div class="cadf-score-wrap"><div class="cadf-score" style="grid-template-columns:{cols}">'
            '<div class="cadf-score-h">J</div><div class="cadf-score-h">Rival</div>'
            '<div class="cadf-score-h">Result.</div>'
            + "".join(f'<div class="cadf-score-h">{h}</div>' for h in heads)]
    for _, r in m.iterrows():
        ev = _video_events_for_rival(video_df, r["rival"])
        if ev.empty:
            fin_own = fin_opp = rec = "—"
            own_bg = opp_bg = "transparent"
        else:
            own = ev[ev["equipo"] == "propio"]
            f_own = int((own["fase"] == "finalizacion").sum())
            f_opp = int(((ev["equipo"] == "rival") & (ev["fase"] == "finalizacion")).sum())
            fin_own, fin_opp = str(f_own), str(f_opp)
            rec = f"{int((own['fase'] == 'recuperacion').sum())} / {int((own['fase'] == 'perdida').sum())}"
            own_bg = "rgba(76,175,130,0.25)" if f_own > f_opp else "transparent"
            opp_bg = "rgba(232,93,117,0.25)" if f_opp > f_own else "transparent"
        pos_bg = "rgba(106,175,230,0.22)" if r["pct_posesion"] >= 50 else "rgba(232,93,117,0.18)"
        html.append(
            f'<div class="cadf-score-j">J{r["jornada"]}</div>'
            f'<div class="cadf-score-rival">{r["rival"]} <span class="cadf-tag">{r["cond"]}</span></div>'
            f'<div>{result_chip(r["res"], f"{r["gf"]}-{r["gc"]}")}</div>'
            f'<div class="cadf-score-c" style="background:{pos_bg}">{r["pct_posesion"]:.0f}%</div>'
            f'<div class="cadf-score-c">{r["pct_pases"]:.0f}%</div>'
            f'<div class="cadf-score-c">{int(r["tiros"] or 0)} ({int(r["tiros_puerta"] or 0)})</div>'
            f'<div class="cadf-score-c" style="background:{own_bg}">{fin_own}</div>'
            f'<div class="cadf-score-c" style="background:{opp_bg}">{fin_opp}</div>'
            f'<div class="cadf-score-c">{rec}</div>'
        )
    html.append("</div></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def page_rivales(df: pd.DataFrame, video_df: pd.DataFrame):
    m = matches_table(df)
    page_header("Rivales", "Cómo nos han jugado y qué conviene recordar para el próximo enfrentamiento",
                kicker=f"Informe de rivales · Temporada {season_label(df)}")

    section("Comparativa de rivales",
            "Qué partido le hicimos a cada uno. Finalizaciones y recuperaciones según el vídeo (LongoMatch); "
            "en verde/rojo, quién finalizó más.")
    _rivals_overview(m, video_df)

    section("Perfil del rival", "Selecciona un rival para ver cómo construyó, cómo nos atacó y dónde nos hizo daño.")
    rivales = m["rival"].tolist()
    rival_sel = st.selectbox("Rival", rivales, index=len(rivales) - 1, key="rival_sel",
                             format_func=lambda r: f"{r} · J{int(m.loc[m['rival'] == r, 'jornada'].iloc[0])}")
    row = m[m["rival"] == rival_sel].iloc[0]
    ev = _video_events_for_rival(video_df, rival_sel)
    opp = ev[ev["equipo"] == "rival"] if not ev.empty else ev

    cols = st.columns(5)
    fin_opp = int((opp["fase"] == "finalizacion").sum()) if not ev.empty else None
    starts = opp.loc[opp["fase"] == "inicio", "inicio_tipo"] if not ev.empty else pd.Series(dtype=str)
    for col, html in zip(cols, [
        metric_card("Resultado", f"{row['gf']}–{row['gc']}", "",
                    hint=f"{ {'V': 'Victoria', 'E': 'Empate', 'D': 'Derrota'}[row['res']] } · {row['condicion']}",
                    accent=RESULT_COLORS[row["res"]]),
        metric_card("Posesión del rival", f"{100 - row['pct_posesion']:.0f}", "%", accent=GRIS_MEDIO),
        metric_card("Goles del rival", row["gc"], "", accent=ROJO),
        metric_card("Finalizaciones del rival", fin_opp if fin_opp is not None else "—", "",
                    hint="según vídeo" if fin_opp is not None else "sin vídeo etiquetado", accent=ROJO),
        metric_card("Inicios en largo", f"{_share(starts, 'Largo'):.0f}" if starts.notna().sum() else "—",
                    "%" if starts.notna().sum() else "", hint="de sus inicios de juego", accent=DORADO),
    ]):
        col.markdown(html, unsafe_allow_html=True)

    insight_panel(rival_insights(df, rival_sel, video_df),
                  heading=f"Claves para el próximo enfrentamiento ante {rival_sel}")

    if not ev.empty:
        c1, c2 = st.columns(2)
        with c1:
            fin = opp[opp["fase"] == "finalizacion"]
            table = pd.crosstab(fin["carril"], fin["tipo_llegada"]).reindex(
                index=["Izquierdo", "Central", "Derecho"], columns=["Centro", "Pase filtrado", "Remate"],
                fill_value=0)
            fig = go.Figure()
            for tipo, color in [("Centro", ROJO), ("Pase filtrado", DORADO), ("Remate", GRIS_MEDIO)]:
                fig.add_trace(depth_bar(color, tipo, table.index, table[tipo],
                                        text=[str(v) if v else "" for v in table[tipo]], pos="inside"))
            t(fig, height=320, barmode="stack", title=f"Cómo finalizó {rival_sel} · por carril (orientación CAdF)",
              margin=dict(t=48, b=36, l=36, r=16))
            fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.14, x=0), margin=dict(b=72))
            fig.update_yaxes(range=[0, max(int(table.sum(axis=1).max()), 1) * 1.2])
            chart(fig)
        with c2:
            prog = opp.loc[opp["fase"] == "progresion", "progresion_tipo"]
            build = pd.DataFrame({
                "Inicio": [int((starts == "Corto").sum()), int((starts == "Largo").sum())],
                "Progresión": [int((prog == "Organizado").sum()), int((prog == "Directo").sum())],
            }, index=["Elaborado (corto / organizado)", "Directo (largo / directo)"])
            fig = go.Figure()
            for idx, color in zip(build.index, [AZUL_CELESTE, ROJO]):
                fig.add_trace(depth_bar(color, idx, build.columns, build.loc[idx],
                                        text=build.loc[idx]))
            t(fig, height=320, barmode="group", title=f"Cómo construyó {rival_sel}",
              margin=dict(t=48, b=36, l=36, r=16))
            fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.14, x=0), margin=dict(b=72))
            fig.update_yaxes(title_text="Acciones", range=[0, max(int(build.to_numpy().max()), 1) * 1.2])
            chart(fig)
    else:
        st.info("Este partido aún no tiene CSV de LongoMatch: el perfil táctico del rival aparecerá al subirlo.")

    section("¿En qué momentos nos quitó el balón?",
            "Posesión CAdF por tramo ante este rival. En rojo, tramos por debajo del 45%.")
    tramos_df = df[(df["rival"] == rival_sel) & (df["nivel"] == "tramo")]
    tramos_mean = (
        tramos_df.groupby("tramo_raw")[["pct_posesion", "pct_pases"]]
        .mean().reindex(TRAMO_ORDER).reset_index()
    )
    fig_r = go.Figure()
    fig_r.add_hrect(y0=50, y1=110, fillcolor="rgba(106,175,230,0.05)", line_width=0)
    fig_r.add_hrect(y0=20, y1=50, fillcolor="rgba(232,93,117,0.05)", line_width=0)
    fig_r.add_hline(y=50, line_dash="dot", line_color="rgba(200,214,229,0.35)", line_width=1.5)
    for i, r in tramos_mean.iterrows():
        if pd.notna(r["pct_posesion"]) and r["pct_posesion"] < 45 and r["tramo_raw"] in TRAMOS_REGULARES:
            fig_r.add_vrect(x0=i - 0.5, x1=i + 0.5, fillcolor=ROJO, opacity=0.15, line_width=0)
    fig_r.add_trace(go.Scatter(
        x=list(range(len(tramos_mean))), y=tramos_mean["pct_posesion"],
        name="Posesión %", mode="lines+markers+text",
        line=dict(color=AZUL_CELESTE, width=3, shape="spline"),
        marker=dict(size=11, color=AZUL_CELESTE, line=dict(color=BLANCO, width=2)),
        text=[f"{v:.0f}%" if pd.notna(v) else "" for v in tramos_mean["pct_posesion"]],
        textposition="top center", textfont=dict(color=AZUL_CELESTE, size=10),
        connectgaps=True,
    ))
    fig_r.add_trace(go.Scatter(
        x=list(range(len(tramos_mean))), y=tramos_mean["pct_pases"],
        name="Precisión de pase %", mode="lines+markers",
        line=dict(color=DORADO, width=2, dash="dash", shape="spline"),
        marker=dict(size=8, color=DORADO), connectgaps=True,
    ))
    t(fig_r, height=360, margin=dict(t=30, b=40, l=44, r=20),
      yaxis=dict(range=[20, 110], ticksuffix="%"),
      xaxis=dict(tickvals=list(range(len(TRAMO_ORDER))), ticktext=TRAMO_ORDER))
    chart(fig_r)


# ── Página: Táctica (LongoMatch) ─────────────────────────────────────────────
def _tactical_counts(events: pd.DataFrame, order: list[str]) -> pd.Series:
    """Devuelve conteos con categorías vacías visibles para comparar partidos."""
    return events.value_counts().reindex(order, fill_value=0)


def _tactical_heatmap(events: pd.DataFrame, title: str, color: str = AZUL_CELESTE) -> go.Figure:
    """Representa eventos por zona y carril sobre un campo, no como una tabla."""
    zones = ["Zona 1", "Zona 2", "Zona 3"]
    lanes = ["Izquierdo", "Central", "Derecho"]
    matrix = (
        events.pivot_table(index="zona", columns="carril", aggfunc="size", fill_value=0)
        .reindex(index=zones, columns=lanes, fill_value=0)
    )
    total = len(events)
    maximum = max(int(matrix.to_numpy().max()), 1)
    color_rgb = {
        AZUL_CELESTE: "106,175,230",
        ROJO: "232,93,117",
    }.get(color, "106,175,230")
    fig = go.Figure()
    # Aplicamos primero el tema común; este define una forma de borde genérica.
    # Las formas del campo se añaden después para que no queden reemplazadas.
    t(fig, height=390, margin=dict(t=50, b=36, l=58, r=18), title=title)

    # Campo en orientación CAdF: zona 1 propia a la izquierda, zona 3 rival a la derecha.
    fig.add_shape(type="rect", x0=0, y0=0, x1=105, y1=68,
                  fillcolor="#285B32", line=dict(color=BLANCO, width=2))
    for x in [35, 70]:
        fig.add_shape(type="line", x0=x, y0=0, x1=x, y1=68,
                      line=dict(color="rgba(255,255,255,0.42)", width=1.2, dash="dot"))
    for y in [68 / 3, 2 * 68 / 3]:
        fig.add_shape(type="line", x0=0, y0=y, x1=105, y1=y,
                      line=dict(color="rgba(255,255,255,0.28)", width=1, dash="dot"))
    fig.add_shape(type="line", x0=52.5, y0=0, x1=52.5, y1=68,
                  line=dict(color="rgba(255,255,255,0.65)", width=1.2))
    fig.add_shape(type="circle", x0=43.35, y0=24.85, x1=61.65, y1=43.15,
                  line=dict(color="rgba(255,255,255,0.65)", width=1.2))
    for x0, x1 in [(0, 16.5), (88.5, 105)]:
        fig.add_shape(type="rect", x0=x0, y0=13.84, x1=x1, y1=54.16,
                      fillcolor="rgba(0,0,0,0)", line=dict(color="rgba(255,255,255,0.65)", width=1.2))

    # Cada celda coloreada recoge una combinación de tercio y carril.
    lane_ranges = {"Izquierdo": (2 * 68 / 3, 68), "Central": (68 / 3, 2 * 68 / 3), "Derecho": (0, 68 / 3)}
    for zone_index, zone in enumerate(zones):
        for lane in lanes:
            value = int(matrix.loc[zone, lane])
            y0, y1 = lane_ranges[lane]
            percentage = 0 if total == 0 else value / total * 100
            alpha = 0.08 if value == 0 else 0.18 + 0.62 * value / maximum
            fig.add_shape(
                type="rect", x0=zone_index * 35 + 1.2, x1=(zone_index + 1) * 35 - 1.2,
                y0=y0 + 1.2, y1=y1 - 1.2,
                fillcolor=f"rgba({color_rgb},{alpha:.2f})",
                line=dict(color="rgba(255,255,255,0.10)", width=1),
            )
            fig.add_annotation(
                x=zone_index * 35 + 17.5, y=(y0 + y1) / 2,
                text=f"<b>{value}</b><br><span style='font-size:10px'>{percentage:.1f}%</span>",
                showarrow=False, font=dict(color=BLANCO, size=18, family="Inter"),
            )

    for zone_index, zone in enumerate(zones):
        fig.add_annotation(x=zone_index * 35 + 17.5, y=-4.2, text=zone,
                           showarrow=False, font=dict(color=GRIS_MEDIO, size=10, family="Inter"))
    for lane, (y0, y1) in lane_ranges.items():
        fig.add_annotation(x=-5, y=(y0 + y1) / 2, text=lane, showarrow=False,
                           textangle=-90, font=dict(color=GRIS_MEDIO, size=10, family="Inter"))
    fig.add_annotation(x=52.5, y=73.5, text="Ataque CAdF  →", showarrow=False,
                       font=dict(color=DORADO, size=11, family="Inter"))
    fig.add_annotation(
        x=0, y=78, xanchor="left", yanchor="bottom", showarrow=False,
        text=f"<span style='font-size:10px'>Total: {total} eventos · cada celda muestra total y % del total</span>",
        font=dict(color=GRIS_MEDIO, size=10, family="Inter"),
    )

    fig.update_xaxes(range=[-8, 108], visible=False, fixedrange=True)
    fig.update_yaxes(range=[-8, 83], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1)
    return fig


def _tactical_rival_key(value: str) -> str:
    """Une los nombres de rival de HUDL y LongoMatch sin forzar el texto mostrado."""
    value = str(value).lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))
    key = "".join(char for char in value if char.isalnum())
    key = key.removesuffix("cf")
    aliases = {
        "rmb": "rayomajadahondab",
        "fundacionadfa": "fundacionadf",
    }
    return aliases.get(key, key)


def _video_events_for_rival(video_df: pd.DataFrame, rival: str) -> pd.DataFrame:
    if video_df.empty:
        return video_df
    key = _tactical_rival_key(rival)
    return video_df[video_df["rival"].map(_tactical_rival_key) == key]


def _tactical_20_second_outcomes(events: pd.DataFrame, trigger_phase: str) -> pd.Series:
    """Clasifica la acción más avanzada durante 20 s tras recuperar o perder."""
    events = events.sort_values("time_seconds").reset_index(drop=True)
    is_recovery = trigger_phase == "recuperacion"
    trigger_team = "propio"
    target_team = "propio" if is_recovery else "rival"
    stop_phase = "perdida" if is_recovery else "recuperacion"
    labels = (
        ["Gol", "Finalización", "Balón parado", "Progresión", "Pérdida sin progresar", "Sin evento"]
        if is_recovery
        else ["Gol rival", "Finalización rival", "Balón parado rival", "Progresión rival", "Recuperamos antes", "Sin evento"]
    )
    priority = [("gol", labels[0]), ("finalizacion", labels[1]),
                ("corner", labels[2]), ("tiro_libre", labels[2]), ("progresion", labels[3])]
    outcomes = []

    for _, trigger in events[events["fase"] == trigger_phase].iterrows():
        start = trigger["time_seconds"]
        future = events[events["time_seconds"] > start]
        stopper = future[(future["equipo"] == trigger_team) & (future["fase"] == stop_phase)]
        stop_at = min(start + 20, stopper["time_seconds"].iloc[0]) if not stopper.empty else start + 20
        window = future[future["time_seconds"] <= stop_at]
        outcome = None
        for phase, label in priority:
            if not window[(window["equipo"] == target_team) & (window["fase"] == phase)].empty:
                outcome = label
                break
        if outcome is None:
            stopped = not stopper.empty and stopper["time_seconds"].iloc[0] <= start + 20
            outcome = labels[4] if stopped else labels[5]
        outcomes.append(outcome)
    return pd.Series(outcomes).value_counts().reindex(labels, fill_value=0)


def _generated_breakdown(events: pd.DataFrame, phase: str) -> pd.Series:
    """Desglosa recuperaciones o pérdidas por si el evento fue generado."""
    relevant = events[events["fase"] == phase]
    if "origen_recuperacion_perdida" not in relevant.columns:
        # Compatibilidad con datos que Streamlit hubiera dejado en caché antes
        # de añadir esta columna al cargador de LongoMatch.
        tags = relevant.get("tags", pd.Series("", index=relevant.index)).fillna("")
        origin = tags.map(
            lambda value: "No generada" if "NO GENERADA" in value
            else ("Generada" if "GENERADA" in value else None)
        )
    else:
        origin = relevant["origen_recuperacion_perdida"]
    counts = _tactical_counts(
        origin.dropna(), ["Generada", "No generada"],
    )
    missing = len(relevant) - int(counts.sum())
    if missing:
        counts.loc["Sin etiquetar"] = missing
    return counts


def _tactical_with_periods(events: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Añade parte y tramo de juego usando saques o, en su defecto, el descanso."""
    timed = events.sort_values("time_seconds").copy()
    if timed.empty:
        timed["parte"] = []
        timed["tramo"] = []
        return timed, ""

    alignment = timed[
        (timed["fase"] == "sustitucion")
        & timed["nombre"].fillna("").str.contains("alineaci", case=False, na=False)
    ]
    first_start = float(alignment["time_seconds"].iloc[0]) if not alignment.empty else float(timed["time_seconds"].min())
    gaps = timed["time_seconds"].diff()
    candidates = gaps[(timed["time_seconds"] > first_start + 25 * 60) & (gaps >= 5 * 60)]
    second_start = None
    if not candidates.empty:
        second_start = float(timed.loc[candidates.idxmax(), "time_seconds"])

    if second_start is None:
        elapsed = timed["time_seconds"] - first_start
        timed["match_seconds"] = elapsed.clip(lower=0)
        source = "Tramos calculados desde el inicio del vídeo; falta marcar el inicio del segundo tiempo."
    else:
        timed["match_seconds"] = (timed["time_seconds"] - first_start).where(
            timed["time_seconds"] < second_start,
            45 * 60 + timed["time_seconds"] - second_start,
        ).clip(lower=0)
        source = "El inicio del segundo tiempo se ha estimado por el descanso; el marcador INICIO 2T lo hará exacto."

    timed["parte"] = pd.cut(
        timed["match_seconds"], bins=[-1, 45 * 60, float("inf")], labels=["1T", "2T"],
    ).astype(str)
    timed["tramo"] = pd.cut(
        timed["match_seconds"],
        bins=[-1, 15 * 60, 30 * 60, 45 * 60, 60 * 60, 75 * 60, float("inf")],
        labels=["0–15'", "15–30'", "30–45+'", "45–60'", "60–75'", "75+'"],
    ).astype(str)
    return timed, source


def _tactical_tramo_counts(events: pd.DataFrame, phase: str, team: str) -> pd.Series:
    """Cuenta eventos de una fase por los seis tramos tácticos del partido."""
    order = ["0–15'", "15–30'", "30–45+'", "45–60'", "60–75'", "75+'"]
    return _tactical_counts(
        events.loc[(events["fase"] == phase) & (events["equipo"] == team), "tramo"].dropna(), order,
    )


def _tactical_origin_by_context(events: pd.DataFrame, phase: str, context: str) -> pd.DataFrame:
    """Prepara el desglose Generada/No generada por parte o por zona."""
    relevant = events[events["fase"] == phase].copy()
    if "origen_recuperacion_perdida" not in relevant.columns:
        tags = relevant.get("tags", pd.Series("", index=relevant.index)).fillna("")
        relevant["origen_recuperacion_perdida"] = tags.map(
            lambda value: "No generada" if "NO GENERADA" in value
            else ("Generada" if "GENERADA" in value else "Sin etiquetar")
        )
    relevant["origen_recuperacion_perdida"] = relevant["origen_recuperacion_perdida"].fillna("Sin etiquetar")
    order = ["1T", "2T"] if context == "parte" else ["Zona 1", "Zona 2", "Zona 3"]
    table = pd.crosstab(relevant[context], relevant["origen_recuperacion_perdida"])
    return table.reindex(index=order, columns=["Generada", "No generada", "Sin etiquetar"], fill_value=0)


def _tactical_transition_minimap(transitions: pd.DataFrame, dimension: str, title: str) -> go.Figure:
    """Representa la transición defensiva por zonas o por carriles sobre un mini campo."""
    groups = ["Zona 1", "Zona 2", "Zona 3"] if dimension == "zona" else ["Izquierdo", "Central", "Derecho"]
    table = pd.crosstab(transitions[dimension], transitions["transicion_defensiva"])
    table = table.reindex(index=groups, columns=["PTP", "Repliegue", "Mixta"], fill_value=0)
    totals = table.sum(axis=1)
    maximum = max(int(totals.max()), 1)

    fig = go.Figure()
    t(fig, height=300, margin=dict(t=44, b=30, l=18, r=18), title=title)
    fig.add_shape(type="rect", x0=0, y0=0, x1=105, y1=68,
                  fillcolor="#285B32", line=dict(color=BLANCO, width=1.5))
    for x in [35, 70]:
        fig.add_shape(type="line", x0=x, y0=0, x1=x, y1=68,
                      line=dict(color="rgba(255,255,255,.35)", width=1, dash="dot"))
    for y in [68 / 3, 2 * 68 / 3]:
        fig.add_shape(type="line", x0=0, y0=y, x1=105, y1=y,
                      line=dict(color="rgba(255,255,255,.25)", width=1, dash="dot"))
    fig.add_shape(type="line", x0=52.5, y0=0, x1=52.5, y1=68,
                  line=dict(color="rgba(255,255,255,.5)", width=1))

    lane_ranges = {"Izquierdo": (2 * 68 / 3, 68), "Central": (68 / 3, 2 * 68 / 3), "Derecho": (0, 68 / 3)}
    for index, group in enumerate(groups):
        if dimension == "zona":
            x0, x1, y0, y1 = index * 35 + 1.2, (index + 1) * 35 - 1.2, 1.2, 66.8
            label_x, label_y = index * 35 + 17.5, 34
        else:
            y0, y1 = lane_ranges[group]
            x0, x1 = 1.2, 103.8
            label_x, label_y = 52.5, (y0 + y1) / 2
        total = int(totals[group])
        alpha = .08 if total == 0 else .18 + .62 * total / maximum
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0 + 1.2, y1=y1 - 1.2,
                      fillcolor=f"rgba(106,175,230,{alpha:.2f})",
                      line=dict(color="rgba(255,255,255,.12)", width=1))
        fig.add_annotation(
            x=label_x, y=label_y,
            text=(f"<b>{total}</b><br><span style='font-size:10px'>"
                  f"PTP {int(table.loc[group, 'PTP'])} · Rep {int(table.loc[group, 'Repliegue'])} · Mixta {int(table.loc[group, 'Mixta'])}</span>"),
            showarrow=False, font=dict(color=BLANCO, size=17, family="Inter"),
        )

    fig.add_annotation(x=52.5, y=73, text="Ataque CAdF  →", showarrow=False,
                       font=dict(color=DORADO, size=10, family="Inter"))
    fig.update_xaxes(range=[-2, 107], visible=False, fixedrange=True)
    fig.update_yaxes(range=[-2, 78], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1)
    return fig


def _render_tactical_match_summary(video_df: pd.DataFrame, rival: str):
    """Añade el análisis táctico LongoMatch al partido HUDL seleccionado."""
    section("Vídeo análisis táctico")
    events = _video_events_for_rival(video_df, rival)
    if events.empty:
        st.info(
            "No hay un CSV de LongoMatch vinculado a este partido todavía. "
            "Cuando se suba a la carpeta Partidos de Drive, aparecerá aquí automáticamente."
        )
        return

    events, timing_note = _tactical_with_periods(events)
    own = events[events["equipo"] == "propio"]
    opponent = events[events["equipo"] == "rival"]
    cards = st.columns(4)
    for col, (label, value, color) in zip(cards, [
        ("Finalizaciones CAdF", int((own["fase"] == "finalizacion").sum()), AZUL_CELESTE),
        ("Finalizaciones rival", int((opponent["fase"] == "finalizacion").sum()), ROJO),
        ("Recuperaciones", int((own["fase"] == "recuperacion").sum()), VERDE),
        ("Pérdidas", int((own["fase"] == "perdida").sum()), DORADO),
    ]):
        col.markdown(f"""
        <div style="background:{AZUL_MEDIO};border-radius:10px;padding:14px 16px;
                    border-top:3px solid {color};text-align:center;margin-bottom:8px;">
            <div style="color:{GRIS_MEDIO};font-size:0.68rem;text-transform:uppercase;
                        letter-spacing:0.08em;margin-bottom:6px;">{label}</div>
            <div style="color:{color};font-size:1.8rem;font-weight:800;">{value}</div>
        </div>""", unsafe_allow_html=True)

    tab_summary, tab_attack, tab_without_ball, tab_set_pieces = st.tabs([
        "Resumen", "Con balón", "Sin balón y transiciones", "Balón parado",
    ])

    with tab_summary:
        phases = ["inicio", "progresion", "finalizacion", "gol"]
        labels = ["Inicio", "Progresión", "Finalización", "Gol"]
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "CAdF", labels, _tactical_counts(own["fase"], phases)))
        fig.add_trace(depth_bar(ROJO, rival, labels, _tactical_counts(opponent["fase"], phases)))
        t(fig, height=330, barmode="group", margin=dict(t=45, b=42, l=40, r=20),
          title="Eventos por fase")
        fig.update_yaxes(title="Eventos")
        chart(fig)

        own_finals_tramo = _tactical_tramo_counts(events, "finalizacion", "propio")
        rival_finals_tramo = _tactical_tramo_counts(events, "finalizacion", "rival")
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "CAdF", own_finals_tramo.index,
                                own_finals_tramo.values, text=own_finals_tramo.values))
        fig.add_trace(depth_bar("#AEB9C9", rival, rival_finals_tramo.index,
                                rival_finals_tramo.values, text=rival_finals_tramo.values))
        own_goals = events[(events["fase"] == "gol") & (events["equipo"] == "propio")]
        rival_goals = events[(events["fase"] == "gol") & (events["equipo"] == "rival")]
        for goals, color, label in [(own_goals, VERDE, "Gol CAdF"), (rival_goals, ROJO, "Gol rival")]:
            goal_counts = goals["tramo"].value_counts().reindex(own_finals_tramo.index, fill_value=0)
            fig.add_trace(go.Scatter(
                x=goal_counts.index, y=[0.35 if value else None for value in goal_counts.values],
                mode="markers", name=label, marker=dict(size=9, color=color, line=dict(color=BLANCO, width=1)),
                hovertemplate=f"{label}: %{{x}}<extra></extra>",
            ))
        t(fig, height=320, barmode="group", margin=dict(t=45, b=45, l=35, r=20),
          title="Finalizaciones por tramos de 15 minutos")
        fig.update_yaxes(title="Finalizaciones", rangemode="tozero")
        chart(fig)

        c1, c2 = st.columns(2)
        with c1:
            recovery_outcomes = _tactical_20_second_outcomes(events, "recuperacion")
            fig = go.Figure(depth_bar(AZUL_CELESTE, "Tras recuperar", recovery_outcomes.index,
                                      recovery_outcomes.values, text=recovery_outcomes.values))
            t(fig, height=310, margin=dict(t=48, b=72, l=35, r=20),
              title="Los 20 s posteriores a recuperar")
            chart(fig)
        with c2:
            loss_outcomes = _tactical_20_second_outcomes(events, "perdida")
            fig = go.Figure(depth_bar(ROJO, "Tras perder", loss_outcomes.index,
                                      loss_outcomes.values, text=loss_outcomes.values))
            t(fig, height=310, margin=dict(t=48, b=72, l=35, r=20),
              title="Los 20 s posteriores a perder")
            chart(fig)

    with tab_attack:
        starts = _tactical_counts(own.loc[own["fase"] == "inicio", "inicio_tipo"].dropna(), ["Corto", "Largo"])
        progressions = _tactical_counts(own.loc[own["fase"] == "progresion", "progresion_tipo"].dropna(),
                                        ["Directo", "Organizado"])
        finals = _tactical_counts(own.loc[own["fase"] == "finalizacion", "tipo_llegada"].dropna(),
                                  ["Centro", "Pase filtrado", "Remate"])
        goals = int((own["fase"] == "gol").sum())
        phase_cards = st.columns(4)
        for column, label, value, detail, color in [
            (phase_cards[0], "Inicio", int((own["fase"] == "inicio").sum()),
             f"corto {starts['Corto']} · largo {starts['Largo']}", AZUL_CELESTE),
            (phase_cards[1], "Progresión", int((own["fase"] == "progresion").sum()),
             f"directo {progressions['Directo']} · organizado {progressions['Organizado']}", "#3574B9"),
            (phase_cards[2], "Finalización", int((own["fase"] == "finalizacion").sum()),
             f"centro {finals['Centro']} · filtrado {finals['Pase filtrado']} · remate {finals['Remate']}", DORADO),
            (phase_cards[3], "Goles", goals, "eventos de gol etiquetados", VERDE),
        ]:
            column.markdown(f"""
            <div style="background:{AZUL_MEDIO};border:1px solid rgba(255,255,255,.12);border-top:4px solid {color};
                        border-radius:9px;padding:13px 15px;margin-bottom:12px;min-height:86px;">
                <div style="font-size:.7rem;text-transform:uppercase;color:{GRIS_MEDIO};letter-spacing:.06em">{label}</div>
                <div style="font-size:1.7rem;color:{color};font-weight:800;line-height:1.15">{value}</div>
                <div style="font-size:.68rem;color:{GRIS_MEDIO};margin-top:5px">{detail}</div>
            </div>""", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            own_types = _tactical_counts(own.loc[own["fase"] == "finalizacion", "tipo_llegada"].dropna(),
                                         ["Centro", "Pase filtrado", "Remate"])
            fig = go.Figure(depth_bar(DORADO, "CAdF", own_types.index, own_types.values, text=own_types.values))
            t(fig, height=290, margin=dict(t=45, b=38, l=35, r=20), title="Cómo finaliza CAdF")
            chart(fig)
        with c2:
            fig = go.Figure(depth_bar(AZUL_CELESTE, "CAdF", progressions.index, progressions.values,
                                      text=progressions.values))
            t(fig, height=290, margin=dict(t=45, b=38, l=35, r=20), title="Tipo de progresión propia")
            chart(fig)

        phase_rows = []
        for phase, label, subtype, subtype_value in [
            ("inicio", "Inicio corto", "inicio_tipo", "Corto"),
            ("progresion", "Progresiones", None, None),
            ("finalizacion", "Finalizaciones", None, None),
        ]:
            phase_events = own[own["fase"] == phase]
            if subtype:
                phase_events = phase_events[phase_events[subtype] == subtype_value]
            values = phase_events.groupby("parte").size().reindex(["1T", "2T"], fill_value=0)
            phase_rows.append({"fase": label, "1T": values["1T"], "2T": values["2T"]})
        phase_by_half = pd.DataFrame(phase_rows)
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "1T", phase_by_half["fase"], phase_by_half["1T"], text=phase_by_half["1T"]))
        fig.add_trace(depth_bar("#B8D8F4", "2T", phase_by_half["fase"], phase_by_half["2T"], text=phase_by_half["2T"]))
        t(fig, height=300, barmode="group", margin=dict(t=45, b=42, l=35, r=20),
          title="Fase ofensiva propia · primer y segundo tiempo")
        fig.update_yaxes(title="Eventos")
        chart(fig)
        chart(_tactical_heatmap(own[own["fase"] == "finalizacion"], "Campograma de finalizaciones CAdF"))

    with tab_without_ball:
        c1, c2 = st.columns(2)
        with c1:
            chart(_tactical_heatmap(
                own[own["fase"] == "recuperacion"], "Campograma de recuperaciones", AZUL_CELESTE,
            ))
        with c2:
            chart(_tactical_heatmap(
                own[own["fase"] == "perdida"], "Campograma de pérdidas", ROJO,
            ))

        section("Cómo se gana y cómo se pierde el balón")
        st.caption(
            "En recuperaciones, Generada significa que CAdF provoca el robo mediante presión, duelo o anticipación. "
            "En pérdidas, Generada significa que el rival provoca la pérdida. No generada: no se atribuye a una acción directa."
        )
        c1, c2 = st.columns(2)
        for column, phase, label, palette in [
            (c1, "recuperacion", "Recuperaciones", {
                "Generada": "#2F8A69", "No generada": "#9BCFBA", "Sin etiquetar": "#8A99AD",
            }),
            (c2, "perdida", "Pérdidas", {
                "Generada": "#E9938B", "No generada": "#C93B30", "Sin etiquetar": "#8A99AD",
            }),
        ]:
            breakdown = _generated_breakdown(own, phase)
            with column:
                total = int((own["fase"] == phase).sum())
                st.markdown(f"""
                <div style="background:{AZUL_MEDIO};border-radius:9px;border-left:4px solid {palette['Generada']};
                            padding:12px 15px;margin-bottom:10px;">
                    <div style="text-transform:uppercase;color:{GRIS_MEDIO};font-size:.72rem;letter-spacing:.06em">{label}</div>
                    <div style="color:{BLANCO};font-size:1.7rem;font-weight:800;line-height:1.1">{total}</div>
                    <div style="color:{GRIS_MEDIO};font-size:.72rem;margin-top:5px">
                        {int(breakdown.get('Generada', 0))} generadas · {int(breakdown.get('No generada', 0))} no generadas
                    </div>
                </div>""", unsafe_allow_html=True)
                for context, context_label in [("parte", "Por tiempo"), ("zona", "Por zona")]:
                    table = _tactical_origin_by_context(own, phase, context)
                    fig = go.Figure()
                    for column_name in ["Generada", "No generada", "Sin etiquetar"]:
                        if table[column_name].sum():
                            fig.add_trace(depth_bar(palette[column_name], column_name, table.index, table[column_name],
                                                    text=table[column_name]))
                    t(fig, height=225, barmode="stack", margin=dict(t=40, b=32, l=35, r=10),
                      title=f"{label} · generadas/no generadas · {context_label.lower()}")
                    fig.update_yaxes(title="Eventos")
                    chart(fig)

        responses = _tactical_counts(
            own.loc[own["fase"] == "transicion_defensiva", "transicion_defensiva"].dropna(),
            ["PTP", "Repliegue", "Mixta"],
        )
        fig = go.Figure(depth_bar(ROJO, "Respuesta tras pérdida", responses.index, responses.values,
                                  text=responses.values))
        t(fig, height=270, margin=dict(t=42, b=35, l=35, r=20), title="Respuesta tras pérdida")
        chart(fig)

        transitions = own[own["fase"] == "transicion_defensiva"]
        c1, c2 = st.columns(2)
        with c1:
            chart(_tactical_transition_minimap(
                transitions, "zona", "Transición defensiva · por zona",
            ))
        with c2:
            chart(_tactical_transition_minimap(
                transitions, "carril", "Transición defensiva · por carril",
            ))

        tramo_order = ["0–15'", "15–30'", "30–45+'", "45–60'", "60–75'", "75+'"]
        table = pd.crosstab(transitions["tramo"], transitions["transicion_defensiva"])
        table = table.reindex(index=tramo_order, columns=["PTP", "Repliegue", "Mixta"], fill_value=0)
        fig = go.Figure()
        for response, color in [("PTP", AZUL_CELESTE), ("Repliegue", "#AEB9C9"), ("Mixta", DORADO)]:
            fig.add_trace(depth_bar(color, response, table.index, table[response], text=table[response]))
        t(fig, height=285, barmode="stack", margin=dict(t=45, b=42, l=35, r=20),
          title="Respuesta tras pérdida por tramos de 15 minutos")
        fig.update_yaxes(title="Transiciones")
        chart(fig)

    with tab_set_pieces:
        phases = ["corner", "tiro_libre"]
        labels = ["Córner", "Tiro libre"]
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "CAdF", labels, _tactical_counts(own["fase"], phases)))
        fig.add_trace(depth_bar(ROJO, rival, labels, _tactical_counts(opponent["fase"], phases)))
        t(fig, height=330, barmode="group", margin=dict(t=45, b=45, l=35, r=20),
          title="Acciones a balón parado")
        fig.update_yaxes(title="Acciones")
        chart(fig)

    st.caption(
        "Fuente: etiquetado LongoMatch. Las ventanas de 20 segundos usan el reloj de vídeo; "
        f"{timing_note}"
    )


def _render_tactical_season_summary(video_df: pd.DataFrame, hudl_matches: int):
    """Resume la temporada de vídeo sin mezclarla con las métricas HUDL."""
    section("Vídeo análisis táctico · acumulado")
    if video_df.empty:
        st.info("Aún no hay CSV de LongoMatch disponibles en Google Drive.")
        return

    own = video_df[video_df["equipo"] == "propio"]
    opponent = video_df[video_df["equipo"] == "rival"]
    tactical_matches = video_df["partido"].nunique()
    cards = st.columns(4)
    for col, (label, value, color) in zip(cards, [
        ("Partidos etiquetados", tactical_matches, AZUL_CELESTE),
        ("Finalizaciones CAdF", int((own["fase"] == "finalizacion").sum()), DORADO),
        ("Recuperaciones", int((own["fase"] == "recuperacion").sum()), VERDE),
        ("Pérdidas", int((own["fase"] == "perdida").sum()), ROJO),
    ]):
        col.markdown(metric_card(label, value), unsafe_allow_html=True)

    tab_summary, tab_attack, tab_without_ball, tab_set_pieces = st.tabs([
        "Resumen acumulado", "Con balón", "Sin balón y transiciones", "Balón parado",
    ])

    with tab_summary:
        rows = []
        for partido, events in video_df.groupby("partido", sort=False):
            own_events = events[events["equipo"] == "propio"]
            rival_events = events[events["equipo"] == "rival"]
            rows.append({
                "partido": partido.replace("CAdF vs ", ""),
                "CAdF": int((own_events["fase"] == "finalizacion").sum()),
                "Rival": int((rival_events["fase"] == "finalizacion").sum()),
            })
        finals = pd.DataFrame(rows)
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "Finalizaciones CAdF", finals["partido"], finals["CAdF"], text=finals["CAdF"]))
        fig.add_trace(depth_bar(ROJO, "Finalizaciones rival", finals["partido"], finals["Rival"], text=finals["Rival"]))
        t(fig, height=340, barmode="group", margin=dict(t=42, b=45, l=35, r=20),
          title="Finalizaciones por partido etiquetado")
        fig.update_yaxes(title="Eventos")
        chart(fig)

    with tab_attack:
        c1, c2 = st.columns(2)
        with c1:
            own_types = _tactical_counts(own.loc[own["fase"] == "finalizacion", "tipo_llegada"].dropna(),
                                         ["Centro", "Pase filtrado", "Remate"])
            fig = go.Figure(depth_bar(AZUL_CELESTE, "CAdF", own_types.index, own_types.values, text=own_types.values))
            t(fig, height=290, margin=dict(t=42, b=38, l=35, r=20), title="Cómo finaliza CAdF")
            chart(fig)
        with c2:
            rival_types = _tactical_counts(opponent.loc[opponent["fase"] == "finalizacion", "tipo_llegada"].dropna(),
                                           ["Centro", "Pase filtrado", "Remate"])
            fig = go.Figure(depth_bar(ROJO, "Rivales", rival_types.index, rival_types.values, text=rival_types.values))
            t(fig, height=290, margin=dict(t=42, b=38, l=35, r=20), title="Cómo finalizan los rivales")
            chart(fig)
        chart(_tactical_heatmap(
            own[own["fase"] == "finalizacion"],
            "Campograma de finalizaciones CAdF · acumulado LongoMatch",
        ))

    with tab_without_ball:
        c1, c2 = st.columns(2)
        with c1:
            chart(_tactical_heatmap(
                own[own["fase"] == "recuperacion"], "Recuperaciones · acumulado", AZUL_CELESTE,
            ))
        with c2:
            chart(_tactical_heatmap(
                own[own["fase"] == "perdida"], "Pérdidas · acumulado", ROJO,
            ))
        recovery_origin = _generated_breakdown(own, "recuperacion")
        loss_origin = _generated_breakdown(own, "perdida")
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "Recuperaciones", recovery_origin.index,
                                recovery_origin.values, text=recovery_origin.values))
        fig.add_trace(depth_bar(ROJO, "Pérdidas", loss_origin.index,
                                loss_origin.values, text=loss_origin.values))
        t(fig, height=300, barmode="group", margin=dict(t=45, b=42, l=35, r=20),
          title="Generadas y no generadas · acumulado")
        chart(fig)

        responses = _tactical_counts(
            own.loc[own["fase"] == "transicion_defensiva", "transicion_defensiva"].dropna(),
            ["PTP", "Repliegue", "Mixta"],
        )
        fig = go.Figure(depth_bar(ROJO, "Transición defensiva", responses.index, responses.values,
                                  text=responses.values))
        t(fig, height=270, margin=dict(t=42, b=35, l=35, r=20), title="Respuesta tras pérdida · acumulado")
        chart(fig)

    with tab_set_pieces:
        phases = ["corner", "tiro_libre"]
        labels = ["Córner", "Tiro libre"]
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "CAdF", labels, _tactical_counts(own["fase"], phases)))
        fig.add_trace(depth_bar(ROJO, "Rivales", labels, _tactical_counts(opponent["fase"], phases)))
        t(fig, height=330, barmode="group", margin=dict(t=45, b=45, l=35, r=20),
          title="Balón parado · acumulado")
        fig.update_yaxes(title="Acciones")
        chart(fig)

    if tactical_matches != hudl_matches:
        st.caption(
            f"LongoMatch contiene {tactical_matches} partidos etiquetados y HUDL {hudl_matches} partidos de resumen. "
            "Ambas fuentes se muestran por separado hasta que estén disponibles los dos archivos de cada encuentro."
        )


def page_tactica(video_df: pd.DataFrame):
    st.markdown(f"""
    <h1 style='color:{BLANCO};font-size:2rem;font-weight:700;margin-bottom:2px;'>
        Análisis Táctico
    </h1>
    <p style='color:{AZUL_CELESTE};font-size:0.9rem;margin-bottom:20px;'>
        Eventos de vídeo · LongoMatch · Referencia espacial CAdF
    </p>""", unsafe_allow_html=True)

    if video_df.empty:
        st.info("Aún no hay CSV de LongoMatch en la carpeta Partidos de Google Drive.")
        return

    partidos = video_df["partido"].drop_duplicates().tolist()
    partido = st.selectbox("Partido analizado", partidos, key="tactica_partido")
    events = video_df[video_df["partido"] == partido].copy()
    rival = events["rival"].iloc[0]
    own = events[events["equipo"] == "propio"]
    opponent = events[events["equipo"] == "rival"]

    own_finals = int((own["fase"] == "finalizacion").sum())
    rival_finals = int((opponent["fase"] == "finalizacion").sum())
    recoveries = int((own["fase"] == "recuperacion").sum())
    losses = int((own["fase"] == "perdida").sum())
    cards = st.columns(4)
    with cards[0]:
        st.markdown(metric_card("Eventos registrados", len(events)), unsafe_allow_html=True)
    with cards[1]:
        st.markdown(metric_card("Finalizaciones CAdF", own_finals), unsafe_allow_html=True)
    with cards[2]:
        st.markdown(metric_card("Finalizaciones rival", rival_finals), unsafe_allow_html=True)
    with cards[3]:
        st.markdown(metric_card("Recuperaciones / pérdidas", f"{recoveries} / {losses}"), unsafe_allow_html=True)

    st.caption(
        "Los carriles del rival se muestran invertidos para que todo el análisis use la orientación del CAdF. "
        "Los recuentos representan eventos etiquetados, no posesiones independientes."
    )
    tab_summary, tab_attack, tab_without_ball, tab_set_pieces = st.tabs(
        ["Resumen", "Con balón", "Sin balón y transiciones", "Balón parado"]
    )

    with tab_summary:
        section(f"Estructura del partido · CAdF vs {rival}")
        phases = ["inicio", "progresion", "finalizacion", "gol"]
        labels = ["Inicio", "Progresión", "Finalización", "Gol"]
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "CAdF", labels, _tactical_counts(own["fase"], phases)))
        fig.add_trace(depth_bar(ROJO, rival, labels, _tactical_counts(opponent["fase"], phases)))
        t(fig, height=360, barmode="group", margin=dict(t=48, b=45, l=45, r=25),
          title="Eventos por fase")
        fig.update_yaxes(title="Eventos")
        chart(fig)

        c1, c2 = st.columns(2)
        with c1:
            own_types = _tactical_counts(own.loc[own["fase"] == "finalizacion", "tipo_llegada"].dropna(),
                                         ["Centro", "Pase filtrado", "Remate"])
            fig = go.Figure(depth_bar(DORADO, "CAdF", own_types.index, own_types.values, text=own_types.values))
            t(fig, height=300, margin=dict(t=48, b=40, l=35, r=20), title="Cómo finaliza CAdF")
            chart(fig)
        with c2:
            opp_types = _tactical_counts(opponent.loc[opponent["fase"] == "finalizacion", "tipo_llegada"].dropna(),
                                         ["Centro", "Pase filtrado", "Remate"])
            fig = go.Figure(depth_bar(ROJO, rival, opp_types.index, opp_types.values, text=opp_types.values))
            t(fig, height=300, margin=dict(t=48, b=40, l=35, r=20), title=f"Cómo finaliza {rival}")
            chart(fig)

    with tab_attack:
        c1, c2 = st.columns(2)
        with c1:
            section("Finalizaciones propias por carril")
            own_lanes = _tactical_counts(own.loc[own["fase"] == "finalizacion", "carril"].dropna(),
                                         ["Izquierdo", "Central", "Derecho"])
            fig = go.Figure(depth_bar(AZUL_CELESTE, "CAdF", own_lanes.index, own_lanes.values, text=own_lanes.values))
            t(fig, height=300, margin=dict(t=40, b=40, l=35, r=20), title="Carril de la acción final")
            chart(fig)
        with c2:
            section("Progresiones propias")
            progressions = _tactical_counts(own.loc[own["fase"] == "progresion", "progresion_tipo"].dropna(),
                                            ["Directo", "Organizado"])
            fig = go.Figure(depth_bar(DORADO, "CAdF", progressions.index, progressions.values, text=progressions.values))
            t(fig, height=300, margin=dict(t=40, b=40, l=35, r=20), title="Tipo de progresión")
            chart(fig)

        section("Mapa de finalizaciones propias")
        chart(_tactical_heatmap(own[own["fase"] == "finalizacion"], "Zona y carril de finalización"))

    with tab_without_ball:
        c1, c2 = st.columns(2)
        with c1:
            section("Recuperaciones")
            chart(_tactical_heatmap(
                own[own["fase"] == "recuperacion"], "Dónde recupera CAdF", AZUL_CELESTE,
            ))
        with c2:
            section("Pérdidas")
            chart(_tactical_heatmap(
                own[own["fase"] == "perdida"], "Dónde pierde CAdF", ROJO,
            ))

        section("Respuesta tras pérdida")
        responses = _tactical_counts(
            own.loc[own["fase"] == "transicion_defensiva", "transicion_defensiva"].dropna(),
            ["PTP", "Repliegue", "Mixta"],
        )
        fig = go.Figure(depth_bar(ROJO, "Transición defensiva", responses.index, responses.values, text=responses.values))
        t(fig, height=300, margin=dict(t=45, b=40, l=35, r=20), title="Acción tras pérdida")
        chart(fig)

    with tab_set_pieces:
        types = ["corner", "tiro_libre"]
        labels = ["Córner", "Tiro libre"]
        fig = go.Figure()
        fig.add_trace(depth_bar(AZUL_CELESTE, "CAdF", labels, _tactical_counts(own["fase"], types)))
        fig.add_trace(depth_bar(ROJO, rival, labels, _tactical_counts(opponent["fase"], types)))
        t(fig, height=330, barmode="group", margin=dict(t=45, b=45, l=35, r=20),
          title="Acciones a balón parado")
        fig.update_yaxes(title="Acciones")
        chart(fig)
        st.info(
            "Cuando el analista incorpore jugador, Generada/No generada y una referencia fija de inicio de segunda parte, "
            "añadiremos análisis individual, calidad de recuperación y secuencias de 20 segundos."
        )


# ── Google Drive loader ──────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _get_google_creds() -> Credentials:
    """Crea una credencial reutilizable; el token se refresca solo al caducar."""
    service_account_json = _streamlit_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
    if service_account_json:
        return service_account.Credentials.from_service_account_info(
            json.loads(service_account_json), scopes=GOOGLE_SCOPES
        )

    if SERVICE_ACCOUNT_FILE.exists():
        return service_account.Credentials.from_service_account_file(
            str(SERVICE_ACCOUNT_FILE), scopes=GOOGLE_SCOPES
        )

    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            "No se encontró la clave de cuenta de servicio ni token_google.json para leer GPS desde Drive."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def _drive_headers() -> dict[str, str]:
    creds = _get_google_creds()
    if not creds.valid:
        creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}"}


@st.cache_data(ttl=300, show_spinner=False)
def _load_match_data(folder_id: str) -> pd.DataFrame:
    """Cachea la tabla HUDL de Drive cinco minutos entre navegaciones."""
    return load_all(drive_folder_id=folder_id, drive_headers=_drive_headers())


@st.cache_data(ttl=300, show_spinner=False)
def _load_video_events(folder_id: str) -> pd.DataFrame:
    """Cachea los CSV de LongoMatch sin usar el token como clave de caché."""
    return load_longomatch_events(folder_id, _drive_headers())


@st.cache_data(ttl=300, show_spinner=False)
def _get_season_subfolder_id(season_folder_id: str, folder_name: str) -> str:
    """Resuelve carpetas como GPS o Partidos dentro de la temporada activa."""
    query = (
        f"'{season_folder_id}' in parents and "
        f"name = '{folder_name.replace("'", "\\'")}' and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resp = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers=_drive_headers(),
        params={
            "q": query,
            "fields": "files(id,name)",
            "pageSize": 10,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=60,
    )
    resp.raise_for_status()
    folders = resp.json().get("files", [])
    if not folders:
        raise FileNotFoundError(f"No existe la carpeta '{folder_name}' en la temporada configurada.")
    return folders[0]["id"]


def _list_drive_gps_files(folder_id: str) -> list[dict]:
    query = (
        f"'{folder_id}' in parents and "
        f"mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' and "
        f"trashed = false"
    )
    resp = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers=_drive_headers(),
        params={
            "q": query,
            "fields": "files(id,name,modifiedTime)",
            "orderBy": "name",
            "pageSize": 200,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=60,
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return [
        f for f in files
        if f.get("name", "").endswith(".xlsx") and not f.get("name", "").startswith("~$")
    ]


def _download_drive_file(file_id: str) -> bytes:
    resp = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers=_drive_headers(),
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.content


def _workbook_to_dataframe(workbook_like) -> pd.DataFrame:
    import openpyxl

    wb = openpyxl.load_workbook(workbook_like, data_only=True, read_only=True)
    if "_synced_data" not in wb.sheetnames:
        return pd.DataFrame()

    ws = wb["_synced_data"]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return pd.DataFrame()

    headers = [str(h).strip() if h else "" for h in rows[0]]
    data = [dict(zip(headers, r)) for r in rows[1:]]
    return pd.DataFrame(data)


def _normalize_gps_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.rename(columns={
        "Date": "fecha",
        "Player Name": "jugador",
        "Distance": "distancia",
        "GPS Load": "carga",
        "Top Speed": "vel_max",
        "Peak Accel": "accel_max",
        "Accel Zones  Count": "accel_count",
        "Speed Zones  Distance": "hsr_dist",
        "Speed Zones  Count": "hsr_count",
    })

    # Titan usa estos encabezados en las exportaciones recientes.
    for source, target in {
        "GPS Distance": "distancia",
        "GPS Player Load": "carga",
        "GPS Top Speed": "vel_max",
        "GPS Peak Accel": "accel_max",
    }.items():
        if source in df.columns and target not in df.columns:
            df = df.rename(columns={source: target})

    for col in ["distancia", "carga", "vel_max", "accel_max", "accel_count", "hsr_dist", "hsr_count"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
        df = df.dropna(subset=["fecha"])
        # Los Training Report acumulados pueden repetir jugadores de sesiones anteriores.
        df = df.sort_values(["fecha", "source_file"]).drop_duplicates(
            subset=["fecha", "jugador"], keep="first"
        )
        df["fecha_str"] = df["fecha"].dt.strftime("%d/%m/%Y")
    return df.sort_values("fecha").reset_index(drop=True)


def _load_gps_from_drive() -> pd.DataFrame:
    if not GOOGLE_SEASON_FOLDER_ID:
        raise ValueError("Falta configurar GOOGLE_SEASON_FOLDER_ID en Streamlit Secrets.")

    frames = []
    gps_folder_id = _get_season_subfolder_id(GOOGLE_SEASON_FOLDER_ID, "GPS")
    for drive_file in _list_drive_gps_files(gps_folder_id):
        content = _download_drive_file(drive_file["id"])
        frame = _workbook_to_dataframe(io.BytesIO(content))
        if not frame.empty:
            frame["source_file"] = drive_file["name"]
            frames.append(frame)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=60, show_spinner=False)
def load_gps() -> pd.DataFrame:
    """Carga exclusivamente los Training Report disponibles en Google Drive."""
    return _normalize_gps_dataframe(_load_gps_from_drive())


# ── Página: Física (GPS) ──────────────────────────────────────────────────────
METRICAS_INFO = {
    "distancia": ("Distancia (km)",        " km",   "Kilómetros recorridos durante la sesión."),
    "vel_max":   ("Vel. Máxima (km/h)",    " km/h", "Velocidad punta máxima registrada."),
    "carga":     ("Carga GPS",             "",      "Índice de estrés físico total (distancia + intensidad + aceleraciones)."),
    "accel_max": ("Accel. Máxima (m/s²)",  " m/s²", "Pico de aceleración. Refleja explosividad del esfuerzo."),
    "hsr_dist":  ("HSR Distancia (km)",    " km",   "Distancia recorrida en zonas de alta velocidad."),
    "hsr_count": ("HSR Entradas",          "",      "Número de esfuerzos en alta velocidad durante la sesión."),
}
METRICA_MAP = {
    "Distancia (km)":       "distancia",
    "Carga GPS":            "carga",
    "Velocidad Máxima":     "vel_max",
    "Aceleración Máxima":   "accel_max",
    "HSR Distancia":        "hsr_dist",
    "HSR Entradas":         "hsr_count",
}

def _fmt(val, col):
    if not pd.notna(val):
        return "—"
    return f"{val:.2f}" if col in ("distancia", "accel_max") else f"{val:.1f}"

def _kpis_equipo(df_sesion):
    cols = st.columns(6)
    for col_ui, (col_key, agg) in zip(
        cols,
        [("distancia","mean"),("vel_max","max"),("carga","mean"),
         ("accel_max","mean"),("hsr_dist","mean"),("hsr_count","mean")]
    ):
        label, suffix, tooltip = METRICAS_INFO[col_key]
        val = df_sesion[col_key].agg(agg) if col_key in df_sesion.columns else None
        with col_ui:
            st.markdown(metric_card(label, _fmt(val, col_key), suffix), unsafe_allow_html=True)
            st.markdown(
                f"<div style='font-size:0.72rem;color:{GRIS_MEDIO};margin-top:4px;"
                f"line-height:1.4;padding:0 4px;'>{tooltip}</div>",
                unsafe_allow_html=True,
            )

def _evo_chart(df_evo, metrica_col, metrica_label, titulo, render=True):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_evo["fecha_str"], y=df_evo[metrica_col],
        name=metrica_label,
        marker=dict(color=AZUL_CELESTE, opacity=0.85, line=dict(color=DORADO, width=1)),
        text=[_fmt(v, metrica_col) for v in df_evo[metrica_col]],
        textposition="outside", textfont=dict(color=BLANCO, size=11),
    ))
    media = df_evo[metrica_col].mean()
    fig.add_hline(y=media, line_dash="dash", line_color=DORADO, line_width=2,
                  annotation_text=f"  Media: {_fmt(media, metrica_col)}",
                  annotation_font_color=DORADO, annotation_font_size=13,
                  annotation_position="top left")
    t(fig, height=360)
    fig.update_layout(title=dict(text=titulo, font=dict(color=GRIS_MEDIO, size=13)))
    if render:
        chart(fig)
    return fig


def _quartile_colors(values: pd.Series) -> list[str]:
    """Distingue cuatro rangos relativos dentro de la sesión, de menor a mayor."""
    palette = ["#477FB8", AZUL_CELESTE, DORADO, ROJO]
    ranks = values.rank(method="first", pct=True)
    return [
        palette[0] if rank <= 0.25 else palette[1] if rank <= 0.5
        else palette[2] if rank <= 0.75 else palette[3]
        for rank in ranks
    ]


def _quartile_legend():
    st.markdown(f"""
    <div style="display:flex;flex-wrap:wrap;gap:16px;align-items:center;margin:2px 0 6px;
                color:{GRIS_MEDIO};font-size:0.78rem;">
        <span><b style="color:#477FB8">■</b> Cuartil 1 · menor valor</span>
        <span><b style="color:{AZUL_CELESTE}">■</b> Cuartil 2</span>
        <span><b style="color:{DORADO}">■</b> Cuartil 3</span>
        <span><b style="color:{ROJO}">■</b> Cuartil 4 · mayor valor</span>
    </div>
    """, unsafe_allow_html=True)


def _load_threshold_legend():
    st.markdown(f"""
    <div style="display:flex;flex-wrap:wrap;gap:16px;align-items:center;margin:2px 0 6px;
                color:{GRIS_MEDIO};font-size:0.78rem;">
        <span><b style="color:{ROJO}">■</b> ≥ 200 · sobrecarga</span>
        <span><b style="color:{DORADO}">■</b> 160–199 · alta carga</span>
        <span><b style="color:{AZUL_CELESTE}">■</b> &lt; 160 · normal</span>
    </div>
    """, unsafe_allow_html=True)


def _session_summary_cards(df_sesion):
    """KPIs operativos que acompañan las vistas de carga de una sesión."""
    distancia_total = df_sesion["distancia"].sum()
    carga_media = df_sesion["carga"].mean()
    vel_media = df_sesion["vel_max"].mean()
    sobrecarga = int((df_sesion["carga"] >= 200).sum())
    jugadores = len(df_sesion.dropna(subset=["jugador"]))

    for col, (label, value, suffix) in zip(st.columns(4), [
        ("Distancia total equipo", _fmt(distancia_total, "distancia"), " km"),
        ("GPS Load promedio", _fmt(carga_media, "carga"), ""),
        ("Velocidad máxima media", _fmt(vel_media, "vel_max"), " km/h"),
        ("Jugadores en sobrecarga", str(sobrecarga), f" de {jugadores}"),
    ]):
        with col:
            st.markdown(metric_card(label, value, suffix), unsafe_allow_html=True)


def _load_chart(df_sesion, render=True):
    data = df_sesion.dropna(subset=["jugador", "carga"]).sort_values("carga", ascending=False)
    colors = [ROJO if value >= 200 else DORADO if value >= 160 else AZUL_CELESTE for value in data["carga"]]
    if render:
        st.markdown(f"<div style='color:{GRIS_MEDIO};font-size:0.85rem;font-weight:700;margin-bottom:2px;'>"
                    "Carga individual · umbrales de referencia</div>", unsafe_allow_html=True)
        _load_threshold_legend()
    fig = go.Figure(go.Bar(
        x=data["jugador"], y=data["carga"],
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0.18)", width=1)),
        text=[_fmt(value, "carga") for value in data["carga"]],
        textposition="outside", textfont=dict(color=BLANCO, size=10),
        customdata=data[["distancia", "vel_max"]],
        hovertemplate=("<b>%{x}</b><br>GPS Load: %{y:.1f}<br>"
                       "Distancia: %{customdata[0]:.2f} km<br>"
                       "Vel. máxima: %{customdata[1]:.1f} km/h<extra></extra>"),
    ))
    fig.add_hline(y=160, line_dash="dot", line_color=DORADO, line_width=1.5)
    fig.add_hline(y=200, line_dash="dot", line_color=ROJO, line_width=1.5)
    t(fig, height=440, margin=dict(t=24, b=110, l=52, r=36))
    fig.update_layout(
        showlegend=False,
    )
    fig.update_xaxes(tickangle=-45, title_text="")
    fig.update_yaxes(title_text="GPS Load", rangemode="tozero")
    if render:
        chart(fig)
    return fig


def _distance_intensity_chart(df_sesion, render=True):
    data = df_sesion.dropna(subset=["jugador", "distancia", "hsr_dist"])
    fig = go.Figure(go.Scatter(
        x=data["distancia"], y=data["hsr_dist"], mode="markers+text",
        marker=dict(size=15, color=AZUL_CELESTE, opacity=0.9,
                    line=dict(color=DORADO, width=1)),
        text=data["jugador"], textposition="top center",
        textfont=dict(color=BLANCO, size=10),
        customdata=data[["jugador", "carga", "vel_max"]],
        hovertemplate=("<b>%{customdata[0]}</b><br>Distancia: %{x:.2f} km<br>"
                       "HSR: %{y:.2f} km<br>GPS Load: %{customdata[1]:.1f}<br>"
                       "Vel. máxima: %{customdata[2]:.1f} km/h<extra></extra>"),
    ))
    t(fig, height=440)
    fig.update_layout(title=dict(
        text="Perfil de esfuerzo individual", font=dict(color=GRIS_MEDIO, size=13)
    ), showlegend=False)
    fig.update_xaxes(title_text="Distancia total (km)", rangemode="tozero")
    fig.update_yaxes(title_text="Distancia a alta intensidad (km)", rangemode="tozero")
    if render:
        chart(fig)
    return fig


def _acceleration_risk_chart(df_sesion, render=True):
    data = df_sesion.dropna(subset=["jugador", "accel_count"]).sort_values("accel_count", ascending=False)
    top_risk = set(data.head(3)["jugador"])
    colors = [ROJO if player in top_risk else AZUL_CELESTE for player in data["jugador"]]
    fig = go.Figure(go.Bar(
        x=data["jugador"], y=data["accel_count"],
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0.18)", width=1)),
        text=[_fmt(value, "accel_count") for value in data["accel_count"]],
        textposition="outside", textfont=dict(color=BLANCO, size=10),
        customdata=data[["distancia", "carga"]],
        hovertemplate=("<b>%{x}</b><br>Aceleraciones: %{y:.0f}<br>"
                       "Distancia: %{customdata[0]:.2f} km<br>"
                       "GPS Load: %{customdata[1]:.1f}<extra></extra>"),
    ))
    t(fig, height=440, margin=dict(t=36, b=110, l=52, r=36))
    fig.update_layout(
        title=dict(text="Top 3 · mayor volumen de aceleraciones", font=dict(color=GRIS_MEDIO, size=13)),
        showlegend=False,
    )
    fig.update_xaxes(tickangle=-45, title_text="")
    fig.update_yaxes(title_text="Aceleraciones", rangemode="tozero")
    if render:
        chart(fig)
    return fig


def _player_comparison_chart(df_sesion, metrica_col, metrica_label, render=True):
    data = df_sesion.dropna(subset=[metrica_col]).sort_values(metrica_col, ascending=True)
    colors = _quartile_colors(data[metrica_col])
    if render:
        _quartile_legend()
    metric_title, _, _ = METRICAS_INFO[metrica_col]
    fig = go.Figure(go.Bar(
        x=data[metrica_col], y=data["jugador"], orientation="h",
        marker=dict(color=colors, opacity=0.9,
                    line=dict(color="rgba(0,0,0,0.2)", width=1)),
        text=[_fmt(value, metrica_col) for value in data[metrica_col]],
        textposition="outside", textfont=dict(color=BLANCO, size=11),
    ))
    t(fig, height=max(300, len(data) * 38))
    fig.update_layout(
        title=dict(text=f"{metric_title} por jugador", font=dict(color=GRIS_MEDIO, size=13)),
        showlegend=False,
    )
    fig.update_xaxes(title_text=metric_title)
    if render:
        chart(fig)
    return fig


def _workload_alerts(df, fecha_sesion: pd.Timestamp) -> pd.DataFrame:
    """Señales de carga relativas a las tres sesiones previas del jugador."""
    current = df[df["fecha"] == fecha_sesion]
    history = df[df["fecha"] < fecha_sesion]
    metrics = [
        ("carga", "GPS Load"),
        ("hsr_dist", "HSR"),
        ("accel_count", "aceleraciones"),
    ]
    rows = []

    for _, player in current.iterrows():
        previous = history[history["jugador"] == player["jugador"]].sort_values("fecha").tail(3)
        if len(previous) < 3:
            continue

        flags = []
        details = []
        for column, label in metrics:
            value = player.get(column)
            baseline = previous[column].mean() if column in previous else None
            if not pd.notna(value) or not pd.notna(baseline) or baseline <= 0:
                continue
            ratio = value / baseline
            if ratio >= 1.30:
                flags.append(label)
                details.append(f"{label} +{(ratio - 1) * 100:.0f}%")

        if flags:
            rows.append({
                "jugador": player["jugador"],
                "nivel": "Prioridad alta" if len(flags) >= 2 else "Vigilar",
                "senales": len(flags),
                "motivo": " · ".join(details),
                "sesiones_base": len(previous),
            })

    if not rows:
        return pd.DataFrame(columns=["jugador", "nivel", "senales", "motivo", "sesiones_base"])
    return pd.DataFrame(rows).sort_values(["senales", "jugador"], ascending=[False, True])


def _workload_conclusion(df, df_sesion, fecha_label: str):
    alerts = _workload_alerts(df, df_sesion["fecha"].iloc[0])
    eligible = sum(
        len(df[(df["jugador"] == player) & (df["fecha"] < df_sesion["fecha"].iloc[0])]) >= 3
        for player in df_sesion["jugador"].dropna().unique()
    )

    section(f"Conclusión automática de carga · {fecha_label}")
    if eligible == 0:
        st.info("Aún no hay tres sesiones previas por jugador para generar alertas individuales fiables.")
        return

    high_priority = alerts[alerts["nivel"] == "Prioridad alta"]
    monitor = alerts[alerts["nivel"] == "Vigilar"]
    if alerts.empty:
        headline = "No se detectan picos relativos de carga en los jugadores con historial suficiente."
        recommendation = "Mantener la planificación prevista y seguir registrando el contexto de cada sesión."
        color = VERDE
    elif not high_priority.empty:
        headline = (f"{len(high_priority)} jugador(es) requieren revisión prioritaria antes de "
                    "decidir la carga de la siguiente sesión.")
        recommendation = ("Antes de la próxima exposición intensa, revisar RPE, bienestar y molestias; "
                          "si la señal se confirma, individualizar el volumen o la intensidad.")
        color = ROJO
    else:
        headline = (f"{len(monitor)} jugador(es) presentan una señal de carga a vigilar "
                    "en la próxima planificación.")
        recommendation = ("Confirmar el contexto de la sesión y el bienestar del jugador antes de "
                          "aumentar de nuevo la carga.")
        color = DORADO

    st.markdown(f"""
    <div style="background:{AZUL_MEDIO};border-left:4px solid {color};border-radius:8px;
                padding:14px 16px;margin-bottom:10px;color:{BLANCO};font-size:0.92rem;">
        <b>{headline}</b><br>
        <span style="color:{GRIS_MEDIO};font-size:0.8rem;line-height:1.45;">
        Regla: cada señal aparece cuando GPS Load, HSR o aceleraciones superan en ≥30% la media de
        las tres sesiones previas del propio jugador. Una señal implica <b>Vigilar</b>; dos o más,
        <b>Prioridad alta</b>. <b>Recomendación:</b> {recommendation}</span>
    </div>
    """, unsafe_allow_html=True)

    if not alerts.empty:
        display = alerts.rename(columns={
            "jugador": "Jugador", "nivel": "Acción", "senales": "Señales", "motivo": "Motivo"
        })[["Jugador", "Acción", "Señales", "Motivo"]]
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.caption(
        "Estas alertas apoyan la decisión del cuerpo técnico. No diagnostican ni predicen lesiones: "
        "contrástalas con RPE, bienestar, dolor, sueño, contexto de la sesión e historial clínico."
    )


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


class _GPSReportPDF(FPDF):
    def __init__(self, club_logo: str, sdc_logo: str):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.club_logo = club_logo
        self.sdc_logo = sdc_logo
        self.set_auto_page_break(auto=True, margin=15)
        self.set_title("Informe de GPS - Club Argentino")

    def header(self):
        # The header is drawn explicitly by _pdf_heading on internal pages.
        return

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-10)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(90, 101, 118)
        self.cell(0, 5, f"Club Argentino | Informe GPS | Pagina {self.page_no()}", align="C")


def _pdf_heading(pdf: _GPSReportPDF, title: str, subtitle: str = ""):
    pdf.image(pdf.club_logo, x=12, y=7, h=10)
    pdf.image(pdf.sdc_logo, x=272, y=7, h=10)
    pdf.set_xy(50, 8)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*_rgb(AZUL_OSCURO))
    pdf.cell(197, 8, "INFORME DE GPS", align="C")
    pdf.set_draw_color(*_rgb(AZUL_MEDIO))
    pdf.set_line_width(0.8)
    pdf.line(12, 21, 285, 21)
    pdf.set_y(29)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*_rgb(AZUL_OSCURO))
    pdf.cell(0, 8, title)
    if subtitle:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_rgb(AZUL_CLARO))
        pdf.ln(8)
        pdf.cell(0, 6, subtitle)
    pdf.ln(10)


def _pdf_card(pdf: _GPSReportPDF, x: float, y: float, width: float, label: str, value: str, suffix: str = ""):
    pdf.set_fill_color(241, 245, 249)
    pdf.rect(x, y, width, 28, style="F")
    pdf.set_xy(x + 5, y + 5)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(width - 10, 5, label.upper())
    pdf.set_xy(x + 5, y + 12)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*_rgb(AZUL_OSCURO))
    pdf.cell(width - 10, 8, value)
    if suffix:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(25, 8, suffix)


def _pdf_short_name(name: str, max_length: int = 11) -> str:
    """Evita que los nombres largos invadan los gráficos estáticos del informe."""
    first_name = str(name).split()[0]
    return first_name if len(first_name) <= max_length else f"{first_name[:max_length - 1]}."


def _pdf_chart_canvas(pdf: _GPSReportPDF, x: float, y: float, width: float, height: float, title: str):
    pdf.set_fill_color(*_rgb(PAPER_BG))
    pdf.rect(x, y, width, height, style="F")
    pdf.set_draw_color(*_rgb(AZUL_CLARO))
    pdf.rect(x, y, width, height)
    pdf.set_text_color(*_rgb(BLANCO))
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(x + 6, y + 4)
    pdf.cell(width - 12, 5, title, align="C")
    return x + 24, y + 16, width - 31, height - 29


def _pdf_vertical_bars(
    pdf: _GPSReportPDF, data: pd.DataFrame, value_col: str, x: float, y: float, width: float,
    height: float, title: str, y_label: str, colors: list[str], show_values: bool = True,
):
    left, top, plot_width, plot_height = _pdf_chart_canvas(pdf, x, y, width, height, title)
    values = pd.to_numeric(data[value_col], errors="coerce").fillna(0).tolist()
    if not values:
        return
    max_value = max(values) or 1
    max_axis = max_value * 1.15
    pdf.set_font("Helvetica", "", 6)
    for index in range(5):
        value = max_axis * index / 4
        line_y = top + plot_height - (plot_height * index / 4)
        pdf.set_draw_color(74, 103, 148)
        pdf.line(left, line_y, left + plot_width, line_y)
        pdf.set_text_color(*_rgb(GRIS_MEDIO))
        pdf.set_xy(x + 2, line_y - 2)
        pdf.cell(19, 4, f"{value:.0f}", align="R")
    pdf.set_draw_color(*_rgb(GRIS_MEDIO))
    pdf.line(left, top, left, top + plot_height)
    pdf.line(left, top + plot_height, left + plot_width, top + plot_height)
    bar_slot = plot_width / len(values)
    bar_width = min(10, bar_slot * 0.7)
    for index, (_, row) in enumerate(data.reset_index(drop=True).iterrows()):
        value = max(float(row[value_col]), 0)
        bar_height = (value / max_axis) * plot_height
        bar_x = left + index * bar_slot + (bar_slot - bar_width) / 2
        bar_y = top + plot_height - bar_height
        pdf.set_fill_color(*_rgb(colors[index]))
        pdf.rect(bar_x, bar_y, bar_width, bar_height, style="F")
        if show_values:
            pdf.set_text_color(*_rgb(BLANCO))
            pdf.set_font("Helvetica", "B", 5.5)
            pdf.set_xy(bar_x - 4, bar_y - 4)
            pdf.cell(bar_width + 8, 3, f"{value:.1f}", align="C")
        pdf.set_text_color(*_rgb(GRIS_MEDIO))
        pdf.set_font("Helvetica", "", 5.5)
        pdf.set_xy(bar_x - 3, top + plot_height + 2)
        pdf.cell(bar_width + 6, 4, _pdf_short_name(row["jugador"]), align="C")
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(*_rgb(GRIS_MEDIO))
    pdf.set_xy(x + 2, top + plot_height / 2 - 2)
    pdf.cell(18, 4, y_label, align="C")


def _pdf_draw_evolution_chart(pdf: _GPSReportPDF, data: pd.DataFrame, value_col: str, label: str):
    plot = data.rename(columns={"fecha_str": "jugador"})
    _pdf_vertical_bars(
        pdf, plot, value_col, 14, 86, 269, 108, f"Media del equipo - {label}", label,
        [AZUL_CELESTE] * len(plot),
    )


def _pdf_draw_load_chart(pdf: _GPSReportPDF, data: pd.DataFrame):
    plot = data.dropna(subset=["jugador", "carga"]).sort_values("carga", ascending=False)
    colors = [ROJO if value >= 200 else DORADO if value >= 160 else AZUL_CELESTE for value in plot["carga"]]
    _pdf_vertical_bars(pdf, plot, "carga", 14, 48, 269, 149, "Carga individual - umbrales de referencia", "GPS Load", colors)


def _pdf_draw_acceleration_chart(pdf: _GPSReportPDF, data: pd.DataFrame):
    plot = data.dropna(subset=["jugador", "accel_count"]).sort_values("accel_count", ascending=False)
    top_risk = set(plot.head(3)["jugador"])
    colors = [ROJO if player in top_risk else AZUL_CELESTE for player in plot["jugador"]]
    _pdf_vertical_bars(pdf, plot, "accel_count", 14, 48, 269, 149, "Top 3 - mayor volumen de aceleraciones", "Aceleraciones", colors)


def _pdf_draw_intensity_chart(pdf: _GPSReportPDF, data: pd.DataFrame):
    plot = data.dropna(subset=["jugador", "distancia", "hsr_dist"])
    left, top, plot_width, plot_height = _pdf_chart_canvas(pdf, 14, 48, 269, 149, "Perfil de esfuerzo individual")
    max_x = max(float(plot["distancia"].max()), 1) * 1.08
    max_y = max(float(plot["hsr_dist"].max()), 1) * 1.12
    pdf.set_font("Helvetica", "", 6)
    for index in range(5):
        grid_x = left + plot_width * index / 4
        grid_y = top + plot_height - plot_height * index / 4
        pdf.set_draw_color(74, 103, 148)
        pdf.line(grid_x, top, grid_x, top + plot_height)
        pdf.line(left, grid_y, left + plot_width, grid_y)
        pdf.set_text_color(*_rgb(GRIS_MEDIO))
        pdf.set_xy(grid_x - 5, top + plot_height + 2)
        pdf.cell(10, 3, f"{max_x * index / 4:.1f}", align="C")
        pdf.set_xy(15, grid_y - 2)
        pdf.cell(16, 3, f"{max_y * index / 4:.1f}", align="R")
    for _, row in plot.iterrows():
        point_x = left + (float(row["distancia"]) / max_x) * plot_width
        point_y = top + plot_height - (float(row["hsr_dist"]) / max_y) * plot_height
        pdf.set_fill_color(*_rgb(AZUL_CELESTE))
        pdf.ellipse(point_x - 1.7, point_y - 1.7, 3.4, 3.4, style="F")
        pdf.set_text_color(*_rgb(BLANCO))
        pdf.set_font("Helvetica", "", 5.5)
        pdf.set_xy(point_x + 2, point_y - 3)
        pdf.cell(28, 3, _pdf_short_name(row["jugador"]))
    pdf.set_text_color(*_rgb(GRIS_MEDIO))
    pdf.set_font("Helvetica", "", 6)
    pdf.set_xy(left + plot_width / 2 - 20, top + plot_height + 7)
    pdf.cell(40, 3, "Distancia total (km)", align="C")
    pdf.set_xy(2, top + plot_height / 2 - 2)
    pdf.cell(23, 3, "HSR (km)", align="C")


def _pdf_draw_comparison_chart(pdf: _GPSReportPDF, data: pd.DataFrame, metric_col: str, metric_label: str):
    plot = data.dropna(subset=["jugador", metric_col]).sort_values(metric_col, ascending=False).reset_index(drop=True)
    left, top, plot_width, plot_height = _pdf_chart_canvas(pdf, 14, 48, 269, 149, f"{metric_label} por jugador")
    label_width = 37
    max_value = max(float(plot[metric_col].max()), 1) * 1.1
    row_height = plot_height / max(len(plot), 1)
    colors = list(reversed(_quartile_colors(plot[metric_col])))
    for index, (_, row) in enumerate(plot.iterrows()):
        value = max(float(row[metric_col]), 0)
        bar_y = top + index * row_height + 1
        bar_width = (value / max_value) * (plot_width - label_width)
        pdf.set_text_color(*_rgb(GRIS_MEDIO))
        pdf.set_font("Helvetica", "", 5.8)
        pdf.set_xy(left - label_width, bar_y + 1)
        pdf.cell(label_width - 2, 3, _pdf_short_name(row["jugador"], 16), align="R")
        pdf.set_fill_color(*_rgb(colors[index]))
        pdf.rect(left, bar_y, bar_width, max(row_height - 2, 1), style="F")
        pdf.set_text_color(*_rgb(BLANCO))
        pdf.set_font("Helvetica", "B", 5.8)
        pdf.set_xy(left + bar_width + 1, bar_y + 1)
        pdf.cell(12, 3, f"{value:.2f}")
    pdf.set_text_color(*_rgb(GRIS_MEDIO))
    pdf.set_font("Helvetica", "", 6)
    pdf.set_xy(left, top + plot_height + 4)
    pdf.cell(plot_width, 3, metric_label, align="C")


def _pdf_add_chart_page(pdf: _GPSReportPDF, title: str, subtitle: str, draw_chart, *args):
    pdf.add_page()
    _pdf_heading(pdf, title, subtitle)
    draw_chart(pdf, *args)


def _build_gps_report_pdf(df, df_sesion, fecha_label: str, metrica_col: str, metrica_label: str) -> bytes:
    """Genera el informe del Equipo en A4 horizontal y lo devuelve listo para descargar."""
    club_logo = os.path.join(ASSETS, "logo_argentino.png")
    sdc_logo = os.path.join(ASSETS, "sport data campus.png")
    pdf = _GPSReportPDF(club_logo, sdc_logo)
    date_range = f"{df['fecha'].min():%d/%m/%Y} - {df['fecha'].max():%d/%m/%Y}"
    print_date = datetime.now().strftime("%d/%m/%Y")

    # Portada
    pdf.add_page()
    pdf.set_fill_color(*_rgb(AZUL_OSCURO))
    pdf.rect(0, 0, 297, 210, style="F")
    pdf.image(club_logo, x=76, y=45, w=42)
    pdf.image(sdc_logo, x=179, y=45, w=42)
    pdf.set_y(101)
    pdf.set_font("Helvetica", "B", 29)
    pdf.set_text_color(*_rgb(BLANCO))
    pdf.cell(0, 14, "INFORME DE GPS", align="C")
    pdf.set_draw_color(*_rgb(DORADO))
    pdf.set_line_width(1.1)
    pdf.line(95, 120, 202, 120)
    pdf.set_y(130)
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(*_rgb(AZUL_CELESTE))
    pdf.cell(0, 8, "Club Argentino", align="C")
    pdf.set_y(151)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_rgb(GRIS_MEDIO))
    pdf.cell(0, 6, f"Rango de datos: {date_range}", align="C")
    pdf.ln(6)
    pdf.cell(0, 6, f"Fecha de emision: {print_date}", align="C")

    # Indice
    pdf.add_page()
    _pdf_heading(pdf, "Indice", "Contenido del informe")
    sections = [
        "1. Resumen del equipo y evolucion",
        "2. Carga GPS",
        "3. Distancia vs intensidad",
        "4. Riesgo por aceleraciones",
        "5. Comparativa de jugadores",
        "6. Conclusion automatica de carga",
    ]
    for section_title in sections:
        pdf.set_font("Helvetica", "", 13)
        pdf.set_text_color(*_rgb(AZUL_OSCURO))
        pdf.set_fill_color(241, 245, 249)
        pdf.set_x(16)
        pdf.cell(265, 11, section_title, fill=True)
        pdf.set_y(pdf.get_y() + 15)

    # Resumen del equipo y evolucion
    pdf.add_page()
    _pdf_heading(pdf, "Resumen del equipo", f"Sesion analizada: {fecha_label}")
    distancia_total = df_sesion["distancia"].sum()
    carga_media = df_sesion["carga"].mean()
    vel_media = df_sesion["vel_max"].mean()
    sobrecarga = int((df_sesion["carga"] >= 200).sum())
    jugadores = len(df_sesion.dropna(subset=["jugador"]))
    card_width = 61
    for index, card in enumerate([
        ("Distancia total equipo", _fmt(distancia_total, "distancia"), "km"),
        ("GPS Load promedio", _fmt(carga_media, "carga"), ""),
        ("Velocidad maxima media", _fmt(vel_media, "vel_max"), "km/h"),
        ("Jugadores en sobrecarga", str(sobrecarga), f"de {jugadores}"),
    ]):
        _pdf_card(pdf, 15 + index * 67, 48, card_width, *card)
    df_evo_eq = df.groupby(["fecha_str", "fecha"])[metrica_col].mean().reset_index().sort_values("fecha")
    _pdf_draw_evolution_chart(pdf, df_evo_eq, metrica_col, metrica_label)
    _pdf_add_chart_page(pdf, "Carga GPS", f"Sesion: {fecha_label}", _pdf_draw_load_chart, df_sesion)
    _pdf_add_chart_page(pdf, "Distancia vs intensidad", f"Sesion: {fecha_label}", _pdf_draw_intensity_chart, df_sesion)
    _pdf_add_chart_page(pdf, "Riesgo por aceleraciones", f"Sesion: {fecha_label}", _pdf_draw_acceleration_chart, df_sesion)
    _pdf_add_chart_page(
        pdf, "Comparativa de jugadores", f"Sesion: {fecha_label}",
        _pdf_draw_comparison_chart, df_sesion, metrica_col, metrica_label,
    )

    # Conclusion
    pdf.add_page()
    _pdf_heading(pdf, "Conclusion automatica de carga", f"Sesion analizada: {fecha_label}")
    alerts = _workload_alerts(df, df_sesion["fecha"].iloc[0])
    if alerts.empty:
        conclusion = "No se detectan picos relativos de carga en los jugadores con historial suficiente."
        color = VERDE
    else:
        priority = alerts[alerts["nivel"] == "Prioridad alta"]
        conclusion = (
            f"{len(priority)} jugador(es) requieren revision prioritaria y "
            f"{len(alerts) - len(priority)} jugador(es) deben mantenerse en seguimiento."
        )
        color = ROJO if not priority.empty else DORADO
    pdf.set_fill_color(*_rgb(AZUL_MEDIO))
    pdf.rect(15, 48, 267, 25, style="F")
    pdf.set_draw_color(*_rgb(color))
    pdf.set_line_width(1.2)
    pdf.line(15, 48, 15, 73)
    pdf.set_xy(22, 54)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*_rgb(BLANCO))
    pdf.multi_cell(252, 6, conclusion)
    pdf.set_xy(16, 83)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_rgb(AZUL_OSCURO))
    pdf.multi_cell(
        266, 6,
        "Regla: cada senal aparece cuando GPS Load, HSR o aceleraciones superan en >=30% la media "
        "de las tres sesiones previas del propio jugador. Una senal implica Vigilar; dos o mas, Prioridad alta.",
    )
    if not alerts.empty:
        y = 110
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_rgb(BLANCO))
        pdf.set_fill_color(*_rgb(AZUL_MEDIO))
        for x, width, label in [(16, 56, "Jugador"), (72, 42, "Accion"), (114, 18, "Senales"), (132, 149, "Motivo")]:
            pdf.set_xy(x, y)
            pdf.cell(width, 8, label, fill=True)
        y += 8
        for _, alert in alerts.iterrows():
            pdf.set_fill_color(241, 245, 249)
            pdf.set_text_color(*_rgb(AZUL_OSCURO))
            pdf.set_font("Helvetica", "", 9)
            for x, width, value in [
                (16, 56, str(alert["jugador"])), (72, 42, str(alert["nivel"])),
                (114, 18, str(alert["senales"])), (132, 149, str(alert["motivo"])),
            ]:
                pdf.set_xy(x, y)
                pdf.cell(width, 9, value, fill=True)
            y += 9
    pdf.set_xy(16, 170)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(90, 101, 118)
    pdf.multi_cell(
        266, 5,
        "Estas alertas apoyan la decision del cuerpo tecnico. No diagnostican ni predicen lesiones: "
        "deben contrastarse con RPE, bienestar, dolor, sueno, contexto de sesion e historial clinico.",
    )
    return bytes(pdf.output())


def page_fisica():
    page_header("Preparación Física", "Carga de entrenamiento por sesión y jugador",
                kicker="Datos GPS · Titan")

    df = load_gps()
    if df.empty:
        st.info("No hay archivos GPS disponibles en la carpeta GPS de Google Drive.")
        return

    jugadores  = sorted(df["jugador"].dropna().unique())
    fechas_str = sorted(df["fecha_str"].unique())

    # ── Filtros globales ──────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        metrica_label = st.selectbox("Métrica", list(METRICA_MAP.keys()), key="gps_metrica")
        metrica_col   = METRICA_MAP[metrica_label]
    with col_f2:
        fecha_sel = st.selectbox("Sesión", ["Última"] + fechas_str, key="gps_fecha")
    with col_f3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

    if fecha_sel == "Última":
        df_sesion = df[df["fecha"] == df["fecha"].max()]
        fecha_label = df["fecha"].max().strftime("%d/%m/%Y")
    else:
        df_sesion   = df[df["fecha_str"] == fecha_sel]
        fecha_label = fecha_sel

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_equipo, tab_individual, tab_glosario = st.tabs(["🏟️  Equipo", "👤  Individual", "📖  Glosario"])

    # ════════════════════════════════════════════════════════
    # TAB EQUIPO
    # ════════════════════════════════════════════════════════
    with tab_equipo:
        section(f"Resumen del equipo · {fecha_label}")
        _kpis_equipo(df_sesion)

        pdf_col, _ = st.columns([1, 4])
        with pdf_col:
            if st.button(
                "Generar informe PDF", key="gps_pdf_generate", type="primary", use_container_width=True
            ):
                with st.spinner("Generando informe PDF..."):
                    try:
                        st.session_state["gps_pdf_bytes"] = _build_gps_report_pdf(
                            df, df_sesion, fecha_label, metrica_col, metrica_label
                        )
                        st.session_state["gps_pdf_name"] = f"Informe_GPS_{fecha_label.replace('/', '-')}.pdf"
                    except Exception:
                        st.error(
                            "No se ha podido preparar el motor de exportación. "
                            "Espera unos segundos y vuelve a intentarlo."
                        )
        if st.session_state.get("gps_pdf_bytes"):
            st.download_button(
                "Descargar informe PDF",
                data=st.session_state["gps_pdf_bytes"],
                file_name=st.session_state["gps_pdf_name"],
                mime="application/pdf",
                key="gps_pdf_download",
            )

        st.markdown("<br>", unsafe_allow_html=True)
        section(f"Evolución del equipo · {metrica_label}")
        df_evo_eq = (
            df.groupby(["fecha_str", "fecha"])[metrica_col]
            .mean().reset_index().sort_values("fecha")
        )
        _evo_chart(df_evo_eq, metrica_col, metrica_label, f"Media del equipo · {metrica_label}")

        section(f"Análisis de sesión · {fecha_label}")
        tab_carga, tab_intensidad, tab_riesgo, tab_comparativa = st.tabs([
            "Carga GPS", "Distancia vs intensidad", "Riesgo (aceleraciones)", "Comparativa jugadores"
        ])
        with tab_carga:
            _session_summary_cards(df_sesion)
            st.markdown("<br>", unsafe_allow_html=True)
            _load_chart(df_sesion)
        with tab_intensidad:
            _distance_intensity_chart(df_sesion)
        with tab_riesgo:
            _acceleration_risk_chart(df_sesion)
        with tab_comparativa:
            _player_comparison_chart(df_sesion, metrica_col, metrica_label)

        _workload_conclusion(df, df_sesion, fecha_label)

        section("Tabla de sesión")
        df_t = df_sesion[["jugador","distancia","vel_max","carga","accel_max","hsr_dist","hsr_count"]].copy()
        df_t = df_t.rename(columns={
            "jugador":"Jugador","distancia":"Dist (km)","vel_max":"Vel Máx",
            "carga":"Carga GPS","accel_max":"Accel Máx",
            "hsr_dist":"HSR Dist (km)","hsr_count":"HSR Entradas"
        }).sort_values("Jugador")
        st.dataframe(df_t, use_container_width=True, hide_index=True)

        # ── Comparación de jugadores ──────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        section("Comparación de jugadores")

        cf1, cf2, cf3 = st.columns([3, 2, 2])
        with cf1:
            jugadores_sel = st.multiselect(
                "Selecciona jugadores", jugadores,
                default=jugadores[:3] if len(jugadores) >= 3 else jugadores,
                key="gps_comp_jugadores"
            )
        with cf2:
            metrica_comp_label = st.selectbox(
                "Métrica", list(METRICA_MAP.keys()), key="gps_comp_metrica"
            )
            metrica_comp_col = METRICA_MAP[metrica_comp_label]
        with cf3:
            vista_comp = st.selectbox(
                "Vista", ["Por sesión", "Media temporada"], key="gps_comp_vista"
            )

        if not jugadores_sel:
            st.info("Selecciona al menos un jugador.")
        else:
            df_comp_multi = df[df["jugador"].isin(jugadores_sel)]

            if vista_comp == "Media temporada":
                df_bar = (df_comp_multi.groupby("jugador")[metrica_comp_col]
                          .mean().reset_index()
                          .sort_values(metrica_comp_col, ascending=True))
                fig_cm = go.Figure(go.Bar(
                    x=df_bar[metrica_comp_col], y=df_bar["jugador"],
                    orientation="h",
                    marker=dict(color=AZUL_CELESTE, opacity=0.9,
                                line=dict(color=DORADO, width=1)),
                    text=[_fmt(v, metrica_comp_col) for v in df_bar[metrica_comp_col]],
                    textposition="outside", textfont=dict(color=BLANCO, size=11),
                ))
                t(fig_cm, height=max(280, len(jugadores_sel) * 44))
                fig_cm.update_layout(title=dict(
                    text=f"Media temporada · {metrica_comp_label}",
                    font=dict(color=GRIS_MEDIO, size=13)))
                chart(fig_cm)

            else:  # Por sesión — líneas
                colores_jugadores = [AZUL_CELESTE, DORADO, VERDE, ROJO,
                                     "#A78BFA", "#F97316", "#34D399", "#FB7185"]
                fig_cm = go.Figure()
                for i, jug in enumerate(jugadores_sel):
                    df_j = (df_comp_multi[df_comp_multi["jugador"] == jug]
                            .sort_values("fecha"))
                    color = colores_jugadores[i % len(colores_jugadores)]
                    fig_cm.add_trace(go.Scatter(
                        x=df_j["fecha_str"], y=df_j[metrica_comp_col],
                        mode="lines+markers+text", name=jug,
                        line=dict(color=color, width=2),
                        marker=dict(size=7, color=color),
                        text=[_fmt(v, metrica_comp_col) for v in df_j[metrica_comp_col]],
                        textposition="top center",
                        textfont=dict(color=color, size=10),
                    ))
                t(fig_cm, height=380)
                fig_cm.update_layout(title=dict(
                    text=f"Evolución por sesión · {metrica_comp_label}",
                    font=dict(color=GRIS_MEDIO, size=13)))
                chart(fig_cm)

    # ════════════════════════════════════════════════════════
    # TAB INDIVIDUAL
    # ════════════════════════════════════════════════════════
    with tab_individual:
        jugador_sel = st.selectbox("Jugador", jugadores, key="gps_jugador_ind")
        df_jug = df[df["jugador"] == jugador_sel].sort_values("fecha")

        if df_jug.empty:
            st.info(f"Sin datos para {jugador_sel}.")
        else:
            # KPIs: última sesión vs media temporada
            section(f"{jugador_sel} · Última sesión vs media temporada")
            ultima = df_jug[df_jug["fecha"] == df_jug["fecha"].max()].iloc[0]
            cols_ind = st.columns(6)
            for col_ui, col_key in zip(cols_ind,
                                        ["distancia","vel_max","carga","accel_max","hsr_dist","hsr_count"]):
                label, suffix, tooltip = METRICAS_INFO[col_key]
                val_ult  = ultima[col_key]  if col_key in ultima.index else None
                val_med  = df_jug[col_key].mean() if col_key in df_jug.columns else None
                delta    = (val_ult - val_med) if pd.notna(val_ult) and pd.notna(val_med) else None
                delta_color = VERDE if delta and delta >= 0 else ROJO
                delta_str   = (f"<span style='color:{delta_color};font-size:0.8rem;'>"
                               f"{'▲' if delta>=0 else '▼'} {abs(delta):.2f} vs media"
                               f"</span>") if delta is not None else ""
                with col_ui:
                    st.markdown(
                        f"<div style='background:{AZUL_MEDIO};border-radius:10px;"
                        f"padding:14px 16px;border-left:4px solid {DORADO};margin-bottom:8px;'>"
                        f"<div style='color:{GRIS_MEDIO};font-size:0.7rem;text-transform:uppercase;"
                        f"letter-spacing:0.08em;margin-bottom:4px;'>{label}</div>"
                        f"<div style='color:{BLANCO};font-size:1.8rem;font-weight:700;line-height:1;'>"
                        f"{_fmt(val_ult, col_key)}<span style='font-size:0.9rem;color:{AZUL_CELESTE}'>{suffix}</span></div>"
                        f"<div style='margin-top:6px;'>{delta_str}</div>"
                        f"<div style='font-size:0.68rem;color:{GRIS_MEDIO};margin-top:6px;line-height:1.3;'>{tooltip}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            # Evolución individual
            section(f"Evolución · {jugador_sel} · {metrica_label}")
            _evo_chart(df_jug, metrica_col, metrica_label, f"{jugador_sel} · {metrica_label}")

            # Tabla individual completa
            section("Historial de sesiones")
            df_hist = df_jug[["fecha_str","distancia","vel_max","carga","accel_max"]].copy()
            df_hist = df_hist.rename(columns={
                "fecha_str":"Fecha","distancia":"Dist (km)",
                "vel_max":"Vel Máx","carga":"Carga GPS","accel_max":"Accel Máx"
            })
            st.dataframe(df_hist, use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════
    # TAB GLOSARIO
    # ════════════════════════════════════════════════════════
    with tab_glosario:
        st.markdown(f"""
        <p style="color:{GRIS_MEDIO};font-size:0.88rem;margin-bottom:20px;">
        Métricas exportadas por Titan en el Training Report.
        Las métricas <b style="color:{BLANCO}">en negrita</b> son las que se utilizan en la App.
        </p>""", unsafe_allow_html=True)

        glosario = [
            ("Date",                    True,  "Fecha",                    "Fecha de la sesión de entrenamiento o partido."),
            ("Player Name",             True,  "Nombre del jugador",       "Nombre completo del jugador registrado en Titan."),
            ("Distance",                True,  "Distancia (km)",           "Kilómetros totales recorridos por el jugador durante la sesión."),
            ("GPS Load",                True,  "Carga GPS",                "Índice de estrés físico total calculado por Titan. Combina distancia, intensidad, aceleraciones y tiempo en alta intensidad. No tiene unidades fijas — sirve para comparar esfuerzos entre sesiones y jugadores."),
            ("Top Speed",               True,  "Velocidad Máxima (km/h)",  "Velocidad punta más alta registrada por el jugador en toda la sesión."),
            ("Speed Zones  Distance",   True,  "HSR Distancia (km)",       "Distancia recorrida a alta velocidad (≥ 21 km/h, umbral configurado en Titan). Equivalente al HSR (High Speed Running) de otros sistemas GPS. Revisar en Titan si el umbral cambia."),
            ("Speed Zones  Count",      True,  "HSR Entradas",             "Número de esfuerzos realizados a ≥ 21 km/h durante la sesión. Indica la frecuencia de acciones de alta intensidad."),
            ("Personal Bands  Distance",False, "Distancia Bandas Personales","Distancia en zonas de velocidad personalizadas por jugador según su perfil físico individual."),
            ("Personal Bands  Count",   False, "Entradas Bandas Personales","Número de entradas en las bandas de velocidad personalizadas del jugador."),
            ("Peak Accel",              True,  "Aceleración Máxima (m/s²)","Pico de aceleración más alto registrado en la sesión. Refleja la explosividad máxima del jugador."),
            ("Accel Zones  Count",      False, "Entradas Zonas Aceleración","Número total de aceleraciones que superaron los umbrales definidos en Titan."),
        ]

        # Cabecera
        st.markdown(f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 2fr;gap:0;
                    background:{AZUL_CLARO};border-radius:8px 8px 0 0;padding:10px 16px;
                    font-size:0.78rem;font-weight:700;color:{BLANCO};
                    text-transform:uppercase;letter-spacing:0.06em;">
            <div>Campo en Excel</div>
            <div>Nombre en castellano</div>
            <div>Descripción</div>
        </div>""", unsafe_allow_html=True)

        for i, (campo, en_app, nombre_es, descripcion) in enumerate(glosario):
            bg = AZUL_MEDIO if i % 2 == 0 else AZUL_OSCURO
            badge = (f"<span style='background:{DORADO};color:{AZUL_OSCURO};font-size:0.65rem;"
                     f"font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px;'>"
                     f"EN APP</span>") if en_app else ""
            nombre_html = (f"<b style='color:{BLANCO}'>{nombre_es}</b>" if en_app
                           else f"<span style='color:{GRIS_MEDIO}'>{nombre_es}</span>")
            campo_html  = (f"<b style='color:{AZUL_CELESTE}'>{campo}</b>" if en_app
                           else f"<span style='color:{GRIS_MEDIO};font-size:0.85rem'>{campo}</span>")
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:1fr 1fr 2fr;gap:0;
                        background:{bg};padding:12px 16px;font-size:0.85rem;
                        border-bottom:1px solid rgba(106,175,230,0.08);">
                <div>{campo_html}{badge}</div>
                <div>{nombre_html}</div>
                <div style="color:{GRIS_MEDIO};font-size:0.82rem;line-height:1.5;">{descripcion}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown(f"""
        <div style="background:{AZUL_MEDIO};border-radius:0 0 8px 8px;padding:10px 16px;
                    font-size:0.75rem;color:{GRIS_MEDIO};border-top:1px solid rgba(106,175,230,0.15);">
            Fuente: Titan by Integrated Bionics · Los datos se actualizan ejecutando <code>script.py</code>
        </div>""", unsafe_allow_html=True)


# ── CSS global ────────────────────────────────────────────────────────────────
def inject_css():
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

    html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
    .stApp {{ background-color: {AZUL_OSCURO}; color: {BLANCO}; }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {AZUL_OSCURO};
        border-right: 1px solid {AZUL_MEDIO};
    }}
    section[data-testid="stSidebar"] label {{
        color: {GRIS_MEDIO} !important;
        font-size: 0.88rem;
    }}

    /* ── Cajitas de navegación ── */
    /* Reset botón base en sidebar */
    section[data-testid="stSidebar"] .stButton button {{
        width: 100%;
        border-radius: 10px;
        padding: 12px 16px;
        font-size: 0.92rem;
        font-weight: 600;
        text-align: left;
        border: 1px solid transparent;
        transition: all 0.18s ease;
        box-shadow: none;
        letter-spacing: 0.01em;
    }}

    /* Acción principal: exportar el informe GPS */
    button[kind="primary"] {{
        background: linear-gradient(135deg, {DORADO} 0%, #af8730 100%) !important;
        color: {AZUL_OSCURO} !important;
        border: 1px solid #e4c46c !important;
        border-radius: 9px !important;
        font-weight: 800 !important;
        box-shadow: 0 5px 14px rgba(0, 0, 0, 0.24) !important;
        transition: transform 0.18s ease, box-shadow 0.18s ease !important;
    }}
    button[kind="primary"]:hover {{
        background: linear-gradient(135deg, #dfbf63 0%, {DORADO} 100%) !important;
        color: {AZUL_OSCURO} !important;
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(0, 0, 0, 0.30) !important;
    }}

    /* Estado INACTIVO */
    div.nav-item-inactive .stButton button {{
        background: {AZUL_MEDIO};
        color: {GRIS_MEDIO};
        border-color: rgba(106,175,230,0.1);
    }}
    div.nav-item-inactive .stButton button:hover {{
        background: {AZUL_CLARO};
        color: {BLANCO};
        border-color: rgba(106,175,230,0.3);
        transform: translateX(3px);
        box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    }}

    /* Estado ACTIVO */
    div.nav-item-active .stButton button {{
        background: linear-gradient(135deg, {AZUL_CLARO} 0%, {AZUL_MEDIO} 100%);
        color: {BLANCO} !important;
        border-color: {DORADO};
        border-left: 3px solid {DORADO};
        box-shadow:
            0 2px 8px rgba(0,0,0,0.3),
            inset 0 1px 0 rgba(255,255,255,0.08);
    }}
    div.nav-item-active .stButton button:hover {{
        background: linear-gradient(135deg, {AZUL_CLARO} 0%, {AZUL_MEDIO} 100%);
        color: {BLANCO} !important;
    }}

    /* Selectbox */
    div[data-baseweb="select"] > div {{
        background-color: {AZUL_MEDIO} !important;
        border-color: {AZUL_CLARO} !important;
        color: {BLANCO} !important;
    }}

    /* ── Sombra y profundidad en gráficos Plotly ── */
    .stPlotlyChart {{
        border-radius: 14px;
        overflow: hidden;
        box-shadow:
            0 2px  4px  rgba(0, 0, 0, 0.35),
            0 6px  16px rgba(0, 0, 0, 0.30),
            0 16px 40px rgba(0, 0, 0, 0.20),
            inset 0 1px 0 rgba(255,255,255,0.04);
        border: 1px solid rgba(106,175,230,0.10);
        transition: box-shadow 0.2s ease;
    }}
    .stPlotlyChart:hover {{
        box-shadow:
            0 2px  4px  rgba(0, 0, 0, 0.40),
            0 8px  24px rgba(0, 0, 0, 0.35),
            0 20px 50px rgba(0, 0, 0, 0.25),
            inset 0 1px 0 rgba(255,255,255,0.06);
        border-color: rgba(106,175,230,0.20);
    }}

    /* ── Sombra en tarjetas HTML (metric cards, tabla resultados, etc.) ── */
    .stMarkdown div[style*="border-radius"] {{
        transition: box-shadow 0.2s ease;
    }}

    /* ── Fondo con profundidad ── */
    .stApp {{
        background:
            radial-gradient(1200px 500px at 85% -10%, rgba(106,175,230,0.13), transparent 60%),
            radial-gradient(900px 400px at -10% 110%, rgba(201,168,76,0.06), transparent 60%),
            {AZUL_OSCURO};
    }}
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #16233F 0%, {AZUL_OSCURO} 100%);
    }}
    .block-container {{ padding-top: 2.2rem; max-width: 1400px; }}

    /* ── Cabecera de página ── */
    .cadf-hero {{
        position: relative; overflow: hidden;
        display: flex; justify-content: space-between; align-items: center; gap: 24px; flex-wrap: wrap;
        padding: 26px 30px; margin-bottom: 18px; border-radius: 18px;
        background: linear-gradient(120deg, {AZUL_MEDIO} 0%, #22406C 45%, #1A2E52 100%);
        border: 1px solid rgba(106,175,230,0.22);
        box-shadow: 0 18px 40px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.08);
    }}
    .cadf-hero::before {{
        content: ""; position: absolute; inset: 0 auto 0 0; width: 6px;
        background: linear-gradient(180deg, {AZUL_CELESTE}, {DORADO});
    }}
    .cadf-hero::after {{
        content: ""; position: absolute; right: -60px; top: -80px; width: 280px; height: 280px;
        border-radius: 50%; border: 38px solid rgba(106,175,230,0.07); pointer-events: none;
    }}
    .cadf-hero-kicker {{
        color: {DORADO}; font-size: 0.72rem; font-weight: 800; letter-spacing: 0.16em;
        text-transform: uppercase; margin-bottom: 4px;
    }}
    .cadf-hero h1 {{
        color: {BLANCO}; font-size: 2.1rem; font-weight: 800; margin: 0; padding: 0;
        line-height: 1.15; letter-spacing: -0.01em;
    }}
    .cadf-hero p {{ color: {GRIS_MEDIO}; font-size: 0.95rem; margin: 6px 0 0; }}
    .cadf-hero-aside {{ display: flex; flex-direction: column; align-items: flex-end; gap: 8px; z-index: 1; }}
    .cadf-hero-stat {{ color: {GRIS_MEDIO}; font-size: 0.78rem; text-align: right; text-transform: uppercase;
                       letter-spacing: 0.08em; }}
    .cadf-hero-stat span {{ display: block; color: {DORADO}; font-size: 2.6rem; font-weight: 800;
                            line-height: 1; letter-spacing: 0; }}
    .cadf-form {{ display: flex; gap: 5px; }}
    .cadf-score-big {{ color: {DORADO}; margin: 0 10px; font-variant-numeric: tabular-nums; }}
    .cadf-score-big em {{ color: {GRIS_MEDIO}; font-style: normal; margin: 0 6px; font-weight: 400; }}

    /* ── Chips de resultado y etiquetas ── */
    .cadf-chip {{
        display: inline-block; min-width: 26px; padding: 3px 9px; border-radius: 7px; text-align: center;
        font-size: 0.78rem; font-weight: 800; color: {AZUL_OSCURO}; background: var(--chip);
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    }}
    .cadf-tag {{
        display: inline-block; margin-left: 8px; padding: 1px 7px; border-radius: 5px; font-size: 0.66rem;
        font-weight: 700; color: {AZUL_CELESTE}; background: rgba(106,175,230,0.12);
        text-transform: uppercase; letter-spacing: 0.06em; vertical-align: middle;
    }}

    /* ── Tarjetas KPI ── */
    .cadf-kpi {{
        position: relative; min-height: 112px; margin-bottom: 10px; padding: 15px 18px 14px;
        border-radius: 14px; overflow: hidden;
        background: linear-gradient(160deg, #31517F 0%, {AZUL_MEDIO} 55%, #26416B 100%);
        border: 1px solid rgba(255,255,255,0.07);
        box-shadow: 0 10px 24px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.08);
    }}
    .cadf-kpi::before {{
        content: ""; position: absolute; left: 0; top: 0; right: 0; height: 3px; background: var(--accent);
    }}
    .cadf-kpi-label {{ color: {GRIS_MEDIO}; font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
                       letter-spacing: 0.09em; margin-bottom: 6px; }}
    .cadf-kpi-value {{ color: {BLANCO}; font-size: 1.95rem; font-weight: 800; line-height: 1.05;
                       font-variant-numeric: tabular-nums; }}
    .cadf-kpi-value span {{ font-size: 0.95rem; color: {AZUL_CELESTE}; margin-left: 2px; font-weight: 600; }}
    .cadf-kpi-delta {{ font-size: 0.74rem; font-weight: 700; margin-top: 6px; }}
    .cadf-kpi-hint {{ color: {GRIS_MEDIO}; font-size: 0.72rem; margin-top: 5px; line-height: 1.35; opacity: 0.85; }}

    /* ── Capítulos ── */
    .cadf-section {{ margin: 30px 0 12px; padding-left: 14px; border-left: 3px solid {DORADO}; }}
    .cadf-section-title {{ color: {BLANCO}; font-size: 1.08rem; font-weight: 800; letter-spacing: 0.01em; }}
    .cadf-section-sub {{ color: {GRIS_MEDIO}; font-size: 0.84rem; margin-top: 3px; line-height: 1.45; }}
    .cadf-sublabel {{ color: {GRIS_MEDIO}; font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
                      letter-spacing: 0.08em; margin: 10px 0 4px; }}

    /* ── Lectura técnica (conclusiones) ── */
    .cadf-insights-head {{ color: {DORADO}; font-size: 0.74rem; font-weight: 800; text-transform: uppercase;
                           letter-spacing: 0.14em; margin: 18px 0 8px; }}
    .cadf-insights {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                      gap: 12px; margin-bottom: 14px; align-items: start; }}
    .cadf-insight-group {{
        border-radius: 14px; padding: 10px; border: 1px solid rgba(255,255,255,0.06);
        border-top: 3px solid var(--tone);
        background: linear-gradient(180deg, rgba(20,34,60,0.75) 0%, rgba(20,34,60,0.35) 100%);
        box-shadow: 0 10px 24px rgba(0,0,0,0.25);
    }}
    .cadf-insight-group-head {{
        display: flex; align-items: center; gap: 8px; padding: 4px 6px 10px; color: var(--tone);
        font-size: 0.74rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.12em;
    }}
    .cadf-insight-group-head b {{
        margin-left: auto; min-width: 22px; padding: 1px 7px; border-radius: 999px; text-align: center;
        background: var(--tone); color: {AZUL_OSCURO}; font-size: 0.72rem; letter-spacing: 0;
    }}
    .cadf-insight {{
        padding: 12px 14px; margin-bottom: 8px; border-radius: 10px; border-left: 3px solid var(--tone);
        background: linear-gradient(135deg, rgba(46,75,122,0.95) 0%, rgba(30,50,85,0.95) 100%);
        box-shadow: 0 6px 14px rgba(0,0,0,0.2);
    }}
    .cadf-insight:last-child {{ margin-bottom: 0; }}
    .cadf-insight-tag {{ color: var(--tone); font-size: 0.64rem; font-weight: 800; text-transform: uppercase;
                         letter-spacing: 0.12em; }}
    .cadf-insight-title {{ color: {BLANCO}; font-size: 0.95rem; font-weight: 800; margin: 3px 0 4px; }}
    .cadf-insight-body {{ color: {GRIS_MEDIO}; font-size: 0.82rem; line-height: 1.5; }}
    .cadf-insight-body b {{ color: {BLANCO}; }}

    /* ── Filas de resultados ── */
    .cadf-row {{
        display: grid; grid-template-columns: 44px minmax(140px, 2fr) 80px 60px repeat(3, minmax(80px, 1fr));
        align-items: center; gap: 6px; padding: 10px 16px; margin-bottom: 6px; border-radius: 11px;
        background: linear-gradient(90deg, rgba(46,75,122,0.95), rgba(37,63,107,0.85));
        border-left: 4px solid var(--res); box-shadow: 0 6px 14px rgba(0,0,0,0.2);
    }}
    .cadf-row-j {{ color: {DORADO}; font-weight: 800; font-size: 0.85rem; }}
    .cadf-row-rival {{ color: {BLANCO}; font-weight: 700; }}
    .cadf-row-score {{ color: {BLANCO}; font-size: 1.35rem; font-weight: 800; text-align: center;
                       font-variant-numeric: tabular-nums; }}
    .cadf-row-score span {{ color: {GRIS_MEDIO}; margin: 0 4px; font-weight: 400; }}
    .cadf-row-stat {{ color: {BLANCO}; font-weight: 800; text-align: center; line-height: 1.1; }}
    .cadf-row-stat small {{ display: block; color: {GRIS_MEDIO}; font-size: 0.62rem; font-weight: 600;
                            text-transform: uppercase; letter-spacing: 0.06em; }}

    /* ── Tablas de rendimiento ── */
    .cadf-score-wrap {{ overflow-x: auto; margin-bottom: 14px; border-radius: 14px;
                        box-shadow: 0 10px 26px rgba(0,0,0,0.28); }}
    .cadf-score {{ display: grid; min-width: 760px; background: {AZUL_MEDIO}; border-radius: 14px;
                   border: 1px solid rgba(106,175,230,0.14); overflow: hidden; }}
    .cadf-score > div {{ padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,0.05);
                         display: flex; align-items: center; }}
    .cadf-score-h {{ background: #22406C; color: {GRIS_MEDIO}; font-size: 0.64rem; font-weight: 800;
                     text-transform: uppercase; letter-spacing: 0.07em; justify-content: center; text-align: center; }}
    .cadf-score-j {{ color: {DORADO}; font-weight: 800; justify-content: center; }}
    .cadf-score-rival {{ color: {BLANCO}; font-weight: 700; font-size: 0.9rem; }}
    .cadf-score-c {{ color: {BLANCO}; font-weight: 700; justify-content: center;
                     font-variant-numeric: tabular-nums; }}
    .cadf-score-mean {{ color: {DORADO}; background: rgba(0,0,0,0.12); }}

    /* ── Pestañas ── */
    .stTabs [data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 1px solid rgba(106,175,230,0.18); }}
    .stTabs [data-baseweb="tab"] {{
        background: rgba(46,75,122,0.55); border-radius: 9px 9px 0 0; padding: 8px 16px;
        color: {GRIS_MEDIO}; font-weight: 700;
    }}
    .stTabs [aria-selected="true"] {{ background: {AZUL_MEDIO}; color: {BLANCO} !important; }}
    .stTabs [data-baseweb="tab-highlight"] {{ background-color: {DORADO}; }}

    @media (max-width: 640px) {{
        .cadf-hero {{ padding: 20px 18px; }}
        .cadf-hero h1 {{ font-size: 1.5rem; }}
        .cadf-hero-aside {{ align-items: flex-start; }}
        .cadf-row {{ grid-template-columns: 34px 1fr 64px 44px; }}
        .cadf-row-stat {{ display: none; }}
    }}

    /* Radio buttons */
    .stRadio > div {{
        background: {AZUL_MEDIO};
        border-radius: 8px;
        padding: 8px 12px;
        border: 1px solid rgba(106,175,230,0.15);
    }}
    .stRadio label {{ color: {GRIS_MEDIO} !important; }}

    /* Spinner */
    .stSpinner > div {{ border-top-color: {AZUL_CELESTE} !important; }}

    /* Scrollbar */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: {AZUL_OSCURO}; }}
    ::-webkit-scrollbar-thumb {{
        background: {AZUL_MEDIO};
        border-radius: 3px;
    }}
    ::-webkit-scrollbar-thumb:hover {{ background: {AZUL_CLARO}; }}
    </style>
    """, unsafe_allow_html=True)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Club Argentino · Análisis",
        page_icon="🔵",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()

    with st.spinner("Cargando datos..."):
        if not GOOGLE_SEASON_FOLDER_ID:
            st.error("Falta configurar GOOGLE_SEASON_FOLDER_ID en Streamlit Secrets.")
            st.stop()
        partidos_folder_id = _get_season_subfolder_id(GOOGLE_SEASON_FOLDER_ID, "Partidos")
        df = _load_match_data(partidos_folder_id)
        video_df = _load_video_events(partidos_folder_id)

    if df.empty:
        st.error("No se encontraron datos en /data")
        return

    page = render_sidebar(season_label(df))
    # Temporada, Inicio y Rivales usan solo competición oficial; Partido permite ver también amistosos.
    df_oficial, video_oficial = split_friendlies(df, video_df)

    if   page == "Inicio":    page_inicio(df_oficial, video_oficial)
    elif page == "Temporada": page_temporada(df_oficial, video_oficial)
    elif page == "Partido":   page_partido(df, video_df)
    elif page == "Rivales":   page_rivales(df_oficial, video_oficial)
    elif page == "Física":    page_fisica()


if __name__ == "__main__":
    main()
