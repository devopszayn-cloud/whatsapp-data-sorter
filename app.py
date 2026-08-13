
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
from PIL import Image, ImageStat, ImageOps
import numpy as np

st.set_page_config(
    page_title="WhatsApp Grafana Audit Organizer",
    page_icon="📊",
    layout="wide"
)

st.title("📊 WhatsApp Grafana Audit Organizer")
st.caption(
    "Extract only Grafana CPU/Memory dashboard screenshots from a WhatsApp export "
    "and organize 2026 audit evidence by WhatsApp message date."
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
TARGET_YEAR = 2026
REFERENCE_PATH = Path(__file__).with_name("grafana_reference.png")

MEDIA_PATTERNS = [
    re.compile(r'<attached:\s*([^>]+)>', re.I),
    re.compile(r'([A-Za-z0-9_\- .()]+\.(?:jpg|jpeg|png|webp|bmp))', re.I),
]

def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*]+', "_", str(name))
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:180] or "file"

def looks_like_whatsapp_chat(path):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False

    sample = "\n".join(text.splitlines()[:500])
    # Common WhatsApp export patterns:
    # 13/08/2026, 09:15 - Name: Message
    # [13/08/2026, 09:15:00] Name: Message
    pat = re.compile(
        r'^\[?\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}'
        r'(?::\d{2})?\s*(?:AM|PM)?\]?\s*(?:-|–)?\s*.+?:',
        re.I | re.M
    )
    return bool(pat.search(sample))

def detect_chat_file(root):
    txts = list(Path(root).rglob("*.txt"))
    valid = [p for p in txts if looks_like_whatsapp_chat(p)]
    if not valid:
        return None

    valid.sort(key=lambda p: (
        0 if p.name.lower() in {"_chat.txt", "chat.txt"} else 1,
        0 if "chat" in p.name.lower() else 1,
        len(p.name)
    ))
    return valid[0]

def parse_datetime_line(line):
    m = re.match(
        r'^\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+'
        r'(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\]?\s*'
        r'(?:-|–)?\s*(.*)$',
        line,
        re.I
    )
    if not m:
        return None

    a, b, y, hh, mm, ss, ampm, rest = m.groups()
    a, b, y, hh, mm = map(int, (a, b, y, hh, mm))
    ss = int(ss or 0)

    if y < 100:
        y += 2000

    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hh != 12:
            hh += 12
        if ampm == "AM" and hh == 12:
            hh = 0

    # Default to DD/MM/YYYY, but switch if the second part is clearly a day.
    day, month = a, b
    if b > 12 and a <= 12:
        month, day = a, b

    try:
        dt = datetime(y, month, day, hh, mm, ss)
    except ValueError:
        return None

    return dt, rest

def extract_media_name(text):
    if not isinstance(text, str):
        return None
    for pat in MEDIA_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None

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
            "media_name": media,
        })

    return pd.DataFrame(records)

def find_images(root):
    return [
        p for p in Path(root).rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def best_media_match(media_name, images):
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

    norm = re.sub(r'[\s_]+', '', target)
    for p in images:
        if re.sub(r'[\s_]+', '', p.name.lower()) == norm:
            return p

    return None

def dhash(img, hash_size=16):
    img = ImageOps.exif_transpose(img).convert("L")
    img = img.resize((hash_size + 1, hash_size))
    arr = np.asarray(img, dtype=np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    return diff.flatten()

def image_features(path):
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img).convert("RGB")
        w, h = img.size

        # Resize for lightweight statistics.
        sample = img.copy()
        sample.thumbnail((500, 500))
        arr = np.asarray(sample, dtype=np.float32)

        # Grafana screenshot is predominantly dark.
        brightness = arr.mean(axis=2)
        dark_ratio = float(np.mean(brightness < 80))
        very_dark_ratio = float(np.mean(brightness < 45))

        # Horizontal dashboard-like aspect ratio.
        aspect = w / h if h else 0

        return {
            "width": w,
            "height": h,
            "aspect": aspect,
            "dark_ratio": dark_ratio,
            "very_dark_ratio": very_dark_ratio,
            "hash": dhash(img),
        }
    except Exception:
        return None

def grafana_similarity(candidate_path, reference_features):
    f = image_features(candidate_path)
    if not f or not reference_features:
        return 0.0, f

    # dHash similarity (layout/edges)
    h1 = f["hash"]
    h2 = reference_features["hash"]
    hash_similarity = 1.0 - float(np.mean(h1 != h2))

    # Aspect ratio similarity
    ar1 = f["aspect"]
    ar2 = reference_features["aspect"]
    if ar1 <= 0 or ar2 <= 0:
        aspect_similarity = 0.0
    else:
        aspect_similarity = max(0.0, 1.0 - abs(ar1 - ar2) / ar2)

    # Dark-theme similarity
    dark_similarity = max(
        0.0,
        1.0 - abs(f["dark_ratio"] - reference_features["dark_ratio"])
    )

    # Weighted score: structure dominates.
    score = (
        0.65 * hash_similarity
        + 0.20 * aspect_similarity
        + 0.15 * dark_similarity
    )
    return score, f

def is_target_grafana(path, reference_features, threshold):
    score, f = grafana_similarity(path, reference_features)
    if not f:
        return False, score, "Unreadable image"

    # Basic guards to reject portraits, small icons, camera photos, etc.
    if f["width"] < 700 or f["height"] < 350:
        return False, score, "Image too small"

    if f["aspect"] < 1.45 or f["aspect"] > 2.10:
        return False, score, "Wrong aspect ratio"

    if f["dark_ratio"] < 0.45:
        return False, score, "Not dark Grafana-like layout"

    if score < threshold:
        return False, score, "Below similarity threshold"

    return True, score, "Matched Grafana reference"

def build_archive(df, images, out_root, threshold):
    out_root = Path(out_root)
    organized = out_root / "Grafana_Audit_2026"
    organized.mkdir(parents=True, exist_ok=True)

    reference_features = image_features(REFERENCE_PATH)
    used = set()
    audit_rows = []
    rejected_rows = []

    if df.empty:
        return organized, pd.DataFrame(), pd.DataFrame()

    # Only messages from 2026 are eligible.
    df = df[df["datetime"].apply(lambda x: getattr(x, "year", None) == TARGET_YEAR)].copy()

    for _, row in df.iterrows():
        matched = best_media_match(row.get("media_name"), images)
        if matched is None:
            continue

        used.add(str(matched.resolve()))

        accepted, score, reason = is_target_grafana(
            matched,
            reference_features,
            threshold
        )

        dt = row["datetime"]

        if not accepted:
            rejected_rows.append({
                "Date": dt.date().isoformat(),
                "Time": dt.strftime("%H:%M:%S"),
                "Sender": row.get("sender", ""),
                "Original Media": matched.name,
                "Similarity": round(score, 4),
                "Reason": reason,
            })
            continue

        # Date-wise folder inside the year 2026.
        folder = organized / "2026" / f"{dt:%Y-%m-%d}"
        folder.mkdir(parents=True, exist_ok=True)

        renamed = safe_name(
            f"{dt:%Y-%m-%d}_{dt:%H-%M-%S}_Grafana_CPU_Memory_{matched.name}"
        )
        dest = folder / renamed
        shutil.copy2(matched, dest)

        audit_rows.append({
            "Date": dt.date().isoformat(),
            "Time": dt.strftime("%H:%M:%S"),
            "Sender": row.get("sender", ""),
            "Original Media": matched.name,
            "Archived File": str(dest.relative_to(organized)),
            "Similarity": round(score, 4),
            "SHA256": file_hash(matched),
            "Status": "Accepted - Grafana CPU/Memory",
        })

    audit_df = pd.DataFrame(audit_rows)
    rejected_df = pd.DataFrame(rejected_rows)

    if not audit_df.empty:
        audit_df.to_csv(organized / "audit_index_2026.csv", index=False)

        coverage = (
            audit_df.groupby("Date")
            .size()
            .reset_index(name="Grafana Screenshots")
        )
        coverage.to_csv(organized / "daily_coverage_2026.csv", index=False)

    if not rejected_df.empty:
        rejected_df.to_csv(organized / "rejected_media_2026.csv", index=False)

    readme = """WhatsApp Grafana Audit Archive - 2026

This archive contains only images accepted as matching the configured Grafana
CPU/Memory dashboard reference.

Folder structure:
2026/YYYY-MM-DD/

Audit integrity:
- WhatsApp message timestamps are used for date placement.
- SHA256 hashes are recorded for accepted screenshots.
- rejected_media_2026.csv records WhatsApp-linked media that was intentionally
  not included because it did not sufficiently resemble the Grafana reference.

Important:
Visual classification is heuristic. Review the Accepted and Rejected previews
before treating the generated archive as final audit evidence.
"""
    (organized / "README.txt").write_text(readme, encoding="utf-8")

    return organized, audit_df, rejected_df

def zip_folder(folder):
    memory = BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as z:
        for p in Path(folder).rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(Path(folder).parent)))
    memory.seek(0)
    return memory

with st.sidebar:
    st.header("Detection settings")
    st.write("Target year: **2026**")
    threshold = st.slider(
        "Grafana similarity threshold",
        min_value=0.45,
        max_value=0.90,
        value=0.58,
        step=0.01,
        help=(
            "Higher values are stricter. If genuine Grafana screenshots are rejected, "
            "lower this slightly. If unrelated screenshots are accepted, raise it."
        ),
    )

    if REFERENCE_PATH.exists():
        st.write("Reference dashboard:")
        st.image(str(REFERENCE_PATH), use_container_width=True)
    else:
        st.error("Reference image is missing from the deployed app.")

    st.markdown(
        """
**This version keeps only:**
- 2026 WhatsApp-linked images
- dark, wide Grafana-style screenshots
- images visually similar to your CPU/Memory dashboard

Other media is excluded from the audit ZIP.
"""
    )

uploaded = st.file_uploader("Upload WhatsApp export ZIP", type=["zip"])

if uploaded:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        zip_path = td / "export.zip"
        zip_path.write_bytes(uploaded.getvalue())

        extract_dir = td / "extracted"
        extract_dir.mkdir()

        try:
            with zipfile.ZipFile(zip_path) as z:
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
        c1.metric("Images in export", len(images))
        c2.metric("WhatsApp chat", "Detected" if chat_file else "Not detected")
        c3.metric("Target year", TARGET_YEAR)

        if not chat_file:
            st.error(
                "This ZIP does not contain a recognizable WhatsApp exported chat. "
                "Use WhatsApp → Export chat → Include media."
            )
            st.stop()

        st.success(f"WhatsApp chat detected: {chat_file.name}")
        df = parse_chat(chat_file)

        msg_2026 = 0
        if not df.empty:
            msg_2026 = int(
                df["datetime"]
                .apply(lambda x: getattr(x, "year", None) == TARGET_YEAR)
                .sum()
            )

        st.write(
            f"Parsed **{len(df):,}** messages; "
            f"**{msg_2026:,}** belong to **2026**."
        )

        out_root = td / "output"
        archive, audit_df, rejected_df = build_archive(
            df, images, out_root, threshold
        )

        a, b = st.columns(2)
        a.metric("Accepted Grafana screenshots", len(audit_df))
        b.metric("Rejected other media", len(rejected_df))

        if not audit_df.empty:
            st.subheader("✅ Accepted audit evidence")
            st.dataframe(audit_df, use_container_width=True)

            st.subheader("2026 daily coverage")
            coverage = (
                audit_df.groupby("Date")
                .size()
                .reset_index(name="Grafana Screenshots")
            )
            st.dataframe(coverage, use_container_width=True)
        else:
            st.warning(
                "No screenshots matched the Grafana reference at the current threshold. "
                "Try lowering the similarity threshold slightly."
            )

        with st.expander("Review rejected media"):
            if rejected_df.empty:
                st.write("No WhatsApp-linked images were rejected.")
            else:
                st.dataframe(rejected_df, use_container_width=True)

        zip_bytes = zip_folder(archive)
        st.download_button(
            "⬇️ Download 2026 Grafana audit archive",
            data=zip_bytes,
            file_name="Grafana_Audit_2026.zip",
            mime="application/zip",
            use_container_width=True,
        )
else:
    st.markdown(
        """
### Output structure

```text
Grafana_Audit_2026/
├── 2026/
│   ├── 2026-01-01/
│   │   └── 2026-01-01_09-15-22_Grafana_CPU_Memory_IMG-....jpg
│   ├── 2026-01-02/
│   └── ...
├── audit_index_2026.csv
├── daily_coverage_2026.csv
├── rejected_media_2026.csv
└── README.txt
```

Only screenshots that visually resemble the configured Grafana CPU/Memory
reference are included in the audit archive.
"""
    )
