
# WhatsApp Grafana Audit Organizer v0.3

This Streamlit application extracts only WhatsApp-linked screenshots that
visually resemble the configured Grafana CPU/Memory dashboard and organizes
2026 evidence by WhatsApp message date.

## Files required in the GitHub repository

- `app.py`
- `requirements.txt`
- `grafana_reference.png`

## Output

```text
Grafana_Audit_2026/
├── 2026/
│   ├── 2026-01-01/
│   ├── 2026-01-02/
│   └── ...
├── audit_index_2026.csv
├── daily_coverage_2026.csv
├── rejected_media_2026.csv
└── README.txt
```

## Detection method

The app compares each WhatsApp-linked image against `grafana_reference.png`
using lightweight image-layout similarity, aspect ratio, and dark-theme
characteristics. The similarity threshold can be adjusted from the sidebar.

This intentionally avoids OCR so the application stays lightweight for
Streamlit Community Cloud.

## Streamlit Community Cloud

Upload all three required files to the root of your GitHub repository and
redeploy the app. `requirements.txt` adds Pillow and NumPy for image matching.

## Audit caution

The image classifier is heuristic. Review the accepted and rejected tables
against a sample of original evidence before treating the archive as final.
