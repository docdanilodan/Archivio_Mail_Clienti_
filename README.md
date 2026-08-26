# FinancePlus Document AI - Archivio Mail Clienti PRO

Web app Streamlit per elaborare archivi email, estrarre allegati, ricostruire file di grandi dimensioni e classificare/rinominare automaticamente documenti con OpenAI.

Aggiornamento: **26 agosto 2026**.

## Funzioni principali

### 1. Email e allegati

- Supporto a `.eml`, `.mbox`, `.msg` e `.zip`.
- Estrazione allegati e riepilogo messaggi.
- Tabella risultati con data/ora, mittente, oggetto, sintesi e allegati.
- Esportazioni PDF, Excel, CSV e ZIP allegati.

### 2. File grandi

- Divisione locale nel browser in parti `.part0001`, `.part0002`, ecc.
- Modalita consigliata: caricamento di una parte alla volta.
- Salvataggio temporaneo su disco Streamlit.
- Ricostruzione del file originale prima del parsing.
- Controllo della sequenza delle parti caricate.

Nota: la divisione in parti migliora l'upload ma non elimina i limiti reali di RAM, disco temporaneo e timeout della piattaforma Streamlit.

### 3. Auto/Riconoscimento IA documenti

Entry point: `mail_attachment_extractor/app.py`

Modulo IA: `mail_attachment_extractor/document_ai.py`

Il motore:

- legge il contenuto reale del documento;
- riconosce tipologia e soggetto principale;
- estrae campi rilevanti;
- mostra sintesi e anteprima;
- propone un nome file professionale;
- permette correzione manuale;
- memorizza esempi di correzione durante l'uso;
- genera download singolo e ZIP dei file rinominati.

## Regole di naming FinancePlus

Esempi principali:

```text
NOME AZIENDA_Visura Camerale.pdf
NOME AZIENDA_Bilancio d'esercizio ANNO.pdf
NOME AZIENDA_Ricevuta deposito Bilancio d'esercizio ANNO.pdf
NOME AZIENDA_Offerta ANNO.pdf
NOME AZIENDA_Preventivo ANNO.pdf
NOME AZIENDA_Estratto conto TRIMESTRE BANCA ANNO.pdf
NOME AZIENDA_Centrale Rischi Banca d'Italia PERIODO.pdf
NOME AZIENDA_Fattura N.NUMERO ANNO.pdf
NOME COGNOME_Curriculum Vitae.pdf
NOME AZIENDA_Presentazione aziendale ANNO.pdf
NOME AZIENDA_Contratto di finanziamento FINANZIATORE ANNO.pdf
NOME AZIENDA_Bozza Bilancio ANNO.pdf
```

Per altre tipologie viene usato il fallback:

```text
SOGGETTO_TIPO DOCUMENTO_ANNO.estensione
```

I dati mancanti non devono essere inventati.

## OpenAI

Modello predefinito Document AI:

```text
gpt-5.6-terra
```

La chiave API deve essere configurata esclusivamente nei Secrets di Streamlit o tramite variabile d'ambiente:

```toml
OPENAI_API_KEY = "..."
```

Non inserire mai la chiave nel repository.

## Plugin e app collegate - stato 26/08/2026

La Plugin Directory e il punto principale per scoprire workflow ChatGPT/Codex. Le integrazioni FinancePlus restano basate sulle app collegate.

Stack consigliato e verificato:

| Componente | Ruolo FinancePlus |
|---|---|
| Gmail | Sorgente email e allegati |
| Google Drive | Archivio documentale e file collegati |
| Airtable | CRM/indice Clienti, Pratiche, Documenti, Email e Analisi Creditizie |
| CData Connect AI | Ponte verso GitHub, database e altre sorgenti strutturate |
| Adobe Acrobat | OCR, estrazione e operazioni PDF |
| GitHub | Versionamento, commit e workflow |
| OpenAI Platform | API e modello Document AI |
| Data Analysis ChatGPT | KPI, tabelle, grafici, Python e analisi numerica |

## Data Analysis / Data Analytics

Per FinancePlus **non serve un plugin separato chiamato "Data Analytics"**. L'analisi dei dati e una capacita nativa di ChatGPT.

Puo essere usata per:

- bilanci e riclassificazioni;
- EBITDA, EBIT, PFN, PFN/EBITDA, leverage, ROE, ROI, ROS e DSCR;
- Centrale Rischi 12/36 mesi;
- estratti conto e analisi flussi;
- CSV/XLS/XLSX;
- tabelle e grafici;
- controlli di completezza dossier;
- analisi portafoglio pratiche e stress test.

L'ambiente Python della Data Analysis non effettua chiamate API/web esterne: i dati devono essere caricati o resi disponibili tramite app/connettori collegati.

## Architettura FinancePlus aggiornata

```text
Gmail
  -> Document AI
  -> regole di naming
  -> Google Drive
  -> Airtable
  -> Data Analysis
  -> report / dossier banca
```

CData Connect AI viene usato quando servono GitHub, SQL o altre sorgenti strutturate aggiuntive.

## Airtable

Base operativa: **FinancePlus AI**.

Struttura prevista:

```text
CLIENTE
  -> Pratiche
  -> Documenti
  -> Email
  -> Analisi Creditizie
```

Le relazioni devono usare linked records, evitando di duplicare lo stesso cliente con grafie differenti.

## Sicurezza e persistenza

- Il filesystem Streamlit e temporaneo.
- La memoria locale delle correzioni non e una persistenza definitiva.
- Per memoria durevole usare Airtable, PostgreSQL, Supabase o altro storage persistente.
- Non salvare API key, password o dati sensibili nel repository.
- Non inserire IBAN completi, saldi o altri dati sensibili nei nomi dei file.
- Le correzioni di naming sono esempi riutilizzati come contesto: non equivalgono a fine-tuning del modello.

## Installazione locale

```bash
cd mail_attachment_extractor
python -m venv .venv
source .venv/bin/activate   # Mac/Linux
# .venv\Scripts\activate  # Windows
pip install -r requirements.txt
streamlit run app.py
```

## Deploy Streamlit Cloud

1. Collega il repository GitHub.
2. Main file: `mail_attachment_extractor/app.py`.
3. Configura `OPENAI_API_KEY` nei Secrets.
4. Esegui deploy/redeploy.
5. Verifica prima un PDF piccolo.
6. Testa Visura, Bilancio, Ricevuta deposito, Estratto conto e almeno una categoria aggiuntiva.

## File principali

```text
mail_attachment_extractor/
  app.py
  document_ai.py
  document_learning.py
  mail_attachment_extractor.py
  requirements.txt
.streamlit/config.toml
```

## Flusso operativo consigliato

1. Ricevi email/allegati.
2. Se necessario, dividi il file grande in parti.
3. Ricostruisci ed elabora.
4. Avvia Auto/Riconoscimento IA.
5. Controlla e conferma il nome proposto.
6. Scarica il file rinominato/ZIP.
7. Archivia in Drive.
8. Collega Cliente/Pratica/Documento in Airtable.
9. Usa Data Analysis per KPI e analisi numerica.
10. Genera report, alert o dossier banca.
