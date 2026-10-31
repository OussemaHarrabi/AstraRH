# Tech CV corpus — 30 profiles, multiple formats

Built from the **CC0-1.0** `opensporks/resumes` dataset (2,484 scraped resume examples; original Kaggle `snehaanbhawal/resume-dataset`). The source text was sanitized and paired with fictional identities. **No real person is represented by the final files.**

## What is here

| Folder | Contents |
|---|---|
| `pdf/` | 30 CVs — classic, modern two-column, compact and table-heavy layouts |
| `docx/` | 30 editable Word CVs |
| `html/` | 30 styled HTML CVs |
| `md/` | 30 Markdown CVs |
| `txt/` | 30 plain-text CVs |
| `json/` | 30 structured CVs (candidate + experience + skills + education) |
| `scanned/` | 2 image-only PDFs (no text layer) for OCR tests |
| `index.csv` | One row per candidate: title, field, source ID, layout, formats, job, contact |
| `applications.csv` | Synthetic applications across 12 job descriptions |
| `ground_truth.json` | Full structured records for evaluation |
| `sources.md` | Provenance and license |
| `preview_grid.png` | One-page visual check of four layouts |

`data/jobs/` contains 12 matching job descriptions (PDF + Markdown).

## Fields covered

Security (analyst, officer, auditor), systems/network/cloud, backend/.NET/web, engineering management, QA/automation, database administration, IT support/helpdesk, UX/UI and product design, software analysis, RF/electrical/embedded, DevOps, data/marketing technology.

## Formats and layouts

- **PDF:** classic single column, modern two-column sidebar, compact, table-heavy.
- **DOCX/HTML/MD/TXT/JSON:** same content, different structure.
- **Scanned:** image-only PDFs to test OCR fallback.

## How to use

1. Ingest `pdf/`, `docx/`, `html/`, `md/` and `txt/` as candidate files.
2. Use `json/` or `ground_truth.json` as expected structured output.
3. Use `scanned/` to verify OCR; text extraction should be empty until OCR runs.
4. Use `applications.csv` + `data/jobs/` to seed an ATS/inbox demo.
5. Use `index.csv` to map files to roles and source IDs.

## Rebuild

```bash
python tools/build_cv_corpus.py
```

The builder reads `data/source/Resume.csv`, sanitizes emails/phones/URLs/addresses/company placeholders, assigns fictional identities, and regenerates every format.

## License and caveats

- Source dataset: **CC0-1.0** (public domain dedication).
- Generated files: free to use for demos and testing.
- The source text is scraped resume *examples*; despite sanitization, residual template artifacts may remain. Review before redistribution.
- Emails use `example.com`; phones use `+33 6 00 00 XX` demo numbers; companies are fictional.
