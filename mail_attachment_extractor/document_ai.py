# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from openai import OpenAI

MODEL = os.getenv("OPENAI_DOCUMENT_MODEL", "gpt-5.6-terra")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MEMORY_FILE = Path(__file__).with_name("document_ai_learning.json")
MAX_MEMORY_EXAMPLES = 250
MAX_PROMPT_EXAMPLES = 40


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        key = ""
    return key


def _client() -> OpenAI:
    key = _api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY non configurata nei Secrets dell'app.")
    return OpenAI(api_key=key)


def _memory_path() -> Path:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not MEMORY_FILE.exists():
            MEMORY_FILE.write_text("[]", encoding="utf-8")
        return MEMORY_FILE
    except Exception:
        return Path(tempfile.gettempdir()) / "financeplus_document_ai_learning.json"


def load_memory() -> list[dict]:
    try:
        p = _memory_path()
        if not p.exists():
            return []
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def save_memory(items: list[dict]) -> None:
    try:
        _memory_path().write_text(
            json.dumps(items[-MAX_MEMORY_EXAMPLES:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def add_learning_example(original_name: str, suggested_name: str, accepted_name: str, result: dict) -> None:
    items = load_memory()
    items.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "original_name": original_name,
        "suggested_name": suggested_name,
        "accepted_name": accepted_name,
        "document_type": result.get("document_type", ""),
        "summary": str(result.get("summary", ""))[:800],
        "key_fields": result.get("key_fields", [])[:15],
    })
    save_memory(items)


def memory_bytes() -> bytes:
    return json.dumps(load_memory(), ensure_ascii=False, indent=2).encode("utf-8")


def import_memory_bytes(data: bytes) -> int:
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed, list):
        raise ValueError("La memoria deve essere un elenco JSON.")
    items = load_memory()
    items.extend(x for x in parsed if isinstance(x, dict))
    save_memory(items)
    return len(load_memory())


def _safe_filename(name: str, original_name: str) -> str:
    original_ext = Path(original_name).suffix
    proposed = (name or "").strip().replace("/", "-").replace("\\", "-")
    proposed = re.sub(r'[\x00-\x1f<>:"|?*]', "-", proposed)
    proposed = re.sub(r"\s+", " ", proposed).strip(" .-")
    if not proposed:
        proposed = Path(original_name).stem + " - classificato"
    if original_ext:
        if not Path(proposed).suffix:
            proposed += original_ext
        elif Path(proposed).suffix.lower() != original_ext.lower():
            proposed = str(Path(proposed).with_suffix(original_ext))
    return proposed[:220]


def _doc_id(filename: str, data: bytes) -> str:
    h = hashlib.sha256()
    h.update(filename.encode("utf-8", errors="ignore"))
    h.update(data)
    return h.hexdigest()[:24]


def _learning_prompt() -> str:
    examples = load_memory()[-MAX_PROMPT_EXAMPLES:]
    if not examples:
        return "Nessuna convenzione precedente disponibile."
    compact = [
        {
            "originale": x.get("original_name", ""),
            "tipo": x.get("document_type", ""),
            "nome_accettato": x.get("accepted_name", ""),
        }
        for x in examples
    ]
    return json.dumps(compact, ensure_ascii=False)


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not m:
        raise ValueError("Risposta IA non interpretabile.")
    value = json.loads(m.group(0))
    if not isinstance(value, dict):
        raise ValueError("Risposta IA non valida.")
    return value


def analyze_document(filename: str, data: bytes) -> dict:
    client = _client()
    ext = Path(filename).suffix.lower()
    prompt = f"""
Sei il motore di riconoscimento documentale di FinancePlus.
Analizza in modo dettagliato e restituisci SOLO JSON valido.

Devi:
1. riconoscere la tipologia reale del documento;
2. descrivere con precisione il contenuto senza inventare dati;
3. estrarre soggetti, società, date, importi, numeri documento, scadenze e altri campi realmente presenti;
4. produrre una breve anteprima leggibile;
5. suggerire un nome file professionale;
6. applicare, quando pertinenti, le convenzioni apprese dalle correzioni precedenti.

Nome originale: {filename}
Convenzioni già accettate dall'utente:
{_learning_prompt()}

Convenzione preferita per il nome: TIPO DOCUMENTO - SOGGETTO - DATA/PERIODO - DETTAGLIO.
Mantieni l'estensione originale e non inserire dati non presenti.

Rispondi esattamente con questo schema:
{{
  "document_type": "string",
  "confidence": 0.0,
  "summary": "string",
  "preview": "string",
  "suggested_filename": "string",
  "reason": "string",
  "key_fields": [{{"label":"string","value":"string"}}]
}}
""".strip()

    remote_file_id = None
    try:
        if ext in IMAGE_EXTS:
            mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
            encoded = base64.b64encode(data).decode("ascii")
            content = [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "high"},
            ]
        else:
            uploaded = client.files.create(file=(filename, io.BytesIO(data)), purpose="user_data")
            remote_file_id = uploaded.id
            content = [
                {"type": "input_text", "text": prompt},
                {"type": "input_file", "file_id": remote_file_id, "detail": "auto"},
            ]

        response = client.responses.create(
            model=MODEL,
            input=[{"role": "user", "content": content}],
            max_output_tokens=2200,
            store=False,
        )
        result = _parse_json(response.output_text)
        result["suggested_filename"] = _safe_filename(result.get("suggested_filename", ""), filename)
        try:
            result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
        except Exception:
            result["confidence"] = 0.0
        if not isinstance(result.get("key_fields"), list):
            result["key_fields"] = []
        return result
    finally:
        if remote_file_id:
            try:
                client.files.delete(remote_file_id)
            except Exception:
                pass


def _renamed_zip(files_by_id: dict, results: dict, names: dict) -> bytes:
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for doc_id, item in files_by_id.items():
            result = results.get(doc_id)
            if not result or result.get("error"):
                continue
            name = _safe_filename(names.get(doc_id) or result.get("suggested_filename", ""), item["name"])
            stem, ext = str(Path(name).with_suffix("")), Path(name).suffix
            candidate = name
            n = 2
            while candidate.lower() in used:
                candidate = f"{stem} ({n}){ext}"
                n += 1
            used.add(candidate.lower())
            zf.writestr(candidate, item["data"])
    return buf.getvalue()


def render_document_ai() -> None:
    st.markdown("---")
    st.markdown("## 3. 🤖 Riconoscimento automatico IA documenti")
    st.caption(
        "Seleziona i documenti: l'IA ne riconosce la tipologia, analizza il contenuto, mostra un'anteprima e propone un nome. "
        "Quando correggi e confermi il nome, la convenzione viene memorizzata e riutilizzata nelle analisi successive."
    )

    try:
        _client()
        key_ready = True
        st.success(f"IA collegata • Modello: {MODEL}")
    except Exception:
        key_ready = False
        st.warning("Modulo IA installato. Configura OPENAI_API_KEY nei Secrets dell'app per attivare il riconoscimento.")

    uploaded = st.file_uploader(
        "Seleziona i documenti",
        type=[
            "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "rtf", "ppt", "pptx",
            "jpg", "jpeg", "png", "webp", "gif", "xml", "eml", "msg"
        ],
        accept_multiple_files=True,
        key="document_ai_uploader",
    )

    st.session_state.setdefault("document_ai_results", {})
    st.session_state.setdefault("document_ai_names", {})

    files_by_id = {}
    if uploaded:
        for f in uploaded:
            data = f.getvalue()
            doc_id = _doc_id(f.name, data)
            files_by_id[doc_id] = {
                "name": f.name,
                "data": data,
                "size": len(data),
                "type": getattr(f, "type", "") or "",
            }

        rows = []
        for doc_id, item in files_by_id.items():
            rows.append({
                "File": item["name"],
                "Formato": Path(item["name"]).suffix.lower() or "—",
                "Dimensione MB": round(item["size"] / 1024**2, 2),
                "Stato": "✅ Analizzato" if doc_id in st.session_state.document_ai_results else "Da analizzare",
            })
        st.markdown("### File selezionati")
        st.dataframe(rows, use_container_width=True, hide_index=True)

        labels = {doc_id: item["name"] for doc_id, item in files_by_id.items()}
        selected_ids = st.multiselect(
            "Documenti da sottoporre ad Auto/Riconoscimento",
            options=list(files_by_id.keys()),
            default=list(files_by_id.keys()),
            format_func=lambda x: labels[x],
        )

        if st.button(
            "🤖 Auto/Riconoscimento IA",
            type="primary",
            use_container_width=True,
            disabled=not key_ready or not selected_ids,
        ):
            bar = st.progress(0, text="Avvio riconoscimento…")
            for i, doc_id in enumerate(selected_ids, start=1):
                item = files_by_id[doc_id]
                bar.progress((i - 1) / len(selected_ids), text=f"Analisi {i}/{len(selected_ids)} • {item['name']}")
                try:
                    result = analyze_document(item["name"], item["data"])
                    st.session_state.document_ai_results[doc_id] = result
                    st.session_state.document_ai_names[doc_id] = result["suggested_filename"]
                except Exception as exc:
                    st.session_state.document_ai_results[doc_id] = {"error": str(exc)}
            bar.empty()
            st.rerun()

        results = st.session_state.document_ai_results
        names = st.session_state.document_ai_names

        for doc_id, item in files_by_id.items():
            result = results.get(doc_id)
            if not result:
                continue

            with st.expander(f"📄 {item['name']}", expanded=True):
                if result.get("error"):
                    st.error(result["error"])
                    continue

                c1, c2 = st.columns(2)
                c1.metric("Tipologia", result.get("document_type", "Non determinata"))
                c2.metric("Affidabilità", f"{result.get('confidence', 0.0) * 100:.0f}%")

                st.markdown("**Sintesi del contenuto**")
                st.write(result.get("summary", ""))

                st.markdown("**Anteprima contenuto**")
                st.text_area(
                    "Anteprima",
                    value=result.get("preview", ""),
                    height=180,
                    disabled=True,
                    key=f"preview_{doc_id}",
                    label_visibility="collapsed",
                )

                fields = result.get("key_fields", [])
                if fields:
                    st.markdown("**Dati riconosciuti**")
                    st.dataframe(fields, use_container_width=True, hide_index=True)

                if result.get("reason"):
                    st.caption("Criterio IA: " + str(result.get("reason")))

                suggested = result.get("suggested_filename", item["name"])
                names.setdefault(doc_id, suggested)
                entered_name = st.text_input(
                    "Nome file suggerito / modificabile",
                    value=names.get(doc_id, suggested),
                    key=f"rename_{doc_id}",
                )
                names[doc_id] = _safe_filename(entered_name, item["name"])

                b1, b2 = st.columns(2)
                if b1.button("✅ Conferma nome e memorizza", key=f"learn_{doc_id}", use_container_width=True):
                    accepted = _safe_filename(names[doc_id], item["name"])
                    names[doc_id] = accepted
                    add_learning_example(item["name"], suggested, accepted, result)
                    st.success(f"Convenzione memorizzata: {accepted}")

                b2.download_button(
                    "⬇️ Scarica rinominato",
                    data=item["data"],
                    file_name=_safe_filename(names[doc_id], item["name"]),
                    mime=item["type"] or "application/octet-stream",
                    key=f"download_{doc_id}",
                    use_container_width=True,
                )

        analyzed = {
            doc_id: files_by_id[doc_id]
            for doc_id in files_by_id
            if doc_id in st.session_state.document_ai_results
            and not st.session_state.document_ai_results[doc_id].get("error")
        }
        if analyzed:
            st.download_button(
                "📦 Scarica tutti i documenti rinominati (ZIP)",
                data=_renamed_zip(analyzed, st.session_state.document_ai_results, st.session_state.document_ai_names),
                file_name="FinancePlus_Documenti_Rinominati.zip",
                mime="application/zip",
                use_container_width=True,
            )

    with st.expander("🧠 Memoria e apprendimento IA"):
        memory = load_memory()
        st.write(f"Correzioni/convenzioni memorizzate: **{len(memory)}**")
        st.caption(
            "La memoria viene salvata sul filesystem dell'app e riutilizzata nei suggerimenti successivi. "
            "È disponibile anche l'esportazione/importazione JSON per conservarla tra deploy o riavvii."
        )
        c1, c2 = st.columns(2)
        c1.download_button(
            "⬇️ Esporta memoria IA",
            data=memory_bytes(),
            file_name="FinancePlus_Document_AI_Memory.json",
            mime="application/json",
            use_container_width=True,
        )
        mem_upload = c2.file_uploader("Importa memoria IA", type=["json"], key="document_ai_memory_upload")
        if mem_upload is not None and st.button("Importa e unisci memoria", use_container_width=True):
            try:
                count = import_memory_bytes(mem_upload.getvalue())
                st.success(f"Memoria importata. Totale esempi: {count}")
                st.rerun()
            except Exception as exc:
                st.error(f"Memoria non valida: {exc}")
