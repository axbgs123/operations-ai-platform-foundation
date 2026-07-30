import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { DemoWorkspace } from "./demo-workspace";


test("labels synthetic data and mock generation clearly", () => {
  render(
    <DemoWorkspace
      initialWorkspace={{
        id: "public-demo",
        name: "内容运营示例工作区",
        label: "示例数据",
        seed_version: "synthetic-ai-tech-v1",
        synthetic: true,
        accounts: [
          { id: "douyin-demo", name: "城市穿搭研究所", platform: "douyin", synthetic: true, posts: [] },
          { id: "xiaohongshu-demo", name: "通勤灵感簿", platform: "xiaohongshu", synthetic: true, posts: [] },
        ],
      }}
    />,
  );

  expect(screen.getByText("示例工作区 · 只读")).toBeInTheDocument();
  expect(screen.getAllByText("示例数据").length).toBeGreaterThan(0);
  expect(screen.getByText("抖音 · 城市穿搭研究所")).toBeInTheDocument();
  expect(screen.getByText("小红书 · 通勤灵感簿")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成 Mock 标题" })).toBeInTheDocument();
  expect(screen.getByText(/不会写入真实工作区/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "进入私有工作区" })).toHaveAttribute(
    "href",
    "/enter",
  );
  expect(screen.queryByText("API Key")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /上传|删除|恢复/ })).not.toBeInTheDocument();
});
