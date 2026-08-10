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

- The new capture metadata column requires deployment migration `20260810_0037` before an upgraded API handles extension uploads.

## Fix round 1

- Added the strict API capture contract and task persistence for `capture_mode`, `complete`, `stop_reason`, and `slice_count`, including a forward-only `20260810_0037` migration. Full-page metadata accepts zero through 30 slices; complete captures require `bottom` and at least one slice, and visible/region captures require exactly one complete matching slice.
- Full-page scrolling now moves to document top before its first slice and still restores the original scroll position in `finally`.
- Full-page overlays create an `AbortController`; cancellation aborts the driver and sends one exact `END_FULL_PAGE_CAPTURE`. The background clears its armed state and its coordinator session map on that end message.
- An un-stitchable capture now attempts bounded prefixes. If no image can be made, the overlay keeps the safe stop reason/slice count and renders `重试` and `关闭` instead of throwing a generic failure.
- Shortcut lookup failures are isolated from Popup rendering and show the unassigned/conflict warning.

Fix-round RED/GREEN:

```text
RED: FastAPI route rejected the four fields with extra_forbidden (422);
     nonzero-scroll capture started at 420; cancelled overlay had no AbortSignal;
     null stitch threw capture-failed; shortcut lookup rejection escaped render.
GREEN: pnpm --filter extension test                 # 14 files, 169 tests passed
       pnpm --filter extension lint && pnpm --filter extension typecheck
       apps/api: uv run pytest tests/imports/test_extension_capture.py -q  # 7 passed
       apps/api: ruff + mypy                         # passed
       pnpm schemas:generate                         # regenerated OpenAPI/shared TS
       extension Chrome/Edge builds and secret scan   # passed
```

## Fix round 2

- Partial full-page requests now accept only full-page driver/stitch stop reasons; `visible`, `region`, and `bottom` are rejected.
- Parent cancellation now aborts the in-flight slice controller immediately.
- A successful bounded prefix is explicitly partial and carries the original stitch failure reason plus its actual prefix slice count.

## Fix round 3

- No-prefix full-page failures now always disclose the original stitch failure reason and captured slice count; a completed driver `bottom` is never used as a partial failure reason.
