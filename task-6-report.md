# Task 6 Report — Device Management UI and Operator Documentation

## RED / GREEN

- RED: `pnpm --filter web test -- extension-device-list extension-device-api extension-pairing-panel` failed as expected before implementation: both new modules were unresolved and the pairing panel lacked the persistent-connection wording.
- GREEN: the same focused command passed with 54 test files and 328 tests after the API client, device list, confirmation flow, and pairing copy were added.
- Final verification: `pnpm --filter web test`, `pnpm --filter web lint`, `pnpm --filter web typecheck`, and `pnpm --filter web build` all completed successfully.

## Files

- Added the CSRF-protected device API client and its request-contract tests.
- Added the role-aware device list, revoke confirmation/retry UI, and UI tests.
- Added persistent-connection and recovery guidance to the pairing panel and tests.
- Mounted device management at workspace settings, using the actual workbench role instead of a route-level assumption.
- Updated installation, privacy, and validation documentation for shortcuts, bounded partial full-page capture, preview, redaction, key-loss recovery, and compatibility evidence.

## Permission, privacy, and copy audit

- Only admins call the device-list endpoint or receive a revoke action; editors and viewers receive guidance only, with no revoke control.
- GET and DELETE use session credentials and `X-CSRF-Token`; 404 text refers only to the current settings page and does not disclose another workspace.
- The interface and tests omit JWK/public-key material, fingerprints, tokens, and hashes. Unexpected server error bodies are replaced with operator-safe messages.
- The UI explains 5-minute pairing codes, persistent connection until user/admin revocation, 8-hour automatic credential renewal, and re-pairing after browser-data or device-key loss.
- Operator docs state the 30-screen/20-second boundary, possible `partial` result, default-off redaction, preview before upload, shortcut conflicts, and that real-platform compatibility remains limited by the validation matrix.

## Commit

`feat: explain and govern persistent extension devices`

## Concerns

- No real websites, browsers, or external providers were opened. Real-page and non-macOS/Chrome compatibility remain deliberately unverified and are documented as such.
