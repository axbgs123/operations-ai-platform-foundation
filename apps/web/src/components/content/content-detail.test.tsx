import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ContentDetail } from "./content-detail";


test("shows content identity, lifecycle, completeness, and later module entrances", () => {
  render(
    <ContentDetail
      initialContent={{
        id: "content-1",
        workspace_id: "workspace-1",
        account_id: "account-1",
        account_name: "城市穿搭研究所",
        platform: "douyin",
        content_type: "video",
        title: "一件衬衫，两种通勤穿法",
        body: "正文",
        status: "draft",
        objective_profile_id: "objective-profile-1",
        benchmark_profile_id: "benchmark-profile-1",
        column_campaign_id: null,
        column_campaign_name: "通勤栏目",
        published_title: null,
        published_body: null,
        published_at: null,
        work_url: null,
        platform_content_id: null,
        deleted_at: null,
        assets: [],
      }}
    />,
  );

  expect(screen.getByRole("heading", { name: "一件衬衫，两种通勤穿法" })).toBeInTheDocument();
  expect(screen.getByText("抖音 · 城市穿搭研究所")).toBeInTheDocument();
  expect(screen.getByText("当前草稿")).toBeInTheDocument();
  expect(screen.getByText("暂无封面")).toBeInTheDocument();
  expect(screen.getByText("数据完整度待计算")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "进入深度分析" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/contents/content-1?tab=analysis",
  );
  expect(screen.getByText("内容生成（即将开放）")).toBeInTheDocument();
});
