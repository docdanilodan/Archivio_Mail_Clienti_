# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

USER_MEMORY_FILE = Path(__file__).with_name("document_ai_learning.json")
MAX_USER_EXAMPLES = 500
MAX_PROMPT_PROFILES = 30
MAX_PROMPT_EXAMPLES = 24

SEED_EXAMPLES: list[dict] = [
    {
        "source": "FinancePlus seed",
        "timestamp": "2026-08-23T00:00:00+00:00",
        "original_name": "FOOD E MEAT SRL VISURA CCIAA.pdf",
        "document_type": "Visura Camerale",
        "company_name": "FOOD E MEAT S.R.L.",
        "document_year": "",
        "document_date": "24/03/2026",
        "accepted_name": "FOOD E MEAT S.R.L._Visura Camerale.pdf",
        "naming_template": "{company_name}_Visura Camerale{extension}",
        "signature_terms": [
            "visura", "camerale", "registro", "imprese", "camera", "commercio",
            "cciaa", "dati", "anagrafici", "rea", "denominazione"
        ],
        "field_labels": [
            "denominazione", "codice fiscale", "partita iva", "numero rea",
            "sede legale", "amministratore"
        ],
    },
    {
        "source": "FinancePlus seed",
        "timestamp": "2026-08-23T00:00:00+00:00",
        "original_name": "BILANCIO 2023_SCHIANO SRL.pdf",
        "document_type": "Bilancio d’esercizio",
        "company_name": "SCHIANO S.R.L.",
        "document_year": "2023",
        "document_date": "31/12/2023",
        "accepted_name": "SCHIANO S.R.L._Bilancio d’esercizio 2023.pdf",
        "naming_template": "{company_name}_Bilancio d’esercizio {document_year}{extension}",
        "signature_terms": [
            "bilancio", "esercizio", "stato", "patrimoniale", "conto", "economico",
            "nota", "integrativa", "attivo", "passivo", "utile", "perdita"
        ],
        "field_labels": [
            "denominazione", "anno esercizio", "data chiusura esercizio",
            "totale attivo", "patrimonio netto", "totale debiti", "utile esercizio"
        ],
    },
]

STOPWORDS = {
    "alla", "alle", "allo", "anche", "come", "con", "dalla", "dalle", "dello",
    "della", "delle", "degli", "del", "dei", "che", "chiuso", "documento", "dati",
    "essere", "file", "nella", "nelle", "nello", "non", "per", "presente", "sono",
    "sul", "sulla", "sulle", "tipo", "viene", "questo", "questa", "dell", "d",
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno", "e", "o", "di",
    "a", "da", "in", "su", "tra", "fra", "al", "ai", "agli", "all"
}


def _normalized(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _label_slug(value: object) -> str:
    text = _normalized(value)
    text = re.sub(r"\s+", "_", text)
    return text[:60]


def _safe_read_json(path: Path) -> list[dict]:
    try:
        if not path.exists():
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
        return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []
    except Exception:
        return []


def load_user_memory() -> list[dict]:
    return _safe_read_json(USER_MEMORY_FILE)


def load_all_memory() -> list[dict]:
    return [*SEED_EXAMPLES, *load_user_memory()]


def save_user_memory(items: list[dict]) -> None:
    USER_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_MEMORY_FILE.write_text(
        json.dumps(items[-MAX_USER_EXAMPLES:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_user_memory() -> None:
    save_user_memory([])


def export_user_memory_bytes() -> bytes:
    return json.dumps(load_user_memory(), ensure_ascii=False, indent=2).encode("utf-8")


def import_user_memory_bytes(data: bytes) -> int:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, list):
        raise ValueError("La memoria deve essere un elenco JSON.")
    current = load_user_memory()
    current.extend(x for x in value if isinstance(x, dict))
    save_user_memory(_deduplicate_examples(current))
    return len(load_user_memory())


def _key_fields_map(result: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in result.get("key_fields", []) or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "") or "").strip()
        value = str(item.get("value", "") or "").strip()
        if label and value:
            values[_label_slug(label)] = value
    return values


def _extract_signature_terms(result: dict, limit: int = 40) -> list[str]:
    parts = [
        result.get("document_type", ""),
        result.get("summary", ""),
        result.get("preview", ""),
        result.get("reason", ""),
        " ".join(str(x.get("label", "")) for x in result.get("key_fields", []) if isinstance(x, dict)),
    ]
    tokens = re.findall(r"[a-zà-ÿ][a-z0-9à-ÿ]{2,}", _normalized(" ".join(map(str, parts))))
    counts = Counter(t for t in tokens if t not in STOPWORDS and not t.isdigit())
    return [term for term, _ in counts.most_common(limit)]


def _replace_insensitive(text: str, value: str, token: str) -> str:
    value = str(value or "").strip()
    if len(value) < 2:
        return text
    return re.sub(re.escape(value), token, text, flags=re.IGNORECASE)


def infer_naming_template(accepted_name: str, original_name: str, result: dict) -> tuple[str, dict[str, str]]:
    extension = Path(original_name).suffix
    accepted = str(accepted_name or "").strip()
    if extension and accepted.lower().endswith(extension.lower()):
        accepted = accepted[: -len(extension)] + "{extension}"
    elif extension:
        accepted += "{extension}"

    replacements = [
        (result.get("company_name", ""), "{company_name}"),
        (result.get("document_year", ""), "{document_year}"),
        (result.get("document_date", ""), "{document_date}"),
    ]
    for value, token in replacements:
        accepted = _replace_insensitive(accepted, str(value or ""), token)

    placeholder_fields: dict[str, str] = {}
    field_map = _key_fields_map(result)
    for slug, value in sorted(field_map.items(), key=lambda pair: len(pair[1]), reverse=True):
        if len(value) < 3 or value.casefold() in {
            str(result.get("company_name", "")).casefold(),
            str(result.get("document_year", "")).casefold(),
            str(result.get("document_date", "")).casefold(),
        }:
            continue
        token = "{field:" + slug + "}"
        replaced = _replace_insensitive(accepted, value, token)
        if replaced != accepted:
            accepted = replaced
            placeholder_fields[slug] = slug

    accepted = re.sub(r"\s+", " ", accepted).strip()
    return accepted, placeholder_fields


def record_correction(
    original_name: str,
    suggested_name: str,
    accepted_name: str,
    result: dict,
) -> dict:
    template, placeholder_fields = infer_naming_template(accepted_name, original_name, result)
    entry = {
        "source": "user correction",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "original_name": original_name,
        "suggested_name": suggested_name,
        "accepted_name": accepted_name,
        "document_type": str(result.get("document_type", "") or "").strip(),
        "company_name": str(result.get("company_name", "") or "").strip(),
        "document_year": str(result.get("document_year", "") or "").strip(),
        "document_date": str(result.get("document_date", "") or "").strip(),
        "summary": str(result.get("summary", "") or "")[:1200],
        "naming_template": template,
        "placeholder_fields": placeholder_fields,
        "signature_terms": _extract_signature_terms(result),
        "field_labels": [
            str(x.get("label", "") or "").strip()
            for x in result.get("key_fields", []) or []
            if isinstance(x, dict) and str(x.get("label", "") or "").strip()
        ][:30],
        "key_fields": result.get("key_fields", [])[:20],
    }
    items = load_user_memory()
    items.append(entry)
    save_user_memory(_deduplicate_examples(items))
    return entry


def _deduplicate_examples(items: list[dict]) -> list[dict]:
    seen: dict[tuple[str, str, str], dict] = {}
    for item in items:
        key = (
            _normalized(item.get("document_type", "")),
            str(item.get("naming_template", "") or "").strip(),
            str(item.get("accepted_name", "") or "").strip().casefold(),
        )
        seen[key] = item
    return list(seen.values())[-MAX_USER_EXAMPLES:]


def build_profiles() -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in load_all_memory():
        document_type = str(item.get("document_type", "") or "").strip()
        if document_type:
            groups[_normalized(document_type)].append(item)

    profiles: list[dict] = []
    for key, examples in groups.items():
        type_counter = Counter(str(x.get("document_type", "") or "").strip() for x in examples)
        template_counter = Counter(str(x.get("naming_template", "") or "").strip() for x in examples if x.get("naming_template"))
        signature_counter: Counter[str] = Counter()
        field_counter: Counter[str] = Counter()
        placeholder_fields: dict[str, str] = {}
        for example in examples:
            signature_counter.update(str(x) for x in example.get("signature_terms", []) if x)
            field_counter.update(str(x) for x in example.get("field_labels", []) if x)
            placeholder_fields.update(example.get("placeholder_fields", {}) or {})

        profiles.append({
            "profile_key": key,
            "document_type": type_counter.most_common(1)[0][0],
            "naming_template": template_counter.most_common(1)[0][0] if template_counter else "",
            "signature_terms": [x for x, _ in signature_counter.most_common(50)],
            "field_labels": [x for x, _ in field_counter.most_common(30)],
            "placeholder_fields": placeholder_fields,
            "examples": len(examples),
            "user_examples": sum(1 for x in examples if x.get("source") == "user correction"),
        })

    return sorted(profiles, key=lambda x: (x["user_examples"], x["examples"]), reverse=True)


def profile_rows() -> list[dict]:
    rows = []
    for profile in build_profiles():
        rows.append({
            "Tipologia": profile["document_type"],
            "Modello nome": profile["naming_template"] or "Solo riconoscimento",
            "Esempi": profile["examples"],
            "Correzioni utente": profile["user_examples"],
            "Campi imparati": ", ".join(profile["field_labels"][:8]),
        })
    return rows


def learning_prompt() -> str:
    profiles = build_profiles()[:MAX_PROMPT_PROFILES]
    recent = load_all_memory()[-MAX_PROMPT_EXAMPLES:]
    payload = {
        "regole_apprese": [
            {
                "tipologia": p["document_type"],
                "modello_nome": p["naming_template"],
                "parole_segnale": p["signature_terms"][:18],
                "campi_da_cercare": p["field_labels"][:15],
                "numero_esempi": p["examples"],
            }
            for p in profiles
        ],
        "esempi_recenti": [
            {
                "nome_originale": x.get("original_name", ""),
                "tipologia": x.get("document_type", ""),
                "azienda": x.get("company_name", ""),
                "anno": x.get("document_year", ""),
                "nome_accettato": x.get("accepted_name", ""),
            }
            for x in recent
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _result_terms(result: dict) -> set[str]:
    return set(_extract_signature_terms(result, limit=80))


def match_profile(result: dict) -> tuple[dict | None, float]:
    result_type = _normalized(result.get("document_type", ""))
    result_terms = _result_terms(result)
    best: dict | None = None
    best_score = 0.0

    for profile in build_profiles():
        profile_type = _normalized(profile["document_type"])
        score = 0.0
        if result_type and profile_type:
            if result_type == profile_type:
                score += 100.0
            elif result_type in profile_type or profile_type in result_type:
                score += 65.0
        signatures = set(profile.get("signature_terms", []))
        overlap = result_terms & signatures
        score += min(40.0, len(overlap) * 4.0)
        if score > best_score:
            best = profile
            best_score = score

    return (best, best_score) if best_score >= 12.0 else (None, best_score)


def _field_value(result: dict, slug: str) -> str:
    fields = _key_fields_map(result)
    if slug in fields:
        return fields[slug]
    for key, value in fields.items():
        if slug in key or key in slug:
            return value
    return ""


def render_template(template: str, result: dict, original_name: str) -> str | None:
    if not template:
        return None
    extension = Path(original_name).suffix
    values = {
        "company_name": str(result.get("company_name", "") or "").strip(),
        "document_year": str(result.get("document_year", "") or "").strip(),
        "document_date": str(result.get("document_date", "") or "").strip(),
        "document_type": str(result.get("document_type", "") or "").strip(),
        "extension": extension,
    }

    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{" + name + "}", value)

    for slug in re.findall(r"\{field:([^}]+)\}", rendered):
        rendered = rendered.replace("{field:" + slug + "}", _field_value(result, slug))

    if re.search(r"\{[^}]+\}", rendered):
        return None
    rendered = re.sub(r"\s+", " ", rendered)
    rendered = re.sub(r"[_-]{2,}", "_", rendered)
    rendered = rendered.strip(" _-")
    if extension and not rendered.lower().endswith(extension.lower()):
        rendered += extension
    return rendered or None


def apply_learned_naming(
    result: dict,
    original_name: str,
    safe_filename: Callable[[str, str], str],
) -> dict:
    if result.get("naming_rule"):
        return result

    profile, score = match_profile(result)
    if not profile:
        return result

    rendered = render_template(profile.get("naming_template", ""), result, original_name)
    if rendered:
        result["suggested_filename"] = safe_filename(rendered, original_name)
        result["naming_rule"] = f"Regola appresa: {profile['document_type']}"
        result["learning_match_score"] = round(score, 1)
        result["reason"] = (
            str(result.get("reason", "") or "").strip()
            + " Convenzione di denominazione applicata dalla memoria FinancePlus."
        ).strip()
    result["learned_profile"] = profile["document_type"]
    result["learned_fields"] = profile.get("field_labels", [])
    return result
