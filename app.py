"""
Club Argentino — Dashboard de Análisis
Desarrollado por Ramón Codesido · Sport Data Campus
"""

import base64
import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from data_loader import load_all, load_partidos

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


# ── Helper: template de plotly con profundidad ────────────────────────────────
# Color del área de plot ligeramente más claro que el paper para crear profundidad
PLOT_BG  = "#253F6B"   # azul medio más cálido para el área de datos
PAPER_BG = "#1B2A4A"   # azul oscuro del fondo general

def t(fig: go.Figure, height=380, margin=None, **extra) -> go.Figure:
    m = margin or dict(t=36, b=36, l=48, r=36)
    fig.update_layout(
        height=height,
        margin=m,
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO, size=12),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLANCO, size=11),
                    orientation="h", y=1.08),
        # Borde sutil alrededor del área de plot
        shapes=[dict(
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
        text=text,
        textposition=pos,
        textfont=dict(color=BLANCO, size=12, family="Inter"),
    )


def chart(fig):
    """Renderiza un plotly chart."""
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def img_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def metric_card(label: str, value, suffix: str = "") -> str:
    return f"""
    <div style="background:{AZUL_MEDIO};border-radius:10px;padding:16px 20px;
                border-left:4px solid {DORADO};margin-bottom:8px;height:90px;">
        <div style="color:{GRIS_MEDIO};font-size:0.7rem;text-transform:uppercase;
                    letter-spacing:0.08em;margin-bottom:6px;">{label}</div>
        <div style="color:{BLANCO};font-size:2rem;font-weight:700;line-height:1;">
            {value}<span style="font-size:1rem;color:{AZUL_CELESTE};margin-left:2px">{suffix}</span>
        </div>
    </div>"""


def section(title: str):
    st.markdown(
        f"<h4 style='color:{DORADO};margin:24px 0 10px 0;font-size:1rem;"
        f"text-transform:uppercase;letter-spacing:0.06em;'>{title}</h4>",
        unsafe_allow_html=True,
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
NAV_ITEMS = [
    ("🏠", "Inicio"),
    ("📋", "Temporada"),
    ("🎮", "Partido"),
    ("⚔️", "Rivales"),
]

def render_sidebar():
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
        <span style="color:{DORADO};font-size:0.85rem;">Temporada 2025–2026</span>
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
def page_inicio(df: pd.DataFrame):
    st.markdown(f"""
    <h1 style="color:{BLANCO};font-size:2rem;font-weight:700;margin-bottom:2px;">
        Club Argentino
    </h1>
    <p style="color:{AZUL_CELESTE};font-size:0.9rem;margin-bottom:20px;">
        Panel de análisis de rendimiento · Temporada 2025–2026
    </p>""", unsafe_allow_html=True)

    temporada = df[df["nivel"] == "temporada"]
    n        = len(temporada)
    goles_f  = int(temporada["goles"].fillna(0).sum())
    # GC solo si tenemos dato real (no contar los NaN como 0)
    gc_known = temporada["goles_enc"].dropna() if "goles_enc" in temporada.columns else pd.Series([], dtype=float)
    goles_c_str = str(int(gc_known.sum())) if not gc_known.empty else "N/D"
    prom_pos = temporada["pct_posesion"].mean()
    prom_pas = temporada["pct_pases"].mean()
    # V/E/D solo con partidos donde tenemos GC real
    victorias = sum(1 for _, r in temporada.iterrows()
                    if pd.notna(r.get("goles_enc")) and (r.get("goles") or 0) > (r.get("goles_enc") or 0))
    empates   = sum(1 for _, r in temporada.iterrows()
                    if pd.notna(r.get("goles_enc")) and (r.get("goles") or 0) == (r.get("goles_enc") or 0))
    derrotas  = sum(1 for _, r in temporada.iterrows()
                    if pd.notna(r.get("goles_enc")) and (r.get("goles") or 0) < (r.get("goles_enc") or 0))
    nd_count  = n - victorias - empates - derrotas  # partidos sin GC

    # ── KPIs ──
    cols = st.columns(4)
    for col, (lbl, val, suf) in zip(cols, [
        ("Partidos jugados", n,                  ""),
        ("Posesión media",   f"{prom_pos:.1f}",  "%"),
        ("Precisión pases",  f"{prom_pas:.1f}",  "%"),
        ("Goles marcados",   goles_f,             ""),
    ]):
        col.markdown(metric_card(lbl, val, suf), unsafe_allow_html=True)

    # ── Balance V/E/D ──
    st.markdown(f"""
    <div style="display:flex;gap:10px;margin:12px 0 24px;">
        <div style="flex:1;background:{AZUL_MEDIO};border-radius:8px;padding:10px 0;
                    text-align:center;border-top:3px solid {VERDE};">
            <div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;
                        letter-spacing:0.08em;">Victorias</div>
            <div style="color:{VERDE};font-size:1.6rem;font-weight:800;">{victorias}</div>
        </div>
        <div style="flex:1;background:{AZUL_MEDIO};border-radius:8px;padding:10px 0;
                    text-align:center;border-top:3px solid {DORADO};">
            <div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;
                        letter-spacing:0.08em;">Empates</div>
            <div style="color:{DORADO};font-size:1.6rem;font-weight:800;">{empates}</div>
        </div>
        <div style="flex:1;background:{AZUL_MEDIO};border-radius:8px;padding:10px 0;
                    text-align:center;border-top:3px solid {ROJO};">
            <div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;
                        letter-spacing:0.08em;">Derrotas</div>
            <div style="color:{ROJO};font-size:1.6rem;font-weight:800;">{derrotas}</div>
        </div>
        <div style="flex:1;background:{AZUL_MEDIO};border-radius:8px;padding:10px 0;
                    text-align:center;border-top:3px solid {AZUL_CELESTE};">
            <div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;
                        letter-spacing:0.08em;">GF / GC</div>
            <div style="color:{BLANCO};font-size:1.6rem;font-weight:800;">
                <span style="color:{VERDE}">{goles_f}</span>
                <span style="color:{GRIS_MEDIO};font-size:1rem;"> / </span>
                <span style="color:{ROJO}">{goles_c_str}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Resultados ──
    section("Resultados de la temporada")
    cols_h = ["Fecha", "Partido", "GF", "GC", "DIF", "Posesión", "Pases %"]
    st.markdown(f"""
    <div style="display:grid;grid-template-columns:1.1fr 2fr 0.6fr 0.6fr 0.6fr 1fr 1fr;
                gap:4px;margin-bottom:6px;padding:0 14px;">
        {"".join(f'<div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;'
                 f'letter-spacing:0.08em;font-weight:600;text-align:center;">{h}</div>'
                 for h in cols_h)}
    </div>""", unsafe_allow_html=True)

    partidos_info = load_partidos()
    for _, row in temporada.iterrows():
        gf      = int(row.get("goles") or 0)
        gc_raw  = row.get("goles_enc")
        gc_known = pd.notna(gc_raw)
        gc      = int(gc_raw) if gc_known else None
        pos     = row.get("pct_posesion") or 0
        pas     = row.get("pct_pases") or 0
        rival   = row.get("rival", "")
        pr      = partidos_info[partidos_info["rival"] == rival]
        fecha_str = (pr["fecha"].dt.strftime("%d/%m/%y").iloc[0]
                     if not pr.empty and pd.notna(pr["fecha"].iloc[0]) else "–")

        # Resultado y diferencia solo si tenemos GC
        if gc_known:
            dif       = gf - gc
            dif_str   = f"+{dif}" if dif > 0 else str(dif)
            dif_color = VERDE if dif > 0 else (ROJO if dif < 0 else DORADO)
            res_color = VERDE if gf > gc else (ROJO if gf < gc else DORADO)
            gc_html   = f'<div style="color:{ROJO};font-size:1.2rem;font-weight:700;text-align:center;">{gc}</div>'
            dif_html  = f'<div style="color:{dif_color};font-weight:700;text-align:center;">{dif_str}</div>'
        else:
            res_color = AZUL_CLARO
            gc_html   = f'<div style="color:{GRIS_MEDIO};font-size:0.8rem;text-align:center;">N/D</div>'
            dif_html  = f'<div style="color:{GRIS_MEDIO};font-size:0.8rem;text-align:center;">N/D</div>'

        st.markdown(f"""
        <div style="display:grid;grid-template-columns:1.1fr 2fr 0.6fr 0.6fr 0.6fr 1fr 1fr;
                    gap:4px;background:{AZUL_MEDIO};border-radius:8px;
                    padding:11px 14px;margin-bottom:5px;
                    border-left:4px solid {res_color};align-items:center;">
            <div style="color:{GRIS_MEDIO};font-size:0.8rem;text-align:center;">{fecha_str}</div>
            <div style="color:{BLANCO};font-weight:600;">CAdF vs {rival}</div>
            <div style="color:{VERDE};font-size:1.2rem;font-weight:700;text-align:center;">{gf}</div>
            {gc_html}
            {dif_html}
            <div style="color:{AZUL_CELESTE};font-weight:600;text-align:center;">{pos:.1f}%</div>
            <div style="color:{DORADO};font-weight:600;text-align:center;">{pas:.0f}%</div>
        </div>""", unsafe_allow_html=True)

    # ── Descripción de secciones ──
    section("Qué encontrarás en esta app")
    for icono, titulo, desc in [
        ("📋", "Temporada",
         "Evolución de métricas partido a partido: posesión, precisión de pases, tiros y goles. "
         "Heatmap de rendimiento por tramos de 15 minutos a lo largo de la temporada."),
        ("🎮", "Partido",
         "Análisis detallado de cada partido: línea de vida del control del juego por tramo, "
         "comparativa de mitades, campograma de pases por tercio del campo."),
        ("⚔️", "Rivales",
         "Histórico de enfrentamientos contra cada rival. Detecta en qué tramos "
         "pierdes el control y prepara tácticamente los próximos duelos."),
    ]:
        st.markdown(f"""
        <div style="background:{AZUL_MEDIO};border-radius:8px;padding:12px 16px;
                    margin-bottom:6px;display:flex;gap:14px;align-items:flex-start;">
            <div style="font-size:1.4rem;margin-top:2px;">{icono}</div>
            <div>
                <div style="color:{DORADO};font-weight:700;font-size:0.88rem;
                            margin-bottom:3px;">{titulo}</div>
                <div style="color:{GRIS_MEDIO};font-size:0.82rem;line-height:1.5;">{desc}</div>
            </div>
        </div>""", unsafe_allow_html=True)


# ── Página: Temporada ─────────────────────────────────────────────────────────
def _cell_color(val):
    if val >= 60: return "rgba(106,175,230,0.9)", AZUL_OSCURO
    if val >= 50: return "rgba(106,175,230,0.5)", BLANCO
    if val >= 45: return "rgba(201,168,76,0.55)", BLANCO
    return "rgba(232,93,117,0.75)", BLANCO


def _timeline_chart(partidos_raw):
    """Gráfico combinado diferencia por partido + acumulado temporada."""
    partidos_raw = partidos_raw.sort_values("fecha").reset_index(drop=True)
    partidos_raw["dif"]      = partidos_raw["gf"] - partidos_raw["gc"]
    partidos_raw["acum_dif"] = partidos_raw["dif"].cumsum()
    etiquetas  = [f"vs {r}  {gf}–{gc}" for r, gf, gc in
                  zip(partidos_raw["rival"], partidos_raw["gf"], partidos_raw["gc"])]
    colors_dif = [VERDE if d > 0 else (ROJO if d < 0 else DORADO)
                  for d in partidos_raw["dif"]]
    acum = partidos_raw["acum_dif"].tolist()

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=etiquetas, y=partidos_raw["dif"], name="Diferencia por partido",
        marker=dict(color=colors_dif, line=dict(color=AZUL_OSCURO, width=1), opacity=0.85),
        text=[f"+{d}" if d > 0 else str(d) for d in partidos_raw["dif"]],
        textposition="outside", textfont=dict(color=BLANCO, size=13),
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=etiquetas, y=acum, name="Acumulado temporada",
        mode="lines+markers+text",
        line=dict(color=DORADO, width=3, shape="spline"),
        marker=dict(size=12, color=[VERDE if v > 0 else (ROJO if v < 0 else DORADO) for v in acum],
                    line=dict(color=BLANCO, width=2)),
        text=[f"+{v}" if v > 0 else str(v) for v in acum],
        textposition="top center", textfont=dict(color=DORADO, size=11),
    ), secondary_y=True)
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.2)", line_width=1.5,
                  line_dash="dot", secondary_y=False)
    fig.update_layout(
        paper_bgcolor=AZUL_OSCURO, plot_bgcolor=PLOT_BG,
        height=340, margin=dict(t=30, b=20, l=40, r=60),
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLANCO),
                    orientation="h", y=1.12),
        bargap=0.35,
    )
    fig.update_xaxes(gridcolor="rgba(200,214,229,0.08)", tickfont=dict(color=BLANCO, size=11))
    fig.update_yaxes(title_text="Diferencia", gridcolor="rgba(200,214,229,0.08)",
                     tickfont=dict(color=BLANCO), secondary_y=False,
                     zeroline=True, zerolinecolor="rgba(255,255,255,0.15)")
    fig.update_yaxes(title_text="Acumulado", gridcolor="rgba(0,0,0,0)",
                     tickfont=dict(color=DORADO), color=DORADO, secondary_y=True)
    return fig


def page_temporada(df: pd.DataFrame):
    st.markdown(f"<h2 style='color:{BLANCO};margin-bottom:4px;'>📋 Temporada</h2>",
                unsafe_allow_html=True)

    temporada = df[df["nivel"] == "temporada"].copy()
    rivales   = temporada["rival"].tolist()
    n_partidos = max(len(rivales), 1)

    # ── 1: Heatmap posesión por tramo ──
    section("Mapa de posesión por tramo y partido")
    tramos_df = df[df["nivel"] == "tramo"].copy()
    pivot = (
        tramos_df.pivot_table(index="rival", columns="tramo_raw", values="pct_posesion")
        .reindex(columns=TRAMO_ORDER)
    )
    promedios = pivot.mean()
    n_rivales = len(pivot.index)
    n_tramos  = len(TRAMO_ORDER)
    prom_y    = n_rivales + 0.3

    fig_hm = go.Figure()
    for r_idx, rival in enumerate(pivot.index):
        for t_idx, tramo in enumerate(TRAMO_ORDER):
            val = pivot.loc[rival, tramo] if tramo in pivot.columns else None
            if pd.isna(val): continue
            bg, tc = _cell_color(val)
            fig_hm.add_shape(type="rect",
                x0=t_idx-0.45, x1=t_idx+0.45, y0=r_idx-0.4, y1=r_idx+0.4,
                fillcolor=bg, line=dict(color="rgba(255,255,255,0.06)", width=1))
            fig_hm.add_annotation(x=t_idx, y=r_idx, text=f"<b>{val:.0f}%</b>",
                showarrow=False, font=dict(color=tc, size=13, family="Inter"))
    for t_idx, tramo in enumerate(TRAMO_ORDER):
        pval = promedios.get(tramo)
        if pd.isna(pval): continue
        bg, tc = _cell_color(pval)
        fig_hm.add_shape(type="rect",
            x0=t_idx-0.45, x1=t_idx+0.45,
            y0=prom_y-0.38, y1=prom_y+0.38,
            fillcolor=bg, line=dict(color=DORADO, width=1.5))
        fig_hm.add_annotation(x=t_idx, y=prom_y, text=f"<b>{pval:.0f}%</b>",
            showarrow=False, font=dict(color=tc, size=12, family="Inter"))

    fig_hm.update_layout(
        paper_bgcolor=AZUL_OSCURO, plot_bgcolor=AZUL_OSCURO,
        height=max(220, (n_rivales + 1) * 85 + 80),
        margin=dict(t=20, b=50, l=90, r=20),
        xaxis=dict(tickvals=list(range(n_tramos)), ticktext=TRAMO_ORDER,
                   showgrid=False, zeroline=False, tickfont=dict(color=GRIS_MEDIO, size=11)),
        yaxis=dict(tickvals=list(range(n_rivales)) + [prom_y],
                   ticktext=list(pivot.index) + ["<b>Promedio</b>"],
                   showgrid=False, zeroline=False, tickfont=dict(color=BLANCO, size=11),
                   autorange="reversed"),
    )
    for color, label in [("rgba(106,175,230,0.9)", "≥60%"),("rgba(106,175,230,0.5)", "50–60%"),
                          ("rgba(201,168,76,0.55)", "45–50%"),("rgba(232,93,117,0.75)", "<45%")]:
        fig_hm.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
            marker=dict(size=11, color=color, symbol="square"), name=label, showlegend=True))
    fig_hm.update_layout(legend=dict(orientation="h", y=-0.18, x=0,
        font=dict(color=GRIS_MEDIO, size=10), bgcolor="rgba(0,0,0,0)"))
    chart(fig_hm)

    # ── 2: Promedio 1ª vs 2ª mitad ──
    section("Promedio 1ª vs 2ª Mitad — toda la temporada")
    partes_df = df[df["nivel"] == "parte"]
    p1m = partes_df[partes_df["tramo_raw"] == "1º mitad"].mean(numeric_only=True)
    p2m = partes_df[partes_df["tramo_raw"] == "2º mitad"].mean(numeric_only=True)
    mets = {"Posesión %": "pct_posesion", "Pases %": "pct_pases",
            "Tiros": "tiros", "Centros": "centros", "Tiros puerta": "tiros_puerta"}
    v1 = [p1m.get(v, 0) or 0 for v in mets.values()]
    v2 = [p2m.get(v, 0) or 0 for v in mets.values()]
    fig_mit = go.Figure()
    fig_mit.add_trace(go.Bar(name="1ª Mitad (prom)", x=list(mets.keys()), y=v1,
        marker_color=AZUL_CELESTE, text=[f"{v:.1f}" for v in v1],
        textposition="outside", textfont=dict(color=BLANCO)))
    fig_mit.add_trace(go.Bar(name="2ª Mitad (prom)", x=list(mets.keys()), y=v2,
        marker_color=DORADO, text=[f"{v:.1f}" for v in v2],
        textposition="outside", textfont=dict(color=BLANCO)))
    t(fig_mit, height=320, barmode="group", margin=dict(t=20, b=20, l=20, r=20))
    chart(fig_mit)

    # ── 3: Posesión + Pases % ──
    section("Control del juego — Posesión & Precisión de pases")
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
                                yshift=16, font=dict(color=AZUL_CELESTE, size=10))
        fig_ctrl.add_annotation(x=rv, y=pas, text=f"{pas:.0f}%", showarrow=False,
                                yshift=-18, font=dict(color=DORADO, size=10))
    t(fig_ctrl, height=360, yaxis=dict(range=[30, 105], ticksuffix="%",
                                       gridcolor="rgba(200,214,229,0.1)",
                                       tickfont=dict(color=BLANCO)))
    chart(fig_ctrl)

    # ── 4: Pases por tercio — campograma con selector ──
    section("Pases por tercio del campo")
    modo = st.radio("", ["Promedio por partido", "Total temporada"],
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

    # ── 5: Tiros totales, a puerta, % eficacia ──
    section("Ataque — Tiros totales, a puerta y eficacia")
    fig_tir = make_subplots(specs=[[{"secondary_y": True}]])
    tiros_tot = temporada["tiros"].fillna(0).astype(int).tolist()
    tiros_prt = temporada["tiros_puerta"].fillna(0).astype(int).tolist()
    pct_efic  = [round(tp/tt*100, 1) if tt > 0 else 0
                 for tt, tp in zip(tiros_tot, tiros_prt)]
    fig_tir.add_trace(go.Bar(
        name="Tiros totales", x=rivales, y=tiros_tot,
        marker=dict(color=AZUL_CELESTE, opacity=0.7, line=dict(color=AZUL_OSCURO, width=1)),
        text=tiros_tot, textposition="outside", textfont=dict(color=AZUL_CELESTE, size=12),
    ), secondary_y=False)
    fig_tir.add_trace(go.Bar(
        name="Tiros a puerta", x=rivales, y=tiros_prt,
        marker=dict(color=DORADO, opacity=0.9, line=dict(color=AZUL_OSCURO, width=1)),
        text=tiros_prt, textposition="inside", textfont=dict(color=BLANCO, size=12),
    ), secondary_y=False)
    fig_tir.add_trace(go.Scatter(
        name="% Eficacia (tiros→puerta)", x=rivales, y=pct_efic,
        mode="lines+markers+text",
        line=dict(color=VERDE, width=3),
        marker=dict(size=12, color=VERDE, line=dict(color=BLANCO, width=2)),
        text=[f"{v}%" for v in pct_efic], textposition="top center",
        textfont=dict(color=VERDE, size=11),
    ), secondary_y=True)
    fig_tir.update_layout(
        paper_bgcolor=AZUL_OSCURO, plot_bgcolor=PLOT_BG,
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO),
        height=380, margin=dict(t=30, b=30, l=40, r=70),
        barmode="group", bargap=0.25, bargroupgap=0.05,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLANCO), orientation="h", y=1.1),
    )
    fig_tir.update_yaxes(title_text="Nº tiros", secondary_y=False,
                          gridcolor="rgba(200,214,229,0.1)", tickfont=dict(color=BLANCO))
    fig_tir.update_yaxes(title_text="% Eficacia", secondary_y=True,
                          gridcolor="rgba(0,0,0,0)", tickfont=dict(color=VERDE),
                          color=VERDE, range=[0, 100], ticksuffix="%")
    fig_tir.update_xaxes(gridcolor="rgba(200,214,229,0.1)", tickfont=dict(color=BLANCO))
    chart(fig_tir)

    # ── 6: Diferencia de goles y acumulado ──
    section("Diferencia de goles y acumulado de temporada")
    partidos_raw = load_partidos()
    # Solo mostrar el timeline con partidos donde tenemos GC real
    partidos_completos = partidos_raw.dropna(subset=["gc"]) if not partidos_raw.empty else partidos_raw
    if not partidos_completos.empty:
        chart(_timeline_chart(partidos_completos))
    else:
        st.markdown(f"""
        <div style="background:{AZUL_MEDIO};border-radius:8px;padding:16px 20px;
                    border-left:4px solid {DORADO};color:{GRIS_MEDIO};font-size:0.85rem;">
            ℹ️ El gráfico de diferencia requiere los goles en contra de cada partido.
            Añádelos en <code>data/partidos.csv</code> o asegúrate de que el
            tagging en Hudl incluye los goles del rival.
        </div>""", unsafe_allow_html=True)


# ── Página: Partido ───────────────────────────────────────────────────────────
def page_partido(df: pd.DataFrame):
    st.markdown(f"<h2 style='color:{BLANCO};margin-bottom:4px;'>🎮 Partido</h2>",
                unsafe_allow_html=True)

    rivales   = df[df["nivel"] == "temporada"]["rival"].unique().tolist()
    rival_sel = st.selectbox("", rivales, format_func=lambda r: f"CAdF vs {r}",
                             label_visibility="collapsed")

    pdata    = df[df["rival"] == rival_sel]
    temp_row = pdata[pdata["nivel"] == "temporada"].iloc[0]
    tramos   = pdata[pdata["nivel"] == "tramo"].set_index("tramo_raw").reindex(TRAMO_ORDER).reset_index()
    partes   = pdata[pdata["nivel"] == "parte"]

    gf       = int(temp_row.get("goles") or 0)
    gc_raw   = temp_row.get("goles_enc")
    gc_known = pd.notna(gc_raw)
    gc       = int(gc_raw) if gc_known else None
    gc_str   = str(gc) if gc_known else "N/D"
    if gc_known:
        res_color = VERDE if gf > gc else (ROJO if gf < gc else DORADO)
        res_text  = "Victoria" if gf > gc else ("Derrota" if gf < gc else "Empate")
    else:
        res_color = AZUL_CLARO
        res_text  = "Resultado parcial"

    # ── Banner resultado ──
    st.markdown(f"""
    <div style="background:{AZUL_MEDIO};border-radius:12px;padding:20px 28px;
                margin-bottom:20px;border-left:6px solid {res_color};
                display:flex;align-items:center;gap:32px;">
        <div>
            <div style="color:{GRIS_MEDIO};font-size:0.7rem;text-transform:uppercase;
                        letter-spacing:0.1em;">Resultado</div>
            <div style="color:{BLANCO};font-size:3rem;font-weight:800;line-height:1.1;">
                {gf} <span style="color:{GRIS_MEDIO};font-size:1.5rem;">–</span> {gc_str}
            </div>
            <div style="color:{res_color};font-size:0.85rem;font-weight:600;">{res_text}</div>
        </div>
        <div style="display:flex;gap:20px;">
            <div style="text-align:center;">
                <div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;">Posesión</div>
                <div style="color:{AZUL_CELESTE};font-size:1.5rem;font-weight:700;">
                    {temp_row.get('pct_posesion') or 0:.1f}%</div>
            </div>
            <div style="text-align:center;">
                <div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;">Pases %</div>
                <div style="color:{DORADO};font-size:1.5rem;font-weight:700;">
                    {temp_row.get('pct_pases') or 0:.0f}%</div>
            </div>
            <div style="text-align:center;">
                <div style="color:{GRIS_MEDIO};font-size:0.65rem;text-transform:uppercase;">Tiros puerta</div>
                <div style="color:{BLANCO};font-size:1.5rem;font-weight:700;">
                    {int(temp_row.get('tiros_puerta') or 0)}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Línea de vida del partido ──
    section("Línea de vida — control del partido por tramo")

    fig_vida = go.Figure()

    # Gradiente de fondo: zona de dominio
    fig_vida.add_hrect(y0=50, y1=100, fillcolor="rgba(106,175,230,0.04)", line_width=0)
    fig_vida.add_hrect(y0=0,  y1=50,  fillcolor="rgba(232,93,117,0.04)",  line_width=0)
    fig_vida.add_hline(y=50, line_dash="dot",
                       line_color="rgba(200,214,229,0.35)", line_width=1.5,
                       annotation_text="50%", annotation_font=dict(color=GRIS_MEDIO, size=9))

    pos_vals  = tramos["pct_posesion"].tolist()
    pas_vals  = tramos["pct_pases"].tolist()
    tramo_labels = tramos["tramo_raw"].tolist()

    # Área de posesión con gradiente
    fig_vida.add_trace(go.Scatter(
        x=tramo_labels, y=pos_vals,
        name="Posesión %", mode="lines+markers",
        line=dict(color=AZUL_CELESTE, width=3.5, shape="spline"),
        marker=dict(size=12, color=AZUL_CELESTE,
                    line=dict(color=BLANCO, width=2.5)),
        fill="tozeroy",
        fillcolor="rgba(106,175,230,0.15)",
        hovertemplate="Tramo %{x}<br>Posesión: <b>%{y:.1f}%</b><extra></extra>",
    ))
    fig_vida.add_trace(go.Scatter(
        x=tramo_labels, y=pas_vals,
        name="Precisión pases %", mode="lines+markers",
        line=dict(color=DORADO, width=2.5, dash="dash", shape="spline"),
        marker=dict(size=9, color=DORADO),
        hovertemplate="Tramo %{x}<br>Pases: <b>%{y:.1f}%</b><extra></extra>",
    ))

    # Anotar goles a favor (⚽ arriba) y en contra (🔴 abajo) por tramo
    for _, trow in tramos.iterrows():
        if pd.notna(trow.get("goles")) and trow["goles"] > 0:
            for _ in range(int(trow["goles"])):
                fig_vida.add_annotation(
                    x=trow["tramo_raw"], y=96,
                    text="⚽", showarrow=False, font=dict(size=18),
                )
        if pd.notna(trow.get("goles_enc")) and trow["goles_enc"] > 0:
            for _ in range(int(trow["goles_enc"])):
                fig_vida.add_annotation(
                    x=trow["tramo_raw"], y=6,
                    text="🔴", showarrow=False, font=dict(size=15),
                )

    # Etiquetas de posesión por tramo
    for i, (tramo, val) in enumerate(zip(tramo_labels, pos_vals)):
        if pd.notna(val):
            color = AZUL_CELESTE if val >= 50 else ROJO
            fig_vida.add_annotation(
                x=tramo, y=val,
                text=f"{val:.0f}%", showarrow=False,
                yshift=18, font=dict(color=color, size=9, family="Inter"),
            )

    fig_vida.update_layout(
        paper_bgcolor=AZUL_OSCURO, plot_bgcolor=PLOT_BG,
        height=400, margin=dict(t=20, b=40, l=40, r=20),
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLANCO),
                    orientation="h", y=1.08),
        yaxis=dict(range=[0, 110], ticksuffix="%",
                   gridcolor="rgba(200,214,229,0.08)",
                   tickfont=dict(color=BLANCO)),
        xaxis=dict(gridcolor="rgba(200,214,229,0.08)",
                   tickfont=dict(color=BLANCO, size=11)),
    )
    chart(fig_vida)

    # ── Comparativa 1ª vs 2ª mitad ──
    section("1ª vs 2ª Mitad")
    p1 = partes[partes["tramo_raw"] == "1º mitad"].iloc[0] if len(partes) >= 1 else {}
    p2 = partes[partes["tramo_raw"] == "2º mitad"].iloc[0] if len(partes) >= 2 else {}

    mets = {"Posesión %": "pct_posesion", "Pases %": "pct_pases",
            "Tiros": "tiros", "Centros": "centros", "Tiros puerta": "tiros_puerta"}
    labels = list(mets.keys())
    v1 = [p1.get(v) or 0 for v in mets.values()]
    v2 = [p2.get(v) or 0 for v in mets.values()]

    fig_m = go.Figure()
    fig_m.add_trace(go.Bar(name="1ª Mitad", x=labels, y=v1,
                           marker_color=AZUL_CELESTE,
                           text=[f"{v:.0f}" for v in v1],
                           textposition="outside", textfont=dict(color=BLANCO)))
    fig_m.add_trace(go.Bar(name="2ª Mitad", x=labels, y=v2,
                           marker_color=DORADO,
                           text=[f"{v:.0f}" for v in v2],
                           textposition="outside", textfont=dict(color=BLANCO)))
    t(fig_m, height=320, barmode="group", margin=dict(t=20, b=20, l=20, r=20))
    chart(fig_m)

    # ── Campograma de pases por tercio ──
    section("Mapa de pases por tercio del campo")

    tercios_data = [
        ("Zona defensiva\n(1er tercio)",  "def_intentados",  "def_completados",  "pct_pases_def"),
        ("Zona media\n(mitad campo)",      "mid_intentados",  "mid_completados",  "pct_pases_mid"),
        ("Zona de ataque\n(último tercio)","atq_intentados",  "atq_completados",  "pct_pases_atq"),
    ]

    fig_pitch = go.Figure()

    # Fondo del campo (verde oscuro)
    pitch_w, pitch_h = 105, 68
    fig_pitch.add_shape(type="rect", x0=0, y0=0, x1=pitch_w, y1=pitch_h,
                        fillcolor="#2D5A1B", line=dict(color="white", width=2))
    # Línea central
    fig_pitch.add_shape(type="line", x0=pitch_w/2, y0=0, x1=pitch_w/2, y1=pitch_h,
                        line=dict(color="white", width=1.5, dash="dot"))
    # Círculo central
    fig_pitch.add_shape(type="circle",
                        x0=pitch_w/2-9.15, y0=pitch_h/2-9.15,
                        x1=pitch_w/2+9.15, y1=pitch_h/2+9.15,
                        line=dict(color="white", width=1.5))
    # Áreas
    for x0, x1 in [(0, 16.5), (pitch_w-16.5, pitch_w)]:
        fig_pitch.add_shape(type="rect", x0=x0, y0=pitch_h/2-20.16,
                            x1=x1, y1=pitch_h/2+20.16,
                            fillcolor="rgba(0,0,0,0)", line=dict(color="white", width=1.5))

    # División en 3 tercios con overlay de datos
    zone_w = pitch_w / 3
    zone_colors = ["rgba(232,93,117,{a})", "rgba(201,168,76,{a})", "rgba(106,175,230,{a})"]

    for i, (zona, ip_col, pc_col, pct_col) in enumerate(tercios_data):
        intentados  = int(temp_row.get(ip_col) or 0)
        completados = int(temp_row.get(pc_col) or 0)
        perdidos    = intentados - completados
        pct         = temp_row.get(pct_col) or 0

        x0 = i * zone_w
        x1 = (i + 1) * zone_w
        cx = (x0 + x1) / 2

        # Intensidad por precisión
        alpha = 0.15 + (pct / 100) * 0.35
        color = zone_colors[i].format(a=round(alpha, 2))
        fig_pitch.add_shape(type="rect", x0=x0+1, y0=1, x1=x1-1, y1=pitch_h-1,
                            fillcolor=color, line=dict(color="rgba(255,255,255,0.15)", width=1))

        # Indicador de % (círculo central de zona)
        pct_color = VERDE if pct >= 80 else (DORADO if pct >= 70 else ROJO)
        r = 9
        fig_pitch.add_shape(type="circle",
                            x0=cx-r, y0=pitch_h/2-r, x1=cx+r, y1=pitch_h/2+r,
                            fillcolor=AZUL_OSCURO,
                            line=dict(color=pct_color, width=2.5))
        fig_pitch.add_annotation(x=cx, y=pitch_h/2, text=f"<b>{pct:.0f}%</b>",
                                  showarrow=False, font=dict(color=pct_color, size=14, family="Inter"))

        # Datos arriba de la zona
        zona_label = zona.replace("\n", "<br>")
        fig_pitch.add_annotation(x=cx, y=pitch_h - 5,
                                  text=f"<b>{zona_label}</b>",
                                  showarrow=False,
                                  font=dict(color="white", size=9, family="Inter"),
                                  align="center")
        # Datos abajo
        fig_pitch.add_annotation(
            x=cx, y=8,
            text=f"✅ {completados}   ❌ {perdidos}",
            showarrow=False, font=dict(color=BLANCO, size=11, family="Inter"),
        )

    fig_pitch.update_layout(
        paper_bgcolor=AZUL_OSCURO, plot_bgcolor=AZUL_OSCURO,
        height=380, margin=dict(t=10, b=10, l=10, r=10),
        xaxis=dict(range=[0, pitch_w], showgrid=False, zeroline=False,
                   showticklabels=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[0, pitch_h], showgrid=False, zeroline=False,
                   showticklabels=False),
        showlegend=False,
    )
    chart(fig_pitch)


# ── Página: Rivales ───────────────────────────────────────────────────────────
def page_rivales(df: pd.DataFrame):
    st.markdown(f"<h2 style='color:{BLANCO};margin-bottom:4px;'>⚔️ Rivales</h2>",
                unsafe_allow_html=True)

    temporada = df[df["nivel"] == "temporada"]
    rivales   = temporada["rival"].unique().tolist()
    rival_sel = st.selectbox("", rivales, format_func=lambda r: f"CAdF vs {r}",
                              label_visibility="collapsed")

    rival_df  = df[df["rival"] == rival_sel]
    temp_rows = rival_df[rival_df["nivel"] == "temporada"]
    tramos_df = rival_df[rival_df["nivel"] == "tramo"].copy()

    st.markdown(f"""
    <div style="background:{AZUL_MEDIO};border-radius:10px;padding:16px 20px;
                border-left:4px solid {DORADO};margin-bottom:20px;">
        <span style="color:{GRIS_MEDIO};font-size:0.72rem;text-transform:uppercase;">
            Enfrentamientos vs</span>
        <h3 style="color:{BLANCO};margin:4px 0 2px;">{rival_sel}</h3>
        <span style="color:{AZUL_CELESTE};font-size:0.85rem;">
            {len(temp_rows)} partido(s) en el histórico</span>
    </div>""", unsafe_allow_html=True)

    cols = st.columns(4)
    for col, (lbl, val, suf) in zip(cols, [
        ("Goles media",    f"{temp_rows['goles'].mean():.1f}",        ""),
        ("Posesión media", f"{temp_rows['pct_posesion'].mean():.1f}", "%"),
        ("Pases % media",  f"{temp_rows['pct_pases'].mean():.1f}",   "%"),
        ("Tiros puerta",   f"{temp_rows['tiros_puerta'].mean():.1f}", ""),
    ]):
        col.markdown(metric_card(lbl, val, suf), unsafe_allow_html=True)

    section("¿En qué momentos dominas y dónde pierdes el control?")
    tramos_mean = (
        tramos_df.groupby("tramo_raw")[["pct_posesion", "pct_pases"]]
        .mean().reindex(TRAMO_ORDER).reset_index()
    )

    fig_r = go.Figure()
    fig_r.add_hrect(y0=50, y1=100, fillcolor="rgba(106,175,230,0.05)", line_width=0)
    fig_r.add_hrect(y0=0,  y1=50,  fillcolor="rgba(232,93,117,0.05)",  line_width=0)
    fig_r.add_hline(y=50, line_dash="dot",
                    line_color="rgba(200,214,229,0.35)", line_width=1.5)

    fig_r.add_trace(go.Scatter(
        x=tramos_mean["tramo_raw"], y=tramos_mean["pct_posesion"],
        name="Posesión %", mode="lines+markers",
        line=dict(color=AZUL_CELESTE, width=3, shape="spline"),
        marker=dict(size=11, color=AZUL_CELESTE, line=dict(color=BLANCO, width=2)),
        fill="tozeroy", fillcolor="rgba(106,175,230,0.12)",
    ))
    fig_r.add_trace(go.Scatter(
        x=tramos_mean["tramo_raw"], y=tramos_mean["pct_pases"],
        name="Pases %", mode="lines+markers",
        line=dict(color=DORADO, width=2.5, dash="dash", shape="spline"),
        marker=dict(size=9, color=DORADO),
    ))

    for _, row in tramos_mean.iterrows():
        if pd.notna(row["pct_posesion"]) and row["pct_posesion"] < 45:
            fig_r.add_vrect(x0=row["tramo_raw"], x1=row["tramo_raw"],
                            fillcolor=ROJO, opacity=0.12, line_width=0)
            fig_r.add_annotation(x=row["tramo_raw"], y=22,
                                  text="⚠️", showarrow=False, font=dict(size=14))

    fig_r.update_layout(
        paper_bgcolor=AZUL_OSCURO, plot_bgcolor=PLOT_BG,
        height=400, margin=dict(t=20, b=40, l=40, r=20),
        font=dict(family="Inter, Arial, sans-serif", color=BLANCO),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=BLANCO),
                    orientation="h", y=1.08),
        yaxis=dict(range=[20, 110], ticksuffix="%",
                   gridcolor="rgba(200,214,229,0.08)",
                   tickfont=dict(color=BLANCO)),
        xaxis=dict(gridcolor="rgba(200,214,229,0.08)",
                   tickfont=dict(color=BLANCO, size=11)),
    )
    chart(fig_r)

    st.markdown(f"""
    <div style="background:{AZUL_MEDIO};border-radius:8px;padding:12px 16px;
                border-left:3px solid {ROJO};font-size:0.82rem;color:{GRIS_MEDIO};
                margin-top:12px;">
        ⚠️ Los tramos marcados en rojo son momentos donde históricamente perdéis
        el control ante <b style="color:{BLANCO}">{rival_sel}</b>.
        Útiles para preparar tácticamente el próximo encuentro.
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
        df = load_all()

    if df.empty:
        st.error("No se encontraron datos en /data")
        return

    page = render_sidebar()

    if   page == "Inicio":    page_inicio(df)
    elif page == "Temporada": page_temporada(df)
    elif page == "Partido":   page_partido(df)
    elif page == "Rivales":   page_rivales(df)


if __name__ == "__main__":
    main()
