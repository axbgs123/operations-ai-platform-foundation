import type { components } from "@operations-ai/shared-schemas";

export type CaptureTaskRead =
  components["schemas"]["ExtensionCaptureTaskRead"];

type PollArgs = {
  serverOrigin: string;
  accessToken: string;
  taskId: string;
  platform: "douyin" | "xiaohongshu";
  pageVersion: string;
  fetcher?: typeof fetch;
  maxAttempts?: number;
  sleep?: (milliseconds: number) => Promise<void>;
  onRebindRequired?: () => Promise<void>;
};

export async function pollCaptureTask(args: PollArgs): Promise<CaptureTaskRead> {
  const fetcher = args.fetcher ?? fetch;
  const sleep = args.sleep ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
  const maxAttempts = args.maxAttempts ?? 8;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const response = await fetcher(
      `${args.serverOrigin}/v1/extension/capture-tasks/${args.taskId}`,
      { headers: { Authorization: `Bearer ${args.accessToken}` } },
    );
    if (response.status === 401 || response.status === 403) {
      await args.onRebindRequired?.();
      throw new Error("rebind-required");
    }
    if (!response.ok) throw new Error("capture task status unavailable");
    const result = (await response.json()) as CaptureTaskRead;
    if (["succeeded", "failed", "cancelled"].includes(result.status)) return result;
    await sleep(Math.min(1000 * 2 ** attempt, 5000));
  }
  return {
    task_id: args.taskId,
    workspace_id: "",
    platform: args.platform,
    page_version: args.pageVersion,
    status: "failed",
    request_id: args.taskId,
    review_url: "",
    expires_at: new Date(0).toISOString(),
    recognition: null,
    formal_snapshot_ids: [],
    error: "识别超时，请在 Web 中重试",
    provider_mode: "unavailable",
    region: null,
  };
}
