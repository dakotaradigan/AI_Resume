# pdf.js (vendored)

Reads the text of an uploaded job-description PDF in the visitor's browser, so
the file itself never reaches the server. Loaded on demand by `app.js` the
first time a PDF is chosen; a visitor who pastes text never downloads it.

| File | Source |
|---|---|
| `pdf.min.mjs` | `pdfjs-dist@6.5.438`, `legacy/build/pdf.min.mjs` |
| `pdf.worker.min.mjs` | `pdfjs-dist@6.5.438`, `legacy/build/pdf.worker.min.mjs` |

Copyright Mozilla Foundation, Apache License 2.0 ([LICENSE](LICENSE)). The
files are unmodified copies of the npm release. They are served from this
origin because the site's Content-Security-Policy allows scripts from `'self'`
only. To update, replace both files from the same `pdfjs-dist` version.
