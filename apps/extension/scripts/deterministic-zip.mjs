import { writeFile } from "node:fs/promises";

const LOCAL_FILE_HEADER = 0x04034b50;
const CENTRAL_DIRECTORY_HEADER = 0x02014b50;
const END_OF_CENTRAL_DIRECTORY = 0x06054b50;
const UTF8_FLAG = 0x0800;
const STORE_COMPRESSION = 0;
const ZIP_VERSION = 20;
const UNIX_CREATE_SYSTEM = 3;
const UNIX_REGULAR_FILE_MODE = 0o100644;
const UINT16_MAX = 0xffff;
const UINT32_MAX = 0xffffffff;

const crcTable = Uint32Array.from({ length: 256 }, (_value, index) => {
  let crc = index;
  for (let bit = 0; bit < 8; bit += 1) {
    crc = (crc & 1) === 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  }
  return crc >>> 0;
});

function crc32(data) {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosUtcFields(sourceDateEpoch) {
  const date = new Date(sourceDateEpoch * 1_000);
  const year = date.getUTCFullYear();
  if (year < 1980 || year > 2107) {
    throw new Error("ZIP timestamp must be between 1980 and 2107 UTC");
  }
  return {
    date:
      ((year - 1980) << 9) |
      ((date.getUTCMonth() + 1) << 5) |
      date.getUTCDate(),
    time:
      (date.getUTCHours() << 11) |
      (date.getUTCMinutes() << 5) |
      Math.floor(date.getUTCSeconds() / 2),
  };
}

function checkedUint32(value, description) {
  if (!Number.isSafeInteger(value) || value < 0 || value > UINT32_MAX) {
    throw new Error(`${description} exceeds classic ZIP bounds`);
  }
  return value;
}

export async function writeDeterministicZip(outputPath, inputEntries, sourceDateEpoch) {
  if (inputEntries.length > UINT16_MAX) {
    throw new Error("entry count exceeds classic ZIP bounds");
  }
  const entries = [...inputEntries].sort(({ name: left }, { name: right }) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  const { date, time } = dosUtcFields(sourceDateEpoch);
  const localRecords = [];
  const centralRecords = [];
  let localOffset = 0;

  for (const { name, data } of entries) {
    const nameBytes = Buffer.from(name, "utf8");
    if (nameBytes.length === 0 || nameBytes.length > UINT16_MAX) {
      throw new Error(`invalid ZIP entry name length: ${name}`);
    }
    const size = checkedUint32(data.length, `ZIP entry size for ${name}`);
    const checksum = crc32(data);
    const localHeader = Buffer.alloc(30);
    localHeader.writeUInt32LE(LOCAL_FILE_HEADER, 0);
    localHeader.writeUInt16LE(ZIP_VERSION, 4);
    localHeader.writeUInt16LE(UTF8_FLAG, 6);
    localHeader.writeUInt16LE(STORE_COMPRESSION, 8);
    localHeader.writeUInt16LE(time, 10);
    localHeader.writeUInt16LE(date, 12);
    localHeader.writeUInt32LE(checksum, 14);
    localHeader.writeUInt32LE(size, 18);
    localHeader.writeUInt32LE(size, 22);
    localHeader.writeUInt16LE(nameBytes.length, 26);
    localHeader.writeUInt16LE(0, 28);
    const localRecord = Buffer.concat([localHeader, nameBytes, data]);
    localRecords.push(localRecord);

    const centralHeader = Buffer.alloc(46);
    centralHeader.writeUInt32LE(CENTRAL_DIRECTORY_HEADER, 0);
    centralHeader.writeUInt16LE((UNIX_CREATE_SYSTEM << 8) | ZIP_VERSION, 4);
    centralHeader.writeUInt16LE(ZIP_VERSION, 6);
    centralHeader.writeUInt16LE(UTF8_FLAG, 8);
    centralHeader.writeUInt16LE(STORE_COMPRESSION, 10);
    centralHeader.writeUInt16LE(time, 12);
    centralHeader.writeUInt16LE(date, 14);
    centralHeader.writeUInt32LE(checksum, 16);
    centralHeader.writeUInt32LE(size, 20);
    centralHeader.writeUInt32LE(size, 24);
    centralHeader.writeUInt16LE(nameBytes.length, 28);
    centralHeader.writeUInt16LE(0, 30);
    centralHeader.writeUInt16LE(0, 32);
    centralHeader.writeUInt16LE(0, 34);
    centralHeader.writeUInt16LE(0, 36);
    centralHeader.writeUInt32LE((UNIX_REGULAR_FILE_MODE << 16) >>> 0, 38);
    centralHeader.writeUInt32LE(
      checkedUint32(localOffset, `ZIP local offset for ${name}`),
      42,
    );
    centralRecords.push(Buffer.concat([centralHeader, nameBytes]));
    localOffset += localRecord.length;
  }

  const centralDirectory = Buffer.concat(centralRecords);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(END_OF_CENTRAL_DIRECTORY, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(
    checkedUint32(centralDirectory.length, "ZIP central directory size"),
    12,
  );
  end.writeUInt32LE(
    checkedUint32(localOffset, "ZIP central directory offset"),
    16,
  );
  end.writeUInt16LE(0, 20);

  await writeFile(
    outputPath,
    Buffer.concat([...localRecords, centralDirectory, end]),
  );
}
