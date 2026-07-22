import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { createContent } from "@/lib/content-api";

import { NewContentForm } from "./new-content-form";


vi.mock("@/lib/content-api", () => ({
  createContent: vi.fn(() => new Promise(() => undefined)),
}));

beforeEach(() => {
  vi.mocked(createContent).mockClear();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
});

test("submits the selected content type through the generated API contract", async () => {
  render(
    <NewContentForm
      accountId="11111111-1111-4111-8111-111111111111"
      platform="xiaohongshu"
      workspaceId="22222222-2222-4222-8222-222222222222"
    />,
  );

  fireEvent.change(screen.getByLabelText("内容类型"), {
    target: { value: "image_text" },
  });
  fireEvent.change(screen.getByLabelText("标题"), {
    target: { value: "图文测试" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建作品" }));

  await waitFor(() => {
    expect(createContent).toHaveBeenCalledWith(
      expect.objectContaining({
        content_type: "image_text",
        title: "图文测试",
      }),
      "csrf-token",
    );
  });
});
