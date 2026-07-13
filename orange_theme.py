# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════
#  Orange Lab — Microbiology CDSS  ·  "Light" UI theme  (minimal + fast)
#  Drop-in CSS skin. Deliberately LIGHTWEIGHT: a small set of scoped rules,
#  NO universal (`*`) selectors and NO gradients, so the browser never re-styles
#  the whole DOM on a Streamlit rerun (that was the cause of the sluggishness).
#
#  USAGE — after st.set_page_config(...):
#      from orange_theme import inject_theme
#      inject_theme()
#  Pair with .streamlit/config.toml (base="light" + matching colours).
# ═══════════════════════════════════════════════════════════════════════════

import streamlit as st

# ── Design tokens (clean light) ─────────────────────────────────────────────
INK      = "#1F2733"   # text
MUTED    = "#6B7280"   # secondary text
BG       = "#F6F7F9"   # app background (soft light)
SURFACE  = "#FFFFFF"   # cards / inputs / sidebar
LINE     = "#E3E6EA"   # hairline borders
ORANGE   = "#E8590C"   # accent / primary
ORANGE_600 = "#C74A08" # pressed
ORANGE_50  = "#FCEEE4" # tint fill

# S / I / R chips
SIR_S_BG, SIR_S_FG = "#E3F1E6", "#1B5E20"
SIR_I_BG, SIR_I_FG = "#FBEFD6", "#8A5A00"
SIR_R_BG, SIR_R_FG = "#F8DEDA", "#9A2317"


def inject_theme() -> None:
    """Inject the light, minimal Orange Lab skin. Call once after set_page_config."""
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap');
html, body, .stApp, [class*="css"] {{ font-family:'Archivo',system-ui,-apple-system,'Segoe UI',sans-serif; }}
.stApp {{ background:{BG}; color:{INK}; }}

/* hide Streamlit chrome */
#MainMenu, footer, header[data-testid="stHeader"], .stActionButton {{ display:none !important; }}
.block-container {{ padding-top:1.4rem; max-width:1180px; }}
a, a:visited {{ color:{ORANGE}; }}

/* headings */
h1, h2, h3, h4, h5 {{ color:{INK}; font-weight:700; letter-spacing:-.01em; }}
h1 {{ font-weight:800; }}
.stApp h1:first-of-type {{ border-bottom:2px solid {ORANGE}; padding-bottom:.4rem; }}

/* sidebar — light panel, orange active nav (buttons styled below) */
[data-testid="stSidebar"] {{ background:{SURFACE}; border-right:1px solid {LINE}; }}
.ol-nav-head {{ color:{ORANGE}; font-size:.68rem; font-weight:800; letter-spacing:.14em;
  text-transform:uppercase; margin:14px 2px 6px; }}
[data-testid="stSidebar"] .stButton > button {{
  width:100%; justify-content:flex-start; text-align:left; background:transparent;
  color:{INK}; border:1px solid transparent; border-left:3px solid transparent;
  border-radius:0; font-weight:600; padding:.5rem .7rem; box-shadow:none; }}
[data-testid="stSidebar"] .stButton > button:hover {{ background:{ORANGE_50}; border-left-color:{ORANGE}; }}
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button:disabled {{
  background:{ORANGE_50}; color:{ORANGE_600}; border-left:3px solid {ORANGE}; opacity:1;
  -webkit-text-fill-color:{ORANGE_600}; }}

/* progress breadcrumb */
.ol-crumbs {{ border:1px solid {LINE}; border-left:3px solid {ORANGE}; background:{SURFACE};
  padding:.5rem .8rem; margin-bottom:12px; font-size:.9rem; }}
.ol-crumb-active {{ color:{ORANGE}; font-weight:700; }}
.ol-crumb-done, .ol-crumb-todo {{ color:{MUTED}; }}

/* buttons (main area) */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  border-radius:0; border:1px solid {LINE}; font-weight:600; box-shadow:none;
  padding:.5rem .9rem; }}
.stButton > button {{ background:{SURFACE}; color:{INK}; }}
.stButton > button:hover {{ background:{ORANGE_50}; border-color:{ORANGE}; color:{ORANGE_600}; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button {{
  background:{ORANGE}; color:#fff; border-color:{ORANGE}; }}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover {{
  background:{ORANGE_600}; border-color:{ORANGE_600}; }}
.stDownloadButton > button {{ background:{ORANGE}; color:#fff; border-color:{ORANGE}; }}

/* inputs */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea,
[data-baseweb="select"] > div {{ border-radius:0; border:1px solid {LINE}; background:{SURFACE}; color:{INK}; }}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus,
[data-baseweb="select"] > div:focus-within {{ border-color:{ORANGE}; box-shadow:0 0 0 2px {ORANGE_50}; }}
[data-baseweb="tag"] {{ background:{ORANGE_50}; color:{ORANGE_600}; border-radius:0; }}
input[type="checkbox"], input[type="radio"] {{ accent-color:{ORANGE}; }}

/* metrics */
[data-testid="stMetric"] {{ background:{SURFACE}; border:1px solid {LINE}; border-top:3px solid {ORANGE}; padding:.7rem .9rem; }}
[data-testid="stMetricValue"] {{ font-weight:800; color:{ORANGE}; }}
[data-testid="stMetricLabel"] {{ color:{MUTED}; text-transform:uppercase; font-size:.72rem; }}

/* tabs / expanders / alerts — light touches */
.stTabs [aria-selected="true"] {{ color:{ORANGE}; border-bottom-color:{ORANGE} !important; }}
[data-testid="stExpander"] {{ border:1px solid {LINE}; border-radius:0; background:{SURFACE}; }}
.stAlert {{ border-radius:0; border-left:4px solid {ORANGE}; }}
hr, [data-testid="stDivider"] {{ border-top:1px solid {LINE} !important; opacity:1; }}

/* helper classes */
.ol-card {{ background:{SURFACE}; border:1px solid {LINE}; border-top:3px solid {ORANGE}; padding:14px 16px; margin-bottom:12px; }}
.orange-badge {{ display:inline-block; background:{ORANGE}; color:#fff; padding:.15rem .6rem; font-size:.78rem; font-weight:700; }}
.muted-text {{ color:{MUTED}; font-size:.92rem; }}
.sir-s {{ background:{SIR_S_BG}; color:{SIR_S_FG}; }}
.sir-i {{ background:{SIR_I_BG}; color:{SIR_I_FG}; }}
.sir-r {{ background:{SIR_R_BG}; color:{SIR_R_FG}; }}
.sir-s,.sir-i,.sir-r {{ display:inline-block; padding:.12rem .55rem; font-weight:800; font-size:.8rem; }}
</style>
""", unsafe_allow_html=True)


def sir_chip(value: str) -> str:
    """Return an HTML chip for an S/I/R value."""
    v = (value or "").strip().upper()[:1]
    cls = {"S": "sir-s", "I": "sir-i", "R": "sir-r"}.get(v, "muted-text")
    return f"<span class='{cls}'>{v or '—'}</span>"
