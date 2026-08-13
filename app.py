
import streamlit as st
import zipfile
import tempfile
import os
import re
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="WhatsApp Grafana Audit Organizer", page_icon="📊", layout="wide")

st.title("📊 WhatsApp Grafana Audit Organizer")
st.caption("Upload a WhatsApp chat export ZIP and organize Grafana screenshots by message date for audit evidence.")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DATE_PATTERNS = [
    # Android-style: 13/08/2026, 09:15 - Name: message
    re.compile(r'^\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*[-–]\s*(.*)$'),
    # Alternate: 8/13/26, 9:15 AM - Name: message
    re.compile(r'^\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\]?\s*[-–]\s*(.*)$', re.I),
]

MEDIA_PATTERNS = [
    re.compile(r'<attached:\s*([^>]+)>', re.I),
    re.compile(r'([A-Za-z0-9_\- ]+\.(?:jpg|jpeg|png|webp|bmp))', re.I),
]

def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:180] or "file"

def detect_chat_file(root):
    txts = list(Path(root).rglob("*.txt"))
    if not txts:
        return None
    # Prefer likely WhatsApp export file
    txts.sort(key=lambda p: (0 if "chat" in p.name.lower() else 1, len(p.name)))
    return txts[0]

def parse_datetime_line(line):
    # Try common DD/MM/YYYY formats first
    m = re.match(r'^\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\]?\s*[-–]\s*(.*)$', line, re.I)
    if not m:
        return None
    a,b,y,hh,mm,ss,ampm,rest = m.groups()
    a,b,y,hh,mm = map(int, (a,b,y,hh,mm))
    ss = int(ss or 0)
    if y < 100:
        y += 2000
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hh != 12:
            hh += 12
        if ampm == "AM" and hh == 12:
            hh = 0

    # Default WhatsApp non-US export assumption: DD/MM/YYYY.
    # If first component > 12, it must be day. If second > 12, swap.
    day, month = a, b
    if b > 12 and a <= 12:
        month, day = a, b
    try:
        dt = datetime(y, month, day, hh, mm, ss)
    except ValueError:
        return None
    return dt, rest

def extract_media_name(text):
    for pat in MEDIA_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    # iPhone exports often say "image omitted"; cannot directly map filename.
    return None

def classify_panel(filename, message_text=""):
    s = f"{filename} {message_text}".lower()
    if "cpu" in s:
        return "CPU"
    if "memory" in s or "mem" in s or "ram" in s:
        return "Memory"
    if "disk" in s or "storage" in s:
        return "Disk"
    if "network" in s:
        return "Network"
    return "Grafana/Other"

def parse_chat(chat_path):
    raw = Path(chat_path).read_text(encoding="utf-8", errors="replace")
    rows = []
    current = None

    for line in raw.splitlines():
        parsed = parse_datetime_line(line)
        if parsed:
            dt, body = parsed
            if current:
                rows.append(current)
            current = {"datetime": dt, "text": body}
        elif current:
            current["text"] += "\n" + line

    if current:
        rows.append(current)

    records = []
    for r in rows:
        media = extract_media_name(r["text"])
        sender = ""
        body = r["text"]
        if ": " in body:
            sender, body = body.split(": ", 1)
        records.append({
            "datetime": r["datetime"],
            "sender": sender.strip(),
            "message": body.strip(),
            "media_name": media
        })
    return pd.DataFrame(records)

def find_images(root):
    files = []
    for p in Path(root).rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(p)
    return files

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def best_media_match(media_name, images):
    # Pandas may represent missing media filenames as NaN/NA rather than None.
    # Only real, non-empty strings should ever be passed to pathlib.Path.
    if media_name is None:
        return None

    try:
        if pd.isna(media_name):
            return None
    except (TypeError, ValueError):
        pass

    if not isinstance(media_name, str):
        return None

    media_name = media_name.strip()
    if not media_name:
        return None

    target = Path(media_name).name.lower()
    exact = [p for p in images if p.name.lower() == target]
    if exact:
        return exact[0]

    # Relax spaces/underscores
    norm = re.sub(r'[\s_]+', '', target)
    for p in images:
        if re.sub(r'[\s_]+', '', p.name.lower()) == norm:
            return p
    return None

def build_archive(df, images, out_root):
    out_root = Path(out_root)
    organized = out_root / "Grafana_Audit"
    organized.mkdir(parents=True, exist_ok=True)

    used = set()
    audit_rows = []

    if not df.empty:
        for _, row in df.iterrows():
            media = row.get("media_name")
            matched = best_media_match(media, images)
            if matched is None:
                continue

            used.add(str(matched.resolve()))
            dt = row["datetime"]
            panel = classify_panel(matched.name, row.get("message", ""))
            folder = organized / f"{dt:%Y}" / f"{dt:%m-%B}" / f"{dt:%Y-%m-%d}"
            folder.mkdir(parents=True, exist_ok=True)

            renamed = safe_name(f"{dt:%H-%M-%S}_{panel}_{matched.name}")
            dest = folder / renamed
            shutil.copy2(matched, dest)

            audit_rows.append({
                "Date": dt.date().isoformat(),
                "Time": dt.strftime("%H:%M:%S"),
                "Sender": row.get("sender", ""),
                "Type": panel,
                "Original Media": matched.name,
                "Archived File": str(dest.relative_to(organized)),
                "Message": row.get("message", ""),
                "SHA256": file_hash(matched),
                "Status": "Matched to WhatsApp message"
            })

    # Keep unmatched images too, separated so nothing is lost.
    unmatched_dir = organized / "_Unmatched_Media"
    for img in images:
        if str(img.resolve()) in used:
            continue
        unmatched_dir.mkdir(parents=True, exist_ok=True)
        dest = unmatched_dir / safe_name(img.name)
        # Avoid collisions
        n = 1
        while dest.exists():
            dest = unmatched_dir / f"{dest.stem}_{n}{dest.suffix}"
            n += 1
        shutil.copy2(img, dest)
        audit_rows.append({
            "Date": "",
            "Time": "",
            "Sender": "",
            "Type": classify_panel(img.name),
            "Original Media": img.name,
            "Archived File": str(dest.relative_to(organized)),
            "Message": "",
            "SHA256": file_hash(img),
            "Status": "Unmatched media"
        })

    audit_df = pd.DataFrame(audit_rows)
    if not audit_df.empty:
        audit_df.to_csv(organized / "audit_index.csv", index=False)

        # Basic coverage summary by day/type
        matched = audit_df[audit_df["Date"] != ""].copy()
        if not matched.empty:
            coverage = pd.crosstab(matched["Date"], matched["Type"])
            coverage.to_csv(organized / "daily_coverage.csv")

    readme = """WhatsApp Grafana Audit Archive

This folder was generated from a WhatsApp chat export.

Important:
- Files matched to chat messages are organized using the WhatsApp message timestamp.
- Unmatched images are retained under _Unmatched_Media so evidence is not silently discarded.
- audit_index.csv contains SHA256 hashes to help demonstrate file integrity.
- Review unmatched media before treating the archive as complete audit evidence.
"""
    (organized / "README.txt").write_text(readme, encoding="utf-8")
    return organized, audit_df

def zip_folder(folder):
    memory = BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as z:
        for p in Path(folder).rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(Path(folder).parent)))
    memory.seek(0)
    return memory

with st.sidebar:
    st.header("Settings")
    st.info("Version 0.1 — designed for WhatsApp exported chats containing Grafana screenshots.")
    st.markdown("""
**Current features**
- ZIP upload
- WhatsApp timestamp parsing
- Media matching
- Date-wise folders
- CPU/Memory keyword classification
- Audit CSV
- SHA256 evidence hashes
- Unmatched-media preservation
""")

uploaded = st.file_uploader("Upload WhatsApp export ZIP", type=["zip"])

if uploaded:
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "export.zip"
        zip_path.write_bytes(uploaded.getvalue())

        extract_dir = Path(td) / "extracted"
        extract_dir.mkdir()

        try:
            with zipfile.ZipFile(zip_path) as z:
                # Basic zip-slip protection
                for member in z.infolist():
                    target = (extract_dir / member.filename).resolve()
                    if not str(target).startswith(str(extract_dir.resolve())):
                        raise ValueError("Unsafe ZIP path detected.")
                z.extractall(extract_dir)
        except Exception as e:
            st.error(f"Could not extract ZIP: {e}")
            st.stop()

        chat_file = detect_chat_file(extract_dir)
        images = find_images(extract_dir)

        c1, c2, c3 = st.columns(3)
        c1.metric("Images found", len(images))
        c2.metric("Chat file", "Yes" if chat_file else "No")
        c3.metric("ZIP", uploaded.name)

        if not chat_file:
            st.warning("No .txt chat export was found. Images can still be retained, but they cannot yet be sorted by WhatsApp message time.")
            df = pd.DataFrame()
        else:
            st.success(f"Chat detected: {chat_file.name}")
            df = parse_chat(chat_file)
            st.write(f"Parsed **{len(df):,}** WhatsApp message records.")

        out_root = Path(td) / "output"
        archive, audit_df = build_archive(df, images, out_root)

        if not audit_df.empty:
            st.subheader("Audit preview")
            st.dataframe(audit_df.head(100), use_container_width=True)

            matched_count = (audit_df["Status"] == "Matched to WhatsApp message").sum()
            unmatched_count = (audit_df["Status"] == "Unmatched media").sum()

            a, b = st.columns(2)
            a.metric("Matched media", int(matched_count))
            b.metric("Unmatched media", int(unmatched_count))

            dated = audit_df[audit_df["Date"] != ""]
            if not dated.empty:
                st.subheader("Daily evidence coverage")
                coverage = pd.crosstab(dated["Date"], dated["Type"])
                st.dataframe(coverage, use_container_width=True)

        zip_bytes = zip_folder(archive)
        st.download_button(
            "⬇️ Download organized audit archive",
            data=zip_bytes,
            file_name="Grafana_Audit_Organized.zip",
            mime="application/zip",
            use_container_width=True
        )

        if not chat_file:
            st.caption("Upload a standard WhatsApp 'Export chat → Include media' ZIP for timestamp-based organization.")
else:
    st.markdown("""
### How it will work

1. In WhatsApp, export the required group chat **with media**.
2. Upload the resulting ZIP here.
3. The app reads WhatsApp message timestamps.
4. Matching screenshots are copied into `Year / Month / Date` folders.
5. An `audit_index.csv` is produced containing timestamps, sender, type, original filename and SHA256 hash.
6. Media that cannot be matched is kept under `_Unmatched_Media` instead of being discarded.

The original ZIP is never modified.
""")
