const canonicalPngPrefix = "data:image/png;base64,";
const canonicalBase64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

export function encodedDataUrlByteLength(dataUrl: string): number {
  if (!dataUrl.startsWith(canonicalPngPrefix)) {
    throw new Error("invalid-base64-data-url");
  }
  const encoded = dataUrl.slice(canonicalPngPrefix.length);
  if (!encoded || encoded.length % 4 !== 0 || !canonicalBase64.test(encoded)) {
    throw new Error("invalid-base64-data-url");
  }
  const padding = encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0;
  return (encoded.length / 4) * 3 - padding;
}
