import {
  establishTrust,
  trustMatches,
  type TrustContext,
  type TrustStorage,
} from "./trust-state";

type OneClickContext = TrustContext & {
  captchaDetected?: boolean;
  loginRequired?: boolean;
};

type OneClickOperations<T> = {
  captureVisibleTab: () => Promise<string>;
  upload: (imageData: string) => Promise<T>;
};

export class OneClickController {
  enabled = false;
  lastFailureReason: string | null = null;
  private hasPreview = false;
  private hasToken = false;

  constructor(private readonly store: TrustStorage) {}

  static restoreAfterRestart(store: TrustStorage): OneClickController {
    return new OneClickController(store);
  }

  async restore(): Promise<void> {
    this.enabled = (await this.store.load()) !== null;
    this.hasPreview = false;
    this.hasToken = false;
  }

  async enable(
    context: TrustContext,
    options: { safeCaptureCompleted: boolean },
  ): Promise<void> {
    await establishTrust(this.store, context, options);
    this.enabled = true;
    this.lastFailureReason = null;
  }

  async disable(): Promise<void> {
    this.enabled = false;
    this.hasPreview = false;
    this.hasToken = false;
    await this.store.clear();
  }

  requiresWebConfirmation(): boolean {
    return true;
  }

  async capture<T>(
    context: OneClickContext,
    operations: OneClickOperations<T>,
  ): Promise<T> {
    if (!this.enabled) return this.fail("one-click-disabled");
    if (context.captchaDetected || context.loginRequired) {
      return this.fail("captcha-or-login");
    }
    const record = await this.store.load();
    if (!record || !trustMatches(record, context)) {
      return this.fail("trust-mismatch");
    }
    let imageData: string;
    try {
      imageData = await operations.captureVisibleTab();
    } catch {
      return this.fail("capture-failed");
    }
    this.hasPreview = true;
    try {
      const result = await operations.upload(imageData);
      if (
        typeof result === "object" &&
        result !== null &&
        "status" in result &&
        (result.status === "failed" || result.status === "cancelled")
      ) {
        return this.fail("recognition-failed");
      }
      this.hasPreview = false;
      return result;
    } catch {
      return this.fail("upload-failed");
    }
  }

  serializedRuntimeState(): {
    enabled: boolean;
    hasPreview: boolean;
    hasToken: boolean;
  } {
    return {
      enabled: this.enabled,
      hasPreview: this.hasPreview,
      hasToken: this.hasToken,
    };
  }

  private async fail<T>(reason: string): Promise<T> {
    this.lastFailureReason = reason;
    await this.disable();
    throw new Error(reason);
  }
}
