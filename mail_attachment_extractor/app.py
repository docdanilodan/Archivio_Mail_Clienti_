# -*- coding: utf-8 -*-
from __future__ import annotations

import mailbox
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import mail_attachment_extractor as core
from document_ai import render_document_ai

PART_RE = re.compile(r"^(?P<base>.+)\.part(?P<num>\d{4,})$", re.IGNORECASE)
SUPPORTED = {".mbox", ".zip", ".eml", ".msg"}


def parse_part_name(name: str):
    m = PART_RE.match(Path(name).name)
    if not m:
        return None
    return m.group("base"), int(m.group("num"))


def validate_part_records(records):
    if not records:
        raise ValueError("Nessuna parte caricata.")
    bases = {r[0] for r in records}
    if len(bases) != 1:
        raise ValueError("Le parti appartengono a file originali diversi.")
    records = sorted(records, key=lambda x: x[1])
    nums = [r[1] for r in records]
    if nums[0] != 1:
        raise ValueError("Manca part0001.")
    expected = list(range(1, max(nums) + 1))
    missing = sorted(set(expected) - set(nums))
    if missing:
        raise ValueError("Parti mancanti: " + ", ".join(f"part{x:04d}" for x in missing))
    return records


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
        raise ValueError("Nome non valido. Deve terminare con .part0001, .part0002, ecc.")
    base, num = info
    stage = ensure_stage_dir()
    current = st.session_state.get("staged_parts", {})
    existing_bases = {v["base"] for v in current.values()}
    if existing_bases and base not in existing_bases:
        raise ValueError("La parte appartiene a un altro archivio. Svuota le parti prima di cambiare file.")

    dest = stage / Path(uploaded.name).name
    uploaded.seek(0)
    with dest.open("wb") as fout:
        while True:
            block = uploaded.read(4 * 1024 * 1024)
            if not block:
                break
            fout.write(block)

    current[num] = {
        "base": base,
        "path": str(dest),
        "name": uploaded.name,
        "size": dest.stat().st_size,
    }
    st.session_state.staged_parts = current
    return num, dest.stat().st_size


def staged_records():
    return [
        (meta["base"], int(num), Path(meta["path"]))
        for num, meta in st.session_state.get("staged_parts", {}).items()
    ]


def next_expected_part():
    nums = sorted(int(x) for x in st.session_state.get("staged_parts", {}).keys())
    expected = 1
    for num in nums:
        if num == expected:
            expected += 1
        elif num > expected:
            break
    return expected


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
                progress.progress(i / len(records), text=f"Ricostruzione {i}/{len(records)}")
    return out_path


def reconstruct_uploaded_parts_to_disk(uploaded_parts, progress=None):
    records = []
    for f in uploaded_parts:
        info = parse_part_name(f.name)
        if not info:
            raise ValueError(f"Nome parte non valido: {f.name}")
        records.append((info[0], info[1], f))
    records = validate_part_records(records)
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
                block = uploaded.read(4 * 1024 * 1024)
                if not block:
                    break
                fout.write(block)
            if progress:
                progress.progress(i / len(records), text=f"Ricostruzione {i}/{len(records)}")
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
        return results, [f"{path.name}: ZIP annidato troppo in profondità"]

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
      .box{border:1px solid #d8dee5;border-top:4px solid #b88952;border-radius:12px;padding:16px;background:white}
      .note{background:#f2f6fa;border-left:4px solid #b88952;border-radius:8px;padding:10px 12px;margin:10px 0;color:#344b5f;font-size:14px;line-height:1.45}
      .note.warn{border-left-color:#d28b25;background:#fff8ed}
      .controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}
      button{background:#12304A;color:white;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}
      button.folder{background:#B88952}
      button.secondary{background:white;color:#12304A;border:1px solid #b88952;padding:7px 10px;font-size:12px}
      button:disabled{opacity:.65;cursor:not-allowed}
      #parts{margin-top:12px;border:1px solid #e0e5ea;border-radius:10px;overflow:hidden;display:none;max-height:420px;overflow-y:auto}
      .ph{position:sticky;top:0;display:grid;grid-template-columns:48px 1fr 85px 120px;background:#12304A;color:white;font-weight:700;padding:8px 9px;font-size:12px;z-index:2}
      .pr{display:grid;grid-template-columns:48px 1fr 85px 120px;align-items:center;padding:7px 9px;border-top:1px solid #e8edf1;font-size:12px;gap:5px}
      .pr:nth-child(odd){background:#f8fafb}
      .filename{word-break:break-all}
      .status{font-weight:700;color:#6b7780}
      .status.ok{color:#1c7c54}
      .status.work{color:#a86810}
      .folder-state{font-weight:700;color:#12304A;margin-top:6px}
      progress{width:100%;margin-top:8px;display:none}
      @media(max-width:600px){
        .ph,.pr{grid-template-columns:38px 1fr 72px}
        .ph div:nth-child(4),.pr div:nth-child(4){grid-column:1/-1}
        .pr button{width:100%}
        .controls button{width:100%}
      }
    </style>

    <div class="box">
      <h3 style="margin-top:0;color:#12304A">1. Dividi e salva il file grande</h3>
      <p style="color:#465866">Il file viene diviso <b>localmente sul dispositivo</b>. Il file originale non viene caricato su Streamlit.</p>

      <div id="mainnote" class="note">
        <b>Flusso:</b><br>
        scegli il file originale, imposta la dimensione delle parti e premi <b>Dividi e salva tutto</b>.
      </div>

      <input id="bigfile" type="file" style="margin:8px 0 10px;width:100%" />

      <div class="controls">
        <label>MB per parte:
          <input id="chunkmb" type="number" value="100" min="50" max="500" step="25" style="width:85px;padding:6px">
        </label>
        <button id="folderbtn" class="folder" type="button">📁 Scegli cartella</button>
        <button id="splitbtn" type="button">✂️ Dividi e salva tutto</button>
      </div>

      <div id="folderstate" class="folder-state"></div>
      <div id="fallbacknote" class="note warn" style="display:none"></div>
      <div id="status" style="margin-top:8px;color:#12304A;font-weight:700"></div>
      <progress id="prog" value="0" max="100"></progress>

      <div id="parts">
        <div class="ph"><div>#</div><div>Parte</div><div>MB</div><div>Stato</div></div>
        <div id="partrows"></div>
      </div>
    </div>

    <script>
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      let selectedFile = null;
      let dirHandle = null;
      let chunk = 100 * 1024 * 1024;
      let total = 0;

      const ua = navigator.userAgent || '';
      const isiOS = /iPhone|iPad|iPod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
      const supportsFolderPicker = !isiOS && ('showDirectoryPicker' in window);

      const folderBtn = document.getElementById('folderbtn');
      const folderState = document.getElementById('folderstate');
      const fallbackNote = document.getElementById('fallbacknote');
      const mainNote = document.getElementById('mainnote');
      const status = document.getElementById('status');
      const prog = document.getElementById('prog');

      function partName(i){
        return selectedFile.name + '.part' + String(i + 1).padStart(4, '0');
      }

      function renderParts(){
        const rows = document.getElementById('partrows');
        rows.innerHTML = '';
        if(!selectedFile){
          document.getElementById('parts').style.display = 'none';
          return;
        }
        const mb = parseInt(document.getElementById('chunkmb').value || '100', 10);
        chunk = mb * 1024 * 1024;
        total = Math.ceil(selectedFile.size / chunk);
        document.getElementById('parts').style.display = 'block';

        for(let i = 0; i < total; i++){
          const start = i * chunk;
          const end = Math.min(start + chunk, selectedFile.size);
          const sizeMb = ((end - start) / 1024 / 1024).toFixed(1);
          const row = document.createElement('div');
          row.className = 'pr';
          row.innerHTML =
            '<div>' + (i + 1) + '</div>' +
            '<div class="filename">' + partName(i) + '</div>' +
            '<div>' + sizeMb + '</div>' +
            '<div><span class="status" id="st-' + i + '">Da salvare</span><br>' +
            '<button class="secondary" id="one-' + i + '" type="button">Salva singola</button></div>';
          rows.appendChild(row);
          document.getElementById('one-' + i).onclick = () => saveOne(i);
        }
        status.textContent = 'Previste ' + total + ' parti.';
      }

      async function browserDownload(blob, filename){
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        await sleep(550);
        URL.revokeObjectURL(url);
      }

      async function writeToFolder(blob, filename){
        const handle = await dirHandle.getFileHandle(filename, {create:true});
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
      }

      async function saveBlob(blob, filename){
        if(dirHandle){
          await writeToFolder(blob, filename);
          return '✅ Salvata nella cartella';
        }
        await browserDownload(blob, filename);
        return isiOS ? '✅ Inviata a Download' : '✅ Download avviato';
      }

      async function saveOne(i){
        if(!selectedFile) return;
        const st = document.getElementById('st-' + i);
        st.textContent = 'Salvataggio…';
        st.className = 'status work';
        try{
          const blob = selectedFile.slice(i * chunk, Math.min((i + 1) * chunk, selectedFile.size));
          st.textContent = await saveBlob(blob, partName(i));
          st.className = 'status ok';
        }catch(err){
          st.textContent = '❌ Errore';
          st.className = 'status';
        }
      }

      if(isiOS){
        folderBtn.disabled = true;
        folderBtn.textContent = '📁 Download di Safari';
        folderState.textContent = 'iPhone/iPad: Safari non permette a questa app di selezionare una cartella di scrittura.';
        mainNote.innerHTML = '<b>Su iPhone:</b><br>la destinazione viene stabilita da Safari. Impostala prima in <b>Impostazioni → App → Safari → Download</b>, scegliendo iCloud Drive oppure “Su iPhone”. Poi torna qui e premi <b>Dividi e salva tutto</b>.';
        fallbackNote.style.display = 'block';
        fallbackNote.innerHTML = '<b>Importante:</b> i download verranno richiesti automaticamente uno dopo l’altro. Se Safari chiede il permesso per download multipli, consenti.';
      }else if(!supportsFolderPicker){
        folderBtn.disabled = true;
        folderState.textContent = 'Questo browser non supporta la selezione di una cartella di scrittura.';
        fallbackNote.style.display = 'block';
        fallbackNote.textContent = 'Verrà usata la cartella Download configurata nel browser.';
      }else{
        folderState.textContent = 'Nessuna cartella selezionata.';
      }

      folderBtn.onclick = async () => {
        if(!supportsFolderPicker) return;
        try{
          dirHandle = await window.showDirectoryPicker({mode:'readwrite'});
          folderState.textContent = '✅ Cartella selezionata: ' + (dirHandle.name || 'destinazione scelta');
          fallbackNote.style.display = 'none';
        }catch(err){
          if(err && err.name === 'AbortError'){
            folderState.textContent = 'Selezione cartella annullata.';
          }else{
            dirHandle = null;
            folderState.textContent = 'Impossibile usare la cartella scelta. Verrà usato Download.';
            fallbackNote.style.display = 'block';
            fallbackNote.textContent = 'Il browser non ha concesso la scrittura diretta. Verranno usati i download.';
          }
        }
      };

      document.getElementById('bigfile').onchange = e => {
        selectedFile = e.target.files[0] || null;
        renderParts();
      };

      document.getElementById('chunkmb').onchange = renderParts;

      document.getElementById('splitbtn').onclick = async () => {
        if(!selectedFile){
          alert('Seleziona prima il file originale.');
          return;
        }

        renderParts();
        prog.style.display = 'block';
        prog.value = 0;

        if(!dirHandle && supportsFolderPicker){
          const proceed = confirm('Non hai selezionato una cartella. Vuoi usare la cartella Download del browser?');
          if(!proceed) return;
        }

        for(let i = 0; i < total; i++){
          const st = document.getElementById('st-' + i);
          const filename = partName(i);
          const blob = selectedFile.slice(i * chunk, Math.min((i + 1) * chunk, selectedFile.size));
          status.textContent = 'Salvataggio ' + (i + 1) + '/' + total + ': ' + filename;
          st.textContent = 'Salvataggio…';
          st.className = 'status work';

          try{
            st.textContent = await saveBlob(blob, filename);
            st.className = 'status ok';
          }catch(err){
            st.textContent = '❌ Errore';
            st.className = 'status';
            status.textContent = 'Errore su ' + filename + '. Usa “Salva singola” per riprovare.';
            return;
          }

          prog.value = ((i + 1) / total) * 100;
          await sleep(dirHandle ? 20 : (isiOS ? 700 : 300));
        }

        const manifest = {
          original_name: selectedFile.name,
          original_size: selectedFile.size,
          chunk_size: chunk,
          total_parts: total,
          created_at: new Date().toISOString()
        };
        const manifestBlob = new Blob([JSON.stringify(manifest, null, 2)], {type:'application/json'});
        await saveBlob(manifestBlob, selectedFile.name + '.manifest.json');

        status.textContent = dirHandle
          ? '✅ Completato: tutte le parti sono state salvate nella cartella selezionata.'
          : '✅ Completato: tutti i download sono stati richiesti alla cartella Download del browser.';
      };
    </script>
    '''
    components.html(html, height=780, scrolling=True)


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
    a.metric("Mail elaborate", len(ms))
    b.metric("Mail con allegati", sum(bool(m.attachments) for m in ms))
    c.metric("Allegati estratti", total_att)
    d.metric("Dimensione allegati", f"{total_bytes/1024**2:.2f} MB")

    st.subheader("🔎 Filtri archivio")
    q = st.text_input("Ricerca", placeholder="Mittente, oggetto, sintesi, allegato…").strip()
    show = df.copy()
    if q:
        show = show[show.astype(str).apply(
            lambda x: x.str.contains(re.escape(q), case=False, na=False, regex=True)
        ).any(axis=1)]

    st.dataframe(
        show[["Data e ora", "Mittente", "Oggetto", "Sintesi del contenuto", "Allegati", "N. allegati"]],
        use_container_width=True,
        hide_index=True,
        height=520,
    )

    st.subheader("📦 Esporta")
    e1, e2, e3, e4 = st.columns(4)
    e1.download_button("📄 PDF", core.pdf_bytes(show), "FinancePlus_Report_Mail.pdf", "application/pdf", use_container_width=True)
    e2.download_button("📊 Excel", core.xlsx_bytes(show), "FinancePlus_Report_Mail.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    e3.download_button("🧾 CSV", show.drop(columns=["DataISO"], errors="ignore").to_csv(index=False).encode("utf-8-sig"), "FinancePlus_Report_Mail.csv", "text/csv", use_container_width=True)
    e4.download_button("📎 Allegati ZIP", core.attachments_zip(ms, show), "FinancePlus_Allegati_Mail.zip", "application/zip", use_container_width=True)


def main():
    st.set_page_config(page_title="FinancePlus | Archivio Mail", page_icon="📬", layout="wide")
    core.css()
    st.markdown(
        '<div class="fp-head"><h1>📬 FinancePlus | Archivio Mail</h1>'
        '<p>Divisione locale • Download automatici su iPhone • scelta cartella sui browser compatibili</p></div>',
        unsafe_allow_html=True,
    )

    mode = st.radio(
        "Scegli il flusso",
        ["File normale", "File grande: dividi in parti"],
        horizontal=True,
    )

    if mode == "File normale":
        files = st.file_uploader(
            "Carica EML, MSG, MBOX o ZIP",
            type=["eml", "msg", "mbox", "zip"],
            accept_multiple_files=True,
            key="normal",
        )
        if files and st.button("⚙️ Elabora archivio", type="primary", use_container_width=True):
            ms, ws = [], []
            for f in files:
                a, b = core.parse_upload(f.name, f.getvalue())
                ms.extend(a)
                ws.extend(b)
            st.session_state.mails = ms
            st.session_state.warns = ws
    else:
        local_splitter_component()

        st.markdown("### 2. Carica le parti nell'app")
        upload_mode = st.radio(
            "Modalità",
            ["Una parte alla volta — consigliata", "Seleziona tutte le parti"],
            horizontal=True,
        )

        if upload_mode.startswith("Una parte"):
            ensure_stage_dir()
            staged = st.session_state.get("staged_parts", {})
            nxt = next_expected_part()
            st.info(
                f"Prossima parte attesa: **part{nxt:04d}**. "
                "Le parti già completate restano salvate durante questa sessione."
            )

            key = f"single_part_{st.session_state.get('part_uploader_key', 0)}"
            one = st.file_uploader("Carica una parte", accept_multiple_files=False, key=key)

            if one is not None:
                try:
                    info = parse_part_name(one.name)
                    if not info:
                        raise ValueError("Il file scelto non è una parte .partXXXX")
                    if info[1] != nxt and info[1] not in staged:
                        st.warning(
                            f"Attesa part{nxt:04d}; hai scelto part{info[1]:04d}. Verrà comunque salvata."
                        )
                    num, size = save_one_part(one)
                    st.toast(f"part{num:04d} caricata: {size/1024**2:.1f} MB", icon="✅")
                    st.session_state.part_uploader_key = st.session_state.get("part_uploader_key", 0) + 1
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            staged = st.session_state.get("staged_parts", {})
            if staged:
                rows = []
                for num, meta in sorted(staged.items()):
                    rows.append({
                        "Parte": f"part{int(num):04d}",
                        "Stato": "✅ Caricata",
                        "Dimensione MB": round(meta["size"] / 1024**2, 1),
                        "File": meta["name"],
                    })
                st.dataframe(rows, use_container_width=True, hide_index=True)
                total = sum(v["size"] for v in staged.values())
                st.success(
                    f"{len(staged)} parti salvate • {total/1024**3:.2f} GB • Prossima: part{next_expected_part():04d}"
                )

                c1, c2 = st.columns([2, 1])
                if c2.button("🗑️ Svuota parti", use_container_width=True):
                    clear_staged_parts()
                    st.rerun()

                if c1.button("🧩 Ricostruisci ed elabora", type="primary", use_container_width=True):
                    bar = st.progress(0, text="Controllo parti…")
                    try:
                        rebuilt = reconstruct_staged_parts_to_disk(bar)
                        bar.progress(1.0, text="Analisi archivio…")
                        ms, ws = parse_reconstructed_path(rebuilt)
                        st.session_state.mails = ms
                        st.session_state.warns = ws
                        st.success(f"Archivio ricostruito: {rebuilt.name}")
                    except Exception as exc:
                        st.error(f"Impossibile ricostruire: {exc}")
                    finally:
                        bar.empty()
        else:
            st.warning(
                "Su dispositivi mobili questa modalità può essere più pesante. "
                "Per archivi grandi è preferibile caricare le parti una alla volta."
            )
            parts = st.file_uploader("Seleziona tutte le parti", accept_multiple_files=True, key="all_parts")
            if parts:
                total = sum(getattr(f, "size", 0) or 0 for f in parts)
                st.caption(f"Selezionate {len(parts)} parti • {total/1024**3:.2f} GB")
                if st.button("🧩 Ricostruisci ed elabora tutte", type="primary", use_container_width=True):
                    bar = st.progress(0, text="Ricostruzione…")
                    try:
                        rebuilt = reconstruct_uploaded_parts_to_disk(parts, bar)
                        ms, ws = parse_reconstructed_path(rebuilt)
                        st.session_state.mails = ms
                        st.session_state.warns = ws
                        st.success(f"Archivio ricostruito: {rebuilt.name}")
                    except Exception as exc:
                        st.error(str(exc))
                    finally:
                        bar.empty()

    render_results(st.session_state.get("mails", []), st.session_state.get("warns", []))

    render_document_ai()


if __name__ == "__main__":
    main()
