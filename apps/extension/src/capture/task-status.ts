import type { components } from "@operations-ai/shared-schemas";
import { boundedJsonFetch } from "./request";

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
  requestMaxAttempts?: number;
  requestTimeoutMs?: number;
};

export async function pollCaptureTask(args: PollArgs): Promise<CaptureTaskRead> {
  const sleep = args.sleep ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
  const maxAttempts = args.maxAttempts ?? 8;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const result = await boundedJsonFetch<CaptureTaskRead>(
      `${args.serverOrigin}/v1/extension/capture-tasks/${args.taskId}`,
      { headers: { Authorization: `Bearer ${args.accessToken}` } },
      {
        fetcher: args.fetcher,
        maxAttempts: args.requestMaxAttempts,
        timeoutMs: args.requestTimeoutMs,
        retrySleep: sleep,
      },
    );
    const { response } = result;
    if (response.status === 401 || response.status === 403) {
      await args.onRebindRequired?.();
      throw new Error("rebind-required");
    }
    if (!response.ok) throw new Error("capture task status unavailable");
    if (!result.body) throw new Error("capture response invalid");
    if (["succeeded", "failed", "cancelled"].includes(result.body.status)) return result.body;
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
