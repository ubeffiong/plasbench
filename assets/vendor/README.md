# Vendored web assets

These files replace runtime CDN requests. A benchmark report must render
identically offline, years later, without depending on a third-party host
staying up or serving the same bytes.

| File | Origin | Licence |
|---|---|---|
| `inter.css`, `fonts/inter-variable.woff2` | Google Fonts, Inter (Latin subset) | SIL Open Font Licence 1.1 |
| `fontawesome-subset.css`, `fonts/fa-solid-900.woff2` | Font Awesome Free 6.5.0, solid | CC BY 4.0 (icons), SIL OFL 1.1 (font) |

`fontawesome-subset.css` declares only the 32 glyphs the report renders,
regenerated from upstream `all.min.css`; the woff2 is the unmodified upstream
solid face. `build_html_report.py` inlines both as base64 at build time so a
report stays a single portable file.
