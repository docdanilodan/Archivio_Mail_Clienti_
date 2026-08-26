# FinancePlus - Aggiornamento Plugin, App e Data Analysis

Data revisione: **26 agosto 2026**

## Esito

Lo stack FinancePlus consigliato e verificato e:

```text
Gmail
  -> Document AI
  -> regole di naming
  -> Google Drive
  -> Airtable
  -> Data Analysis nativa di ChatGPT
  -> report / dossier banca
```

CData Connect AI viene usato quando servono GitHub, SQL o altre sorgenti strutturate aggiuntive.

## Plugin Directory

Dal 9 luglio 2026 la directory delle App e confluita nella **Plugin Directory**. I plugin sono il punto principale per scoprire workflow in ChatGPT e Codex; possono includere app, skill e app template. Le connessioni app esistenti restano utilizzabili.

Riferimenti ufficiali OpenAI:

- https://help.openai.com/en/articles/20001256
- https://help.openai.com/en/articles/11487775

## Data Analysis / Data Analytics

Per FinancePlus non e necessario un plugin separato denominato "Data Analytics".

La **Data Analysis di ChatGPT** e una capacita nativa e supporta, in base al piano/modello/configurazione:

- XLS / XLSX / CSV
- PDF
- JSON / XML / YAML
- TXT / Markdown
- tabelle e grafici
- analisi supportate da codice Python

Riferimento ufficiale:

- https://help.openai.com/en/articles/8437071

### Utilizzo FinancePlus

- bilanci: EBITDA, EBIT, PFN, PFN/EBITDA, leverage, ROE, ROI, ROS e DSCR;
- Centrale Rischi: trend accordato/utilizzato, sconfinamenti, concentrazioni e anomalie;
- estratti conto: saldi medi, ricorrenze, movimenti e tensioni di liquidita;
- Airtable/CSV: portafoglio pratiche, completezza dossier, scadenze e alert;
- reportistica: tabelle, grafici e dataset di supporto al dossier banca.

L'ambiente Python della Data Analysis non deve essere usato per chiamare API esterne direttamente: i dati vanno caricati oppure resi disponibili tramite app/connettori.

## App/integrazioni verificate

| Componente | Stato | Ruolo |
|---|---|---|
| Gmail | connesso | email e allegati |
| Google Drive | connesso | archivio e file collegati |
| Airtable | connesso | CRM e indice documentale |
| CData Connect AI | connesso | GitHub / SQL / sorgenti strutturate |
| GitHub | connesso | codice, commit e workflow |
| Adobe Acrobat | disponibile | OCR e operazioni PDF specialistiche |
| OpenAI Platform | configurato per API | Document AI |
| Data Analysis | nativo | KPI, Python, tabelle e grafici |

## CData Connect AI

Connessioni verificate durante la revisione:

- `GitHubConnection` - driver GitHub - permessi: Select, Insert, Update, Delete, Execute
- `SampleConnection1` - PostgreSQL - Select
- `SampleConnection2` - MySQL - Select

## Airtable

Base verificata: **FinancePlus AI**.

Architettura dati raccomandata:

```text
CLIENTE
  -> Pratiche
  -> Documenti
  -> Email
  -> Analisi Creditizie
```

Usare linked records e non semplici campi testo per Cliente/Pratica quando possibile.

## Google Drive

Drive e utilizzato come archivio documentale e come fonte collegata a ChatGPT. Sono stati rilevati file e cartelle FinancePlus accessibili nella connessione.

## Gmail

La connessione Gmail e operativa e consente ricerca, lettura di email/thread/allegati, etichette e azioni esplicite.

## Document AI

Il modulo `mail_attachment_extractor/document_ai.py` continua a gestire:

- Visura Camerale
- Bilancio d'esercizio
- Ricevuta deposito Bilancio
- Offerta
- Preventivo
- Estratto conto
- Centrale Rischi Banca d'Italia
- Fattura
- Curriculum Vitae
- Presentazione aziendale
- Contratto di finanziamento
- Bozza Bilancio
- fallback `SOGGETTO_TIPO DOCUMENTO_ANNO`

## Sicurezza

- `OPENAI_API_KEY` esclusivamente nei Secrets di Streamlit o variabile ambiente.
- Nessuna API key nel repository.
- Nessun dato bancario sensibile nei nomi file.
- Il filesystem Streamlit e temporaneo.
- Per memoria durevole usare Airtable/PostgreSQL/Supabase o altra persistenza esterna.

## Manuali associati

La documentazione aggiornata al 26/08/2026 comprende:

1. Guida facile per programmare FinancePlus Document AI.
2. Manuale d'uso illustrato con schermate reali.
3. Guida rapida d'uso aggiornata Plugin + Data Analysis.

Questa nota e il `README.md` del repository devono essere mantenuti allineati alle evoluzioni dell'app.