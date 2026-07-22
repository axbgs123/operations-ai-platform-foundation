"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import {
  DashboardChart,
  dashboardDrillDownHref,
} from "@/lib/dashboard-api";


function chartOption(chart: DashboardChart) {
  if (chart.kind === "funnel") {
    return {
      tooltip: { trigger: "item" },
      series: [{
        type: "funnel",
        data: chart.points.map((point) => ({ name: point.x, value: point.y })),
      }],
    };
  }
  if (chart.kind === "heatmap") {
    const values = chart.points.map((point) => point.value ?? point.y);
    return {
      tooltip: {},
      xAxis: { type: "category", data: [...new Set(chart.points.map((point) => point.x))] },
      yAxis: { type: "category", data: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"] },
      visualMap: { min: Math.min(...values), max: Math.max(...values), calculable: true },
      series: [{
        type: "heatmap",
        data: chart.points.map((point) => [point.x, point.y, point.value ?? point.y]),
      }],
    };
  }
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: chart.points.map((point) => point.x.slice(5, 10)) },
    yAxis: { type: "value", name: chart.unit },
    series: [{ type: "line", smooth: true, data: chart.points.map((point) => point.y) }],
  };
}

export function ChartPanel({ chart }: { chart: DashboardChart }) {
  const target = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!target.current || typeof window.matchMedia !== "function") return;
    let disposed = false;
    let cleanup = () => {};
    void import("echarts").then((echarts) => {
      if (disposed || !target.current) return;
      const instance = echarts.init(target.current, "dark");
      instance.setOption(chartOption(chart));
      const resize = () => instance.resize();
      window.addEventListener("resize", resize);
      cleanup = () => {
        window.removeEventListener("resize", resize);
        instance.dispose();
      };
    });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [chart]);

  return (
    <Link
      aria-label={`查看${chart.title}对应内容`}
      className="group block rounded-3xl border border-slate-800 bg-slate-900 p-5 transition hover:border-cyan-500"
      href={dashboardDrillDownHref(chart.drill_down_filter)}
    >
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-lg font-semibold">{chart.title}</h3>
        <span className="text-sm text-cyan-300">查看内容 →</span>
      </div>
      <div aria-hidden="true" className="mt-4 h-64 w-full" ref={target} />
      <p className="mt-3 text-xs text-slate-400">
        有效样本 {chart.sample_count} 条 · {chart.explanation}
      </p>
      <p className="sr-only">单一量纲：{chart.unit}，共 {chart.points.length} 个数据点</p>
    </Link>
  );
}
