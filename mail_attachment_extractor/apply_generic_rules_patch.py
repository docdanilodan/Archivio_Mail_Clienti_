from pathlib import Path

path = Path(__file__).with_name("document_ai.py")
text = path.read_text(encoding="utf-8")

if "def _is_estratto_conto" not in text:
    marker = "def _is_ricevuta_deposito_bilancio(result: dict) -> bool:\n"
    helpers = r'''def _document_haystack(result: dict) -> str:
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


'''
    if marker not in text:
        raise RuntimeError("Helper marker not found")
    text = text.replace(marker, helpers + marker, 1)

if "NOME AZIENDA_Estratto conto TRIMESTRE BANCA ANNO" not in text:
    marker = "    elif _is_visura_camerale(result):\n"
    rules = '''    elif _is_estratto_conto(result):
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
    elif _is_visura_camerale(result):
'''
    if marker not in text:
        raise RuntimeError("Priority marker not found")
    text = text.replace(marker, rules, 1)

if "REGOLA GENERALE FINANCEPLUS — AUTO DENOMINAZIONE:" not in text:
    marker = "REGOLA FINANCEPLUS PRIORITARIA — RICEVUTA DEPOSITO BILANCIO:\n"
    prompt = '''REGOLA GENERALE FINANCEPLUS — AUTO DENOMINAZIONE:
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

'''
    if marker not in text:
        raise RuntimeError("Prompt marker not found")
    text = text.replace(marker, prompt + marker, 1)

if '"bank_name": "string"' not in text:
    old = '  "document_year": "string",\n  "confidence": 0.0,\n'
    new = (
        '  "document_year": "string",\n'
        '  "bank_name": "string",\n'
        '  "period_start": "string",\n'
        '  "period_end": "string",\n'
        '  "document_quarter": "string",\n'
        '  "confidence": 0.0,\n'
    )
    if old not in text:
        raise RuntimeError("Schema marker not found")
    text = text.replace(old, new, 1)

old_ui = '''    st.info(
        "Regole automatiche attive: Ricevute deposito bilancio → NOME AZIENDA_Ricevuta deposito Bilancio d’esercizio ANNO; "
        "Visure Camerali → NOME AZIENDA_Visura Camerale; "
        "Bilanci d’esercizio → NOME AZIENDA_Bilancio d’esercizio ANNO."
    )
'''
new_ui = '''    st.info(
        "Auto-denominazione dal contenuto: Visure, Bilanci, Ricevute deposito Bilancio, "
        "Offerte, Preventivi ed Estratti conto. Gli estratti conto includono trimestre, banca e anno."
    )
'''
if old_ui in text:
    text = text.replace(old_ui, new_ui, 1)

path.write_text(text, encoding="utf-8")
print("Patch applied")
