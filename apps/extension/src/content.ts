import { detectPage } from "./content/page-adapters/base";

const pageDetection = detectPage({ url: window.location.href, document });
document.documentElement.dataset.operationsCaptureSupported = String(pageDetection.supported);
document.documentElement.dataset.operationsCapturePlatform = pageDetection.platform ?? "unknown";
document.documentElement.dataset.operationsCaptureSignature = pageDetection.signature;
