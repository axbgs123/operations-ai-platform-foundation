import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { RiskScanData } from "@/lib/risk-api";

import { RiskReport } from "./risk-report";


const scan = {
  id: "scan-2",
  workspace_id: "workspace-1",
  account_id: "account-1",
  content_id: "content-1",
  cover_asset_id: "asset-1",
  previous_scan_id: "scan-1",
  platform: "douyin",
  node: "before_publication",
  status: "succeeded",
  idempotency_key: "scan-key-2",
  input_snapshot: {},
  result: {
    findings: [
      {
        risk_type: "synthetic-rule",
        severity: "high",
        matched_content: "SYNTHETIC_HIGH",
        region: "cover",
        ocr_bbox: [0.1, 0.2, 0.8, 0.3],
        ocr_confidence: 0.42,
        evidence_document_ids: ["document-1"],
        citations: [],
        reason: "确定性规则命中",
        suggestion: "人工复核",
        origin: "deterministic",
        requires_human_review: true,
        deterministic_confirmed: false,
      },
      {
        risk_type: "synthetic-context",
        severity: "medium",
        matched_content: "SYNTHETIC_CONTEXT",
        region: "body",
        ocr_bbox: null,
        ocr_confidence: null,
        evidence_document_ids: ["document-2"],
        citations: [
          {
            document_title: "人工合成证据",
            source_level: "S1",
            source_url: "https://example.invalid/evidence",
            private_document_id: null,
            document_version: 1,
            effective_at: "2026-07-23T08:00:00Z",
            chunk_id: "chunk-1",
            chunk_location: "人工条款 1",
            excerpt: "SYNTHETIC_CONTEXT",
          },
        ],
        reason: "RAG 辅助判断",
        suggestion: "增加限定说明",
        origin: "rag",
        requires_human_review: false,
        deterministic_confirmed: false,
      },
    ],
    ocr_status: "succeeded",
    diagnostics: ["OCR_LOW_CONFIDENCE"],
    error_code: null,
    versions: {
      rule_version: "rules-v1",
      evidence_version: "evidence-v1",
      embedding_model_id: "mock-risk-embedding",
      embedding_version: "embed-v1",
      embedding_dimension: 3,
      rag_model_version: "mock-rag-v1",
    scanner_version: "scanner-v1",
    ocr_provider: "mock",
    ocr_model_id: "mock-ocr-v1",
    ocr_contract_version: "mock-ocr-v1",
    ocr_config_version: "mock-static-v1",
    },
    scanned_at: "2026-07-23T08:00:00Z",
    disclaimer: "辅助判断，不保证通过平台审核",
  },
  error_code: null,
  diagnostics: ["OCR_LOW_CONFIDENCE"],
  rule_version: "rules-v1",
  evidence_version: "evidence-v1",
  embedding_model_id: "mock-risk-embedding",
  embedding_version: "embed-v1",
  embedding_dimension: 3,
  rag_model_version: "mock-rag-v1",
  scanner_version: "scanner-v1",
  ocr_provider: "mock",
  ocr_model_id: "mock-ocr-v1",
  ocr_contract_version: "mock-ocr-v1",
  ocr_config_version: "mock-static-v1",
  created_at: "2026-07-23T08:00:00Z",
} satisfies RiskScanData;


afterEach(cleanup);

test("distinguishes deterministic rag low-ocr no-evidence and history", () => {
  render(<RiskReport historical scan={scan} />);

  expect(screen.getByText("确定性命中")).toBeInTheDocument();
  expect(screen.getByText("RAG 辅助判断")).toBeInTheDocument();
  expect(screen.getByText("OCR 低置信度 · 42%")).toBeInTheDocument();
  expect(screen.getByText("历史扫描")).toBeInTheDocument();
  expect(
    screen.getByText("辅助判断，不保证通过平台审核"),
  ).toBeInTheDocument();
  expect(screen.getByText("人工合成证据 · S1 · v1")).toBeInTheDocument();

  cleanup();
  render(
    <RiskReport
      scan={{
        ...scan,
        previous_scan_id: null,
        result: scan.result
          ? {
              ...scan.result,
              findings: [scan.result.findings[0]],
              error_code: "NO_ACTIVE_RISK_EVIDENCE",
            }
          : null,
        error_code: "NO_ACTIVE_RISK_EVIDENCE",
      }}
    />,
  );
  expect(screen.getByText("未检索到有效规则")).toBeInTheDocument();
});
