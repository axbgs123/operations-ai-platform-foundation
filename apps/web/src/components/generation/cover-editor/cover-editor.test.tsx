import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";

import { CoverEditor } from "./cover-editor";


afterEach(cleanup);


test("offers all four modes and the three primary cover sizes", () => {
  render(<CoverEditor />);

  expect(screen.getByRole("option", { name: "模板模式" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "AI 视觉模式" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "混合模式" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "自定义模式" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "1080 × 1440" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "1080 × 1920" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "1080 × 1080" })).toBeInTheDocument();
});


test("shows the exact model data disclosure before generating", async () => {
  const user = userEvent.setup();
  render(<CoverEditor />);

  await user.selectOptions(screen.getByLabelText("封面模式"), "ai_visual");
  await user.type(screen.getByLabelText("视觉提示词"), "蓝色科技感，主体居中");
  await user.type(screen.getByLabelText("封面主标题"), "准确中文标题");
  await user.upload(
    screen.getByLabelText("参考图文件"),
    new File(["synthetic"], "product-reference.png", { type: "image/png" }),
  );
  await user.selectOptions(screen.getByLabelText("参考图用途"), "product");
  await user.upload(
    screen.getByLabelText("Logo 文件"),
    new File(["logo"], "brand-logo.png", { type: "image/png" }),
  );
  await user.click(screen.getByRole("button", { name: "检查发送范围" }));

  const disclosure = screen
    .getByRole("heading", { name: "发送给图片模型的数据" })
    .closest("article");
  expect(disclosure).not.toBeNull();
  expect(within(disclosure!).getByText("蓝色科技感，主体居中")).toBeInTheDocument();
  expect(
    within(disclosure!).getByText("product-reference.png · 产品"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("最终中文、Logo 和品牌元素不会发送给图片模型"),
  ).toBeInTheDocument();
  expect(screen.getByText("brand-logo.png · 仅由程序叠加")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "确认并生成 Mock 封面" }),
  ).toBeDisabled();

  await user.click(screen.getByLabelText("我已确认发送范围"));
  await user.click(screen.getByRole("button", { name: "确认并生成 Mock 封面" }));

  expect(screen.getByText("准确中文标题")).toBeInTheDocument();
  expect(screen.getByText("Mock 视觉层 · 最终文字由程序叠加")).toBeInTheDocument();
});


test("only permits the five supported reference purposes", () => {
  render(<CoverEditor />);

  const purposes = screen.getByLabelText("参考图用途");
  expect(purposes).toHaveTextContent("构图");
  expect(purposes).toHaveTextContent("风格");
  expect(purposes).toHaveTextContent("人物");
  expect(purposes).toHaveTextContent("产品");
  expect(purposes).toHaveTextContent("配色");
  expect(purposes).not.toHaveTextContent("Logo");
});
