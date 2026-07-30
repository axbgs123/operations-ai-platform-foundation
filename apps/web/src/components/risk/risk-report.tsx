import type { RiskScanData } from "@/lib/risk-api";


const severityStyle = {
  low: "border-sky-200 bg-sky-50",
  medium: "border-amber-300 bg-amber-50",
  high: "border-rose-300 bg-rose-50",
} as const;

const regionLabel = {
  title: "标题",
  body: "正文",
  cover: "封面",
} as const;

type RiskReportProps = {
  scan: RiskScanData;
  historical?: boolean;
};

export function RiskReport({ scan, historical = false }: RiskReportProps) {
  const result = scan.result;

  return (
    <section className="space-y-5 rounded-xl border border-[var(--border)] bg-white p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-[var(--text-secondary)]">风险扫描 · {scan.node}</p>
          <h2 className="text-xl font-semibold">可验证风险报告</h2>
        </div>
        {historical || scan.previous_scan_id ? (
          <span className="rounded-full bg-violet-100 px-3 py-1 text-sm text-violet-900">
            历史扫描
          </span>
        ) : null}
      </header>

      {result?.error_code === "NO_ACTIVE_RISK_EVIDENCE" ? (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-amber-950">
          <p>未检索到有效规则</p>
          <p className="mt-1 text-sm">证据不足，不能据此判断为安全通过。</p>
        </div>
      ) : null}
      {result?.ocr_status === "failed" || result?.ocr_status === "unavailable" ? (
        <p className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-rose-900">
          OCR失败或不可用，不能进入待发布；标题与正文的确定性检查结果仍可供人工复核。
        </p>
      ) : null}

      <div className="space-y-4">
        {result?.findings.map((finding, index) => (
          <article
            className={`space-y-3 rounded-2xl border p-4 ${severityStyle[finding.severity]}`}
            key={`${finding.risk_type}-${finding.region}-${index}`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <strong>{finding.risk_type}</strong>
              <span className="rounded-full bg-slate-100 px-2 py-1 text-xs">
                {finding.origin === "rag"
                  ? "RAG 辅助判断"
                  : finding.origin === "deterministic_and_rag"
                    ? "确定性命中 + RAG 辅助判断"
                    : "确定性命中"}
              </span>
              <span className="text-sm text-[var(--text-secondary)]">
                {regionLabel[finding.region]}
              </span>
            </div>
            <p className="font-mono text-sm">{finding.matched_content}</p>
            {finding.ocr_confidence != null
              && finding.ocr_confidence < 0.8 ? (
                <p className="text-sm font-medium text-amber-900">
                  OCR 低置信度 · {Math.round(finding.ocr_confidence * 100)}%
                </p>
              ) : null}
            {finding.requires_human_review ? (
              <p className="text-sm text-amber-900">需要人工确认或复核</p>
            ) : null}
            <p className="text-sm text-[var(--text-secondary)]">原因：{finding.reason}</p>
            <p className="text-sm text-[var(--text-secondary)]">
              建议：{finding.suggestion}
            </p>
            {finding.citations.map((citation) => (
              <blockquote
                className="rounded-xl border-l-2 border-[var(--brand)] bg-slate-50 p-3 text-sm"
                key={citation.chunk_id}
              >
                <p>
                  {citation.document_title} · {citation.source_level} · v
                  {citation.document_version}
                </p>
                <p className="mt-1 text-[var(--text-secondary)]">{citation.excerpt}</p>
              </blockquote>
            ))}
          </article>
        ))}
      </div>

      {result ? (
        <footer className="space-y-2 border-t border-[var(--border)] pt-4 text-xs text-[var(--text-secondary)]">
          <p>
            规则 {result.versions.rule_version} · 证据{" "}
            {result.versions.evidence_version} · Embedding{" "}
            {result.versions.embedding_model_id}/
            {result.versions.embedding_version} · RAG{" "}
            {result.versions.rag_model_version} · 扫描器{" "}
            {result.versions.scanner_version}
          </p>
          <p className="font-medium text-[var(--text-primary)]">{result.disclaimer}</p>
        </footer>
      ) : null}
    </section>
  );
}
