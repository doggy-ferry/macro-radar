"""Multi-Theme Engine for the Buy-Side Quant Portal (Streamlit + Plotly).

Three dark skins, one API:

    from ui_theme import inject_theme, apply_quant_theme, theme_selector

    THEME = theme_selector()          # optional sidebar selectbox, returns the theme name
    inject_theme(THEME)               # CSS for the whole page

    # in base_layout():
    return apply_quant_theme(fig, height, hovermode, THEME)

Public API
    THEME_NAMES                                   list[str]
    DEFAULT_THEME                                 str
    inject_theme(theme_name)                      -> None
    get_quant_plotly_theme(height, hovermode, theme_name) -> dict
    apply_quant_theme(fig, height, hovermode, theme_name) -> go.Figure
    theme_selector(label, key, container)         -> str
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

BLOOMBERG = "Bloomberg Pro (买方经典)"
CYBERPUNK = "Cyberpunk 2077 (赛博朋克)"
MATRIX = "Matrix Green (黑客终端)"
DEFAULT_THEME = BLOOMBERG

_SANS = "Inter, 'Segoe UI', system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif"
_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, 'Courier New', monospace"
_FONTS_STD = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
              "&family=JetBrains+Mono:wght@400;500;600;700&display=swap")
_FONTS_CYBER = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
                "&family=JetBrains+Mono:wght@400;500;600;700&family=Orbitron:wght@600;700;800&display=swap")

# ── Theme token tables ───────────────────────────────────────────────────────
THEMES: dict[str, dict] = {
    BLOOMBERG: {
        "key": "bloomberg",
        "fonts_url": _FONTS_STD,
        "sans": _SANS, "mono": _MONO, "title_font": _SANS,
        "bg": "#0a0d14", "sidebar_bg": "#080b11", "header_bg": "rgba(10,13,20,.85)",
        "surface": "#131722", "surface2": "#0f131c", "thead_bg": "#0c1018",
        "card_bg": "linear-gradient(160deg,#151b29 0%,#131722 55%,#0f131c 100%)",
        "border": "#1f2937", "border_hi": "#2b3a52",
        "grid": "#1e2433", "axis_line": "#273246",
        "text": "#e5e7eb", "dim": "#8b97ab", "mute": "#5b677a",
        "value": "#f3f7fd", "value_shadow": "0 0 18px rgba(56,189,248,.18)",
        "accent": "#38bdf8", "accent_soft": "rgba(56,189,248,.10)", "accent_glow": "rgba(56,189,248,.35)",
        "up": "#26d6a0", "down": "#ff5874", "warn": "#f6c453",
        "card_border": "#1f2937",
        "card_shadow": "0 0 0 1px rgba(56,189,248,.025),0 6px 20px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.035)",
        "card_hover_border": "#2b3a52",
        "card_hover_shadow": "0 0 0 1px rgba(56,189,248,.10),0 0 22px rgba(56,189,248,.10),0 6px 20px rgba(0,0,0,.4)",
        "bar": "linear-gradient(180deg,#38bdf8,transparent)", "bar_opacity": ".55",
        "tab_bg": "linear-gradient(180deg,rgba(56,189,248,.10),rgba(56,189,248,.02))",
        "tab_glow": "0 0 10px rgba(56,189,248,.35),0 0 2px #38bdf8",
        "stripe": "rgba(255,255,255,.018)", "row_line": "rgba(31,41,55,.55)",
        "scroll": "rgba(139,151,171,.28)", "scroll_hi": "rgba(139,151,171,.5)",
        "btn_glow": "0 0 12px rgba(56,189,248,.15)",
        "title_shadow": "none", "title_spacing": ".14em",
        "colorway": ["#38bdf8", "#f0a13a", "#26d6a0", "#a78bfa", "#ff5874", "#f6c453", "#ff8f5a", "#8bcf74"],
        "spike": "#4b5b78", "hover_bg": "#0f1623", "hover_border": "#2b3a52", "hover_text": "#edf4ff",
        "plot_font": "#b8c5d6",
    },
    CYBERPUNK: {
        "key": "cyberpunk",
        "fonts_url": _FONTS_CYBER,
        "sans": _SANS, "mono": _MONO, "title_font": "Orbitron, " + _SANS,
        "bg": "#050811", "sidebar_bg": "#03050c", "header_bg": "rgba(5,8,17,.88)",
        "surface": "#0b0f19", "surface2": "#080b14", "thead_bg": "#0a0720",
        "card_bg": "linear-gradient(160deg,#0e1424 0%,#0b0f19 60%,#080b14 100%)",
        "border": "#16314a", "border_hi": "#00f0ff",
        "grid": "#1a103c", "axis_line": "#2a1a5e",
        "text": "#e6f4ff", "dim": "#8fb3d1", "mute": "#4f6b8a",
        "value": "#f4fdff", "value_shadow": "0 0 12px rgba(0,240,255,.55)",
        "accent": "#00f0ff", "accent_soft": "rgba(0,240,255,.10)", "accent_glow": "rgba(0,240,255,.75)",
        "up": "#00ffa3", "down": "#ff0055", "warn": "#fcee0a",
        "card_border": "#00f0ff",
        "card_shadow": "0 0 10px rgba(0,240,255,.25),inset 0 0 14px rgba(0,240,255,.04)",
        "card_hover_border": "#ff0055",
        "card_hover_shadow": "0 0 16px rgba(255,0,85,.45),inset 0 0 16px rgba(255,0,85,.06)",
        "bar": "linear-gradient(180deg,#00f0ff,#ff0055)", "bar_opacity": ".9",
        "tab_bg": "linear-gradient(180deg,rgba(0,240,255,.12),rgba(0,240,255,.01))",
        "tab_glow": "0 0 8px #00f0ff,0 0 18px rgba(0,240,255,.65),0 0 32px rgba(0,240,255,.35)",
        "stripe": "rgba(0,240,255,.03)", "row_line": "rgba(26,16,60,.9)",
        "scroll": "rgba(0,240,255,.35)", "scroll_hi": "rgba(255,0,85,.7)",
        "btn_glow": "0 0 14px rgba(0,240,255,.45)",
        "title_shadow": "0 0 14px rgba(0,240,255,.6)", "title_spacing": ".16em",
        "colorway": ["#00f0ff", "#ff0055", "#fcee0a", "#b026ff", "#00ffa3", "#ff7a00", "#5b8cff", "#ff5ec8"],
        "spike": "#ff0055", "hover_bg": "#0b0f19", "hover_border": "#00f0ff", "hover_text": "#e6faff",
        "plot_font": "#a9c8e4",
    },
    MATRIX: {
        "key": "matrix",
        "fonts_url": _FONTS_STD,
        "sans": _MONO, "mono": _MONO, "title_font": _MONO,
        "bg": "#000000", "sidebar_bg": "#000000", "header_bg": "rgba(0,0,0,.9)",
        "surface": "#060d08", "surface2": "#030804", "thead_bg": "#04100a",
        "card_bg": "linear-gradient(160deg,#08130b 0%,#060d08 60%,#030804 100%)",
        "border": "#00ff66", "border_hi": "#00ff66",
        "grid": "#0b2412", "axis_line": "#0f4a24",
        "text": "#00ff66", "dim": "#00cc44", "mute": "#08882f",
        "value": "#00ff66", "value_shadow": "0 0 10px rgba(0,255,102,.55)",
        "accent": "#00ff66", "accent_soft": "rgba(0,255,102,.10)", "accent_glow": "rgba(0,255,102,.65)",
        "up": "#00ff66", "down": "#ff4d4d", "warn": "#d6ff3a",
        "card_border": "rgba(0,255,102,.55)",
        "card_shadow": "0 0 8px rgba(0,255,102,.18),inset 0 0 12px rgba(0,255,102,.03)",
        "card_hover_border": "#00ff66",
        "card_hover_shadow": "0 0 16px rgba(0,255,102,.5),inset 0 0 14px rgba(0,255,102,.06)",
        "bar": "linear-gradient(180deg,#00ff66,transparent)", "bar_opacity": ".8",
        "tab_bg": "rgba(0,255,102,.10)",
        "tab_glow": "0 0 8px #00ff66,0 0 16px rgba(0,255,102,.5)",
        "stripe": "rgba(0,255,102,.035)", "row_line": "rgba(0,255,102,.14)",
        "scroll": "rgba(0,255,102,.32)", "scroll_hi": "rgba(0,255,102,.65)",
        "btn_glow": "0 0 12px rgba(0,255,102,.4)",
        "title_shadow": "0 0 10px rgba(0,255,102,.6)", "title_spacing": ".16em",
        "colorway": ["#00ff66", "#00cc44", "#7dffb0", "#00e0a0", "#33ff99", "#b6ffd0", "#66ff00", "#009933"],
        "spike": "#00cc44", "hover_bg": "#030804", "hover_border": "#00ff66", "hover_text": "#00ff66",
        "plot_font": "#00cc44",
    },
}
THEME_NAMES: list[str] = list(THEMES)


def _resolve(theme_name: str | None) -> tuple[str, dict]:
    """Return (canonical name, tokens); accept display names, short keys, or fall back to default."""
    if theme_name in THEMES:
        return theme_name, THEMES[theme_name]  # type: ignore[index]
    lowered = str(theme_name or "").lower()
    for name, tokens in THEMES.items():
        if lowered and (lowered == tokens["key"] or lowered in name.lower()):
            return name, tokens
    return DEFAULT_THEME, THEMES[DEFAULT_THEME]


# ── CSS (tokens are substituted for @@name@@ placeholders) ───────────────────
_CSS_TEMPLATE = """
<style>
@import url('@@fonts_url@@');

:root{
  --bg:@@bg@@; --surface:@@surface@@; --surface-2:@@surface2@@; --border:@@border@@; --border-hi:@@border_hi@@;
  --grid:@@grid@@; --text:@@text@@; --dim:@@dim@@; --mute:@@mute@@;
  --accent:@@accent@@; --accent-soft:@@accent_soft@@; --accent-glow:@@accent_glow@@;
  --up:@@up@@; --down:@@down@@; --warn:@@warn@@;
  --card-border:@@card_border@@; --card-shadow:@@card_shadow@@;
  --card-hover-border:@@card_hover_border@@; --card-hover-shadow:@@card_hover_shadow@@;
  --sans:@@sans@@; --mono:@@mono@@;
}

/* ── Base ─────────────────────────────────────────────── */
.stApp{background:var(--bg);color:var(--text);font-family:var(--sans);-webkit-font-smoothing:antialiased}
.stApp .block-container{max-width:1900px;padding:4.5rem 1.5rem 2rem}
.stApp [data-testid="stHeader"]{background:@@header_bg@@;backdrop-filter:blur(8px);border-bottom:1px solid var(--border)}
.stApp [data-testid="stSidebar"]{background:@@sidebar_bg@@;border-right:1px solid var(--border)}
.stApp h1,.stApp h2,.stApp h3,.stApp h4{font-family:var(--sans);letter-spacing:.02em;color:var(--text)}
.stApp [data-testid="stMarkdownContainer"] p,.stApp [data-testid="stMarkdownContainer"] li{color:var(--text)}
.stApp hr{border-color:var(--border)!important;margin:.8rem 0!important}
.stApp code,.stApp pre{font-family:var(--mono)!important}
.stApp [data-testid="stCaptionContainer"],.stApp [data-testid="stCaptionContainer"] p{color:var(--mute);font-size:.7rem;letter-spacing:.02em}

/* ── Metric cards ─────────────────────────────────────── */
.stApp [data-testid="stMetric"]{
  background:@@card_bg@@;
  border:1px solid var(--card-border);border-radius:6px;
  padding:.6rem .8rem .55rem;min-height:94px;position:relative;overflow:hidden;
  box-shadow:var(--card-shadow);transition:border-color .18s ease,box-shadow .18s ease;
}
.stApp [data-testid="stMetric"]::before{
  content:'';position:absolute;left:0;top:0;bottom:0;width:2px;
  background:@@bar@@;opacity:@@bar_opacity@@;
}
.stApp [data-testid="stMetric"]:hover{border-color:var(--card-hover-border);box-shadow:var(--card-hover-shadow)}
.stApp [data-testid="stMetricLabel"]{color:var(--dim);font:600 .66rem var(--sans);letter-spacing:.09em;text-transform:uppercase}
.stApp [data-testid="stMetricLabel"] p{font-size:.66rem!important;color:var(--dim)}
.stApp [data-testid="stMetricValue"]{
  color:@@value@@;font:600 1.5rem/1.15 var(--mono);letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;text-shadow:@@value_shadow@@;padding-top:.15rem;
}
.stApp [data-testid="stMetricDelta"]{font:500 .72rem var(--mono);font-variant-numeric:tabular-nums;margin-top:.1rem}

/* ── Tabs ─────────────────────────────────────────────── */
.stApp [data-testid="stTabs"] [data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid var(--border);background:transparent}
.stApp [data-testid="stTabs"] [data-baseweb="tab-border"]{background:transparent!important}
.stApp [data-testid="stTabs"] button[role="tab"]{
  font:600 .7rem var(--sans);letter-spacing:.07em;color:var(--mute);
  padding:.55rem 1rem;margin:0;background:transparent;
  border:1px solid transparent;border-bottom:none;border-radius:4px 4px 0 0;
  outline:none!important;box-shadow:none!important;transition:color .15s,background .15s;
}
.stApp [data-testid="stTabs"] button[role="tab"]:hover{color:var(--text);background:var(--accent-soft)}
.stApp [data-testid="stTabs"] button[role="tab"]:focus,
.stApp [data-testid="stTabs"] button[role="tab"]:focus-visible{outline:none!important;box-shadow:none!important}
.stApp [data-testid="stTabs"] button[role="tab"][aria-selected="true"]{
  color:var(--accent);background:@@tab_bg@@;border-color:var(--border);
}
.stApp [data-testid="stTabs"] button[role="tab"] p{font-size:.7rem!important;font-weight:600;color:inherit}
.stApp [data-testid="stTabs"] [data-baseweb="tab-highlight"]{
  background:var(--accent)!important;height:2px!important;box-shadow:@@tab_glow@@;
}

/* ── Tables / dataframes ──────────────────────────────── */
.stApp [data-testid="stDataFrame"],.stApp [data-testid="stTable"]{
  border:1px solid var(--card-border);border-radius:6px;overflow:hidden;background:var(--surface);
  box-shadow:var(--card-shadow);transition:border-color .18s ease,box-shadow .18s ease;
}
.stApp [data-testid="stDataFrame"]:hover,.stApp [data-testid="stTable"]:hover{
  border-color:var(--card-hover-border);box-shadow:var(--card-hover-shadow);
}
.stApp table{border-collapse:collapse;width:100%;font-family:var(--mono);font-size:.74rem;color:var(--text)}
.stApp table thead th{
  background:@@thead_bg@@;color:var(--dim);font:600 .64rem var(--sans);letter-spacing:.08em;text-transform:uppercase;
  padding:.38rem .6rem;border-bottom:1px solid var(--border);text-align:left;vertical-align:middle;
}
.stApp table tbody td{padding:.28rem .6rem;vertical-align:middle;border-bottom:1px solid @@row_line@@;font-variant-numeric:tabular-nums}
.stApp table tbody tr:nth-child(even){background:@@stripe@@}
.stApp table tbody tr:hover{background:var(--accent-soft)}
/* st.dataframe is canvas-rendered: CSS styles its frame only; set cell colors in .streamlit/config.toml [theme] */

/* ── Scrollbars ───────────────────────────────────────── */
*{scrollbar-width:thin;scrollbar-color:@@scroll@@ transparent}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:@@scroll@@;border-radius:6px}
::-webkit-scrollbar-thumb:hover{background:@@scroll_hi@@}
::-webkit-scrollbar-corner{background:transparent}

/* ── Inputs / buttons / expanders ─────────────────────── */
.stApp [data-baseweb="select"]>div,.stApp [data-baseweb="input"],.stApp [data-baseweb="base-input"],
.stApp .stNumberInput input,.stApp .stTextInput input{
  background:var(--surface)!important;border-color:var(--border)!important;border-radius:5px!important;
  font-family:var(--mono)!important;font-size:.8rem!important;color:var(--text)!important;
}
.stApp [data-baseweb="select"]>div:hover,.stApp [data-baseweb="input"]:hover{border-color:var(--border-hi)!important}
.stApp [data-baseweb="select"]>div:focus-within,.stApp [data-baseweb="input"]:focus-within{
  border-color:var(--accent)!important;box-shadow:0 0 0 1px var(--accent-soft),0 0 12px var(--accent-soft)!important;
}
/* dropdown menus are rendered in a body-level portal, outside .stApp */
[data-baseweb="popover"] [data-baseweb="menu"],[data-baseweb="popover"] ul{background:@@surface@@!important;border:1px solid @@border@@}
[data-baseweb="popover"] li,[data-baseweb="popover"] [role="option"]{
  background:transparent!important;color:@@text@@!important;font-family:@@mono@@;font-size:.78rem
}
[data-baseweb="popover"] li:hover,[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] [aria-selected="true"]{background:@@accent_soft@@!important;color:@@accent@@!important}
.stApp label,.stApp [data-testid="stWidgetLabel"] p{color:var(--dim)!important;font:600 .7rem var(--sans)!important;letter-spacing:.05em}
.stApp .stButton>button{
  background:var(--surface);border:1px solid var(--border);color:var(--text);border-radius:5px;
  font:600 .72rem var(--sans);letter-spacing:.05em;padding:.35rem .8rem;transition:all .15s;
}
.stApp .stButton>button:hover{border-color:var(--accent);color:var(--accent);box-shadow:@@btn_glow@@}
.stApp [data-testid="stExpander"]{
  border:1px solid var(--card-border);border-radius:6px;background:var(--surface-2);
  box-shadow:var(--card-shadow);transition:border-color .18s ease,box-shadow .18s ease;
}
.stApp [data-testid="stExpander"]:hover{border-color:var(--card-hover-border);box-shadow:var(--card-hover-shadow)}
.stApp [data-testid="stAlert"]{border-radius:5px;border:1px solid var(--border);font-size:.8rem}

/* ── Portal components (compatible with existing app.py markup) ── */
.stApp .portal-head{display:flex;align-items:flex-end;justify-content:space-between;border-bottom:1px solid var(--border);padding:.2rem 0 .8rem;margin-bottom:.7rem}
.stApp .portal-title{font:700 1.3rem @@title_font@@;letter-spacing:@@title_spacing@@;color:@@value@@;text-shadow:@@title_shadow@@}
.stApp .portal-sub{font:500 .62rem var(--mono);color:var(--mute);letter-spacing:.14em;margin-top:.3rem}
.stApp .live{font:600 .66rem var(--mono);color:var(--up);letter-spacing:.06em;text-align:right}
.stApp .live:before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--up);box-shadow:0 0 8px var(--up);margin-right:6px}
.stApp .market-clock{display:flex;flex-direction:column;align-items:center;gap:3px;font:600 .66rem var(--mono);letter-spacing:.07em}
.stApp .market-clock small{color:var(--mute);font-size:.6rem}
.stApp .deck-label{font:600 .6rem var(--mono);color:var(--mute);letter-spacing:.16em;text-transform:uppercase;margin:.25rem 0 .4rem}
.stApp .module{border-left:2px solid var(--accent);padding-left:.7rem;margin:.3rem 0 .5rem;box-shadow:-6px 0 12px -8px var(--accent-glow)}
.stApp .kicker{font:700 .58rem var(--mono);color:var(--accent);letter-spacing:.18em;text-transform:uppercase}
.stApp .module-title{font:600 .98rem var(--sans);color:var(--text);margin-top:.1rem}
.stApp .module-note{font:400 .68rem var(--sans);color:var(--dim);margin-top:.12rem}
.stApp .risk-lock{
  border:1px solid var(--down);background:linear-gradient(90deg,rgba(132,24,43,.28),rgba(51,11,20,.12));
  color:var(--down);padding:.6rem .9rem;border-radius:5px;font:600 .74rem var(--mono);margin:.25rem 0 .75rem;
  box-shadow:0 0 18px rgba(255,88,116,.12);
}
.stApp .continuation-panel{
  border:1px solid var(--card-border);background:@@card_bg@@;border-radius:6px;padding:.65rem .75rem;margin:.6rem 0 .8rem;
  box-shadow:var(--card-shadow);transition:border-color .18s ease,box-shadow .18s ease;
}
.stApp .continuation-panel:hover{border-color:var(--card-hover-border);box-shadow:var(--card-hover-shadow)}
.stApp .continuation-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.5rem}
.stApp .continuation-title{color:var(--accent);font:700 .64rem var(--mono);letter-spacing:.13em}
.stApp .continuation-meta{color:var(--dim);font:500 .62rem var(--mono)}
.stApp .continuation-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.45rem}
.stApp .continuation-item{border:1px solid var(--border);background:var(--surface-2);border-radius:5px;padding:.5rem .6rem;min-height:74px}
.stApp .continuation-label{color:var(--mute);font:600 .6rem var(--mono);letter-spacing:.06em}
.stApp .continuation-value{color:@@value@@;font:600 .82rem var(--mono);margin:.2rem 0 .1rem}
.stApp .continuation-note{color:var(--dim);font-size:.66rem;line-height:1.35}
.stApp .continuation-badge{display:inline-block;border-radius:3px;padding:.3rem .55rem;font:700 .7rem var(--mono)}
.stApp .continuation-gold{color:#ffd76a;border:1px solid #8d6b18;background:rgba(142,102,10,.20)}
.stApp .continuation-red{color:#ff7187;border:1px solid #7c2938;background:rgba(126,31,47,.20)}
.stApp .continuation-watch{color:#7fc8ff;border:1px solid #24577c;background:rgba(31,91,132,.18)}
@media(max-width:900px){.stApp .continuation-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
"""


def _build_css(tokens: dict) -> str:
    css = _CSS_TEMPLATE
    for key, value in tokens.items():
        css = css.replace(f"@@{key}@@", str(value))
    return css


# ── Plotly ───────────────────────────────────────────────────────────────────
def _axis(tokens: dict) -> dict:
    return dict(
        gridcolor=tokens["grid"], gridwidth=1, linecolor=tokens["axis_line"], zeroline=False,
        tickfont=dict(family=tokens["mono"], size=10, color=tokens["dim"]),
        title=dict(font=dict(family=tokens["sans"], size=11, color=tokens["dim"])),
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikedash="dot", spikecolor=tokens["spike"],
    )


def _layout(tokens: dict) -> dict:
    return dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=tokens["sans"], size=11, color=tokens["plot_font"]),
        colorway=list(tokens["colorway"]),
        xaxis=_axis(tokens), yaxis=_axis(tokens),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=10, family=tokens["sans"], color=tokens["dim"]),
                    bgcolor="rgba(0,0,0,0)", itemsizing="constant"),
        hoverlabel=dict(bgcolor=tokens["hover_bg"], bordercolor=tokens["hover_border"],
                        font=dict(family=tokens["mono"], size=11, color=tokens["hover_text"])),
        modebar=dict(bgcolor="rgba(0,0,0,0)", color=tokens["mute"], activecolor=tokens["accent"]),
    )


def _ensure_template(theme_name: str | None) -> tuple[str, dict]:
    """Register the Plotly template for a theme (idempotent) and return (template id, tokens)."""
    canonical, tokens = _resolve(theme_name)
    template_id = f"quant_{tokens['key']}"
    if template_id not in pio.templates:
        pio.templates[template_id] = go.layout.Template(layout=go.Layout(**_layout(tokens)))
    return template_id, tokens


def get_quant_plotly_theme(height: int | None = None, hovermode: str = "closest",
                           theme_name: str = DEFAULT_THEME) -> dict:
    """Layout dict for the chosen theme: fig.update_layout(**get_quant_plotly_theme(h, hm, name))."""
    template_id, tokens = _ensure_template(theme_name)
    theme = _layout(tokens)
    theme.update(template=template_id, margin=dict(l=48, r=18, t=34, b=42),
                 hovermode=hovermode, hoverdistance=30, spikedistance=-1)
    if height:
        theme["height"] = height
    return theme


def apply_quant_theme(fig: go.Figure, height: int | None = None, hovermode: str = "closest",
                      theme_name: str = DEFAULT_THEME) -> go.Figure:
    """Apply background, grid, crosshair, fonts and colorway of the chosen theme to a figure."""
    _, tokens = _ensure_template(theme_name)
    fig.update_layout(**get_quant_plotly_theme(height, hovermode, theme_name))
    axis = _axis(tokens)
    fig.update_xaxes(**axis)      # also reaches subplot axes (xaxis2, ...)
    fig.update_yaxes(**axis)
    return fig


# ── Streamlit entry points ───────────────────────────────────────────────────
def inject_theme(theme_name: str = DEFAULT_THEME) -> None:
    """Inject the full CSS of the chosen theme and make its Plotly template the default."""
    template_id, tokens = _ensure_template(theme_name)
    pio.templates.default = template_id
    st.markdown(_build_css(tokens), unsafe_allow_html=True)


def theme_selector(label: str = "🎨 视觉主题 · Theme", key: str = "ui_theme_name", container=None) -> str:
    """Selectbox (sidebar by default) that returns the active theme name; state persists in session_state."""
    host = container if container is not None else st.sidebar
    return host.selectbox(label, THEME_NAMES, index=THEME_NAMES.index(DEFAULT_THEME), key=key)
