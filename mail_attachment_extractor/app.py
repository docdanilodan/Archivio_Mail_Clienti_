# -*- coding: utf-8 -*-
from __future__ import annotations

import mailbox
import os
import re
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

import mail_attachment_extractor as core

PART_RE = re.compile(r"^(?P<base>.+)\.part(?P<num>\d{4,})$", re.IGNORECASE)
SUPPORTED = {".mbox", ".zip", ".eml", ".msg"}


def parse_part_name(name: str):
    m = PART_RE.match(Path(name).name)
    if not m:
        return None
    return m.group("base"), int(m.group("num"))


def validate_parts(uploaded_parts):
    parsed = []
    for f in uploaded_parts:
        info = parse_part_name(f.name)
        if not info:
            raise ValueError(f"Nome parte non valido: {f.name}. Formato atteso: nomefile.ext.part0001")
        base, num = info
        parsed.append((base, num, f))

    bases = {x[0] for x in parsed}
    if len(bases) != 1:
        raise ValueError("Le parti appartengono a file originali diversi. Seleziona le parti di un solo archivio alla volta.")

    parsed.sort(key=lambda x: x[1])
    nums = [x[1] for x in parsed]
    expected = list(range(nums[0], nums[0] + len(nums)))
    if nums != expected:
        missing = sorted(set(expected) - set(nums))
        raise ValueError(f"Sequenza parti non continua. Parti mancanti: {missing or 'verificare numerazione'}")
    if nums[0] != 1:
        raise ValueError("La prima parte deve essere .part0001")

    return parsed


def reconstruct_parts_to_disk(uploaded_parts, progress=None):
    parsed = validate_parts(uploaded_parts)
    original_name = parsed[0][0]
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Formato originale non supportato: {suffix}. Usa MBOX, ZIP, EML o MSG.")

    workdir = tempfile.mkdtemp(prefix="financeplus_parts_")
    out_path = Path(workdir) / Path(original_name).name

    total = len(parsed)
    with out_path.open("wb") as fout:
        for i, (_, _, uploaded) in enumerate(parsed, start=1):
            uploaded.seek(0)
            while True:
                block = uploaded.read(8 * 1024 * 1024)
                if not block:
                    break
                fout.write(block)
            if progress:
                progress.progress(i / total, text=f"Ricostruzione parte {i}/{total}")

    return out_path


def parse_mbox_path(path: Path):
    results = []
    box = mailbox.mbox(str(path), factory=None, create=False)
    try:
        for index, raw_msg in enumerate(box, start=1):
            try:
                results.append(core.parse_eml(raw_msg.as_bytes(policy=core.policy.default), path.name, index))
            except Exception as exc:
                results.append(core.ParsedMail(path.name, index, None, "(errore parsing)", str(exc), "", []))
    finally:
        box.close()
    return results, []


def parse_zip_path(path: Path, depth: int = 0):
    results = []
    warnings = []
    if depth > 4:
        return results, [f"{path.name}: profondità ZIP annidato oltre il limite tecnico di sicurezza"]

    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext not in SUPPORTED:
                continue
            source = f"{path.name} > {info.filename}"
            try:
                if ext == ".eml":
                    with zf.open(info, "r") as src:
                        results.append(core.parse_eml(src.read(), source, 1))
                elif ext == ".msg":
                    with zf.open(info, "r") as src:
                        results.append(core.parse_msg(src.read(), source, 1))
                else:
                    nested_dir = Path(tempfile.mkdtemp(prefix="financeplus_nested_"))
                    nested_path = nested_dir / Path(info.filename).name
                    with zf.open(info, "r") as src, nested_path.open("wb") as dst:
                        while True:
                            block = src.read(8 * 1024 * 1024)
                            if not block:
                                break
                            dst.write(block)
                    if ext == ".mbox":
                        a, b = parse_mbox_path(nested_path)
                    else:
                        a, b = parse_zip_path(nested_path, depth + 1)
                    results.extend(a)
                    warnings.extend(b)
            except Exception as exc:
                warnings.append(f"{source}: {exc}")
    return results, warnings


def parse_reconstructed_path(path: Path):
    ext = path.suffix.lower()
    if ext == ".mbox":
        return parse_mbox_path(path)
    if ext == ".zip":
        return parse_zip_path(path)
    if ext == ".eml":
        return [core.parse_eml(path.read_bytes(), path.name, 1)], []
    if ext == ".msg":
        return [core.parse_msg(path.read_bytes(), path.name, 1)], []
    return [], [f"Formato non supportato: {ext}"]


def render_results(ms, ws):
    if ws:
        with st.expander(f"Avvisi ({len(ws)})"):
            for w in ws:
                st.warning(w)
    if not ms:
        st.info("Nessuna mail elaborata.")
        return

    df = core.dataframe(ms)
    total_att = sum(len(m.attachments) for m in ms)
    total_bytes = sum(len(a.content) for m in ms for a in m.attachments)

    a, b, c, d = st.columns(4)
    a.metric("Mail elaborate", len(ms))
    b.metric("Mail con allegati", sum(bool(m.attachments) for m in ms))
    c.metric("Allegati estratti", total_att)
    d.metric("Dimensione allegati", f"{total_bytes / 1024**2:.2f} MB")

    st.subheader("🔎 Filtri archivio")
    f1, f2, f3, f4 = st.columns([1.1, 1.1, 1.5, 2])
    dated = [m.dt.date() for m in ms if m.dt]
    if dated:
        mind, maxd = min(dated), max(dated)
        start = f1.date_input("Dal", value=mind, min_value=mind, max_value=maxd)
        end = f2.date_input("Al", value=maxd, min_value=mind, max_value=maxd)
    else:
        start = end = None
        f1.caption("Date non disponibili")
        f2.caption("Date non disponibili")

    senders = sorted(x for x in df["Mittente"].dropna().unique())
    sel = f3.multiselect("Mittente", senders, placeholder="Tutti i mittenti")
    q = f4.text_input("Ricerca libera", placeholder="Oggetto, sintesi, allegato…").strip()
    only = st.checkbox("Mostra solo mail con allegati")

    show = df.copy()
    if start and end:
        show = show[(show["DataISO"] == "") | ((show["DataISO"] >= start.isoformat()) & (show["DataISO"] <= end.isoformat()))]
    if sel:
        show = show[show["Mittente"].isin(sel)]
    if only:
        show = show[show["N. allegati"] > 0]
    if q:
        show = show[show.astype(str).apply(lambda x: x.str.contains(re.escape(q), case=False, na=False, regex=True)).any(axis=1)]

    st.caption(f"Risultati visualizzati: {len(show)} su {len(df)}")
    st.dataframe(
        show[["Data e ora", "Mittente", "Oggetto", "Sintesi del contenuto", "Allegati", "N. allegati"]],
        use_container_width=True,
        hide_index=True,
        height=520,
    )

    st.subheader("📦 Esporta risultati filtrati")
    e1, e2, e3, e4 = st.columns(4)
    e1.download_button("📄 Report PDF", core.pdf_bytes(show), "FinancePlus_Report_Mail.pdf", "application/pdf", use_container_width=True)
    e2.download_button("📊 Report Excel", core.xlsx_bytes(show), "FinancePlus_Report_Mail.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    e3.download_button("🧾 Report CSV", show.drop(columns=["DataISO"], errors="ignore").to_csv(index=False).encode("utf-8-sig"), "FinancePlus_Report_Mail.csv", "text/csv", use_container_width=True)
    e4.download_button("📎 Archivio allegati ZIP", core.attachments_zip(ms, show), "FinancePlus_Allegati_Mail.zip", "application/zip", use_container_width=True)


def main():
    st.set_page_config(page_title="FinancePlus | Archivio Mail", page_icon="📬", layout="wide")
    core.css()
    st.markdown(
        '<div class="fp-head"><h1>📬 FinancePlus | Archivio Mail</h1><p>File normali o archivi suddivisi in parti da circa 500 MB</p></div>',
        unsafe_allow_html=True,
    )

    mode = st.radio(
        "Modalità di caricamento",
        ["File normale", "Parti da 500 MB"],
        horizontal=True,
    )

    if mode == "File normale":
        files = st.file_uploader("Carica EML, MSG, MBOX o ZIP", type=["eml", "msg", "mbox", "zip"], accept_multiple_files=True, key="normal")
        if files and st.button("⚙️ Elabora archivio", type="primary", use_container_width=True):
            ms, ws = [], []
            bar = st.progress(0)
            for i, f in enumerate(files, start=1):
                a, b = core.parse_upload(f.name, f.getvalue())
                ms.extend(a)
                ws.extend(b)
                bar.progress(i / len(files))
            bar.empty()
            st.session_state.mails = ms
            st.session_state.warns = ws

    else:
        st.info("Seleziona insieme tutte le parti: esempio archivio.mbox.part0001, archivio.mbox.part0002, …")
        parts = st.file_uploader(
            "Carica tutte le parti del file",
            accept_multiple_files=True,
            key="parts",
            help="Le parti devono appartenere allo stesso file e avere numerazione continua a partire da part0001.",
        )
        if parts:
            infos = [parse_part_name(f.name) for f in parts]
            valid_infos = [x for x in infos if x]
            if len(valid_infos) == len(parts):
                total_size = sum(getattr(f, "size", 0) or 0 for f in parts)
                st.success(f"Parti selezionate: {len(parts)} • Totale caricato: {total_size / 1024**3:.2f} GB")
        if parts and st.button("🧩 Ricostruisci ed elabora", type="primary", use_container_width=True):
            bar = st.progress(0, text="Controllo parti…")
            try:
                rebuilt = reconstruct_parts_to_disk(parts, bar)
                st.success(f"File ricostruito: {rebuilt.name} ({rebuilt.stat().st_size / 1024**3:.2f} GB)")
                bar.progress(1.0, text="Analisi archivio…")
                ms, ws = parse_reconstructed_path(rebuilt)
                st.session_state.mails = ms
                st.session_state.warns = ws
                st.session_state.rebuilt_name = rebuilt.name
            except Exception as exc:
                st.error(f"Impossibile ricostruire/elaborare il file: {exc}")
            finally:
                bar.empty()

    render_results(st.session_state.get("mails", []), st.session_state.get("warns", []))


if __name__ == "__main__":
    main()
