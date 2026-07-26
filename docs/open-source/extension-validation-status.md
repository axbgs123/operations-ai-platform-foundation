# Capture Extension validation status

This document records what has actually been validated for the capture
extension. A successful fixture test or package build is not evidence that a
real platform page works.

## Current evidence

- The Douyin and Xiaohongshu adapters pass synthetic, redacted HTML fixture
  tests.
- Chrome and Edge packages are built from the same source and have an identical
  archive hash for the recorded build.
- No real Douyin or Xiaohongshu page was opened during automated validation.
- An automated Chrome package-load attempt was made, but the current sandbox
  terminated the browser process before the MV3 service worker could be
  observed. The package therefore remains runtime-unverified. Static-page E2E
  exercises the workflow but must not be described as an installed-extension
  runtime test.
- Microsoft Edge is not installed in the current validation environment. An
  identical Edge archive is a packaging result, not Edge runtime evidence.

## Environment matrix

| Environment | Real page status | Package runtime status |
| --- | --- | --- |
| macOS / Chrome | Unverified | Unverified |
| macOS / Edge | Unverified | Unverified |
| Windows / Chrome | Unverified | Unverified |
| Windows / Edge | Unverified | Unverified |

These rows are independent. Evidence from one browser or operating system must
not be used to mark another row as verified.

## Promotion rule

An environment may be marked `real_page_verified` in
`apps/extension/supported-pages.json` only after an authorized user completes
the manual checklist in
`docs/open-source/extension-real-page-validation-template.md`. The evidence
must not contain account names, cookies, screenshots, private business data,
passwords, invitation codes, bearer tokens, or CAPTCHA contents.

If anchors, capture regions, sensitive regions, page versions, or signatures
change, the entry must be marked `stale` and the extension must fall back to
safe mode until it is revalidated.
