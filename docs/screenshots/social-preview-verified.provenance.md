# DocExtract social preview provenance

- Source: `frontend/demo_data/invoice_sample.json`, source commit `c4562bb10980b7c9abf289c9020de6633ece079c`.
- Source SHA-256: `f75eb3ea9d28e9a2d4f40daae6d58235e7a48ce6b2b654345468e1b943cc8ba5`.
- The three visible values are copied from `extracted_data.invoice_number`, `extracted_data.invoice_date`, and `extracted_data.total`.
- This is an editorial card of a stored JSON sample, not a product screenshot or a live extraction result.
- The card explicitly says `STORED JSON SAMPLE / NO LIVE MODEL CALL`.
- Confidence, latency, accuracy, and evaluation scores are intentionally absent. The subtitle describes project scope, not the sample's measured performance.
- SVG source is 1280 by 640. PNG is a browser rasterization of that SVG. Palette matches the sibling MCP cache receipt: background `#101820`, panel `#182530`, border `#344958`, accent `#98dcce`.
- Existing `social-preview.jpg` is retained. No repository setting has been changed.
- Verification: rendered in installed Google Chrome using agent-browser, then inspected at 1280 by 640 and at 375 by 188. Title, sample marker, and all three values remain legible; secondary source explanation is smaller at mobile width. PNG size: 65680 bytes, under 1 MB. SVG parses successfully. No external model or API call was made.
