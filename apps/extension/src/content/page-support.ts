export type SupportedPlatform = "douyin" | "xiaohongshu";

export type PageSupport = {
  supported: boolean;
  platform: SupportedPlatform | null;
  pageVersion: string;
  anchors: string[];
};

export const SUPPORTED = {
  douyin: {
    hostname: "creator.douyin.com",
    pathPrefix: "/creator-micro/content/manage",
    pageVersion: "douyin-visible-tab-v1",
  },
  xiaohongshu: {
    hostname: "creator.xiaohongshu.com",
    pathPrefix: "/publish/publish-manage",
    pageVersion: "xiaohongshu-visible-tab-v1",
  },
} as const;

const pageDefinitions: Array<{
  platform: SupportedPlatform;
  hostname: string;
  pathnamePrefix: string;
  pageVersion: string;
  anchors: string[];
}> = [
  {
    platform: "douyin",
    hostname: SUPPORTED.douyin.hostname,
    pathnamePrefix: SUPPORTED.douyin.pathPrefix,
    pageVersion: SUPPORTED.douyin.pageVersion,
    anchors: [],
  },
  {
    platform: "xiaohongshu",
    hostname: SUPPORTED.xiaohongshu.hostname,
    pathnamePrefix: SUPPORTED.xiaohongshu.pathPrefix,
    pageVersion: SUPPORTED.xiaohongshu.pageVersion,
    anchors: [],
  },
];

export function detectSupportedPage(url: string): PageSupport {
  let locationLike: Pick<Location, "hostname" | "pathname">;
  try {
    locationLike = new URL(url);
  } catch {
    return { supported: false, platform: null, pageVersion: "unknown", anchors: [] };
  }
  const definition = pageDefinitions.find(
    (candidate) =>
      candidate.hostname === locationLike.hostname &&
      locationLike.pathname.startsWith(candidate.pathnamePrefix),
  );
  if (!definition) {
    return { supported: false, platform: null, pageVersion: "unknown", anchors: [] };
  }
  return {
    supported: true,
    platform: definition.platform,
    pageVersion: definition.pageVersion,
    anchors: definition.anchors,
  };
}
