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
    status_detail: "未检索到有效风控证据；草稿已保存，但不能进入待发布",
  });
});

test("generates alternatives, shows citations, and saves the human final", async () => {
  const user = userEvent.setup();
  render(<TextEditor workspaceId="workspace-1" />);

  await user.type(screen.getByLabelText("账号 ID"), run.account_id);
  await user.type(screen.getByLabelText("模型配置 ID"), run.model_config_id);
  await user.type(
    screen.getByLabelText("栏目或活动 ID"),
    "55555555-5555-4555-8555-555555555555",
  );
  await user.type(
    screen.getByLabelText("风格档案 ID"),
    "66666666-6666-4666-8666-666666666666",
  );
  await user.type(
    screen.getByLabelText("爆款引用 ID（最多 3 条）"),
    "77777777-7777-4777-8777-777777777777",
  );
  await user.type(screen.getByLabelText("生成目标"), "新品发布");
  await user.click(screen.getByRole("button", { name: "生成标题与文案" }));

  expect(requestTextGeneration).toHaveBeenCalledWith(
    "workspace-1",
    expect.objectContaining({
      column_campaign_id: "55555555-5555-4555-8555-555555555555",
      style_profile_id: "66666666-6666-4666-8666-666666666666",
      style_switches: { title: true, copy: true, cover: true },
      viral_library_item_ids: [
        "77777777-7777-4777-8777-777777777777",
      ],
    }),
    "csrf-token",
  );
  expect(await screen.findByText("标题二")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("执行成功");
  expect(screen.getByText("price：199 元")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "采用标题二" }));
  await user.click(
    screen.getByRole("button", { name: "复检并保存草稿" }),
  );

  expect(editTextGeneration).toHaveBeenCalledWith(
    "workspace-1",
    "run-1",
    expect.objectContaining({
      final_title: "标题二",
      adoption_status: "adopted",
    }),
    "csrf-token",
  );
  expect(await screen.findByText("复检完成，草稿已保存")).toBeInTheDocument();
});
