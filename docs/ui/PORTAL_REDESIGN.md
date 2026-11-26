# Sign-in and procurement workspace design

Implements the reviewed navy/teal concepts with large readable text, industrial photography, grouped navigation, a responsive menu, an overview with real account data, and links into existing workflows.

The sign-in retains local account and configured OIDC token flows, password visibility, errors and website navigation. The sidebar retains all eighteen internal screens and the two supplier screens. Dashboard totals use the authenticated API response, not the concept image numbers; source data, business permissions and approval rules remain server responsibilities. Original record/evidence details stay available.

## Validation

- `npm --prefix frontend run build`: TypeScript and production build.
- `python scripts/test_browser.py --prepare`: fresh SQLite and Chromium acceptance, including password toggle, mobile fit, real empty and closed-order dashboard values, quick actions, all eighteen screens, separate approval, timeout/reconciliation, receipts, invoice recheck, order closure, supplier isolation and audit.
- Photographic assets are local WebP files (about 375 KiB combined), generated for these concepts; no remote font, stock-photo service or image hotlink is required.
- Layout screenshots are test outputs, not seeded application facts. Browser automation is targeted acceptance, not a comprehensive accessibility audit.

## Generated asset provenance

Built-in image generation was used, with the approved UI previews as references. The prompts requested only photographic assets, excluding UI/text/logos. Both original generated PNGs are retained locally; WebP encoding preserves their dimensions.

Banner prompt: modern clean industrial loading bays, orderly steel pipe racks on the right, an open yard, golden sunrise, cool navy/teal shadows and a dark uncluttered left third for CSS text. No UI, text, logos, icons, frames or watermark.

Sign-in prompt: portrait industrial warehouse interior, stainless steel pipes on the left, tidy material racks, sunlight through a loading bay on the lower right, dark navy upper half for CSS headings, warm floor reflections. No interface, text, logos, icons, people or watermark.

The new UI branch is based on the existing customer-quote storage branch so its tested procurement baseline is preserved. Its CI trigger permits that stacked target. No merge, database migration or deployment is part of the UI change.
