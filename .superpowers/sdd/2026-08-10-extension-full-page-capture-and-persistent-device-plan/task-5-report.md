# Task 5 Report — Shortcut, Full-Page Preview, and Optional Redaction UX

## Implementation

- Added the `capture-full-page` command with the documented `Ctrl+Shift+8` / `Command+Shift+8` suggestions.
- Added one background `CaptureCoordinator`; Popup sends `START_CAPTURE` to it and `chrome.commands.onCommand` passes its command-provided tab to the same coordinator.
- Made automatic full-page capture the primary Popup action. Visible-area and manual-region modes are under `更多采集方式`; the Popup reads the browser-assigned shortcut and warns when it is unavailable or conflicted.
- Connected the armed Task 4 scrolling driver and stitcher to a preview-first full-page overlay. The preview shows complete/partial state, slice count, dimensions, and encoded size. Every mode keeps upload behind `确认上传`.
- Redaction starts disabled. Its controls are not mounted until enabled; disabling it with masks asks for confirmation before clearing them.
- Uploads include `capture_mode`, `complete`, `stop_reason`, and `slice_count`. The request carries exactly one final screenshot data URL and does not add page body text or an unredacted duplicate.

## RED

Command run:

```text
pnpm --filter extension test -- tests/manifest.test.ts tests/capture-overlay.test.ts tests/popup-pairing.test.ts tests/runtime-wiring.test.ts
```

Observed expected RED result: 5 targeted failures for the absent manifest command, command coordinator listener, Popup full-page action/shortcut display, and disabled-by-default redaction controls. Existing tests passed.

## GREEN and verification

```text
pnpm --filter extension test                 # 14 files, 162 tests passed
pnpm --filter extension lint                 # passed
pnpm --filter extension typecheck            # passed
pnpm --filter extension build:chrome         # passed
pnpm --filter extension build:edge           # passed
bash scripts/secret-scan.sh                  # secret_scan=clean
git diff --check                             # passed
```

The brief named `scripts/scan-secrets.sh`; that file does not exist in this checkout. The repository-provided equivalent is `scripts/secret-scan.sh`, used above.

## Permission audit

- Named permissions remain exactly `activeTab`, `scripting`, and `storage`.
- No `tabs`, `cookies`, `webRequest`, `debugger`, or `<all_urls>` permission was added.
- Command capture uses the command-provided tab as the explicit user gesture; Popup starts are routed through the same background coordinator.

## Self-review

- Full-page arming remains bound to tab, URL, page metadata, viewport, session, and ordered slices.
- Upload still uses the established confirmed-preview flow, polling, 401 re-pair cleanup, validated review link, and workspace/platform fields.
- Preview image data is retained only in memory and cleared on cancellation; only the final redacted image reaches the upload request.

## Commit

`feat: add shortcut-driven full-page capture preview`

## Concerns

- The extension request now sends the required capture metadata. Persisting or displaying those fields server-side is outside this extension-only task and depends on the API schema accepting the additive fields.
