import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

export default function buildCurrentExtension(): void {
  execFileSync("pnpm", ["--filter", "extension", "build"], {
    cwd: resolve(import.meta.dirname, "../.."),
    stdio: "inherit",
  });
}
