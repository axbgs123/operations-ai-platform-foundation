import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

const extensionRoot = resolve(import.meta.dirname, "..");
const epoch = 1_785_744_000;

type ZipEntry = {
  name: string;
  createSystem: number;
  compressionMethod: number;
  dosDate: number;
  dosTime: number;
  unixMode: number;
};

function sha256(value: Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function parseCentralDirectory(archive: Buffer): ZipEntry[] {
  let eocd = archive.length - 22;
  while (eocd >= 0 && archive.readUInt32LE(eocd) !== 0x06054b50) eocd -= 1;
  if (eocd < 0) throw new Error("zip-eocd-missing");
  const entryCount = archive.readUInt16LE(eocd + 10);
  let offset = archive.readUInt32LE(eocd + 16);
  const entries: ZipEntry[] = [];
  for (let index = 0; index < entryCount; index += 1) {
    if (archive.readUInt32LE(offset) !== 0x02014b50) throw new Error("zip-central-header-missing");
    const nameLength = archive.readUInt16LE(offset + 28);
    const extraLength = archive.readUInt16LE(offset + 30);
    const commentLength = archive.readUInt16LE(offset + 32);
    const versionMadeBy = archive.readUInt16LE(offset + 4);
    const externalAttributes = archive.readUInt32LE(offset + 38);
    entries.push({
      name: archive.subarray(offset + 46, offset + 46 + nameLength).toString("utf8"),
      createSystem: versionMadeBy >>> 8,
      compressionMethod: archive.readUInt16LE(offset + 10),
      dosTime: archive.readUInt16LE(offset + 12),
      dosDate: archive.readUInt16LE(offset + 14),
      unixMode: externalAttributes >>> 16,
    });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function utcDosFields(timestamp: number): { dosDate: number; dosTime: number } {
  const date = new Date(timestamp * 1_000);
  return {
    dosDate:
      ((date.getUTCFullYear() - 1980) << 9) |
      ((date.getUTCMonth() + 1) << 5) |
      date.getUTCDate(),
    dosTime:
      (date.getUTCHours() << 11) |
      (date.getUTCMinutes() << 5) |
      Math.floor(date.getUTCSeconds() / 2),
  };
}

async function packageInTimezone(timezone: string) {
  execFileSync(process.execPath, ["scripts/package-extension.mjs"], {
    cwd: extensionRoot,
    env: {
      ...process.env,
      SOURCE_DATE_EPOCH: String(epoch),
      TZ: timezone,
    },
    stdio: "pipe",
  });
  return {
    chrome: await readFile(
      resolve(extensionRoot, "release/operations-capture-extension-chrome-0.3.0.zip"),
    ),
    edge: await readFile(
      resolve(extensionRoot, "release/operations-capture-extension-edge-0.3.0.zip"),
    ),
  };
}

describe("deterministic extension archives", () => {
  let utc: Awaited<ReturnType<typeof packageInTimezone>>;
  let shanghai: Awaited<ReturnType<typeof packageInTimezone>>;

  beforeAll(async () => {
    utc = await packageInTimezone("UTC");
    shanghai = await packageInTimezone("Asia/Shanghai");
  });

  it("produces identical Chrome and Edge archives across process timezones", () => {
    expect(sha256(utc.chrome)).toBe(sha256(shanghai.chrome));
    expect(sha256(utc.edge)).toBe(sha256(shanghai.edge));
    expect(utc.chrome.equals(utc.edge)).toBe(true);
    expect(shanghai.chrome.equals(shanghai.edge)).toBe(true);
  });

  it("writes sorted entries with fixed UTC time, Unix mode, creator, and compression", () => {
    const expectedTime = utcDosFields(epoch);
    const entries = parseCentralDirectory(utc.chrome);

    expect(entries.map(({ name }) => name)).toEqual(
      entries.map(({ name }) => name).sort(),
    );
    expect(entries).toHaveLength(11);
    for (const entry of entries) {
      expect(entry).toMatchObject({
        createSystem: 3,
        compressionMethod: 0,
        dosDate: expectedTime.dosDate,
        dosTime: expectedTime.dosTime,
        unixMode: 0o100644,
      });
    }
  });
});
