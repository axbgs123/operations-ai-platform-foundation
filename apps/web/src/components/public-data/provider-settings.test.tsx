import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { PublicDataProviderSettings } from "./provider-settings";

vi.mock("@/lib/operations-api", () => ({
  readOperationsAccess: vi.fn(),
}));
vi.mock("@/lib/public-data-api", () => ({
  getPublicProvider: vi.fn(),
  savePublicProvider: vi.fn(),
  testPublicProvider: vi.fn(),
}));

import { readOperationsAccess } from "@/lib/operations-api";
import {
  getPublicProvider,
  savePublicProvider,
} from "@/lib/public-data-api";

beforeEach(() => {
  sessionStorage.clear();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(readOperationsAccess).mockResolvedValue({ role: "admin" } as never);
  vi.mocked(getPublicProvider).mockResolvedValue(null);
  vi.mocked(savePublicProvider).mockResolvedValue({
    id: "provider-1",
    provider: "tikhub",
    endpoint_region: "china",
    status: "unverified",
    daily_request_limit: 500,
    daily_requests_used: 0,
    configuration_revision: 1,
    last_tested_at: null,
    safe_error_code: null,
    has_api_key: true,
  });
});

test("admin can save a private TikHub key and sees the next step", async () => {
  render(<PublicDataProviderSettings workspaceId="workspace-1" />);

  const keyInput = await screen.findByLabelText("TikHub API Key");
  fireEvent.change(keyInput, { target: { value: "private-test-key" } });
  fireEvent.click(screen.getByRole("button", { name: "保存密钥" }));

  await waitFor(() => {
    expect(savePublicProvider).toHaveBeenCalledWith(
      "workspace-1",
      "csrf-token",
      expect.objectContaining({ api_key: "private-test-key" }),
    );
  });
  expect(await screen.findByText(/请继续测试连接/)).toBeInTheDocument();
  expect(keyInput).toHaveValue("");
});
