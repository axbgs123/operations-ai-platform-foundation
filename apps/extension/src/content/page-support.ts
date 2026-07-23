export type SupportedPlatform = "douyin" | "xiaohongshu";

export type PageSupport = {
  supported: boolean;
  platform: SupportedPlatform | null;
  pageVersion: string;
  anchors: string[];
};

const pageDefinitions: Array<{
  platform: SupportedPlatform;
  hostname: string;
  pathnamePrefix: string;
  anchors: string[];
}> = [
  {
    platform: "douyin",
    hostname: "creator.douyin.com",
    pathnamePrefix: "/creator-micro/content/manage",
    anchors: ["作品管理"],
  },
  {
    platform: "xiaohongshu",
    hostname: "creator.xiaohongshu.com",
    pathnamePrefix: "/publish/publish-manage",
    anchors: ["笔记管理"],
  },
];

export function detectSupportedPage(
  locationLike: Pick<Location, "hostname" | "pathname">,
  pageText = "",
): PageSupport {
  const definition = pageDefinitions.find(
    (candidate) =>
      candidate.hostname === locationLike.hostname &&
      locationLike.pathname.startsWith(candidate.pathnamePrefix),
  );
  if (!definition) {
    return { supported: false, platform: null, pageVersion: "unknown", anchors: [] };
  }
  const anchors = definition.anchors.filter((anchor) => pageText.includes(anchor));
  return {
    supported: anchors.length > 0,
    platform: anchors.length > 0 ? definition.platform : null,
    pageVersion: "task-1",
    anchors,
  };
}
