from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Preformatted
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from pathlib import Path

out = Path('/mnt/data/Archivio_Mail_Clienti_Streamlit/Guida_Archivio_Mail_Clienti_Streamlit.pdf')
doc = SimpleDocTemplate(str(out), pagesize=A4, rightMargin=1.6*cm, leftMargin=1.6*cm, topMargin=1.4*cm, bottomMargin=1.4*cm)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleBlue', parent=styles['Title'], textColor=colors.HexColor('#0B3A66'), fontSize=24, leading=28, spaceAfter=18))
styles.add(ParagraphStyle(name='H1Blue', parent=styles['Heading1'], textColor=colors.HexColor('#0B3A66'), fontSize=16, leading=20, spaceBefore=12, spaceAfter=8))
styles.add(ParagraphStyle(name='H2Blue', parent=styles['Heading2'], textColor=colors.HexColor('#0B3A66'), fontSize=13, leading=16, spaceBefore=8, spaceAfter=5))
styles.add(ParagraphStyle(name='BodyX', parent=styles['BodyText'], fontSize=9.5, leading=13))
styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], fontSize=8, leading=10, textColor=colors.HexColor('#374151')))

def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor('#0B3A66'))
    canvas.rect(0, A4[1]-0.55*cm, A4[0], 0.55*cm, fill=1, stroke=0)
    canvas.setFont('Helvetica-Bold', 8)
    canvas.setFillColor(colors.white)
    canvas.drawString(1.6*cm, A4[1]-0.36*cm, 'Archivio Mail Clienti PRO - Streamlit')
    canvas.setFillColor(colors.HexColor('#6B7280'))
    canvas.setFont('Helvetica', 8)
    canvas.drawRightString(A4[0]-1.6*cm, 0.8*cm, f'Pagina {doc.page}')
    canvas.restoreState()

story=[]
story.append(Paragraph('Archivio Mail Clienti PRO<br/>GitHub + Streamlit', styles['TitleBlue']))
story.append(Paragraph('Guida operativa per installare, pubblicare e usare la web app che scarica allegati Gmail, li ordina per mittente e azienda, elimina duplicati e genera uno ZIP da salvare sul Desktop.', styles['BodyX']))
story.append(Spacer(1, 0.4*cm))

data = [
    ['Funzione', 'Descrizione'],
    ['Periodo', '01/05/2026 - 30/06/2026 modificabile dalla dashboard'],
    ['Mittenti', '8 indirizzi gia configurati nella web app'],
    ['Cartelle', 'Cartella generale / mittente / azienda'],
    ['Azienda', 'Rilevata da oggetto, testo email e nome allegato'],
    ['Duplicati', 'Riconoscimento tramite MD5 del contenuto'],
    ['Output', 'ZIP scaricabile e report CSV']
]
t=Table(data, colWidths=[4*cm, 12*cm])
t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0B3A66')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#D1D5DB')),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),8.5),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#F8FAFC')])]))
story.append(t)
story.append(PageBreak())

sections = [
('1. File del pacchetto', '''Il pacchetto contiene: app.py, requirements.txt, README.md, cartella .streamlit, guida PDF e file .gitignore. app.py e il cuore della web app Streamlit.'''),
('2. Installazione locale su PC', '''Installa Python, apri il Prompt dei comandi nella cartella del progetto e lancia: python -m venv .venv, poi .venv\\Scripts\\activate, poi pip install -r requirements.txt, infine streamlit run app.py.'''),
('3. Credenziali Google', '''Serve un file OAuth chiamato client_secret.json. Da Google Cloud Console crea un progetto, abilita Gmail API, crea credenziali OAuth di tipo Desktop App e scarica il JSON. La web app chiede di caricarlo nella sidebar.'''),
('4. Uso della dashboard', '''Imposta data inizio 01/05/2026, data fine 30/06/2026, controlla i mittenti, premi Scarica allegati e genera archivio. Dopo l'autorizzazione Google, la app elabora le email e produce un pulsante per scaricare lo ZIP.'''),
('5. Struttura archivio', '''Lo ZIP contiene la cartella generale ALLEGATI_MAIL_01-05-2026_30-06-2026. Dentro: una cartella per ogni indirizzo mittente, poi una cartella per ogni azienda. Se il nome azienda non e certo, il file viene messo in Da_verificare.'''),
('6. Duplicati', '''La app calcola l'hash MD5 di ogni allegato. Se due file hanno lo stesso contenuto, il secondo viene registrato nel report come duplicato e non viene risalvato. Questo evita copie inutili anche se il nome file cambia.'''),
('7. GitHub', '''Crea una repository GitHub, carica tutti i file del pacchetto, conserva requirements.txt nella radice e verifica che app.py sia nella radice. Non caricare token.json o client_secret.json pubblicamente.'''),
('8. Streamlit Cloud', '''Su Streamlit Community Cloud crea una nuova app, collega la repository GitHub, imposta Main file path: app.py e avvia il deploy. Nota: il filesystem cloud e temporaneo, quindi scarica sempre lo ZIP finale.'''),
('9. Salvataggio sul Desktop', '''Dopo il download dello ZIP, spostalo o estrailo sul Desktop del PC. In Windows: tasto destro sul file ZIP, Estrai tutto, scegli Desktop come destinazione.'''),
('10. Sicurezza', '''Non pubblicare credenziali Google in repository pubbliche. Per uso professionale, usa repository privata e aggiorna periodicamente i token. La app usa sola lettura Gmail.''')
]
for title, body in sections:
    story.append(Paragraph(title, styles['H1Blue']))
    story.append(Paragraph(body, styles['BodyX']))
    story.append(Spacer(1, 0.25*cm))

story.append(Paragraph('Comandi rapidi', styles['H1Blue']))
story.append(Preformatted('''python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py''', styles['Code'] if 'Code' in styles else styles['BodyText']))

story.append(Paragraph('Mittenti preconfigurati', styles['H1Blue']))
for m in ['elibetty731@gmail.com','Valentinaboratto82@gmail.com','stefano.faraone@eurofintechsrl.it','praticheBS@proton.me','sergio.pedolazzi@katudi.it','paolo.baldinelli@katudi.it','pratiche@katudi.it','niccolo.sovico@ener2crowd.com']:
    story.append(Paragraph('- ' + m, styles['BodyX']))

doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
print(out)
