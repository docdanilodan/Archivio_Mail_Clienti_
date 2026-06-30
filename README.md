# Archivio Mail Clienti PRO - Streamlit

Web app Streamlit per scaricare allegati Gmail da mittenti predefiniti, creare cartelle per indirizzo email e azienda, eliminare duplicati e generare report CSV.

## Funzioni

- Periodo preimpostato: 01/05/2026 - 30/06/2026.
- Mittenti preimpostati.
- Struttura archivio: cartella generale / mittente / azienda / allegati.
- Rilevamento azienda da oggetto, corpo email e nome allegato.
- Cartella `Da_verificare` se l'azienda non e identificata.
- Deduplica con hash MD5 del contenuto.
- Download finale in ZIP.
- Report CSV con data, mittente, azienda, oggetto, nome file, percorso.

## Installazione locale

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Su Mac/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Credenziali Google

1. Vai su Google Cloud Console.
2. Crea un progetto.
3. Abilita Gmail API.
4. Crea credenziali OAuth Desktop App.
5. Scarica il file `client_secret.json`.
6. Caricalo nella web app quando richiesto.

## GitHub + Streamlit Cloud

1. Carica questi file in una repository GitHub.
2. Vai su Streamlit Community Cloud.
3. Collega la repo.
4. Main file: `app.py`.
5. Deploy.

Nota: su Streamlit Cloud il filesystem e temporaneo. La app genera uno ZIP da scaricare sul PC.
