import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import {
  editTextGeneration,
  requestTextGeneration,
} from "@/lib/generation-api";
import { TextEditor } from "./text-editor";


vi.mock("@/lib/generation-api", () => ({
  requestTextGeneration: vi.fn(),
  readTextGeneration: vi.fn(),
  editTextGeneration: vi.fn(),
  cancelTextGeneration: vi.fn(),
  retryTextGeneration: vi.fn(),
}));

const run = {
  id: "run-1",
  workspace_id: "workspace-1",
  account_id: "11111111-1111-4111-8111-111111111111",
  model_config_id: "22222222-2222-4222-8222-222222222222",
  status: "succeeded" as const,
  original_result: {
    titles: ["标题一", "标题二", "标题三"],
    copy: "已确认售价 199 元",
    claims: [{ field_name: "price", value: "199 元" }],
    citations: [{
      fact_item_id: "33333333-3333-4333-8333-333333333333",
      source_id: "44444444-4444-4444-8444-444444444444",
      field_code: "price",
      value: "199 元",
    }],
    warnings: [],
  },
  final_title: "标题一",
  final_copy: "已确认售价 199 元",
  adoption_status: "pending" as const,
  modification_magnitude: 0,
  retry_of_run_id: null,
  error_code: null,
  status_detail: null,
  completed_at: "2026-07-23T00:00:00Z",
  created_at: "2026-07-23T00:00:00Z",
  context: {} as never,
};

beforeEach(() => {
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(requestTextGeneration).mockResolvedValue(run);
  vi.mocked(editTextGeneration).mockResolvedValue({
    ...run,
    adoption_status: "adopted",
  });
});

test("generates alternatives, shows citations, and saves the human final", async () => {
  const user = userEvent.setup();
  render(<TextEditor workspaceId="workspace-1" />);

  await user.type(screen.getByLabelText("账号 ID"), run.account_id);
  await user.type(screen.getByLabelText("模型配置 ID"), run.model_config_id);
  await user.type(screen.getByLabelText("生成目标"), "新品发布");
  await user.click(screen.getByRole("button", { name: "生成标题与文案" }));

  expect(await screen.findByText("标题二")).toBeInTheDocument();
  expect(screen.getByText("price：199 元")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "采用标题二" }));
  await user.click(screen.getByRole("button", { name: "采用并保存" }));

  expect(editTextGeneration).toHaveBeenCalledWith(
    "workspace-1",
    "run-1",
    expect.objectContaining({
      final_title: "标题二",
      adoption_status: "adopted",
    }),
    "csrf-token",
  );
  expect(await screen.findByText("已保存人工最终稿")).toBeInTheDocument();
});
