# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Proyecto

Dashboard de análisis de rendimiento para **Club Argentino (CAdF)** — temporada 2025-2026.
Desarrollado por Ramón Codesido · Sport Data Campus.

Stack: **Python + Streamlit + Plotly**. Sin base de datos — los datos viven en CSVs de Hudl Titan en `data/`.

---

## Comandos

```bash
# Entorno virtual (ya creado)
source venv/bin/activate

# Arrancar la app
venv/bin/streamlit run app.py

# Verificar sintaxis sin arrancar
venv/bin/python -c "import py_compile; py_compile.compile('app.py', doraise=True)"

# Comprobar que data_loader lee bien los CSVs
venv/bin/python data_loader.py

# Subir cambios al repo (Streamlit Cloud se auto-despliega)
git add app.py data_loader.py && git commit -m "mensaje" && git push
```

---

## Arquitectura

### Flujo de datos

```
data/*.csv (Hudl Titan exports)
    → data_loader.load_all()
    → DataFrame "largo": 1 fila por (partido × nivel × tramo)
    → app.py consume el df en cada página
```

### data_loader.py

- **`load_all()`** — punto de entrada único. Lee todos los `.csv` de `data/`, los parsea y concatena.
- **`_parse_csv(filepath)`** — parsea un CSV individual. El formato Hudl tiene: título en línea 1, cabecera en línea 2, separadores de columna con nombre `"0"`, filas de sección repetidas ("Por Parte", "Por Minutos").
- **`_clean_value(val, col_interno)`** — normaliza valores: porcentajes → float, `mm:ss` → minutos decimales, coma decimal española → punto. **Importante:** `"0"` es `None` salvo en columnas de `ZERO_IS_VALID` (goles_enc, tiros, etc.), donde es un resultado real.

**Columna `nivel`** — cada fila tiene uno de tres valores:
- `"temporada"` → fila resumen del partido completo
- `"parte"` → 1ª mitad / 2ª mitad
- `"tramo"` → intervalos de 15' (0-15, 16-30, … 90+)

**Columnas clave del df:**

| Col interna | Hudl | Significado |
|---|---|---|
| `goles` | G | Goles CAdF |
| `goles_enc` | GE | Goles encajados (solo tagueado en AED) |
| `tiros` | S | Tiros totales |
| `tiros_puerta` | SOT | Tiros a puerta |
| `pct_posesion` | P% | % posesión |
| `pct_pases` | %PC | % precisión pases |
| `atq_intentados/completados/perdidos` | IP/PC/PI Atq | Pases último tercio |
| `mid_*` | IP/PC/PI Mitad | Pases mitad campo |
| `def_*` | IP/PC/PI Defensa | Pases primer tercio |
| `pct_pases_atq/mid/def` | %PC Atq/Mitad/Defensa | % precisión por tercio |

### app.py

#### Constantes globales (top of file)

```python
AZUL_OSCURO, AZUL_CELESTE, AZUL_MEDIO, AZUL_CLARO  # colores del club
DORADO, BLANCO, GRIS_MEDIO, VERDE, ROJO             # paleta
PLOT_BG  = "#253F6B"   # fondo área de datos (más claro que PAPER_BG)
PAPER_BG = "#1B2A4A"   # fondo general del gráfico
TRAMO_ORDER = ["0-15","16-30","31-45","45+","46-60","61-75","76-90","90+"]
```

#### Helpers

- **`t(fig, height, **extra)`** — aplica template a cualquier figura Plotly (bgcolor, grid, font). Usar siempre en lugar de `update_layout` manual para charts simples.
- **`chart(fig)`** — `st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})`. Usar siempre.
- **`section(title)`** — título de sección en dorado con estilo uniforme.
- **`metric_card(label, value, suffix)`** — tarjeta HTML con borde dorado.
- **`_cell_color(val)`** — devuelve `(fillcolor, textcolor)` para el heatmap según % posesión.
- **`_timeline_chart(temporada_df)`** — gráfico combinado diferencia+acumulado de goles.

#### Navegación (session_state)

La navegación usa `st.session_state.page` + botones estilizados como cajitas. **No hay `st.radio`**. Los valores posibles son `"Inicio"`, `"Temporada"`, `"Partido"`, `"Rivales"`.

#### Páginas

| Función | Contenido principal |
|---|---|
| `page_inicio(df)` | KPIs, balance V/E/D, tabla resultados, gráfico diferencia+acumulado, descripción secciones |
| `page_temporada(df)` | Heatmap posesión por tramo, 1ª vs 2ª mitad, posesión+pases, campograma temporada, tiros+eficacia, timeline diferencia |
| `page_partido(df)` | Banner resultado, match momentum, línea de vida, 1ª vs 2ª mitad, campograma partido (pitch+barras en `make_subplots`) |
| `page_rivales(df)` | Perfil rival, gráfico tramos de control |

---

## Datos — Hudl CSV format

**Estructura de cada CSV:**
```
Línea 1:  "CAdF vs RIVAL — Todos Atletas — Promedios"   ← título (extraemos rival)
Línea 2:  cabecera de columnas (con columnas "0" separadoras)
Línea 3+: datos (incluyendo filas de sección repetidas que se descartan)
```

**Partidos actuales** (`data/`):
- `CAdF vs AED` → 2-2 (GF=2, GE=2 en Hudl)
- `CAdF vs CSE` → 3-0 (GF=3, GE=0 en Hudl)
- `CAdF vs RFC` → 2-0 (GF=2, GE=0 en Hudl)

**Añadir un partido nuevo:** copiar el CSV de Hudl en `data/` y hacer `git push`. Sin más cambios.

**Lo que Hudl NO exporta:** fechas de partido, datos del rival, coordenadas de eventos (sin shot maps ni pass networks).

---

## Campograma (pitch visualization)

El campograma en `page_partido` usa **`make_subplots(rows=2)`** con eje X compartido (0-105, coordenadas del campo):
- Row 1 (62%): campo con shapes (`layer="below"`) + burbujas como `go.Scatter` (siempre encima)
- Row 2 (38%): barras apiladas completados/perdidos alineadas con las zonas del campo

Las burbujas usan `marker.sizemode="diameter"` en píxeles para ser siempre circulares.

**Zonas del campo** — centros en coordenadas pitch (pitch_w=105):
- DEF: x=17.5, MED: x=52.5, ATQ: x=87.5

---

## CSS / Styling

El CSS se inyecta en `inject_css()`. Lo más relevante:
- `.stPlotlyChart` tiene `box-shadow` y `border-radius:14px` para profundidad
- `.nav-item-active / .nav-item-inactive` controlan el estilo de los botones de nav en el sidebar
- Los gráficos usan `PLOT_BG` (más claro) para el área de datos y `PAPER_BG` para el fondo, creando efecto de profundidad

---

## Deploy

- **Repo:** https://github.com/M0ntx1nh0/argentinos
- **Deploy:** Streamlit Cloud — auto-despliega en cada `git push` a `main`
- **Entrypoint:** `app.py`
- **requirements.txt:** solo 4 dependencias (streamlit, plotly, pandas, Pillow)
