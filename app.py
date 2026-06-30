import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_SENDERS = [
    "elibetty731@gmail.com",
    "Valentinaboratto82@gmail.com",
    "stefano.faraone@eurofintechsrl.it",
    "praticheBS@proton.me",
    "sergio.pedolazzi@katudi.it",
    "paolo.baldinelli@katudi.it",
    "pratiche@katudi.it",
    "niccolo.sovico@ener2crowd.com",
]
DEFAULT_ROOT = "ALLEGATI_MAIL_01-05-2026_30-06-2026"
OUTPUT_DIR = Path("output")
TOKEN_FILE = Path("token.json")
CLIENT_SECRET_FILE = Path("client_secret.json")

st.set_page_config(page_title="Archivio Mail Clienti PRO", page_icon="📥", layout="wide")

CUSTOM_CSS = """
<style>
.main-title {font-size: 2.0rem; font-weight: 800; color: #0B3A66;}
.metric-card {background:#fff; border:1px solid #e5e7eb; padding:18px; border-radius:16px; box-shadow:0 2px 10px rgba(0,0,0,.04);} 
.small-muted {color:#6b7280; font-size:.9rem;}
.ok-box {background:#ecfdf5; border:1px solid #10b981; padding:12px; border-radius:12px;}
.warn-box {background:#fffbeb; border:1px solid #f59e0b; padding:12px; border-radius:12px;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def save_uploaded_secret(uploaded_file) -> None:
    CLIENT_SECRET_FILE.write_bytes(uploaded_file.getvalue())


def get_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        if not CLIENT_SECRET_FILE.exists():
            raise FileNotFoundError("Carica prima il file client_secret.json")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_gmail_service():
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds)


def sanitize_folder_name(name: str, max_len: int = 90) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "-", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:max_len] if name else "Da_verificare")


def detect_company(text: str) -> str:
    text = re.sub(r"\s+", " ", text or " ")
    patterns = [
        r"([A-Z0-9À-Ù '&.\-]{2,80}\s+(?:SRL|S\.R\.L\.|SPA|S\.P\.A\.|SAS|SNC|SRLS|S\.R\.L\.S\.))",
        r"(?:azienda|cliente|pratica|documenti|bilancio|visura|societa|società)\s*[:\-]?\s*([A-Z0-9À-Ù '&.\-]{3,80})",
    ]
    upper_text = text.upper()
    for pat in patterns:
        match = re.search(pat, upper_text, flags=re.IGNORECASE)
        if match:
            return sanitize_folder_name(match.group(1).upper())
    return "Da_verificare"


def gmail_query(sender: str, start: date, end: date) -> str:
    # Gmail before: is exclusive; add one day to include the end date.
    end_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)
    return f'from:{sender} after:{start.strftime("%Y/%m/%d")} before:{end_exclusive.strftime("%Y/%m/%d")} has:attachment'


def list_message_ids(service, query: str, limit: int = 500) -> List[str]:
    ids = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=min(500, limit - len(ids))
        ).execute()
        ids.extend([m["id"] for m in resp.get("messages", [])])
        page_token = resp.get("nextPageToken")
        if not page_token or len(ids) >= limit:
            break
    return ids


def iter_parts(payload: Dict) -> Iterable[Dict]:
    if "parts" in payload:
        for part in payload["parts"]:
            yield from iter_parts(part)
    else:
        yield payload


def extract_plain_text(payload: Dict) -> str:
    texts = []
    for part in iter_parts(payload):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            try:
                texts.append(base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="ignore"))
            except Exception:
                pass
    return "\n".join(texts)


def get_header(headers: List[Dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def download_attachment(service, message_id: str, attachment_id: str) -> bytes:
    att = service.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()
    return base64.urlsafe_b64decode(att["data"].encode())


def attachment_parts(payload: Dict) -> Iterable[Dict]:
    for part in iter_parts(payload):
        filename = part.get("filename")
        body = part.get("body", {})
        if filename and body.get("attachmentId"):
            yield part


def zip_folder(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(folder.parent))
    buffer.seek(0)
    return buffer.read()


def archive_mail(start: date, end: date, senders: List[str], root_name: str, max_messages: int) -> Tuple[pd.DataFrame, Path, Dict[str, int]]:
    service = build_gmail_service()
    root = OUTPUT_DIR / sanitize_folder_name(root_name)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    seen_md5 = set()
    rows = []
    stats = {"messages": 0, "attachments_saved": 0, "duplicates_skipped": 0, "errors": 0}

    for sender in senders:
        sender_clean = sender.strip()
        if not sender_clean:
            continue
        q = gmail_query(sender_clean, start, end)
        msg_ids = list_message_ids(service, q, limit=max_messages)
        for msg_id in msg_ids:
            stats["messages"] += 1
            try:
                msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
                payload = msg.get("payload", {})
                headers = payload.get("headers", [])
                subject = get_header(headers, "Subject")
                msg_date = get_header(headers, "Date")
                body_text = extract_plain_text(payload)
                for part in attachment_parts(payload):
                    filename = sanitize_folder_name(part.get("filename", "allegato"), max_len=140)
                    raw = download_attachment(service, msg_id, part["body"]["attachmentId"])
                    md5 = hashlib.md5(raw).hexdigest()
                    company = detect_company(f"{subject} {body_text} {filename}")
                    target = root / sanitize_folder_name(sender_clean) / company
                    target.mkdir(parents=True, exist_ok=True)
                    file_path = target / filename

                    duplicate = md5 in seen_md5
                    if duplicate:
                        stats["duplicates_skipped"] += 1
                    else:
                        seen_md5.add(md5)
                        # Avoid filename collision inside the same folder.
                        if file_path.exists():
                            stem, suffix = file_path.stem, file_path.suffix
                            i = 2
                            while (target / f"{stem}_{i}{suffix}").exists():
                                i += 1
                            file_path = target / f"{stem}_{i}{suffix}"
                        file_path.write_bytes(raw)
                        stats["attachments_saved"] += 1

                    rows.append({
                        "data_email": msg_date,
                        "mittente": sender_clean,
                        "azienda": company,
                        "oggetto": subject,
                        "allegato": filename,
                        "md5": md5,
                        "duplicato": "SI" if duplicate else "NO",
                        "percorso": str(file_path.relative_to(root.parent)),
                    })
            except Exception as exc:
                stats["errors"] += 1
                rows.append({"data_email": "", "mittente": sender_clean, "azienda": "ERRORE", "oggetto": str(exc), "allegato": "", "md5": "", "duplicato": "", "percorso": ""})

    df = pd.DataFrame(rows)
    if not df.empty:
        report_path = root / "REPORT_ARCHIVIAZIONE.csv"
        df.to_csv(report_path, index=False, quoting=csv.QUOTE_ALL, encoding="utf-8-sig")
    return df, root, stats


st.markdown('<div class="main-title">📥 Archivio Mail Clienti PRO - GitHub + Streamlit</div>', unsafe_allow_html=True)
st.caption("Scarica allegati Gmail, crea cartelle per mittente e azienda, elimina duplicati e genera ZIP finale.")

with st.sidebar:
    st.header("Configurazione")
    secret = st.file_uploader("Carica client_secret.json", type=["json"])
    if secret is not None:
        save_uploaded_secret(secret)
        st.success("client_secret.json caricato")
    st.write("Stato credenziali:")
    st.write("✅ Token presente" if TOKEN_FILE.exists() else "⚠️ Token non ancora creato")
    if st.button("Reset token Google"):
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        st.warning("Token eliminato. Riesegui l'autorizzazione.")

col1, col2, col3 = st.columns(3)
with col1:
    start_date = st.date_input("Data inizio", value=date(2026, 5, 1), format="DD/MM/YYYY")
with col2:
    end_date = st.date_input("Data fine", value=date(2026, 6, 30), format="DD/MM/YYYY")
with col3:
    root_name = st.text_input("Cartella generale", value=DEFAULT_ROOT)

senders_text = st.text_area("Mittenti da elaborare", value="\n".join(DEFAULT_SENDERS), height=170)
max_messages = st.number_input("Limite messaggi per mittente", min_value=10, max_value=5000, value=500, step=50)
senders = [x.strip() for x in senders_text.splitlines() if x.strip()]

run = st.button("🚀 Scarica allegati e genera archivio", type="primary")

if run:
    if start_date > end_date:
        st.error("La data iniziale non puo essere successiva alla data finale.")
    else:
        with st.spinner("Elaborazione Gmail in corso..."):
            try:
                df, root_folder, stats = archive_mail(start_date, end_date, senders, root_name, int(max_messages))
                st.success("Archivio completato")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Email elaborate", stats["messages"])
                m2.metric("Allegati salvati", stats["attachments_saved"])
                m3.metric("Duplicati saltati", stats["duplicates_skipped"])
                m4.metric("Errori", stats["errors"])
                if not df.empty:
                    st.subheader("Report")
                    st.dataframe(df, use_container_width=True)
                zip_bytes = zip_folder(root_folder)
                st.download_button(
                    "⬇️ Scarica archivio ZIP sul PC",
                    data=zip_bytes,
                    file_name=f"{root_folder.name}.zip",
                    mime="application/zip",
                )
            except Exception as exc:
                st.error(f"Errore: {exc}")
                st.info("Controlla di avere caricato client_secret.json e abilitato Gmail API nel progetto Google Cloud.")
else:
    st.markdown("""
<div class="warn-box">
<b>Uso operativo:</b> carica <code>client_secret.json</code>, premi il pulsante blu, autorizza Gmail, poi scarica lo ZIP finale e salvalo sul Desktop del PC.
</div>
""", unsafe_allow_html=True)
