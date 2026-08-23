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
        "company_name": result.get("company_name", ""),
        "person_name": result.get("person_name", ""),
        "document_year": result.get("document_year", ""),
        "document_number": result.get("document_number", ""),
        "bank_name": result.get("bank_name", ""),
        "lender_name": result.get("lender_name", ""),
        "reference_period": result.get("reference_period", ""),
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
            "azienda": x.get("company_name", ""),
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


def _normalized(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _field_value(result: dict, labels: set[str]) -> str:
    wanted = {_normalized(x) for x in labels}
    for field in result.get("key_fields", []) or []:
        if not isinstance(field, dict):
            continue
        label = _normalized(field.get("label", ""))
        value = str(field.get("value", "") or "").strip()
        if not value:
            continue
        if label in wanted or any(token in label for token in wanted):
            return value
    return ""


def _document_haystack(result: dict) -> str:
    return _normalized(" ".join(
        str(result.get(k, "") or "")
        for k in ("document_type", "summary", "preview", "reason")
    ))


def _is_estratto_conto(result: dict) -> bool:
    text = _document_haystack(result)
    positive = (
        "estratto conto", "estratto di conto", "conto corrente",
        "movimenti conto", "saldo iniziale", "saldo finale",
        "periodo contabile", "iban"
    )
    bank_signals = (
        "banca", "bank", "unicredit", "mps", "monte dei paschi",
        "intesa sanpaolo", "bper", "banco bpm", "credit agricole",
        "credem", "mediolanum", "fineco", "poste italiane"
    )
    return any(x in text for x in positive) and any(x in text for x in bank_signals)


def _is_preventivo(result: dict) -> bool:
    text = _document_haystack(result)
    return "preventivo" in text and "estratto conto" not in text


def _is_offerta(result: dict) -> bool:
    text = _document_haystack(result)
    positive = (
        "offerta commerciale", "offerta economica", "offerta tecnica",
        "offerta tecnico economica", "proposta commerciale", "nostra offerta"
    )
    return any(x in text for x in positive) and "preventivo" not in text


def _bank_name(result: dict) -> str:
    direct = str(result.get("bank_name", "") or "").strip()
    if direct:
        return direct
    return _field_value(result, {
        "banca", "istituto", "istituto bancario", "banca emittente",
        "nome banca", "denominazione banca"
    })


def _year_from_document(result: dict) -> str:
    direct = str(result.get("document_year", "") or "").strip()
    if re.fullmatch(r"(?:19|20)\d{2}", direct):
        return direct
    for value in (
        result.get("document_date", ""),
        _field_value(result, {"data", "data documento", "data offerta", "data preventivo"}),
        result.get("summary", ""), result.get("preview", ""),
    ):
        match = re.search(r"\b((?:19|20)\d{2})\b", str(value or ""))
        if match:
            return match.group(1)
    return ""


def _month_from_date(value: object):
    text = str(value or "").strip()
    for pattern in (
        r"\b\d{1,2}[/-](\d{1,2})[/-](?:19|20)\d{2}\b",
        r"\b(?:19|20)\d{2}[/-](\d{1,2})[/-]\d{1,2}\b",
    ):
        match = re.search(pattern, text)
        if match:
            month = int(match.group(1))
            if 1 <= month <= 12:
                return month
    lowered = _normalized(text)
    months = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
        "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
        "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    }
    for name, number in months.items():
        if name in lowered:
            return number
    return None


def _statement_year(result: dict) -> str:
    for value in (
        result.get("period_end", ""), result.get("period_start", ""),
        result.get("document_year", ""), result.get("document_date", ""),
        _field_value(result, {"periodo", "periodo estratto conto", "dal", "al"}),
        result.get("summary", ""), result.get("preview", ""),
    ):
        match = re.search(r"\b((?:19|20)\d{2})\b", str(value or ""))
        if match:
            return match.group(1)
    return ""


def _statement_quarter(result: dict) -> str:
    direct = str(result.get("document_quarter", "") or "").strip()
    match = re.search(r"\b([1-4])\b", direct)
    if match:
        return f"{match.group(1)}° trimestre"
    for value in (
        result.get("period_end", ""), result.get("period_start", ""),
        _field_value(result, {"periodo", "periodo estratto conto", "data fine periodo", "al"}),
    ):
        month = _month_from_date(value)
        if month:
            return f"{((month - 1) // 3) + 1}° trimestre"
    text = _document_haystack(result)
    mapping = {
        "primo trimestre": "1° trimestre", "secondo trimestre": "2° trimestre",
        "terzo trimestre": "3° trimestre", "quarto trimestre": "4° trimestre",
        "1 trimestre": "1° trimestre", "2 trimestre": "2° trimestre",
        "3 trimestre": "3° trimestre", "4 trimestre": "4° trimestre",
    }
    for token, label in mapping.items():
        if token in text:
            return label
    return ""


def _subject_name(result: dict) -> str:
    company = _company_name(result)
    if company:
        return company
    person = str(result.get("person_name", "") or "").strip()
    if person:
        return person
    return _field_value(result, {
        "nominativo", "nome e cognome", "persona", "intestatario",
        "amministratore", "soggetto"
    })


def _is_curriculum_vitae(result: dict) -> bool:
    text = _document_haystack(result)
    return (
        "curriculum vitae" in text
        or "curriculum professionale" in text
        or ("esperienze professionali" in text and ("istruzione" in text or "formazione" in text))
    )


def _is_fattura(result: dict) -> bool:
    text = _document_haystack(result)
    signals = (
        "fattura elettronica", "fattura n", "numero fattura", "invoice",
        "cedente prestatore", "cessionario committente", "imponibile iva",
        "totale fattura"
    )
    return any(x in text for x in signals)


def _is_presentazione_aziendale(result: dict) -> bool:
    text = _document_haystack(result)
    signals = (
        "presentazione aziendale", "company profile", "corporate presentation",
        "profilo aziendale", "profilo societario", "presentazione societaria"
    )
    return any(x in text for x in signals)


def _is_contratto_finanziamento(result: dict) -> bool:
    text = _document_haystack(result)
    signals = (
        "contratto di finanziamento", "contratto finanziamento", "contratto di mutuo",
        "finanziamento chirografario", "loan agreement", "contratto di credito",
        "contratto di prestito"
    )
    return any(x in text for x in signals)


def _is_centrale_rischi_bdi(result: dict) -> bool:
    text = _document_haystack(result)
    strong = (
        "centrale dei rischi", "centrale rischi", "servizio centrale dei rischi"
    )
    return any(x in text for x in strong) and (
        "banca d italia" in text
        or "bankitalia" in text
        or "accordato operativo" in text
        or "utilizzato" in text
    )


def _is_bozza_bilancio(result: dict) -> bool:
    text = _document_haystack(result)
    signals = (
        "bozza di bilancio", "bozza bilancio", "bilancio provvisorio",
        "progetto di bilancio", "draft bilancio", "bilancio non approvato"
    )
    return any(x in text for x in signals)


def _document_number(result: dict) -> str:
    direct = str(result.get("document_number", "") or "").strip()
    if direct:
        return direct
    return _field_value(result, {
        "numero documento", "numero fattura", "n fattura", "fattura n",
        "numero", "document number"
    })


def _lender_name(result: dict) -> str:
    direct = str(result.get("lender_name", "") or "").strip()
    if direct:
        return direct
    bank = _bank_name(result)
    if bank:
        return bank
    return _field_value(result, {
        "finanziatore", "ente finanziatore", "banca finanziatrice",
        "istituto finanziatore", "creditore", "lender"
    })


def _month_year_label(value: object) -> str:
    value = str(value or "").strip()
    month = _month_from_date(value)
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    if not month or not match:
        return ""
    months = {
        1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile",
        5: "maggio", 6: "giugno", 7: "luglio", 8: "agosto",
        9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre",
    }
    return f"{months[month]} {match.group(1)}"


def _risk_reference_period(result: dict) -> str:
    direct = str(result.get("reference_period", "") or "").strip()
    if direct:
        return direct
    field = _field_value(result, {
        "periodo di riferimento", "mese di riferimento", "data riferimento",
        "rilevazione", "periodo", "ultimo mese"
    })
    if field:
        return _month_year_label(field) or field
    for value in (
        result.get("period_end", ""), result.get("document_date", ""),
        result.get("summary", ""), result.get("preview", "")
    ):
        label = _month_year_label(value)
        if label:
            return label
    return _year_from_document(result)


def _clean_document_type(value: object) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" ._-:")
    generic = {
        "", "documento", "documento generico", "altro", "file",
        "unknown", "sconosciuto", "non determinato"
    }
    return "" if _normalized(value) in generic else value[:80]


def _apply_generic_content_naming(result: dict, original_name: str) -> dict:
    if result.get("naming_rule"):
        return result
    subject = _subject_name(result)
    document_type = _clean_document_type(result.get("document_type", ""))
    year = _year_from_document(result)
    if subject and document_type:
        base = f"{subject}_{document_type}"
        if year and document_type.casefold() not in {"curriculum vitae", "cv"}:
            base += f" {year}"
        result["suggested_filename"] = _safe_filename(base, original_name)
        result["naming_rule"] = "Regola generale: SOGGETTO_TIPO DOCUMENTO_ANNO"
        result["reason"] = (
            str(result.get("reason", "") or "").strip()
            + " Auto-denominazione FinancePlus applicata in base al contenuto reale del documento."
        ).strip()
    return result


def _is_ricevuta_deposito_bilancio(result: dict) -> bool:
    haystack = " ".join(
        str(result.get(k, "") or "")
        for k in ("document_type", "summary", "preview", "reason")
    )
    text = _normalized(haystack)
    strong_indicators = (
        "ricevuta dell avvenuta presentazione",
        "ricevuta deposito bilancio",
        "deposito bilancio",
        "elenco degli atti presentati",
        "presentazione via telematica",
    )
    has_receipt = any(x in text for x in strong_indicators)
    has_balance = (
        "bilancio" in text
        and ("esercizio" in text or "deposito" in text or "atto" in text)
    )
    return has_receipt and has_balance


def _receipt_bilancio_year(result: dict) -> str:
    direct = str(result.get("document_year", "") or "").strip()
    if re.fullmatch(r"(?:19|20)\d{2}", direct):
        return direct

    value = _field_value(
        result,
        {
            "anno bilancio", "anno esercizio", "esercizio", "data atto",
            "dt atto", "data chiusura esercizio", "bilancio esercizio"
        },
    )
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    if match:
        return match.group(1)

    sources = [result.get("preview", ""), result.get("summary", ""), result.get("reason", "")]
    patterns = (
        r"bilancio(?:\s+abbreviato)?\s+(?:d[’']?esercizio|di esercizio).*?((?:19|20)\d{2})",
        r"(?:dt\.?\s*atto|data\s*atto)\s*[:=-]?\s*\d{1,2}[/-]\d{1,2}[/-]((?:19|20)\d{2})",
        r"esercizio.*?((?:19|20)\d{2})",
    )
    for source in sources:
        normalized_source = _normalized(source)
        for pattern in patterns:
            match = re.search(pattern, normalized_source, flags=re.IGNORECASE)
            if match:
                return match.group(1)
    return ""


def _is_visura_camerale(result: dict) -> bool:
    haystack = " ".join(
        str(result.get(k, "") or "")
        for k in ("document_type", "summary", "preview", "reason")
    )
    text = _normalized(haystack)
    indicators = (
        "visura camerale",
        "visura ordinaria",
        "visura storica",
        "registro imprese",
        "camera di commercio",
        "archivio ufficiale della cciaa",
    )
    return any(x in text for x in indicators)


def _is_bilancio_esercizio(result: dict) -> bool:
    haystack = " ".join(
        str(result.get(k, "") or "")
        for k in ("document_type", "summary", "preview", "reason")
    )
    text = _normalized(haystack)
    return (
        "bilancio di esercizio" in text
        or "bilancio d esercizio" in text
        or ("stato patrimoniale" in text and "conto economico" in text)
    )


def _document_year(result: dict) -> str:
    sources = [
        result.get("document_year", ""),
        result.get("document_date", ""),
        result.get("summary", ""),
        result.get("preview", ""),
    ]
    for source in sources:
        match = re.search(r"\b((?:19|20)\d{2})\b", str(source or ""))
        if match:
            return match.group(1)
    return _field_value(
        result,
        {"anno", "anno esercizio", "esercizio", "data bilancio", "data chiusura esercizio"},
    )


def _company_name(result: dict) -> str:
    direct = str(result.get("company_name", "") or "").strip()
    if direct:
        return direct
    return _field_value(
        result,
        {
            "denominazione impresa",
            "denominazione",
            "ragione sociale",
            "nome azienda",
            "società",
            "societa",
            "impresa",
        },
    )


def _apply_priority_naming_rules(result: dict, original_name: str) -> dict:
    if _is_ricevuta_deposito_bilancio(result):
        company = _company_name(result)
        year = _receipt_bilancio_year(result)
        result["document_type"] = "Ricevuta deposito Bilancio d’esercizio"
        if company:
            result["company_name"] = company
        if year:
            result["document_year"] = year
        if company and year:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Ricevuta deposito Bilancio d’esercizio {year}",
                original_name,
            )
            result["naming_rule"] = "NOME AZIENDA_Ricevuta deposito Bilancio d’esercizio ANNO"
            result["reason"] = (
                "Regola FinancePlus prioritaria: documento riconosciuto come ricevuta di deposito del bilancio; "
                "usa la denominazione dell’impresa e l’anno dell’esercizio depositato, non l’anno del protocollo."
            )
    elif _is_centrale_rischi_bdi(result):
        company = _company_name(result)
        period = _risk_reference_period(result)
        result["document_type"] = "Centrale Rischi Banca d’Italia"
        if company:
            result["company_name"] = company
        if period:
            result["reference_period"] = period
        if company:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Centrale Rischi Banca d’Italia" + (f" {period}" if period else ""),
                original_name,
            )
            result["naming_rule"] = "NOME AZIENDA_Centrale Rischi Banca d’Italia PERIODO"
            result["reason"] = "Regola FinancePlus: Centrale Rischi Banca d’Italia riconosciuta dal contenuto."
    elif _is_estratto_conto(result):
        company = _company_name(result)
        bank = _bank_name(result)
        quarter = _statement_quarter(result)
        year = _statement_year(result)
        result["document_type"] = "Estratto conto"
        if company:
            result["company_name"] = company
        if bank:
            result["bank_name"] = bank
        if quarter:
            result["document_quarter"] = quarter
        if year:
            result["document_year"] = year
        if company and bank and quarter and year:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Estratto conto {quarter} {bank} {year}", original_name
            )
            result["naming_rule"] = "NOME AZIENDA_Estratto conto TRIMESTRE BANCA ANNO"
            result["reason"] = (
                "Regola FinancePlus: estratto conto riconosciuto dal contenuto; "
                "usa azienda intestataria, trimestre, banca e anno del periodo contabile."
            )
    elif _is_contratto_finanziamento(result):
        company = _company_name(result)
        lender = _lender_name(result)
        year = _year_from_document(result)
        result["document_type"] = "Contratto di finanziamento"
        if company:
            result["company_name"] = company
        if lender:
            result["lender_name"] = lender
        if year:
            result["document_year"] = year
        if company:
            base = f"{company}_Contratto di finanziamento"
            if lender:
                base += f" {lender}"
            if year:
                base += f" {year}"
            result["suggested_filename"] = _safe_filename(base, original_name)
            result["naming_rule"] = "NOME AZIENDA_Contratto di finanziamento FINANZIATORE ANNO"
            result["reason"] = "Regola FinancePlus: contratto di finanziamento riconosciuto dal contenuto."
    elif _is_fattura(result):
        company = _company_name(result)
        number = _document_number(result)
        year = _year_from_document(result)
        result["document_type"] = "Fattura"
        if company:
            result["company_name"] = company
        if number:
            result["document_number"] = number
        if year:
            result["document_year"] = year
        if company:
            base = f"{company}_Fattura"
            if number:
                base += f" N.{number}"
            if year:
                base += f" {year}"
            result["suggested_filename"] = _safe_filename(base, original_name)
            result["naming_rule"] = "NOME AZIENDA_Fattura N.NUMERO ANNO"
            result["reason"] = "Regola FinancePlus: fattura riconosciuta dal contenuto."
    elif _is_curriculum_vitae(result):
        person = str(result.get("person_name", "") or "").strip() or _subject_name(result)
        result["document_type"] = "Curriculum Vitae"
        if person:
            result["person_name"] = person
            result["suggested_filename"] = _safe_filename(
                f"{person}_Curriculum Vitae", original_name
            )
            result["naming_rule"] = "NOME COGNOME_Curriculum Vitae"
            result["reason"] = "Regola FinancePlus: Curriculum Vitae riconosciuto dal contenuto."
    elif _is_presentazione_aziendale(result):
        company = _company_name(result)
        year = _year_from_document(result)
        result["document_type"] = "Presentazione aziendale"
        if company:
            result["company_name"] = company
        if year:
            result["document_year"] = year
        if company:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Presentazione aziendale" + (f" {year}" if year else ""),
                original_name,
            )
            result["naming_rule"] = "NOME AZIENDA_Presentazione aziendale ANNO"
            result["reason"] = "Regola FinancePlus: presentazione aziendale riconosciuta dal contenuto."
    elif _is_preventivo(result):
        company = _company_name(result)
        year = _year_from_document(result)
        result["document_type"] = "Preventivo"
        if company:
            result["company_name"] = company
        if year:
            result["document_year"] = year
        if company:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Preventivo" + (f" {year}" if year else ""), original_name
            )
            result["naming_rule"] = "NOME AZIENDA_Preventivo ANNO"
            result["reason"] = "Regola FinancePlus: preventivo riconosciuto dal contenuto."
    elif _is_offerta(result):
        company = _company_name(result)
        year = _year_from_document(result)
        result["document_type"] = "Offerta"
        if company:
            result["company_name"] = company
        if year:
            result["document_year"] = year
        if company:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Offerta" + (f" {year}" if year else ""), original_name
            )
            result["naming_rule"] = "NOME AZIENDA_Offerta ANNO"
            result["reason"] = "Regola FinancePlus: offerta riconosciuta dal contenuto."
    elif _is_bozza_bilancio(result):
        company = _company_name(result)
        year = _year_from_document(result)
        result["document_type"] = "Bozza Bilancio"
        if company:
            result["company_name"] = company
        if year:
            result["document_year"] = year
        if company:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Bozza Bilancio" + (f" {year}" if year else ""), original_name
            )
            result["naming_rule"] = "NOME AZIENDA_Bozza Bilancio ANNO"
            result["reason"] = "Regola FinancePlus: bozza/progetto di bilancio riconosciuto e distinto dal bilancio definitivo."
    elif _is_visura_camerale(result):
        company = _company_name(result)
        result["document_type"] = "Visura Camerale"
        if company:
            result["company_name"] = company
            result["suggested_filename"] = _safe_filename(
                f"{company}_Visura Camerale",
                original_name,
            )
            result["naming_rule"] = "NOME AZIENDA_Visura Camerale"
            result["reason"] = (
                "Regola FinancePlus prioritaria: documento riconosciuto come Visura Camerale; "
                "usa la denominazione ufficiale dell'impresa presente nella visura."
            )
    elif _is_bilancio_esercizio(result):
        company = _company_name(result)
        year = _document_year(result)
        result["document_type"] = "Bilancio d’esercizio"
        if company:
            result["company_name"] = company
        if year:
            result["document_year"] = year
        if company and year:
            result["suggested_filename"] = _safe_filename(
                f"{company}_Bilancio d’esercizio {year}",
                original_name,
            )
            result["naming_rule"] = "NOME AZIENDA_Bilancio d’esercizio ANNO"
            result["reason"] = (
                "Regola FinancePlus prioritaria: documento riconosciuto come Bilancio d’esercizio; "
                "usa la denominazione ufficiale dell’azienda e l’anno di esercizio presenti nel documento."
            )
    return _apply_generic_content_naming(result, original_name)


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

REGOLA ESTESA FINANCEPLUS — ALTRE TIPOLOGIE:
- CURRICULUM VITAE: identifica il nominativo della persona (es. amministratore) in person_name. Nome: NOME COGNOME_Curriculum Vitae + estensione. Non usare anni di nascita, studi o esperienze come anno del file.
- FATTURA: identifica l’azienda principale/destinataria in company_name, numero fattura in document_number e anno dalla data fattura. Nome: NOME AZIENDA_Fattura N.NUMERO ANNO + estensione. Se numero o anno non sono leggibili, omettili senza inventarli.
- PRESENTAZIONE AZIENDALE / COMPANY PROFILE: identifica l’azienda presentata. Nome: NOME AZIENDA_Presentazione aziendale ANNO + estensione; ometti l’anno se non è chiaramente una data/versione del documento.
- CONTRATTO DI FINANZIAMENTO: identifica azienda finanziata, banca/finanziatore in lender_name e data/anno del contratto. Nome: NOME AZIENDA_Contratto di finanziamento FINANZIATORE ANNO + estensione.
- CENTRALE RISCHI BANCA D’ITALIA: identifica azienda segnalata e periodo di riferimento in reference_period. Nome: NOME AZIENDA_Centrale Rischi Banca d’Italia PERIODO + estensione. Non inserire importi, codici intermediario o dettagli delle esposizioni nel nome.
- BOZZA/PROGETTO DI BILANCIO: deve essere distinta dal bilancio definitivo. Nome: NOME AZIENDA_Bozza Bilancio ANNO + estensione.
- Per QUALSIASI ALTRA TIPOLOGIA non coperta da regole specifiche: identifica soggetto principale, document_type e anno/data pertinente. Crea un nome conciso: SOGGETTO_TIPO DOCUMENTO_ANNO + estensione. Non inventare mai campi mancanti.
- Se il documento riguarda principalmente una persona, usa person_name; se riguarda una società, usa company_name.

REGOLA GENERALE FINANCEPLUS — AUTO DENOMINAZIONE:
- Leggi sempre il contenuto reale; il nome file originale è solo un indizio e non è la fonte principale.
- Individua l’azienda principale/intestataria e inseriscila in company_name.
- OFFERTA: NOME AZIENDA_Offerta ANNO + estensione.
- PREVENTIVO: NOME AZIENDA_Preventivo ANNO + estensione.
- ESTRATTO CONTO: NOME AZIENDA_Estratto conto TRIMESTRE BANCA ANNO + estensione.
- Per l’estratto conto estrai company_name, bank_name, period_start, period_end, document_quarter e document_year.
- Il trimestre deriva dal periodo contabile: gennaio-marzo 1°, aprile-giugno 2°, luglio-settembre 3°, ottobre-dicembre 4°.
- Esempio: AZIENDA SRL_Estratto conto 2° trimestre UniCredit 2026.pdf.
- Non inserire IBAN, numero conto, saldo, filiale o altri dati sensibili nel nome.
- Mantieni le regole specifiche già definite per Visura Camerale, Bilancio d’esercizio e Ricevuta deposito Bilancio.

REGOLA FINANCEPLUS PRIORITARIA — RICEVUTA DEPOSITO BILANCIO:
- Questa regola deve essere verificata PRIMA della Visura Camerale e del Bilancio d’esercizio.
- Se il documento è una ricevuta/ricevuta telematica della Camera di Commercio o Registro Imprese relativa alla presentazione/deposito di un bilancio, imposta document_type esattamente a "Ricevuta deposito Bilancio d’esercizio".
- Elementi tipici: "Ricevuta dell’avvenuta presentazione", "presentazione via telematica", "Elenco degli atti presentati", "Deposito bilancio", protocollo, diritti di segreteria o bollo.
- Trova la DENOMINAZIONE UFFICIALE DELL’IMPRESA indicata nella ricevuta e inseriscila in company_name.
- Ricava document_year dall’ANNO DEL BILANCIO/ESERCIZIO DEPOSITATO, non dalla data della domanda, protocollo, ricevuta o firma.
- Esempio: ricevuta datata 22/02/2025 con atto "Bilancio abbreviato d’esercizio" e DT.ATTO 31/12/2023 => document_year = "2023".
- Il nome suggerito DEVE essere esattamente: NOME AZIENDA_Ricevuta deposito Bilancio d’esercizio ANNO + estensione originale.
- Esempio: SCHIANO S.R.L._Ricevuta deposito Bilancio d’esercizio 2023.pdf
- NON aggiungere data protocollo, numero protocollo, REA, codice fiscale, importi di bollo/diritti o altri dettagli.

REGOLA FINANCEPLUS PRIORITARIA — VISURA CAMERALE:
- Se il documento è una Visura Camerale, Visura ordinaria, Visura storica o altro documento di visura del Registro Imprese/CCIAA, imposta document_type esattamente a "Visura Camerale".
- Trova la DENOMINAZIONE UFFICIALE DELL'IMPRESA nel contenuto della visura, soprattutto nella prima pagina, nei campi "Denominazione", "Dati anagrafici" o intestazione dell'impresa.
- Inserisci tale denominazione, senza abbreviazioni inventate, nel campo company_name.
- Il nome suggerito DEVE essere esattamente: NOME AZIENDA_Visura Camerale + estensione originale.
- Esempio di forma: FOOD E MEAT S.R.L._Visura Camerale.pdf
- Per una Visura Camerale NON aggiungere data, codice fiscale, REA, città o altri dettagli al nome.
- Questa regola ha priorità sulle convenzioni apprese e sulla convenzione generica di denominazione.

REGOLA FINANCEPLUS PRIORITARIA — BILANCIO D’ESERCIZIO:
- Se il documento è un Bilancio di esercizio, un fascicolo di bilancio con Stato patrimoniale/Conto economico/Nota integrativa o documento equivalente, imposta document_type esattamente a "Bilancio d’esercizio".
- Trova la DENOMINAZIONE UFFICIALE DELL’AZIENDA nella prima pagina o nell’intestazione del bilancio e inseriscila in company_name senza abbreviazioni inventate.
- Ricava l’ANNO DI ESERCIZIO dalla dicitura del documento, ad esempio "Bilancio di esercizio al 31-12-2023" deve produrre document_year = "2023".
- Il nome suggerito DEVE essere esattamente: NOME AZIENDA_Bilancio d’esercizio ANNO + estensione originale.
- Esempio di forma: SCHIANO S.R.L._Bilancio d’esercizio 2023.pdf
- NON aggiungere al nome data completa, codice fiscale, REA, città, utile/perdita o altri dettagli.
- Questa regola ha priorità sulle convenzioni apprese e sulla convenzione generica di denominazione, ma viene dopo la regola specifica Visura Camerale.

Nome originale: {filename}
Convenzioni già accettate dall'utente:
{_learning_prompt()}

Per tutti gli altri documenti usa, quando possibile, una convenzione professionale basata su tipo documento, soggetto, data/periodo e dettaglio.
Mantieni l'estensione originale e non inserire dati non presenti.

Rispondi esattamente con questo schema:
{{
  "document_type": "string",
  "company_name": "string",
  "document_date": "string",
  "document_year": "string",
  "bank_name": "string",
  "person_name": "string",
  "document_number": "string",
  "lender_name": "string",
  "reference_period": "string",
  "period_start": "string",
  "period_end": "string",
  "document_quarter": "string",
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
        if not isinstance(result.get("key_fields"), list):
            result["key_fields"] = []
        result = _apply_priority_naming_rules(result, filename)
        result["suggested_filename"] = _safe_filename(result.get("suggested_filename", ""), filename)
        try:
            result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
        except Exception:
            result["confidence"] = 0.0
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
    st.info(
        "Auto-denominazione dal contenuto: Visure, Bilanci, Ricevute deposito Bilancio, "
        "Offerte, Preventivi ed Estratti conto. Gli estratti conto includono trimestre, banca e anno."
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

                if result.get("company_name"):
                    st.markdown(f"**Azienda riconosciuta:** {result.get('company_name')}")
                if result.get("naming_rule"):
                    st.success(f"Regola nome applicata: {result.get('naming_rule')}")

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
