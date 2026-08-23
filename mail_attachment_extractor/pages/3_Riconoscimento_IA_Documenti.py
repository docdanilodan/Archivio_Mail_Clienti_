# -*- coding: utf-8 -*-
from pathlib import Path
import sys

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from document_ai import render_document_ai

st.set_page_config(
    page_title="FinancePlus | Riconoscimento IA Documenti",
    page_icon="🤖",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {background:#f5f7fa}
    .block-container {padding-top:1.4rem;max-width:1500px}
    h1,h2,h3 {color:#12304A!important}
    .fp-page-head {
        background:linear-gradient(120deg,#0D2940,#173F5F);
        padding:22px 26px;
        border-radius:16px;
        border-bottom:4px solid #B88952;
        color:white;
        margin-bottom:18px;
    }
    .fp-page-head h1 {color:white!important;margin:0;font-size:30px}
    .fp-page-head p {margin:6px 0 0;color:#dfe8ef}
    </style>
    <div class="fp-page-head">
      <h1>🤖 Schermata 3 | Riconoscimento IA Documenti</h1>
      <p>Classificazione, analisi dettagliata, anteprima, rinomina intelligente e apprendimento dalle correzioni.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

render_document_ai()
