# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Proyecto

Dashboard de análisis de rendimiento para **Club Argentino (CAdF)** — temporada 2026-2027.
Desarrollado por Ramón Codesido · Sport Data Campus.

Stack: **Python + Streamlit + Plotly**. La app lee los datos de la temporada desde Google Drive.

---

## Comandos

```bash
# Entorno virtual (ya creado)
source venv/bin/activate

# Arrancar la app
venv/bin/streamlit run app.py --server.address 127.0.0.1

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
Drive / Partidos (CSV de HUDL)
    → data_loader.load_all()
    → DataFrame "largo": 1 fila por (partido × nivel × tramo)
    → app.py consume el df en cada página
```

### data_loader.py

- **`load_all()`** — lee, parsea y concatena los CSV de HUDL en la carpeta `Partidos` de Drive.
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
- **`page_header(title, subtitle, kicker, aside)`** — cabecera de página con degradado del club.
- **`section(title, subtitle)`** — cabecera de capítulo; el subtítulo dice qué pregunta responde el bloque.
- **`metric_card(label, value, suffix, delta, hint, accent)`** — tarjeta KPI; `delta=vs_ref(valor, media)` compara con la media de temporada.
- **`insight_panel(items, heading)`** — conclusiones automáticas `(tono, titular, texto)`; tonos `pos/neg/warn/info`.
- **`matches_table(df)`** — una fila por partido en orden cronológico (jornada, condición, resultado, puntos).
- **`season_insights` / `match_insights` / `rival_insights`** — reglas que convierten los datos en las conclusiones de cada página.
- Las clases CSS `cadf-*` (en `inject_css()`) definen todos estos componentes.
- **`_cell_color(val)`** — devuelve `(fillcolor, textcolor)` para el heatmap según % posesión.
- **`_timeline_chart(temporada_df)`** — gráfico combinado diferencia+acumulado de goles.

#### Navegación (session_state)

La navegación usa `st.session_state.page` + botones estilizados como cajitas. **No hay `st.radio`**. Los valores posibles son `"Inicio"`, `"Temporada"`, `"Partido"`, `"Rivales"`, `"Jugadores"`, `"Física"`.

#### Páginas

| Función | Contenido principal |
|---|---|
| `page_inicio(df, video_df)` | Cabecera con puntos y racha, KPIs, "La temporada en claves", puntos acumulados, goles por tramo, resultados |
| `page_temporada(df, video_df)` | Capítulos: 1 rendimiento (scorecard vs media + diferencia de goles), 2 control por tramos, 3 mitades, 4 ataque, 5 defensa y balón parado, 6 vídeo |
| `page_partido(df, video_df)` | Marcador, KPIs vs media, "Claves del partido", momentum, mitades, campograma, cadenas, defensa, vídeo |
| `page_rivales(df, video_df)` | Comparativa de rivales, perfil del rival (construcción y finalización según vídeo), claves para la vuelta, tramos de control |

---

## Datos — Hudl CSV format

**Estructura de cada CSV:**
```
Línea 1:  "CAdF vs RIVAL — Todos Atletas — Promedios"   ← título (extraemos rival)
Línea 2:  cabecera de columnas (con columnas "0" separadoras)
Línea 3+: datos (incluyendo filas de sección repetidas que se descartan)
```

**Datos federativos**. Los tres CSV de calendario, clasificación e historial se leen de `Calendario y clasificación` en Drive. Los PNG se leen de `Escudos`. Las copias locales de `data/` y `output/` se excluyen de Git.

**Publicación en Drive**. El botón de sincronización se habilita al arrancar en una dirección local con `RFFM_DRIVE_WRITE_ENABLED=1` en `.env`. Actualiza los tres CSV existentes con la cuenta de servicio del club.

**Añadir un partido nuevo:** subir el CSV de Hudl a la carpeta `Partidos` de la temporada en Drive.
- **Orden cronológico (`jornada`):** fecha del nombre del archivo si la lleva (`2026-09-06` o `06-09-2026`); si no, la fecha de subida a Drive. Subir los partidos en orden o incluir la fecha en el nombre.
- **Local/visitante (`condicion`):** `CAdF vs Rival` = local, `CAdF @ Rival` = visitante (título del CSV o nombre del archivo).
- La etiqueta de temporada se lee de la fila `"2026-2027 Season"`; no está escrita en el código.
- **Amistosos (`competicion`):** se detectan si el nombre del archivo contiene "Amistoso" o "Pretemporada", o si el rival está en `AMISTOSOS_CONOCIDOS` (data_loader.py, por temporada). Llevan `jornada = 0`, se excluyen de Inicio/Temporada/Rivales (`split_friendlies`) y solo se ven en Partido.
- **Vídeo LongoMatch ↔ partido HUDL (`align_video_rivals`):** al cargar, cada CSV de LongoMatch se asigna al partido de HUDL por nombre del rival: igual, prefijo (Fundacion ADF ↔ Fundacion ADF A) o siglas de HUDL (CGD ↔ CD Guadalix, RMB ↔ Rayo Majadahonda B), solo si hay un único candidato. Lo que no empareja aparece en el aviso "Estado del vídeo análisis" (Temporada). Los `.lgm` no se leen: hay que exportar a CSV.
- **Categorías y etiquetas LongoMatch (`video_loader.py`):** `INICIO 1T`/`INICIO 2T` son marcas de inicio de parte (fase `inicio_parte`, no cuentan como inicio de juego) y fijan los minutos exactos en `_tactical_with_periods`. `Asistencia` → fase `asistencia`. Columnas de etiquetas: `remate` (Remata/No remata), `destino_bp` (primer palo, segundo palo, punto de penalti), `zona_falta` (lateral, frontal, lejana, directa), `rol_transicion` (influencia, cooperación, vigilancia), `jugador` (columna Player). Si el CSV se llama como el de HUDL ("CAdF @ UDA - Todos Atletas - …"), el sufijo se elimina del nombre del rival.
- **Jugadores:** `jugador` = columna Player (quien da el pase/centro o ejecuta el balón parado); `rematador` = etiqueta con nombre y dorsal ("SOLDATI 20"). `_canonical_players` unifica por dorsal con el nombre más usado ("7-Lucas Appiolaza"); "Player N" se descarta. Página `page_jugadores` (solo partidos oficiales con jugador etiquetado).
- **Criterios del analista (nov. 2026):** Finalización = toda llegada al último tercio. En llegadas de tipo «Remate», Player es quien dispara (`rematador`), no hay pasador; en centro/pase filtrado Player = `pasador` y la etiqueta con nombre = `rematador` (solo si alguien remata). Generada = robo/pérdida provocada por presión o quite; No generada = error del rival / balón regalado. PTP = presión tras pérdida. Carriles del rival desde su punto de vista, salvo en transiciones defensivas (referencia CAdF). Balón parado: `ejecucion_bp` = Corto / Remate directo / Al área; solo «Al área» lleva destino. `tagging_review` lista lo que parece incompleto (expander en Temporada).
- **Remate inferido:** una finalización con tipo de llegada «Remate» sin etiqueta Remata/No remata se cuenta como «Remata» (`remate_inferido = True`). El bloque de calidad de finalización muestra siempre el total de llegadas (igual que el campograma) y cuántas faltan por etiquetar.
- **Bloques de vídeo nuevos:** `_finishing_quality_block` (% de llegadas con remate, por tipo y partido; conexiones pasador → rematador) y `_set_piece_block` (mapa de destino de córners y faltas a favor/en contra + zona de la falta), en las pestañas "Con balón" y "Balón parado" de Partido y Temporada.
- **Tipos de gol (`goal_sequence` / `_classify_goals`):** tramo según HUDL; orden dentro del mismo tramo según LongoMatch. Remontada = gol que pone por delante a quien iba perdiendo, siendo el último gol del partido.

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
- La página activa del menú es un `st.button(type="primary")`; su estilo está en `section[data-testid="stSidebar"] button[kind="primary"]`. La barra fija `.cadf-topbar` (en `main()`) indica siempre la página actual.
- Los gráficos usan `PLOT_BG` (más claro) para el área de datos y `PAPER_BG` para el fondo, creando efecto de profundidad

---

## Deploy

- **Repo:** https://github.com/M0ntx1nh0/argentinos
- **Deploy:** Streamlit Cloud — auto-despliega en cada `git push` a `main`
- **Entrypoint:** `app.py`
- **requirements.txt:** solo 4 dependencias (streamlit, plotly, pandas, Pillow)
