import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { PublicDataBindingPanel } from "./content-binding-panel";

vi.mock("@/lib/public-data-api", () => ({
  collectPublicContentNow: vi.fn(),
  getPublicContentBinding: vi.fn(),
  savePublicContentBinding: vi.fn(),
}));

import {
  getPublicContentBinding,
  savePublicContentBinding,
} from "@/lib/public-data-api";

const binding = {
  id: "binding-1",
  content_id: "content-1",
  account_id: "account-1",
  platform: "douyin" as const,
  public_url: "https://www.douyin.com/video/73000123456789",
  platform_content_id: "73000123456789",
  published_at: "2026-09-04T01:00:00Z",
  status: "active" as const,
  last_verified_at: "2026-09-04T01:02:00Z",
  safe_error_code: null,
  jobs: [
    {
      id: "job-1",
      target_window: "1h",
      due_at: "2026-09-04T02:00:00Z",
      next_attempt_at: "2026-09-04T02:00:00Z",
      status: "scheduled" as const,
      attempt_count: 0,
      snapshot_id: null,
      safe_error_code: null,
    },
  ],
};

beforeEach(() => {
  sessionStorage.clear();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(getPublicContentBinding).mockResolvedValue(null);
  vi.mocked(savePublicContentBinding).mockResolvedValue(binding);
});

test("editor binds a public work and sees its automatic schedule", async () => {
  render(
    <PublicDataBindingPanel
      contentId="content-1"
      initialPublishedAt={null}
      initialUrl={null}
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  fireEvent.change(await screen.findByLabelText("作品公开链接"), {
    target: { value: binding.public_url },
  });
  fireEvent.change(screen.getByLabelText("发布时间"), {
    target: { value: "2026-09-04T09:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: "绑定作品并开始计划" }));

  await waitFor(() => {
    expect(savePublicContentBinding).toHaveBeenCalledWith(
      "workspace-1",
      "content-1",
      "csrf-token",
      expect.objectContaining({ public_url: binding.public_url }),
    );
  });
  expect(await screen.findByText("发布后 1 小时")).toBeInTheDocument();
  expect(screen.getByText("等待采集")).toBeInTheDocument();
});
