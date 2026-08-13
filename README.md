
# WhatsApp Grafana Audit Organizer

A Streamlit tool for converting WhatsApp group exports containing Grafana screenshots into a date-organized audit archive.

## Features

- Upload WhatsApp exported ZIP
- Parse common WhatsApp chat timestamp formats
- Match media files referenced in chat messages
- Sort evidence into Year / Month / Date folders
- Basic CPU / Memory / Disk / Network classification from filename or message text
- Generate `audit_index.csv`
- Generate `daily_coverage.csv`
- SHA256 hash every image for integrity verification
- Preserve unmatched media under `_Unmatched_Media`

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Run on Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload `app.py` and `requirements.txt`.
3. In Streamlit Community Cloud, create an app from the repository.
4. Set the main file to `app.py`.

## Important limitation in v0.1

WhatsApp export formats differ between Android/iPhone, locale, and app version. This version handles common exported-text formats. Once a real sample export is available, the parser can be tuned to your organization's exact format.

For audit use, validate the generated index against a sample of the original export before relying on it as authoritative evidence.
