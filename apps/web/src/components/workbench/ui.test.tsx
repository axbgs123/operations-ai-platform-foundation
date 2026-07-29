import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  DataTableFrame,
  DesktopOnlyNotice,
  DetailTabs,
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  PermissionNotice,
  Skeleton,
  StatusBadge,
} from "./ui";

afterEach(() => {
  cleanup();
});


test("renders status text in addition to color", () => {
  render(<StatusBadge tone="danger">高风险</StatusBadge>);

  expect(screen.getByText("高风险")).toHaveAttribute("data-tone", "danger");
});

test("keeps one h1 and labels the page actions", () => {
  const { container } = render(
    <PageHeader
      description="管理已发布内容"
      primaryAction={<button type="button">新建内容</button>}
      secondaryActions={<button type="button">导入数据</button>}
      title="内容库"
    />,
  );

  expect(container.querySelectorAll("h1")).toHaveLength(1);
  expect(screen.getByRole("heading", { level: 1, name: "内容库" })).toBeVisible();
  expect(screen.getByRole("group", { name: "页面操作" })).toBeVisible();
});

test("associates a panel with its visible heading", () => {
  render(
    <Panel description="最近一次同步结果" title="数据状态">
      <p>全部正常</p>
    </Panel>,
  );

  expect(screen.getByRole("region", { name: "数据状态" })).toBeVisible();
  expect(screen.getByText("最近一次同步结果")).toBeVisible();
});

test("gives empty and error states distinct accessible semantics", () => {
  const retry = vi.fn();
  const { rerender } = render(
    <EmptyState
      action={<button type="button">导入数据</button>}
      description="完成首次导入后会在这里显示内容"
      title="还没有内容"
    />,
  );

  expect(screen.getByRole("status")).toHaveTextContent("还没有内容");
  expect(screen.getByRole("button", { name: "导入数据" })).toBeVisible();

  rerender(
    <ErrorState
      description="请检查网络后重试"
      retryAction={<button onClick={retry} type="button">重新加载</button>}
      title="内容加载失败"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  expect(screen.getByRole("alert")).toHaveTextContent("内容加载失败");
  expect(retry).toHaveBeenCalledOnce();
});

test("explains role and desktop-only restrictions in text", () => {
  const { rerender } = render(
    <PermissionNotice currentRole="查看者" requiredRole="编辑者或管理员" />,
  );

  expect(screen.getByRole("note")).toHaveTextContent(
    "当前角色：查看者；需要角色：编辑者或管理员",
  );

  rerender(<DesktopOnlyNotice action="完整 ZIP 恢复" />);
  expect(screen.getByText(/请在电脑端继续完整 ZIP 恢复/)).toBeVisible();
});

test("labels loading placeholders without exposing decorative content", () => {
  render(<Skeleton label="正在加载内容列表" />);

  expect(screen.getByRole("status", { name: "正在加载内容列表" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
});

test("exposes detail tabs and their selected panel", () => {
  const onTabChange = vi.fn();
  render(
    <DetailTabs
      activeTab="overview"
      ariaLabel="内容详情"
      onTabChange={onTabChange}
      tabs={[
        { id: "overview", label: "概览", panel: <p>概览内容</p> },
        { id: "analysis", label: "分析", panel: <p>分析内容</p> },
      ]}
    />,
  );

  expect(screen.getByRole("tablist", { name: "内容详情" })).toBeVisible();
  expect(screen.getByRole("tab", { name: "概览" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("tabpanel", { name: "概览" })).toHaveTextContent(
    "概览内容",
  );

  fireEvent.click(screen.getByRole("tab", { name: "分析" }));
  expect(onTabChange).toHaveBeenCalledWith("analysis");
});

test("labels horizontally scrollable data tables", () => {
  render(
    <DataTableFrame label="内容数据">
      <table>
        <tbody>
          <tr>
            <td>合成内容</td>
          </tr>
        </tbody>
      </table>
    </DataTableFrame>,
  );

  expect(screen.getByRole("region", { name: "内容数据" })).toHaveAttribute(
    "tabindex",
    "0",
  );
  expect(screen.getByRole("table")).toBeVisible();
});
