# Entry point Streamlit per Mail Attachment Extractor
# Versione completa disponibile come file mail_attachment_extractor.py generato nel progetto.

import runpy
from pathlib import Path

app_file = Path(__file__).with_name("mail_attachment_extractor.py")
if not app_file.exists():
    raise FileNotFoundError("File mail_attachment_extractor.py non trovato nella cartella dell'app.")
runpy.run_path(str(app_file), run_name="__main__")
