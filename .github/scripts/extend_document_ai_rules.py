from __future__ import annotations

from pathlib import Path

TARGET = Path("mail_attachment_extractor/document_ai.py")


def insert_before(text: str, marker: str, block: str, feature: str) -> str:
    if feature in text:
        return text
    if marker not in text:
        raise RuntimeError(f"Marker not found for {feature}: {marker!r}")
    return text.replace(marker, block + marker, 1)


def replace_once(text: str, old: str, new: str, feature: str) -> str:
    if feature in text:
        return text
    if old not in text:
        raise RuntimeError(f"Marker not found for {feature}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    helpers = r'''def _subject_name(result: dict) -> str:
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


'''
    text = insert_before(
        text,
        "def _is_ricevuta_deposito_bilancio(result: dict) -> bool:\n",
        helpers,
        "def _is_curriculum_vitae",
    )

    text = replace_once(
        text,
        "    elif _is_estratto_conto(result):\n",
        '''    elif _is_centrale_rischi_bdi(result):
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
''',
        "elif _is_centrale_rischi_bdi",
    )

    text = replace_once(
        text,
        "    elif _is_preventivo(result):\n",
        '''    elif _is_contratto_finanziamento(result):
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
''',
        "elif _is_contratto_finanziamento",
    )

    text = replace_once(
        text,
        "    elif _is_visura_camerale(result):\n",
        '''    elif _is_bozza_bilancio(result):
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
''',
        "elif _is_bozza_bilancio",
    )

    text = replace_once(
        text,
        "    return result\n\n\ndef analyze_document(filename: str, data: bytes) -> dict:\n",
        "    return _apply_generic_content_naming(result, original_name)\n\n\ndef analyze_document(filename: str, data: bytes) -> dict:\n",
        "return _apply_generic_content_naming",
    )

    prompt_block = '''REGOLA ESTESA FINANCEPLUS — ALTRE TIPOLOGIE:
- CURRICULUM VITAE: identifica il nominativo della persona (es. amministratore) in person_name. Nome: NOME COGNOME_Curriculum Vitae + estensione. Non usare anni di nascita, studi o esperienze come anno del file.
- FATTURA: identifica l’azienda principale/destinataria in company_name, numero fattura in document_number e anno dalla data fattura. Nome: NOME AZIENDA_Fattura N.NUMERO ANNO + estensione. Se numero o anno non sono leggibili, omettili senza inventarli.
- PRESENTAZIONE AZIENDALE / COMPANY PROFILE: identifica l’azienda presentata. Nome: NOME AZIENDA_Presentazione aziendale ANNO + estensione; ometti l’anno se non è chiaramente una data/versione del documento.
- CONTRATTO DI FINANZIAMENTO: identifica azienda finanziata, banca/finanziatore in lender_name e data/anno del contratto. Nome: NOME AZIENDA_Contratto di finanziamento FINANZIATORE ANNO + estensione.
- CENTRALE RISCHI BANCA D’ITALIA: identifica azienda segnalata e periodo di riferimento in reference_period. Nome: NOME AZIENDA_Centrale Rischi Banca d’Italia PERIODO + estensione. Non inserire importi, codici intermediario o dettagli delle esposizioni nel nome.
- BOZZA/PROGETTO DI BILANCIO: deve essere distinta dal bilancio definitivo. Nome: NOME AZIENDA_Bozza Bilancio ANNO + estensione.
- Per QUALSIASI ALTRA TIPOLOGIA non coperta da regole specifiche: identifica soggetto principale, document_type e anno/data pertinente. Crea un nome conciso: SOGGETTO_TIPO DOCUMENTO_ANNO + estensione. Non inventare mai campi mancanti.
- Se il documento riguarda principalmente una persona, usa person_name; se riguarda una società, usa company_name.

'''
    text = insert_before(
        text,
        "REGOLA GENERALE FINANCEPLUS — AUTO DENOMINAZIONE:\n",
        prompt_block,
        "REGOLA ESTESA FINANCEPLUS — ALTRE TIPOLOGIE:",
    )

    old_schema = '''  "bank_name": "string",
  "period_start": "string",
'''
    new_schema = '''  "bank_name": "string",
  "person_name": "string",
  "document_number": "string",
  "lender_name": "string",
  "reference_period": "string",
  "period_start": "string",
'''
    if '"person_name": "string"' not in text:
        if old_schema not in text:
            raise RuntimeError("Schema marker not found")
        text = text.replace(old_schema, new_schema, 1)

    old_ui = '''        "Auto-denominazione attiva in base al contenuto: Visure, Bilanci, Ricevute deposito Bilancio, "
        "Offerte, Preventivi ed Estratti conto. Gli estratti conto includono trimestre, banca e anno."
'''
    new_ui = '''        "Auto-denominazione attiva in base al contenuto: Visure, Bilanci e bozze, Ricevute deposito Bilancio, "
        "Offerte, Preventivi, Estratti conto, Fatture, CV, Presentazioni aziendali, Contratti di finanziamento, "
        "Centrale Rischi Banca d’Italia e fallback automatico per le altre tipologie."
'''
    if old_ui in text:
        text = text.replace(old_ui, new_ui, 1)

    old_memory = '''        "company_name": result.get("company_name", ""),
        "summary": str(result.get("summary", ""))[:800],
'''
    new_memory = '''        "company_name": result.get("company_name", ""),
        "person_name": result.get("person_name", ""),
        "document_year": result.get("document_year", ""),
        "document_number": result.get("document_number", ""),
        "bank_name": result.get("bank_name", ""),
        "lender_name": result.get("lender_name", ""),
        "reference_period": result.get("reference_period", ""),
        "summary": str(result.get("summary", ""))[:800],
'''
    if old_memory in text:
        text = text.replace(old_memory, new_memory, 1)

    TARGET.write_text(text, encoding="utf-8")
    print("Extended document naming rules applied")


if __name__ == "__main__":
    main()
