import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { SETTINGS_ITEMS, SettingsNav } from "./settings-nav";

test("exposes the four operator-facing settings destinations", () => {
  render(<SettingsNav workspaceId="ws-1" />);

  expect(SETTINGS_ITEMS).toHaveLength(4);
  for (const item of SETTINGS_ITEMS) {
    expect(screen.getByRole("link", { name: item.label })).toHaveAttribute(
      "href",
      expect.stringContaining("/workspaces/ws-1/"),
    );
  }
});
