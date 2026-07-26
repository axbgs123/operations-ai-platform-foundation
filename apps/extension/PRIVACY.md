# Privacy Summary

- Capture starts only after a user action and is limited to the visible tab.
- The extension does not read cookies, passwords, browsing history, hidden APIs, or offscreen page content.
- Invite codes are exchanged once and are not retained.
- Short-lived bearer tokens are stored only in `chrome.storage.session`.
- Screenshots enter a staging area; recognized fields require Web review before becoming formal snapshots.
- One-click mode never skips Web confirmation and is disabled on page, signature, sensitive-region, login, token, capture, upload, or recognition failures.
- Users can revoke the token, disable one-click trust, cancel staging tasks, and remove extension storage.
- The extension does not bypass login, CAPTCHA, or platform controls.
- Fixture verification does not constitute real-page, Windows, Chrome, or Edge compatibility evidence.

完整说明见 `docs/open-source/extension-privacy.md`。
