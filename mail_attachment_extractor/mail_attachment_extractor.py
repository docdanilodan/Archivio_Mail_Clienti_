# -*- coding: utf-8 -*-
from __future__ import annotations
import io, mailbox, os, re, tempfile, zipfile
from dataclasses import dataclass, field
from datetime import datetime, date
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

TZ=ZoneInfo('Europe/Rome'); MAX_ZIP_FILES=5000; MAX_ZIP_BYTES=1_000_000_000; MAX_DEPTH=2

@dataclass
class Attachment: filename:str; content:bytes
@dataclass
class ParsedMail:
    source:str; index:int; dt:Optional[datetime]; sender:str; subject:str; body:str; attachments:list[Attachment]=field(default_factory=list)

def dec(v):
    if not v:return ''
    o=[]
    for p,e in decode_header(v):
        if isinstance(p,bytes):
            try:o.append(p.decode(e or 'utf-8',errors='replace'))
            except:o.append(p.decode('utf-8',errors='replace'))
        else:o.append(p)
    return ''.join(o).strip()

def safe_name(n,fallback='allegato'):
    n=PurePosixPath((n or fallback).replace('\\','/')).name
    return (re.sub(r'[<>:"/\\|?*\r\n\t]+','_',n).strip(' .')[:180] or fallback)

def parse_dt(v):
    if not v:return None
    try:
        d=parsedate_to_datetime(str(v)); d=d.replace(tzinfo=TZ) if d and d.tzinfo is None else d
        return d.astimezone(TZ) if d else None
    except:return None

def html_to_text(t):
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(t,'html.parser').get_text(' ',strip=True)
    except:return re.sub(r'(?s)<[^>]+>',' ',t)

def clean_body(t):
    if not t:return ''
    t=t.replace('\r\n','\n').replace('\r','\n')
    for pat in [r'(?im)^\s*-----Original Message-----',r'(?im)^\s*From:\s+.+$',r'(?im)^\s*Da:\s+.+$']:
        m=re.search(pat,t)
        if m and m.start()>100:t=t[:m.start()]
    return re.sub(r'\s+',' ',' '.join(x.strip() for x in t.splitlines() if x.strip() and not x.lstrip().startswith('>'))).strip()

def body_from_msg(m:Message):
    plain=[]; html=[]
    for p in (m.walk() if m.is_multipart() else [m]):
        if (p.get_content_disposition() or '').lower()=='attachment' or p.get_content_type() not in ('text/plain','text/html'):continue
        try:v=p.get_content()
        except:
            r=p.get_payload(decode=True) or b''; v=r.decode(p.get_content_charset() or 'utf-8',errors='replace')
        if isinstance(v,bytes):v=v.decode('utf-8',errors='replace')
        (plain if p.get_content_type()=='text/plain' else html).append(str(v))
    return clean_body('\n'.join(plain)) if plain else clean_body(html_to_text('\n'.join(html)))

def summary(t,max_chars=500):
    t=clean_body(t)
    if not t:return 'Messaggio senza testo utile o contenuto non leggibile.'
    t=re.sub(r'(?i)^(gentile|buongiorno|buonasera|salve|ciao)[^.!?]{0,80}[,.!?]\s*','',t)
    good=[]
    for s in re.split(r'(?<=[.!?])\s+',t):
        if len(s.strip())<20 or any(x in s.lower() for x in ['cordiali saluti','distinti saluti','privacy','sent from my iphone']):continue
        good.append(s.strip())
        if len(' '.join(good))>380 or len(good)>=3:break
    o=' '.join(good) or t
    return o if len(o)<=max_chars else o[:max_chars-1].rsplit(' ',1)[0]+'…'

def attachments_from_msg(m):
    out=[]; used=set(); n=1
    for p in m.walk():
        fn=p.get_filename(); disp=(p.get_content_disposition() or '').lower()
        if not fn and disp!='attachment':continue
        name=safe_name(dec(fn) if fn else f'allegato_{n}'); n+=1; stem,suf=Path(name).stem,Path(name).suffix; c=name; k=2
        while c.lower() in used:c=f'{stem}_{k}{suf}'; k+=1
        used.add(c.lower())
        try:r=p.get_payload(decode=True) or b''
        except:r=b''
        out.append(Attachment(c,r))
    return out

def parse_eml(data,source,index=1):
    m=BytesParser(policy=policy.default).parsebytes(data)
    return ParsedMail(source,index,parse_dt(m.get('Date')),dec(m.get('From')) or '(mittente non disponibile)',dec(m.get('Subject')) or '(senza oggetto)',body_from_msg(m),attachments_from_msg(m))

def parse_mbox(data,source):
    out=[]
    with tempfile.NamedTemporaryFile(suffix='.mbox',delete=False) as t:t.write(data); path=t.name
    try:
        b=mailbox.mbox(path,create=False)
        try:
            for i,m in enumerate(b,1):
                try:out.append(parse_eml(m.as_bytes(policy=policy.default),source,i))
                except Exception as e:out.append(ParsedMail(source,i,None,'(errore parsing)',str(e),'',[]))
        finally:b.close()
    finally:
        try:os.remove(path)
        except OSError:pass
    return out

def parse_msg(data,source,index=1):
    try:import extract_msg
    except ImportError:raise RuntimeError('Per i file .msg installare extract-msg')
    with tempfile.NamedTemporaryFile(suffix='.msg',delete=False) as t:t.write(data); path=t.name
    try:
        m=extract_msg.Message(path); body=getattr(m,'body',None) or ''
        if not body:
            h=getattr(m,'htmlBody',None) or ''; h=h.decode('utf-8',errors='replace') if isinstance(h,bytes) else h; body=html_to_text(str(h))
        at=[]
        for i,a in enumerate(getattr(m,'attachments',[]) or [],1):
            name=safe_name(getattr(a,'longFilename',None) or getattr(a,'shortFilename',None) or f'allegato_{i}')
            try:r=getattr(a,'data',b''); r=r() if callable(r) else r; r=bytes(r or b'')
            except:r=b''
            at.append(Attachment(name,r))
        x=ParsedMail(source,index,parse_dt(getattr(m,'date','')),str(getattr(m,'sender',None) or '(mittente non disponibile)'),str(getattr(m,'subject',None) or '(senza oggetto)'),clean_body(body),at)
        try:m.close()
        except:pass
        return x
    finally:
        try:os.remove(path)
        except OSError:pass

def parse_zip(data,source,depth=0):
    if depth>MAX_DEPTH:return [],[f'{source}: ZIP annidato ignorato oltre profondità {MAX_DEPTH}']
    out=[]; warns=[]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos=z.infolist()
        if len(infos)>MAX_ZIP_FILES:raise RuntimeError('ZIP con troppi file')
        if sum(x.file_size for x in infos)>MAX_ZIP_BYTES:raise RuntimeError('ZIP troppo grande dopo decompressione')
        for inf in infos:
            if inf.is_dir():continue
            ext=Path(inf.filename).suffix.lower(); src=f'{source} > {inf.filename}'
            if ext not in ('.eml','.mbox','.msg','.zip'):continue
            try:
                r=z.read(inf)
                if ext=='.eml':out.append(parse_eml(r,src))
                elif ext=='.mbox':out.extend(parse_mbox(r,src))
                elif ext=='.msg':out.append(parse_msg(r,src))
                else:a,b=parse_zip(r,src,depth+1);out.extend(a);warns.extend(b)
            except Exception as e:warns.append(f'{src}: {e}')
    return out,warns

def parse_upload(name,data):
    try:
        e=Path(name).suffix.lower()
        if e=='.eml':return [parse_eml(data,name)],[]
        if e=='.mbox':return parse_mbox(data,name),[]
        if e=='.msg':return [parse_msg(data,name)],[]
        if e=='.zip':return parse_zip(data,name)
        return [],[f'{name}: formato non supportato']
    except Exception as x:return [],[f'{name}: {x}']

def fmt(d):return d.astimezone(TZ).strftime('%d/%m/%Y %H:%M:%S') if d else ''
def sort_key(m):return (m.dt is None,m.dt or datetime.max.replace(tzinfo=TZ))
def dataframe(ms):
    return pd.DataFrame([{'Data e ora':fmt(m.dt),'DataISO':m.dt.date().isoformat() if m.dt else '','Mittente':m.sender,'Oggetto':m.subject,'Sintesi del contenuto':summary(m.body),'Allegati':'; '.join(a.filename for a in m.attachments) if m.attachments else 'Nessun allegato','N. allegati':len(m.attachments),'Sorgente':m.source} for m in sorted(ms,key=sort_key)])

def xlsx_bytes(df):
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine='openpyxl') as w:
        df.drop(columns=['DataISO'],errors='ignore').to_excel(w,index=False,sheet_name='Email'); ws=w.book['Email'];ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for c,v in {'A':20,'B':38,'C':48,'D':85,'E':70,'F':12,'G':55}.items():ws.column_dimensions[c].width=v
        from openpyxl.styles import Alignment,Font
        for c in ws[1]:c.font=Font(bold=True)
        for row in ws.iter_rows(min_row=2):
            for c in row:c.alignment=Alignment(vertical='top',wrap_text=True)
    return b.getvalue()

def pdf_bytes(df):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer,PageBreak
    b=io.BytesIO(); doc=SimpleDocTemplate(b,pagesize=landscape(A4),rightMargin=10*mm,leftMargin=10*mm,topMargin=12*mm,bottomMargin=12*mm)
    styles=getSampleStyleSheet(); title=ParagraphStyle('fp',parent=styles['Title'],textColor=colors.HexColor('#12304A'),alignment=TA_CENTER,fontSize=18,spaceAfter=8)
    small=ParagraphStyle('sm',parent=styles['BodyText'],fontSize=6.5,leading=8)
    story=[Paragraph('FINANCEPLUS | Archivio Mail',title),Paragraph(f'Report cronologico - {len(df)} messaggi',styles['Normal']),Spacer(1,5*mm)]
    cols=['Data e ora','Mittente','Oggetto','Sintesi del contenuto','Allegati']; data=[[Paragraph(f'<b>{x}</b>',small) for x in cols]]
    for _,r in df.iterrows():data.append([Paragraph(str(r[c]).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'),small) for c in cols])
    t=Table(data,colWidths=[31*mm,45*mm,52*mm,91*mm,56*mm],repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#12304A')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#C7A06A')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F4F6F8')])]))
    story.append(t);doc.build(story);return b.getvalue()

def attachments_zip(ms,df):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('report_email.csv',df.drop(columns=['DataISO'],errors='ignore').to_csv(index=False).encode('utf-8-sig'))
        try:z.writestr('report_email.xlsx',xlsx_bytes(df));z.writestr('report_email.pdf',pdf_bytes(df))
        except:pass
        for i,m in enumerate(sorted(ms,key=sort_key),1):
            d=m.dt.strftime('%Y-%m-%d_%H-%M-%S') if m.dt else 'senza_data'; subj=re.sub(r'[^\w.-]+','_',m.subject)[:60] or 'email'
            for a in m.attachments:z.writestr(f'allegati/{i:04d}_{d}_{subj}/{safe_name(a.filename)}',a.content)
    return b.getvalue()

def css():
    st.markdown('''<style>
    .stApp{background:#f5f7fa}.block-container{padding-top:1.5rem;max-width:1500px}
    h1,h2,h3{color:#12304A!important}.fp-head{background:linear-gradient(120deg,#0D2940,#173F5F);padding:22px 26px;border-radius:16px;border-bottom:4px solid #B88952;color:white;margin-bottom:18px}.fp-head h1{color:white!important;margin:0;font-size:30px}.fp-head p{margin:5px 0 0;color:#dfe8ef}
    div[data-testid="stMetric"]{background:white;border:1px solid #dfe4e8;border-top:3px solid #B88952;padding:12px;border-radius:12px;box-shadow:0 2px 8px #0000000a}
    .stButton>button,.stDownloadButton>button{border-radius:9px;border:1px solid #B88952;font-weight:700}
    </style>''',unsafe_allow_html=True)

def app():
    st.set_page_config(page_title='FinancePlus | Archivio Mail',page_icon='📬',layout='wide');css()
    st.markdown('<div class="fp-head"><h1>📬 FinancePlus | Archivio Mail</h1><p>Estrazione allegati • Sintesi mail • Report cronologico • Export PDF / Excel / ZIP</p></div>',unsafe_allow_html=True)
    files=st.file_uploader('Carica EML, MSG, MBOX o ZIP',type=['eml','msg','mbox','zip'],accept_multiple_files=True)
    if files and st.button('⚙️ Elabora archivio',type='primary',use_container_width=True):
        ms=[];ws=[];bar=st.progress(0)
        for i,f in enumerate(files,1):a,b=parse_upload(f.name,f.getvalue());ms.extend(a);ws.extend(b);bar.progress(i/len(files))
        bar.empty();st.session_state.mails=ms;st.session_state.warns=ws
    ms=st.session_state.get('mails',[]);ws=st.session_state.get('warns',[])
    if ws:
        with st.expander(f'Avvisi ({len(ws)})'):
            for w in ws:st.warning(w)
    if not ms:
        st.info('Carica uno o più file e premi “Elabora archivio”.');return
    df=dataframe(ms); total_att=sum(len(m.attachments) for m in ms); total_bytes=sum(len(a.content) for m in ms for a in m.attachments)
    a,b,c,d=st.columns(4);a.metric('Mail elaborate',len(ms));b.metric('Mail con allegati',sum(bool(m.attachments) for m in ms));c.metric('Allegati estratti',total_att);d.metric('Dimensione allegati',f'{total_bytes/1024**2:.2f} MB')
    st.subheader('🔎 Filtri archivio')
    f1,f2,f3,f4=st.columns([1.1,1.1,1.5,2])
    dated=[m.dt.date() for m in ms if m.dt]; mind=min(dated) if dated else date.today();maxd=max(dated) if dated else date.today()
    start=f1.date_input('Dal',value=mind,min_value=mind,max_value=maxd);end=f2.date_input('Al',value=maxd,min_value=mind,max_value=maxd)
    senders=sorted(x for x in df['Mittente'].dropna().unique());sel=f3.multiselect('Mittente',senders,placeholder='Tutti i mittenti');q=f4.text_input('Ricerca libera',placeholder='Oggetto, sintesi, allegato…').strip()
    only=st.checkbox('Mostra solo mail con allegati')
    show=df.copy(); show=show[(show['DataISO']=='')|((show['DataISO']>=start.isoformat())&(show['DataISO']<=end.isoformat()))]
    if sel:show=show[show['Mittente'].isin(sel)]
    if only:show=show[show['N. allegati']>0]
    if q:show=show[show.astype(str).apply(lambda x:x.str.contains(re.escape(q),case=False,na=False,regex=True)).any(axis=1)]
    st.caption(f'Risultati visualizzati: {len(show)} su {len(df)}')
    display=show[['Data e ora','Mittente','Oggetto','Sintesi del contenuto','Allegati','N. allegati']]
    st.dataframe(display,use_container_width=True,hide_index=True,height=520,column_config={'Sintesi del contenuto':st.column_config.TextColumn(width='large'),'Allegati':st.column_config.TextColumn(width='large')})
    st.subheader('📦 Esporta risultati filtrati')
    e1,e2,e3,e4=st.columns(4)
    e1.download_button('📄 Report PDF',pdf_bytes(show),'FinancePlus_Report_Mail.pdf','application/pdf',use_container_width=True)
    e2.download_button('📊 Report Excel',xlsx_bytes(show),'FinancePlus_Report_Mail.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
    e3.download_button('🧾 Report CSV',show.drop(columns=['DataISO'],errors='ignore').to_csv(index=False).encode('utf-8-sig'),'FinancePlus_Report_Mail.csv','text/csv',use_container_width=True)
    e4.download_button('📎 Archivio allegati ZIP',attachments_zip(ms,show),'FinancePlus_Allegati_Mail.zip','application/zip',use_container_width=True)
    with st.expander('📚 Dettaglio messaggi'):
        for i,m in enumerate(sorted(ms,key=sort_key),1):
            with st.expander(f'{i:04d} | {fmt(m.dt) or "senza data"} | {m.subject[:100]}'):
                st.write('**Mittente:**',m.sender);st.write('**Sintesi:**',summary(m.body));st.write('**Allegati:**',', '.join(a.filename for a in m.attachments) or 'Nessuno')

if __name__=='__main__':app()
