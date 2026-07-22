// Generated from the API metric registry. Do not edit manually.
export type Platform = "douyin" | "xiaohongshu";
export type ContentType = "video" | "image_text";
export type MetricUnit = "count" | "ratio" | "seconds" | "number";
export type MetricAggregation = "latest" | "sum" | "average";

export interface MetricDisplayMetadata {
  key: string;
  label: string;
  unit: MetricUnit;
  aggregation: MetricAggregation;
  higherIsBetter: boolean;
}

export const PLATFORM_METRICS = {
  "douyin:video": [
    {
      key: "views",
      label: "播放量",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "likes",
      label: "点赞",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "comments",
      label: "评论",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "shares",
      label: "分享",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "favorites",
      label: "收藏",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "bounce_rate_2s",
      label: "2 秒跳出率",
      unit: "ratio",
      aggregation: "latest",
      higherIsBetter: false,
    },
    {
      key: "completion_rate_5s",
      label: "5 秒完播率",
      unit: "ratio",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "completion_rate",
      label: "整体完播率",
      unit: "ratio",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "average_watch_duration",
      label: "平均播放时长",
      unit: "seconds",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "profile_visits",
      label: "主页访问",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "followers_gained",
      label: "新增关注",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
  ],
  "douyin:image_text": [
    {
      key: "views",
      label: "播放量",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "likes",
      label: "点赞",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "comments",
      label: "评论",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "shares",
      label: "分享",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "favorites",
      label: "收藏",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "profile_visits",
      label: "主页访问",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "followers_gained",
      label: "新增关注",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
  ],
  "xiaohongshu:video": [
    {
      key: "impressions",
      label: "曝光量",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "views",
      label: "阅读/播放量",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "cover_click_rate",
      label: "封面点击率",
      unit: "ratio",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "likes",
      label: "点赞",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "comments",
      label: "评论",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "favorites",
      label: "收藏",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "shares",
      label: "分享",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "profile_visits",
      label: "主页访问",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "followers_gained",
      label: "新增关注",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "average_watch_duration",
      label: "平均观看时长",
      unit: "seconds",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "completion_rate",
      label: "完播率",
      unit: "ratio",
      aggregation: "latest",
      higherIsBetter: true,
    },
  ],
  "xiaohongshu:image_text": [
    {
      key: "impressions",
      label: "曝光量",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "views",
      label: "阅读/播放量",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "cover_click_rate",
      label: "封面点击率",
      unit: "ratio",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "likes",
      label: "点赞",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "comments",
      label: "评论",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "favorites",
      label: "收藏",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "shares",
      label: "分享",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "profile_visits",
      label: "主页访问",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
    {
      key: "followers_gained",
      label: "新增关注",
      unit: "count",
      aggregation: "latest",
      higherIsBetter: true,
    },
  ],
} as const satisfies Record<
  `${Platform}:${ContentType}`,
  readonly MetricDisplayMetadata[]
>;
