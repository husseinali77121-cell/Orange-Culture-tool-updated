# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════
#  Orange Lab — Microbiology CDSS  ·  "Cyber-Bio" UI theme  (DARK)
#  Drop-in CSS skin for the existing Streamlit app (no layout changes needed).
#
#  USAGE — add TWO lines to the main file, right AFTER st.set_page_config(...):
#
#      from orange_theme import inject_theme
#      inject_theme()
#
#  Pair with .streamlit/config.toml  (base="dark" + matching colours) so the
#  native widgets (dataframe, menus) are dark too.
#
#  Design language: deep-navy lab console, bio-luminescent cyan/green accent,
#  orange data highlights (metrics / resistance), hairline circuitry borders,
#  0px corners, Archivo type, flush-left.
# ═══════════════════════════════════════════════════════════════════════════

import streamlit as st

# ── Cyber-Bio design tokens ─────────────────────────────────────────────────
BG         = "#0A1424"   # deep navy — app background
BG_DEEP    = "#060E1B"   # darkest — sidebar panel
SURFACE    = "#0F2138"   # cards / inputs / metrics
TEXT       = "#E7EEF8"   # primary text (near-white)
MUTED      = "#8A9BB6"   # secondary text
LINE       = "#22395C"   # borders / hairlines (navy circuitry)
LINE_SOFT  = "#1A2C48"

CYAN       = "#00E5A0"   # primary bio accent (mint-green)
CYAN_600   = "#00B884"   # pressed
CYAN_INK   = "#052A20"   # text on cyan buttons (dark)
CYAN_TINT  = "rgba(0,229,160,.14)"
CYAN_TINT2 = "rgba(0,229,160,.22)"

ORANGE     = "#FF7A1A"   # secondary accent — metrics / resistance
ORANGE_600 = "#E4620A"

# S / I / R clinical chips (tuned for dark)
SIR_S_BG, SIR_S_FG = "rgba(0,229,160,.16)", "#39E9B2"
SIR_I_BG, SIR_I_FG = "rgba(245,181,50,.16)", "#F5B532"
SIR_R_BG, SIR_R_FG = "rgba(255,96,86,.16)",  "#FF6B5E"


def inject_theme() -> None:
    """Inject the Cyber-Bio (dark) skin. Call once after set_page_config."""
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap');
/* ══ Globals ════════════════════════════════════════════════════════════ */
:root {{
  --ol-bg:{BG}; --ol-surface:{SURFACE}; --ol-text:{TEXT}; --ol-muted:{MUTED};
  --ol-accent:{CYAN}; --ol-accent-600:{CYAN_600}; --ol-accent-tint:{CYAN_TINT};
  --ol-orange:{ORANGE}; --ol-line:{LINE};
}}
html, body, .stApp, [class*="css"] {{
  font-family:'Archivo',system-ui,-apple-system,'Segoe UI',sans-serif !important;
}}
/* flat deep-navy background — no universal selectors / heavy gradients so the
   browser doesn't re-style the whole DOM on every Streamlit rerun (that was the
   cause of the freezing / sluggish AST interaction). */
.stApp {{ background:{BG} !important; color:{TEXT} !important; }}

/* hide Streamlit chrome */
#MainMenu, footer, header[data-testid="stHeader"], .stActionButton {{ display:none !important; visibility:hidden !important; }}

/* 0px corners — TARGETED at the components we actually style (NOT `.stApp *`,
   which forces a full-page style recalc on every rerun and freezes the app). */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button,
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea,
[data-baseweb="select"] > div, [data-baseweb="tag"], [data-baseweb="popover"],
[data-testid="stMetric"], [data-testid="stExpander"], .stAlert, [data-testid="stNotification"],
[data-testid="stTable"] table, .stDataFrame, [data-testid="stFileUploaderDropzone"],
.ol-card, .ol-crumbs, .orange-badge, .sir-s, .sir-i, .sir-r {{ border-radius:0 !important; }}

/* main content width + rhythm */
.block-container {{ padding-top:1.6rem !important; max-width:1180px; }}

/* links only — text colour itself comes from config.toml base="dark" + textColor,
   so we avoid broad `.stApp span/p` selectors that add per-rerun style cost. */
a, a:visited {{ color:{CYAN} !important; }}

/* ══ Headings — flush left, tight, Archivo ══════════════════════════════ */
h1, h2, h3, h4, h5 {{
  font-family:'Archivo',sans-serif !important; color:{TEXT} !important;
  font-weight:700 !important; letter-spacing:-.01em !important; text-align:left !important;
}}
h1 {{ font-size:2.0rem !important; font-weight:800 !important; }}
/* app title underline — bio-accent rule */
.stApp h1:first-of-type {{ border-bottom:2px solid {CYAN}; padding-bottom:.5rem; }}
.stApp h2, .stApp h3 {{ border-left:3px solid {CYAN}; padding-left:.55rem; }}

/* ══ Sidebar — darkest navy console, cyan active nav ═══════════════════ */
[data-testid="stSidebar"] {{ background:{BG_DEEP} !important; border-right:1px solid {LINE}; }}
[data-testid="stSidebar"] * {{ color:{TEXT}; }}
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ color:{MUTED} !important; }}
/* nav section header */
.ol-nav-head {{
  color:{CYAN}; font-size:.68rem; font-weight:800; letter-spacing:.16em;
  text-transform:uppercase; margin:14px 2px 6px; opacity:.9;
}}
/* nav buttons in the sidebar (WORKFLOW / DATABASE items) */
[data-testid="stSidebar"] .stButton > button {{
  width:100%; justify-content:flex-start !important; text-align:left !important;
  background:transparent !important; color:{TEXT} !important;
  border:1px solid transparent !important; border-left:3px solid transparent !important;
  font-weight:600 !important; padding:.5rem .7rem !important; box-shadow:none !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
  background:{CYAN_TINT} !important; border-left-color:{CYAN} !important; color:#fff !important;
}}
/* active nav item = Streamlit "primary" (disabled) */
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button:disabled {{
  background:{CYAN_TINT2} !important; color:#fff !important;
  border-left:3px solid {CYAN} !important; opacity:1 !important; -webkit-text-fill-color:#fff !important;
}}

/* ══ Progress breadcrumb (main area) ══════════════════════════════════ */
.ol-crumbs {{
  border:1px solid {LINE}; border-left:3px solid {CYAN}; background:{SURFACE};
  padding:.5rem .8rem; margin-bottom:12px; font-size:.9rem;
}}
.ol-crumb-active {{ color:{CYAN} !important; }}
.ol-crumb-done   {{ color:{MUTED} !important; }}
.ol-crumb-todo   {{ color:{MUTED} !important; opacity:.6; }}

/* ══ Buttons — flush-left, cyan primary ════════════════════════════════ */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  font-family:'Archivo',sans-serif !important; font-weight:600 !important;
  border:1px solid {LINE} !important; justify-content:flex-start !important;
  text-align:left !important; padding:.5rem .9rem !important; box-shadow:none !important;
  transition:all .12s;
}}
/* secondary / default (main area) */
.stButton > button {{ background:{SURFACE} !important; color:{TEXT} !important; }}
.stButton > button:hover {{ background:{CYAN_TINT} !important; border-color:{CYAN} !important; color:#fff !important; }}
.stButton > button:active {{ background:{CYAN} !important; color:{CYAN_INK} !important; }}
/* primary (main area) */
.stButton > button[kind="primary"], .stButton > button[data-testid="baseButton-primary"],
.stFormSubmitButton > button {{
  background:{CYAN} !important; color:{CYAN_INK} !important; border-color:{CYAN} !important; font-weight:700 !important;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover {{ background:{CYAN_600} !important; border-color:{CYAN_600} !important; }}
/* download → orange data action */
.stDownloadButton > button {{ background:{ORANGE} !important; color:#241000 !important; border-color:{ORANGE} !important; font-weight:700 !important; }}
.stDownloadButton > button:hover {{ background:{ORANGE_600} !important; border-color:{ORANGE_600} !important; }}

/* ══ Inputs — square, navy, cyan focus ═════════════════════════════════ */
.stTextInput input, .stNumberInput input, .stDateInput input,
[data-baseweb="select"] > div, .stTextArea textarea {{
  border:1px solid {LINE} !important; background:{SURFACE} !important;
  color:{TEXT} !important; font-family:'Archivo',sans-serif !important;
}}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {{ color:{MUTED} !important; }}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus,
[data-baseweb="select"] > div:focus-within {{
  border-color:{CYAN} !important; box-shadow:0 0 0 2px {CYAN_TINT} !important; outline:none !important;
}}
label, .stTextInput label, .stSelectbox label, .stNumberInput label, .stMultiSelect label,
.stRadio label, .stCheckbox label, .stDateInput label, .stTextArea label {{
  font-weight:600 !important; color:{TEXT} !important; font-size:.86rem !important;
}}
/* dropdown / popover menus → dark */
[data-baseweb="popover"], [data-baseweb="menu"], ul[role="listbox"], [role="listbox"] {{
  background:{SURFACE} !important; border:1px solid {LINE} !important;
}}
[role="option"] {{ color:{TEXT} !important; background:transparent !important; }}
[role="option"]:hover, [role="option"][aria-selected="true"] {{ background:{CYAN_TINT} !important; color:#fff !important; }}
/* multiselect / select tags → cyan chips */
[data-baseweb="tag"] {{ background:{CYAN_TINT2} !important; color:{CYAN} !important; }}
[data-baseweb="tag"] span {{ color:{CYAN} !important; }}
/* checkboxes / radios accent */
input[type="checkbox"], input[type="radio"] {{ accent-color:{CYAN} !important; }}

/* ══ Metrics — orange data cells ═══════════════════════════════════════ */
[data-testid="stMetric"] {{
  background:{SURFACE}; border:1px solid {LINE}; border-top:3px solid {ORANGE};
  padding:.7rem .9rem;
}}
[data-testid="stMetricLabel"] {{ color:{MUTED} !important; text-transform:uppercase; letter-spacing:.04em; font-size:.72rem !important; }}
[data-testid="stMetricValue"] {{ font-weight:800 !important; color:{ORANGE} !important; }}
[data-testid="stMetricDelta"] {{ color:{CYAN} !important; }}

/* ══ Tabs — cyan underline on active ═══════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {{ gap:0; border-bottom:1px solid {LINE}; }}
.stTabs [data-baseweb="tab"] {{
  padding:.55rem 1.1rem !important; font-weight:600 !important; color:{MUTED} !important;
  border-bottom:3px solid transparent !important; margin-bottom:-1px;
}}
.stTabs [aria-selected="true"] {{ color:{TEXT} !important; border-bottom-color:{CYAN} !important; }}

/* ══ Expanders — navy, ruled ═══════════════════════════════════════════ */
[data-testid="stExpander"] {{ border:1px solid {LINE} !important; background:{SURFACE}; }}
[data-testid="stExpander"] summary {{ font-weight:600 !important; color:{TEXT} !important; }}
[data-testid="stExpander"] summary:hover {{ color:{CYAN} !important; }}
[data-testid="stExpander"] svg {{ fill:{CYAN} !important; }}

/* ══ Alerts — left accent bar ══════════════════════════════════════════ */
.stAlert, [data-testid="stNotification"] {{ background:{SURFACE} !important; border-left:4px solid {CYAN}; }}
.stAlert p, [data-testid="stNotification"] p {{ color:{TEXT} !important; }}

/* ══ Tables / DataFrame — ruled, dark header ═══════════════════════════ */
[data-testid="stTable"] table, .stDataFrame {{ border:1px solid {LINE} !important; }}
[data-testid="stTable"] thead th, .stDataFrame thead th {{
  background:{BG_DEEP} !important; color:{CYAN} !important; font-weight:700 !important; text-align:left !important;
}}
[data-testid="stTable"] tbody td {{ color:{TEXT} !important; border-color:{LINE_SOFT} !important; }}
[data-testid="stTable"] tbody tr:hover {{ background:{CYAN_TINT} !important; }}

/* dividers → circuitry line */
hr, [data-testid="stDivider"] {{ border:none !important; border-top:1px solid {LINE} !important; opacity:1 !important; }}

/* file uploader */
[data-testid="stFileUploaderDropzone"] {{ border:2px dashed {LINE} !important; background:{SURFACE} !important; }}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color:{CYAN} !important; }}
[data-testid="stFileUploaderDropzone"] * {{ color:{MUTED} !important; }}

/* progress / spinner accents */
.stProgress > div > div > div {{ background:{CYAN} !important; }}

/* focus ring + selection */
:focus-visible {{ outline:2px solid {CYAN} !important; outline-offset:2px !important; }}
::selection {{ background:{CYAN_TINT2}; color:#fff; }}

/* ══ Helper classes for st.markdown HTML blocks ════════════════════════ */
.ol-card {{ background:{SURFACE}; border:1px solid {LINE}; border-top:3px solid {CYAN}; padding:14px 16px; margin-bottom:12px; }}
.ol-kicker {{ text-transform:uppercase; letter-spacing:.06em; font-size:.72rem; color:{MUTED}; font-weight:700; }}
.orange-badge {{ display:inline-block; background:{ORANGE}; color:#241000; padding:.15rem .6rem; font-size:.78rem; font-weight:700; }}
.muted-text {{ color:{MUTED}; font-size:.92rem; }}
/* S / I / R chips — use in your AST HTML */
.sir-s {{ background:{SIR_S_BG}; color:{SIR_S_FG}; }}
.sir-i {{ background:{SIR_I_BG}; color:{SIR_I_FG}; }}
.sir-r {{ background:{SIR_R_BG}; color:{SIR_R_FG}; }}
.sir-s,.sir-i,.sir-r {{ display:inline-block; padding:.12rem .55rem; font-weight:800; font-size:.8rem; }}
</style>
""", unsafe_allow_html=True)


def sir_chip(value: str) -> str:
    """Return an HTML chip for an S/I/R value — use inside st.markdown(...,unsafe_allow_html=True)."""
    v = (value or "").strip().upper()[:1]
    cls = {"S": "sir-s", "I": "sir-i", "R": "sir-r"}.get(v, "muted-text")
    return f"<span class='{cls}'>{v or '—'}</span>"
