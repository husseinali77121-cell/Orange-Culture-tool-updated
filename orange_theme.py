# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════════════════
#  Orange Lab — Microbiology CDSS  ·  Modernist UI theme
#  Drop-in CSS skin for the existing Streamlit app (no layout changes needed).
#
#  USAGE — add TWO lines to orange_lab.py, right AFTER st.set_page_config(...):
#
#      from orange_theme import inject_theme
#      inject_theme()
#
#  You can then DELETE the old inline <style> st.markdown block in orange_lab.py
#  (the .app-card / .orange-badge one) — this file supersedes it.
#
#  Design language: Modernist — flat, ink-on-ground, single orange accent,
#  0px corner radius everywhere, strong 2px rules, Archivo type, flush-left.
# ═══════════════════════════════════════════════════════════════════════════

import streamlit as st

# ── Design tokens ───────────────────────────────────────────────────────────
INK        = "#201E1D"
GROUND     = "#F3F2F2"
SURFACE    = "#FFFFFF"
ORANGE     = "#E8590C"   # accent / primary
ORANGE_600 = "#C74A08"   # pressed
ORANGE_100 = "#FCE7D8"   # tint fill
DIVIDER    = "#201E1D"    # 2px rules use ink
LINE       = "#D6D2CE"    # hairline for inputs/tables
MUTED      = "#6E6A66"

# S / I / R clinical colors (kept accessible on white)
SIR_S_BG, SIR_S_FG = "#E3F1E6", "#1B5E20"
SIR_I_BG, SIR_I_FG = "#FBEFD6", "#8A5A00"
SIR_R_BG, SIR_R_FG = "#F7DEDA", "#9A2317"


def inject_theme() -> None:
    """Inject the Modernist / Orange Lab skin. Call once after set_page_config."""
    st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* ══ Globals ════════════════════════════════════════════════════════════ */
:root {{
  --ol-ink:{INK}; --ol-ground:{GROUND}; --ol-surface:{SURFACE};
  --ol-accent:{ORANGE}; --ol-accent-600:{ORANGE_600}; --ol-accent-100:{ORANGE_100};
  --ol-line:{LINE};
}}
html, body, .stApp, [class*="css"] {{
  font-family:'Archivo',system-ui,-apple-system,'Segoe UI',sans-serif !important;
}}
.stApp {{ background:{GROUND} !important; color:{INK} !important; }}

/* hide Streamlit chrome */
#MainMenu, footer, header[data-testid="stHeader"], .stActionButton {{ display:none !important; visibility:hidden !important; }}

/* kill rounded corners everywhere — Modernist is 0px radius */
.stApp * {{ border-radius:0 !important; }}

/* main content width + rhythm */
.block-container {{ padding-top:1.6rem !important; max-width:1180px; }}

/* ══ Headings — flush left, tight, Archivo ══════════════════════════════ */
h1, h2, h3, h4, h5 {{
  font-family:'Archivo',sans-serif !important; color:{INK} !important;
  font-weight:700 !important; letter-spacing:-.01em !important; text-align:left !important;
}}
h1 {{ font-size:2.0rem !important; font-weight:800 !important; }}
/* app title underline rule */
.stApp h1:first-of-type {{ border-bottom:2px solid {DIVIDER}; padding-bottom:.5rem; }}

/* ══ Sidebar — dark ink panel, orange active nav ═══════════════════════ */
[data-testid="stSidebar"] {{ background:{INK} !important; border-right:2px solid {INK}; }}
[data-testid="stSidebar"] * {{ color:#EDEBE9 !important; }}
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ color:#A7A29D !important; }}
/* radio nav → block items */
[data-testid="stSidebar"] [role="radiogroup"] {{ gap:2px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  display:flex; align-items:center; width:100%;
  padding:10px 12px !important; margin:0 !important;
  border-left:3px solid transparent; transition:background .12s,border-color .12s;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background:rgba(232,89,12,.16) !important; }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background:rgba(232,89,12,.22) !important; border-left-color:{ORANGE};
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ font-weight:700 !important; color:#fff !important; }}
[data-testid="stSidebar"] [role="radiogroup"] div[data-testid="stMarkdownContainer"] p {{ font-size:.95rem; }}
[data-testid="stSidebar"] [role="radiogroup"] input {{ accent-color:{ORANGE}; }}

/* ══ Buttons — flush-left labels, solid accent primary ═════════════════ */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  font-family:'Archivo',sans-serif !important; font-weight:600 !important;
  border:2px solid {INK} !important; border-radius:0 !important;
  justify-content:flex-start !important; text-align:left !important;
  padding:.5rem .9rem !important; box-shadow:none !important; transition:all .12s;
}}
/* secondary / default */
.stButton > button {{ background:{SURFACE} !important; color:{INK} !important; }}
.stButton > button:hover {{ background:{ORANGE_100} !important; border-color:{ORANGE} !important; color:{ORANGE_600} !important; }}
.stButton > button:active {{ background:{ORANGE} !important; color:#fff !important; }}
/* primary */
.stButton > button[kind="primary"], .stButton > button[data-testid="baseButton-primary"],
.stFormSubmitButton > button {{
  background:{ORANGE} !important; color:#fff !important; border-color:{ORANGE} !important;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover {{ background:{ORANGE_600} !important; border-color:{ORANGE_600} !important; }}
/* download */
.stDownloadButton > button {{ background:{INK} !important; color:#fff !important; border-color:{INK} !important; }}
.stDownloadButton > button:hover {{ background:{ORANGE} !important; border-color:{ORANGE} !important; }}

/* ══ Inputs — square, hairline, orange focus ═══════════════════════════ */
.stTextInput input, .stNumberInput input, .stDateInput input,
[data-baseweb="select"] > div, .stTextArea textarea {{
  border-radius:0 !important; border:1px solid {LINE} !important;
  background:{SURFACE} !important; color:{INK} !important; font-family:'Archivo',sans-serif !important;
}}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus,
[data-baseweb="select"] > div:focus-within {{
  border-color:{ORANGE} !important; box-shadow:0 0 0 2px {ORANGE_100} !important; outline:none !important;
}}
label, .stTextInput label, .stSelectbox label, .stNumberInput label, .stMultiSelect label {{
  font-weight:600 !important; color:{INK} !important; font-size:.86rem !important;
}}
/* multiselect / select tags → orange tint chips */
[data-baseweb="tag"] {{ background:{ORANGE_100} !important; color:{ORANGE_600} !important; border-radius:0 !important; }}

/* checkboxes / radios accent */
input[type="checkbox"], input[type="radio"] {{ accent-color:{ORANGE} !important; }}

/* ══ Metrics — bordered stat cells ═════════════════════════════════════ */
[data-testid="stMetric"] {{
  background:{SURFACE}; border:1px solid {LINE}; border-top:3px solid {ORANGE};
  padding:.7rem .9rem;
}}
[data-testid="stMetricLabel"] {{ color:{MUTED} !important; text-transform:uppercase; letter-spacing:.04em; font-size:.72rem !important; }}
[data-testid="stMetricValue"] {{ font-weight:800 !important; color:{INK} !important; }}

/* ══ Tabs — flush-left, orange underline on active ═════════════════════ */
.stTabs [data-baseweb="tab-list"] {{ gap:0; border-bottom:2px solid {DIVIDER}; }}
.stTabs [data-baseweb="tab"] {{
  border-radius:0 !important; padding:.55rem 1.1rem !important; font-weight:600 !important;
  color:{MUTED} !important; border-bottom:3px solid transparent !important; margin-bottom:-2px;
}}
.stTabs [aria-selected="true"] {{ color:{INK} !important; border-bottom-color:{ORANGE} !important; }}

/* ══ Expanders — square, ruled ═════════════════════════════════════════ */
[data-testid="stExpander"] {{ border:1px solid {LINE} !important; border-radius:0 !important; background:{SURFACE}; }}
[data-testid="stExpander"] summary {{ font-weight:600 !important; }}
[data-testid="stExpander"] summary:hover {{ color:{ORANGE_600} !important; }}

/* ══ Alerts — left accent bar, no rounding ═════════════════════════════ */
.stAlert, [data-testid="stNotification"] {{ border-radius:0 !important; border-left:4px solid {INK}; }}
.stAlert p {{ color:{INK} !important; }}

/* ══ Tables / DataFrame — ruled header ═════════════════════════════════ */
[data-testid="stTable"] table, .stDataFrame {{ border:1px solid {LINE} !important; border-radius:0 !important; }}
[data-testid="stTable"] thead th, .stDataFrame thead th {{
  background:{INK} !important; color:#fff !important; font-weight:700 !important;
  text-align:left !important; border-radius:0 !important;
}}
[data-testid="stTable"] tbody tr:hover {{ background:{ORANGE_100}55 !important; }}

/* dividers → strong 2px */
hr, [data-testid="stDivider"] {{ border:none !important; border-top:2px solid {DIVIDER} !important; opacity:1 !important; }}

/* file uploader */
[data-testid="stFileUploaderDropzone"] {{ border:2px dashed {LINE} !important; border-radius:0 !important; background:{SURFACE} !important; }}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color:{ORANGE} !important; }}

/* focus-visible ring (keyboard) */
:focus-visible {{ outline:2px solid {ORANGE} !important; outline-offset:2px !important; }}
::selection {{ background:{ORANGE_100}; }}

/* ══ Helper classes for your st.markdown HTML blocks ═══════════════════ */
.ol-card {{ background:{SURFACE}; border:1px solid {LINE}; border-top:3px solid {ORANGE}; padding:14px 16px; margin-bottom:12px; }}
.ol-kicker {{ text-transform:uppercase; letter-spacing:.06em; font-size:.72rem; color:{MUTED}; font-weight:700; }}
.orange-badge {{ display:inline-block; background:{ORANGE}; color:#fff; padding:.15rem .6rem; font-size:.78rem; font-weight:700; }}
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
