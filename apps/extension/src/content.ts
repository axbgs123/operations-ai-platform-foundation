import { detectSupportedPage } from "./content/page-support";

const pageSupport = detectSupportedPage(window.location, document.body.innerText);
document.documentElement.dataset.operationsCaptureSupported = String(
  pageSupport.supported,
);
