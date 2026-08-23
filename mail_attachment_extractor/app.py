# -*- coding: utf-8 -*-
from __future__ import annotations

import mailbox
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import mail_attachment_extractor as core

PART_RE = re.compile(r"^(?P<base>.+)\.part(?P<num>\d{4,})$", re.IGNORECASE)
SUPPORTED = {".mbox", ".zip", ".eml", ".msg"}


def parse_part_name(name: str):
    m = PART_RE.match(Path(name).name)
    if not m:
        return None
    return m.group("base"), int(m.group("num"))


def validate_part_records(records):
    if not records:
        raise ValueError("Nessuna parte selezionata.")
    bases = {r[0] for r in records}
    if len(bases) != 1:
        raise ValueError("Le parti appartengono a file originali diversi.")
    records = sorted(records, key=lambda x: x[1])
    nums = [r[1] for r in records]
    if nums[0] != 1:
        raise ValueError("La prima parte deve essere .part0001")
    expected = list(range(1, len(nums) + 1))
    if nums != expected:
        missing = sorted(set(expected) - set(nums))
        raise ValueError(f"Sequenza parti non continua. Parti mancanti: {missing or 'verificare numerazione'}")
    return records


def validate_uploaded_parts(uploaded_parts):
    records = []
    for f in uploaded_parts:
        info = parse_part_name(f.name)
        if not info:
            raise ValueError(f"Nome parte non valido: {f.name}. Atteso: nomefile.ext.part0001")
        base, num = info
        records.append((base, num, f))
    return validate_part_records(records)


def ensure_stage_dir():
    if "stage_dir" not in st.session_state or not Path(st.session_state.stage_dir).exists():
        st.session_state.stage_dir = tempfile.mkdtemp(prefix="financeplus_staged_parts_")
        st.session_state.staged_parts = {}
        st.session_state.part_uploader_key = 0
    return Path(st.session_state.stage_dir)


def clear_staged_parts():
    stage = st.session_state.get("stage_dir")
    if stage and Path(stage).exists():
        shutil.rmtree(stage, ignore_errors=True)
    st.session_state.pop("stage_dir", None)
    st.session_state.staged_parts = {}
    st.session_state.part_uploader_key = st.session_state.get("part_uploader_key", 0) + 1


def save_one_part(uploaded):
    info = parse_part_name(uploaded.name)
    if not info:
        raise ValueError("Nome parte non valido. Esempio: archivio.mbox.part0001")
    base, num = info
    stage = ensure_stage_dir()
    current = st.session_state.get("staged_parts", {})
    existing_bases = {v["base"] for v in current.values()}
    if existing_bases and base not in existing_bases:
        raise ValueError("Questa parte appartiene a un altro file. Svuota le parti già caricate oppure scegli il file corretto.")
    dest = stage / Path(uploaded.name).name
    uploaded.seek(0)
    with dest.open("wb") as fout:
        while True:
            block = uploaded.read(8 * 1024 * 1024)
            if not block:
                break
            fout.write(block)
    current[num] = {"base": base, "path": str(dest), "name": uploaded.name, "size": dest.stat().st_size}
    st.session_state.staged_parts = current


def staged_records():
    recs = []
    for num, meta in st.session_state.get("staged_parts", {}).items():
        recs.append((meta["base"], int(num), Path(meta["path"])))
    return recs


def reconstruct_uploaded_parts_to_disk(uploaded_parts, progress=None):
    records = validate_uploaded_parts(uploaded_parts)
    original_name = records[0][0]
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Formato originale non supportato: {suffix}")
    workdir = tempfile.mkdtemp(prefix="financeplus_rebuilt_")
    out_path = Path(workdir) / Path(original_name).name
    with out_path.open("wb") as fout:
        for i, (_, _, uploaded) in enumerate(records, start=1):
            uploaded.seek(0)
            while True:
                block = uploaded.read(8 * 1024 * 1024)
                if not block:
                    break
                fout.write(block)
            if progress:
                progress.progress(i / len(records), text=f"Ricostruzione parte {i}/{len(records)}")
    return out_path


def reconstruct_staged_parts_to_disk(progress=None):
    records = validate_part_records(staged_records())
    original_name = records[0][0]
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Formato originale non supportato: {suffix}")
    workdir = tempfile.mkdtemp(prefix="financeplus_rebuilt_")
    out_path = Path(workdir) / Path(original_name).name
    with out_path.open("wb") as fout:
        for i, (_, _, part_path) in enumerate(records, start=1):
            with part_path.open("rb") as fin:
                while True:
                    block = fin.read(8 * 1024 * 1024)
                    if not block:
                        break
                    fout.write(block)
            if progress:
                progress.progress(i / len(records), text=f"Ricostruzione parte {i}/{len(records)}")
    return out_path


def parse_mbox_path(path: Path):
    results = []
    box = mailbox.mbox(str(path), factory=None, create=False)
    try:
        for index, raw_msg in enumerate(box, start=1):
            try:
                results.append(core.parse_eml(raw_msg.as_bytes(policy=core.policy.default), path.name, index))
            except Exception as exc:
                results.append(core.ParsedMail(path.name, index, None, "(errore parsing)", str(exc), "", []))
    finally:
        box.close()
    return results, []


def parse_zip_path(path: Path, depth: int = 0):
    results, warnings = [], []
    if depth > 4:
        return results, [f"{path.name}: profondità ZIP annidato oltre il limite tecnico di sicurezza"]
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext not in SUPPORTED:
                continue
            source = f"{path.name} > {info.filename}"
            try:
                if ext == ".eml":
                    with zf.open(info, "r") as src:
                        results.append(core.parse_eml(src.read(), source, 1))
                elif ext == ".msg":
                    with zf.open(info, "r") as src:
                        results.append(core.parse_msg(src.read(), source, 1))
                else:
                    nested_dir = Path(tempfile.mkdtemp(prefix="financeplus_nested_"))
                    nested_path = nested_dir / Path(info.filename).name
                    with zf.open(info, "r") as src, nested_path.open("wb") as dst:
                        while True:
                            block = src.read(8 * 1024 * 1024)
                            if not block:
                                break
                            dst.write(block)
                    if ext == ".mbox":
                        a, b = parse_mbox_path(nested_path)
                    else:
                        a, b = parse_zip_path(nested_path, depth + 1)
                    results.extend(a)
                    warnings.extend(b)
            except Exception as exc:
                warnings.append(f"{source}: {exc}")
    return results, warnings


def parse_reconstructed_path(path: Path):
    ext = path.suffix.lower()
    if ext == ".mbox":
        return parse_mbox_path(path)
    if ext == ".zip":
        return parse_zip_path(path)
    if ext == ".eml":
        return [core.parse_eml(path.read_bytes(), path.name, 1)], []
    if ext == ".msg":
        return [core.parse_msg(path.read_bytes(), path.name, 1)], []
    return [], [f"Formato non supportato: {ext}"]


def local_splitter_component():
    html = r'''
    <style>
      *{box-sizing:border-box}
      body{margin:0;font-family:Arial,sans-serif;color:#17324a}
      .box{border:1px solid #d8dee5;border-top:4px solid #b88952;border-radius:12px;padding:18px;background:white}
      .note{background:#f2f6fa;border-left:4px solid #b88952;border-radius:8px;padding:11px 13px;margin:12px 0;color:#344b5f;font-size:14px;line-height:1.4}
      .controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0}
      button{background:#12304A;color:white;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}
      button.secondary{background:white;color:#12304A;border:1px solid #b88952;padding:7px 10px;font-size:12px}
      #parts{margin-top:14px;border:1px solid #e0e5ea;border-radius:10px;overflow:hidden;display:none}
      .ph{display:grid;grid-template-columns:55px 1fr 95px 105px;background:#12304A;color:white;font-weight:700;padding:9px 10px;font-size:12px}
      .pr{display:grid;grid-template-columns:55px 1fr 95px 105px;align-items:center;padding:8px 10px;border-top:1px solid #e8edf1;font-size:12px;gap:6px}
      .pr:nth-child(odd){background:#f8fafb}
      .filename{word-break:break-all}
      .status{font-weight:700;color:#6b7780}
      .status.ok{color:#1c7c54}
      progress{width:100%;margin-top:8px;display:none}
      @media(max-width:600px){.ph,.pr{grid-template-columns:42px 1fr 78px}.ph div:nth-child(4),.pr div:nth-child(4){grid-column:1/-1}.pr button{width:100%}}
    </style>
    <div class="box">
      <h3 style="margin-top:0;color:#12304A">1. Seleziona il file grande e dividilo localmente</h3>
      <p style="color:#465866;margin-bottom:6px">Il file originale non viene caricato su Streamlit. Il browser legge il file sul dispositivo e crea parti da circa 500 MB.</p>
      <div class="note"><b>Dove vengono salvate?</b><br>Su iPhone/Safari: nell'app <b>File → Download</b> (iCloud Drive oppure “Su iPhone”, secondo le impostazioni Safari). Su computer, se il browser consente la scelta cartella, potrai scegliere dove salvarle; altrimenti finiscono nella cartella Download.</div>
      <input id="bigfile" type="file" style="margin:8px 0 10px;width:100%" />
      <div class="controls">
        <label>Dimensione parte (MB): <input id="chunkmb" type="number" value="500" min="100" max="900" step="50" style="width:90px;padding:6px"></label>
        <button id="splitbtn">Dividi e salva tutte le parti</button>
      </div>
      <div id="status" style="margin-top:10px;color:#12304A;font-weight:700"></div>
      <progress id="prog" value="0" max="100"></progress>
      <div id="parts">
        <div class="ph"><div>#</div><div>Nome parte</div><div>Dimensione</div><div>Stato / Azione</div></div>
        <div id="partrows"></div>
      </div>
    </div>
    <script>
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let selectedFile=null, currentChunk=500*1024*1024, totalParts=0;
    function fmtBytes(n){ const u=['B','KB','MB','GB','TB']; let i=0,v=n; while(v>=1024&&i<u.length-1){v/=1024;i++;} return v.toFixed(i>1?2:1)+' '+u[i]; }
    function partName(i){ return selectedFile.name+'.part'+String(i+1).padStart(4,'0'); }
    function renderParts(){
      const rows=document.getElementById('partrows'); rows.innerHTML='';
      if(!selectedFile){document.getElementById('parts').style.display='none';return;}
      const mb=parseInt(document.getElementById('chunkmb').value||'500',10); currentChunk=mb*1024*1024; totalParts=Math.ceil(selectedFile.size/currentChunk);
      document.getElementById('parts').style.display='block';
      for(let i=0;i<totalParts;i++){
        const start=i*currentChunk,end=Math.min(start+currentChunk,selectedFile.size),size=end-start;
        const row=document.createElement('div'); row.className='pr'; row.id='row-'+i;
        row.innerHTML='<div>'+(i+1)+'</div><div class="filename">'+partName(i)+'</div><div>'+fmtBytes(size)+'</div><div><span class="status" id="st-'+i+'">Da creare</span><br><button class="secondary" id="btn-'+i+'" type="button">Scarica</button></div>';
        rows.appendChild(row);
        document.getElementById('btn-'+i).addEventListener('click',()=>downloadOne(i));
      }
    }
    async function downloadBlob(blob,name){
      const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=name; document.body.appendChild(a); a.click(); a.remove(); await sleep(500); URL.revokeObjectURL(url);
    }
    async function downloadOne(i){
      if(!selectedFile)return;
      const start=i*currentChunk,end=Math.min(start+currentChunk,selectedFile.size),blob=selectedFile.slice(start,end),name=partName(i),st=document.getElementById('st-'+i);
      st.textContent='Preparazione…'; await downloadBlob(blob,name); st.textContent='✅ Scaricata'; st.className='status ok';
    }
    document.getElementById('bigfile').addEventListener('change',e=>{
      selectedFile=e.target.files[0]||null;
      const status=document.getElementById('status');
      if(selectedFile){status.textContent='File selezionato: '+selectedFile.name+' • '+fmtBytes(selectedFile.size);renderParts();}
      else{status.textContent='';renderParts();}
    });
    document.getElementById('chunkmb').addEventListener('change',renderParts);
    document.getElementById('splitbtn').addEventListener('click',async()=>{
      if(!selectedFile){alert('Seleziona prima il file grande.');return;}
      renderParts();
      const status=document.getElementById('status'),prog=document.getElementById('prog');prog.style.display='block';prog.value=0;
      let dir=null;
      if('showDirectoryPicker' in window){try{dir=await window.showDirectoryPicker({mode:'readwrite'});}catch(e){dir=null;}}
      for(let i=0;i<totalParts;i++){
        const start=i*currentChunk,end=Math.min(start+currentChunk,selectedFile.size),blob=selectedFile.slice(start,end),name=partName(i),st=document.getElementById('st-'+i);
        status.textContent='Creazione '+name+' • '+(i+1)+'/'+totalParts; st.textContent='Creazione…';
        if(dir){const h=await dir.getFileHandle(name,{create:true});const w=await h.createWritable();await w.write(blob);await w.close();st.textContent='✅ Salvata';}
        else{await downloadBlob(blob,name);st.textContent='✅ Scaricata';}
        st.className='status ok';prog.value=((i+1)/totalParts)*100;await sleep(80);
      }
      const manifest={original_name:selectedFile.name,original_size:selectedFile.size,chunk_size:currentChunk,total_parts:totalParts,created_at:new Date().toISOString()};
      const mblob=new Blob([JSON.stringify(manifest,null,2)],{type:'application/json'}),mname=selectedFile.name+'.manifest.json';
      if(dir){const h=await dir.getFileHandle(mname,{create:true});const w=await h.createWritable();await w.write(mblob);await w.close();}else{await downloadBlob(mblob,mname);}
      status.textContent='Completato: '+totalParts+' parti create. Ora le trovi in Download e puoi caricarle nell’app qui sotto.';
    });
    </script>
    '''
    components.html(html, height=720, scrolling=True)


def render_results(ms, ws):
    if ws:
        with st.expander(f"Avvisi ({len(ws)})"):
            for w in ws:
                st.warning(w)
    if not ms:
        return
    df = core.dataframe(ms)
    total_att = sum(len(m.attachments) for m in ms)
    total_bytes = sum(len(a.content) for m in ms for a in m.attachments)
    a, b, c, d = st.columns(4)
    a.metric("Mail elaborate", len(ms)); b.metric("Mail con allegati", sum(bool(m.attachments) for m in ms)); c.metric("Allegati estratti", total_att); d.metric("Dimensione allegati", f"{total_bytes/1024**2:.2f} MB")
    st.subheader("🔎 Filtri archivio")
    f1, f2, f3, f4 = st.columns([1.1,1.1,1.5,2])
    dated = [m.dt.date() for m in ms if m.dt]
    if dated:
        mind,maxd=min(dated),max(dated); start=f1.date_input("Dal",value=mind,min_value=mind,max_value=maxd); end=f2.date_input("Al",value=maxd,min_value=mind,max_value=maxd)
    else:
        start=end=None; f1.caption("Date non disponibili"); f2.caption("Date non disponibili")
    senders=sorted(x for x in df["Mittente"].dropna().unique()); sel=f3.multiselect("Mittente",senders,placeholder="Tutti i mittenti"); q=f4.text_input("Ricerca libera",placeholder="Oggetto, sintesi, allegato…").strip(); only=st.checkbox("Mostra solo mail con allegati")
    show=df.copy()
    if start and end: show=show[(show["DataISO"]=="")|((show["DataISO"]>=start.isoformat())&(show["DataISO"]<=end.isoformat()))]
    if sel: show=show[show["Mittente"].isin(sel)]
    if only: show=show[show["N. allegati"]>0]
    if q: show=show[show.astype(str).apply(lambda x:x.str.contains(re.escape(q),case=False,na=False,regex=True)).any(axis=1)]
    st.caption(f"Risultati visualizzati: {len(show)} su {len(df)}")
    st.dataframe(show[["Data e ora","Mittente","Oggetto","Sintesi del contenuto","Allegati","N. allegati"]],use_container_width=True,hide_index=True,height=520)
    st.subheader("📦 Esporta risultati filtrati")
    e1,e2,e3,e4=st.columns(4)
    e1.download_button("📄 Report PDF",core.pdf_bytes(show),"FinancePlus_Report_Mail.pdf","application/pdf",use_container_width=True)
    e2.download_button("📊 Report Excel",core.xlsx_bytes(show),"FinancePlus_Report_Mail.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
    e3.download_button("🧾 Report CSV",show.drop(columns=["DataISO"],errors="ignore").to_csv(index=False).encode("utf-8-sig"),"FinancePlus_Report_Mail.csv","text/csv",use_container_width=True)
    e4.download_button("📎 Archivio allegati ZIP",core.attachments_zip(ms,show),"FinancePlus_Allegati_Mail.zip","application/zip",use_container_width=True)


def main():
    st.set_page_config(page_title="FinancePlus | Archivio Mail",page_icon="📬",layout="wide"); core.css()
    st.markdown('<div class="fp-head"><h1>📬 FinancePlus | Archivio Mail</h1><p>File fino a decine di GB: divisione locale in parti da ~500 MB e caricamento controllato</p></div>',unsafe_allow_html=True)

    mode=st.radio("Scegli il flusso",["File normale","File grande: dividi in parti"],horizontal=True)

    if mode=="File normale":
        files=st.file_uploader("Carica EML, MSG, MBOX o ZIP",type=["eml","msg","mbox","zip"],accept_multiple_files=True,key="normal")
        if files and st.button("⚙️ Elabora archivio",type="primary",use_container_width=True):
            ms,ws=[],[]; bar=st.progress(0)
            for i,f in enumerate(files,1):
                a,b=core.parse_upload(f.name,f.getvalue()); ms.extend(a); ws.extend(b); bar.progress(i/len(files))
            bar.empty(); st.session_state.mails=ms; st.session_state.warns=ws
    else:
        local_splitter_component()
        st.markdown("### 2. Carica le parti nell'app")
        upload_mode=st.radio("Come vuoi caricare le parti?",["Una parte alla volta","Seleziona tutte le parti"],horizontal=True)

        if upload_mode=="Una parte alla volta":
            ensure_stage_dir()
            key=f"single_part_{st.session_state.get('part_uploader_key',0)}"
            one=st.file_uploader("Seleziona una parte .partXXXX",accept_multiple_files=False,key=key)
            c1,c2=st.columns([2,1])
            if one and c1.button("➕ Aggiungi questa parte",type="primary",use_container_width=True):
                try:
                    save_one_part(one)
                    st.session_state.part_uploader_key=st.session_state.get("part_uploader_key",0)+1
                    st.rerun()
                except Exception as exc: st.error(str(exc))
            if c2.button("🗑️ Svuota parti",use_container_width=True):
                clear_staged_parts(); st.rerun()
            staged=st.session_state.get("staged_parts",{})
            if staged:
                rows=[]
                for num,meta in sorted(staged.items()): rows.append({"Parte":f"part{int(num):04d}","File":meta["name"],"Dimensione MB":round(meta["size"]/1024**2,1)})
                st.dataframe(rows,use_container_width=True,hide_index=True)
                total=sum(v["size"] for v in staged.values()); st.success(f"Parti caricate: {len(staged)} • Totale: {total/1024**3:.2f} GB")
                if st.button("🧩 Ricostruisci file ed elabora",type="primary",use_container_width=True):
                    bar=st.progress(0,text="Controllo sequenza…")
                    try:
                        rebuilt=reconstruct_staged_parts_to_disk(bar); st.success(f"Ricostruito: {rebuilt.name} • {rebuilt.stat().st_size/1024**3:.2f} GB"); bar.progress(1.0,text="Analisi archivio…")
                        ms,ws=parse_reconstructed_path(rebuilt); st.session_state.mails=ms; st.session_state.warns=ws
                    except Exception as exc: st.error(f"Errore: {exc}")
                    finally: bar.empty()
        else:
            parts=st.file_uploader("Seleziona tutte le parti insieme",accept_multiple_files=True,key="all_parts")
            if parts:
                total=sum(getattr(f,"size",0) or 0 for f in parts); st.success(f"Parti selezionate: {len(parts)} • Totale: {total/1024**3:.2f} GB")
            if parts and st.button("🧩 Ricostruisci tutte le parti ed elabora",type="primary",use_container_width=True):
                bar=st.progress(0,text="Controllo sequenza…")
                try:
                    rebuilt=reconstruct_uploaded_parts_to_disk(parts,bar); st.success(f"Ricostruito: {rebuilt.name} • {rebuilt.stat().st_size/1024**3:.2f} GB"); bar.progress(1.0,text="Analisi archivio…")
                    ms,ws=parse_reconstructed_path(rebuilt); st.session_state.mails=ms; st.session_state.warns=ws
                except Exception as exc: st.error(f"Errore: {exc}")
                finally: bar.empty()

    render_results(st.session_state.get("mails",[]),st.session_state.get("warns",[]))


if __name__=="__main__":
    main()
