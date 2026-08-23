# -*- coding: utf-8 -*-
from __future__ import annotations

import io, mailbox, os, re, tempfile, zipfile
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

TZ = ZoneInfo('Europe/Rome')
MAX_ZIP_FILES = 5000
MAX_ZIP_BYTES = 1_000_000_000
MAX_DEPTH = 2

@dataclass
class Attachment:
    filename: str
    content: bytes

@dataclass
class ParsedMail:
    source: str
    index: int
    dt: Optional[datetime]
    sender: str
    subject: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)


def dec(value):
    if not value: return ''
    out=[]
    for part, enc in decode_header(value):
        if isinstance(part, bytes):
            try: out.append(part.decode(enc or 'utf-8', errors='replace'))
            except Exception: out.append(part.decode('utf-8', errors='replace'))
        else: out.append(part)
    return ''.join(out).strip()


def safe_name(name, fallback='allegato'):
    name = PurePosixPath((name or fallback).replace('\\','/')).name
    name = re.sub(r'[<>:"/\\|?*\r\n\t]+','_',name).strip(' .')
    return name[:180] or fallback


def parse_dt(value):
    if not value: return None
    try:
        d=parsedate_to_datetime(str(value))
        if d and d.tzinfo is None: d=d.replace(tzinfo=TZ)
        return d.astimezone(TZ) if d else None
    except Exception: return None


def html_to_text(txt):
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(txt,'html.parser').get_text(' ',strip=True)
    except Exception:
        return re.sub(r'(?s)<[^>]+>',' ',txt)


def clean_body(txt):
    if not txt: return ''
    txt=txt.replace('\r\n','\n').replace('\r','\n')
    for marker in [r'(?im)^\s*-----Original Message-----',r'(?im)^\s*From:\s+.+$',r'(?im)^\s*Da:\s+.+$']:
        m=re.search(marker,txt)
        if m and m.start()>100: txt=txt[:m.start()]
    lines=[x.strip() for x in txt.splitlines() if x.strip() and not x.lstrip().startswith('>')]
    return re.sub(r'\s+',' ',' '.join(lines)).strip()


def body_from_msg(msg: Message):
    plain=[]; html=[]
    parts=msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        if (p.get_content_disposition() or '').lower()=='attachment': continue
        if p.get_content_type() not in ('text/plain','text/html'): continue
        try: val=p.get_content()
        except Exception:
            raw=p.get_payload(decode=True) or b''
            val=raw.decode(p.get_content_charset() or 'utf-8',errors='replace')
        if isinstance(val,bytes): val=val.decode('utf-8',errors='replace')
        (plain if p.get_content_type()=='text/plain' else html).append(str(val))
    txt='\n'.join(plain).strip()
    if txt: return clean_body(txt)
    return clean_body(html_to_text('\n'.join(html)))


def summary(txt, max_chars=500):
    txt=clean_body(txt)
    if not txt: return 'Messaggio senza testo utile o contenuto non leggibile.'
    txt=re.sub(r'(?i)^(gentile|buongiorno|buonasera|salve|ciao)[^.!?]{0,80}[,.!?]\s*','',txt)
    parts=re.split(r'(?<=[.!?])\s+',txt)
    good=[]
    for s in parts:
        if len(s.strip())<20: continue
        if any(x in s.lower() for x in ['cordiali saluti','distinti saluti','privacy','sent from my iphone']): continue
        good.append(s.strip())
        if len(' '.join(good))>380 or len(good)>=3: break
    out=' '.join(good) or txt
    return out if len(out)<=max_chars else out[:max_chars-1].rsplit(' ',1)[0]+'…'


def attachments_from_msg(msg):
    out=[]; used=set(); n=1
    for p in msg.walk():
        fn=p.get_filename(); disp=(p.get_content_disposition() or '').lower()
        if not fn and disp!='attachment': continue
        name=safe_name(dec(fn) if fn else f'allegato_{n}'); n+=1
        stem,suf=Path(name).stem,Path(name).suffix; cand=name; k=2
        while cand.lower() in used:
            cand=f'{stem}_{k}{suf}'; k+=1
        used.add(cand.lower())
        try: raw=p.get_payload(decode=True) or b''
        except Exception: raw=b''
        out.append(Attachment(cand,raw))
    return out


def parse_eml(data, source, index=1):
    msg=BytesParser(policy=policy.default).parsebytes(data)
    return ParsedMail(source,index,parse_dt(msg.get('Date')),dec(msg.get('From')) or '(mittente non disponibile)',dec(msg.get('Subject')) or '(senza oggetto)',body_from_msg(msg),attachments_from_msg(msg))


def parse_mbox(data, source):
    out=[]
    with tempfile.NamedTemporaryFile(suffix='.mbox',delete=False) as t:
        t.write(data); path=t.name
    try:
        box=mailbox.mbox(path,create=False)
        try:
            for i,m in enumerate(box,1):
                try: out.append(parse_eml(m.as_bytes(policy=policy.default),source,i))
                except Exception as e: out.append(ParsedMail(source,i,None,'(errore parsing)',str(e),'',[]))
        finally: box.close()
    finally:
        try: os.remove(path)
        except OSError: pass
    return out


def parse_msg(data, source, index=1):
    try: import extract_msg
    except ImportError: raise RuntimeError('Per i file .msg installare extract-msg')
    with tempfile.NamedTemporaryFile(suffix='.msg',delete=False) as t:
        t.write(data); path=t.name
    try:
        m=extract_msg.Message(path)
        body=getattr(m,'body',None) or ''
        if not body:
            h=getattr(m,'htmlBody',None) or ''
            if isinstance(h,bytes): h=h.decode('utf-8',errors='replace')
            body=html_to_text(str(h))
        at=[]
        for i,a in enumerate(getattr(m,'attachments',[]) or [],1):
            name=safe_name(getattr(a,'longFilename',None) or getattr(a,'shortFilename',None) or f'allegato_{i}')
            try:
                raw=getattr(a,'data',b''); raw=raw() if callable(raw) else raw; raw=bytes(raw or b'')
            except Exception: raw=b''
            at.append(Attachment(name,raw))
        result=ParsedMail(source,index,parse_dt(getattr(m,'date','')),str(getattr(m,'sender',None) or '(mittente non disponibile)'),str(getattr(m,'subject',None) or '(senza oggetto)'),clean_body(body),at)
        try: m.close()
        except Exception: pass
        return result
    finally:
        try: os.remove(path)
        except OSError: pass


def parse_zip(data, source, depth=0):
    if depth>MAX_DEPTH: return [],[f'{source}: ZIP annidato ignorato oltre profondità {MAX_DEPTH}']
    out=[]; warns=[]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos=z.infolist()
        if len(infos)>MAX_ZIP_FILES: raise RuntimeError('ZIP con troppi file')
        if sum(x.file_size for x in infos)>MAX_ZIP_BYTES: raise RuntimeError('ZIP troppo grande dopo decompressione')
        for inf in infos:
            if inf.is_dir(): continue
            name=inf.filename; ext=Path(name).suffix.lower(); src=f'{source} > {name}'
            if ext not in ('.eml','.mbox','.msg','.zip'): continue
            try:
                raw=z.read(inf)
                if ext=='.eml': out.append(parse_eml(raw,src))
                elif ext=='.mbox': out.extend(parse_mbox(raw,src))
                elif ext=='.msg': out.append(parse_msg(raw,src))
                else:
                    a,b=parse_zip(raw,src,depth+1); out.extend(a); warns.extend(b)
            except Exception as e: warns.append(f'{src}: {e}')
    return out,warns


def parse_upload(name,data):
    ext=Path(name).suffix.lower()
    try:
        if ext=='.eml': return [parse_eml(data,name)],[]
        if ext=='.mbox': return parse_mbox(data,name),[]
        if ext=='.msg': return [parse_msg(data,name)],[]
        if ext=='.zip': return parse_zip(data,name)
        return [],[f'{name}: formato non supportato']
    except Exception as e: return [],[f'{name}: {e}']


def fmt(d): return d.astimezone(TZ).strftime('%d/%m/%Y %H:%M:%S') if d else ''

def sort_key(m): return (m.dt is None,m.dt or datetime.max.replace(tzinfo=TZ))


def dataframe(mails):
    rows=[]
    for m in sorted(mails,key=sort_key):
        rows.append({'Data e ora':fmt(m.dt),'Mittente':m.sender,'Oggetto':m.subject,'Sintesi del contenuto':summary(m.body),'Allegati':'; '.join(a.filename for a in m.attachments) if m.attachments else 'Nessun allegato','N. allegati':len(m.attachments),'Sorgente':m.source})
    return pd.DataFrame(rows)


def xlsx_bytes(df):
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine='openpyxl') as w:
        df.to_excel(w,index=False,sheet_name='Email')
        ws=w.book['Email']; ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
        widths={'A':20,'B':38,'C':48,'D':85,'E':70,'F':12,'G':55}
        for c,v in widths.items(): ws.column_dimensions[c].width=v
        from openpyxl.styles import Alignment,Font
        for c in ws[1]: c.font=Font(bold=True)
        for row in ws.iter_rows(min_row=2):
            for c in row: c.alignment=Alignment(vertical='top',wrap_text=True)
    return b.getvalue()


def attachments_zip(mails,df):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('report_email.csv',df.to_csv(index=False).encode('utf-8-sig'))
        try: z.writestr('report_email.xlsx',xlsx_bytes(df))
        except Exception: pass
        for i,m in enumerate(sorted(mails,key=sort_key),1):
            if not m.attachments: continue
            d=m.dt.strftime('%Y-%m-%d_%H-%M-%S') if m.dt else 'senza_data'
            subj=re.sub(r'[^\w.-]+','_',m.subject)[:60] or 'email'
            for a in m.attachments: z.writestr(f'allegati/{i:04d}_{d}_{subj}/{safe_name(a.filename)}',a.content)
    return b.getvalue()


def app():
    st.set_page_config(page_title='Mail Attachment Extractor',page_icon='📬',layout='wide')
    st.title('📬 Mail Attachment Extractor')
    st.caption('Carica EML, MSG, MBOX o ZIP. Estrazione allegati, sintesi e tabella cronologica.')
    files=st.file_uploader('Carica uno o più file',type=['eml','msg','mbox','zip'],accept_multiple_files=True)
    if not files:
        st.info('Carica almeno un file per iniziare.'); return
    if st.button('Elabora mail',type='primary',use_container_width=True):
        mails=[]; warns=[]; bar=st.progress(0)
        for i,f in enumerate(files,1):
            a,b=parse_upload(f.name,f.getvalue()); mails.extend(a); warns.extend(b); bar.progress(i/len(files))
        bar.empty(); st.session_state.mails=mails; st.session_state.warns=warns
    mails=st.session_state.get('mails',[]); warns=st.session_state.get('warns',[])
    if warns:
        with st.expander(f'Avvisi ({len(warns)})'):
            for w in warns: st.warning(w)
    if not mails: return
    df=dataframe(mails)
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Mail elaborate',len(mails)); c2.metric('Mail con allegati',sum(bool(m.attachments) for m in mails)); c3.metric('Allegati estratti',sum(len(m.attachments) for m in mails)); c4.metric('Dimensione allegati',f"{sum(len(a.content) for m in mails for a in m.attachments)/1024**2:.2f} MB")
    st.subheader('Tabella riepilogativa')
    only=st.checkbox('Solo mail con allegati')
    q=st.text_input('Cerca in mittente, oggetto, sintesi o allegati').strip()
    show=df.copy()
    if only: show=show[show['N. allegati']>0]
    if q:
        mask=show.astype(str).apply(lambda c:c.str.contains(re.escape(q),case=False,na=False,regex=True)).any(axis=1); show=show[mask]
    st.dataframe(show[['Data e ora','Mittente','Oggetto','Sintesi del contenuto','Allegati','N. allegati']],use_container_width=True,hide_index=True)
    st.subheader('Download')
    a,b,c=st.columns(3)
    a.download_button('⬇️ Tutti gli allegati (.zip)',attachments_zip(mails,df),'archivio_allegati_email.zip','application/zip',use_container_width=True)
    b.download_button('⬇️ Tabella (.csv)',df.to_csv(index=False).encode('utf-8-sig'),'report_email.csv','text/csv',use_container_width=True)
    try: c.download_button('⬇️ Tabella (.xlsx)',xlsx_bytes(df),'report_email.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
    except Exception: c.info('Excel non disponibile')

if __name__=='__main__': app()
