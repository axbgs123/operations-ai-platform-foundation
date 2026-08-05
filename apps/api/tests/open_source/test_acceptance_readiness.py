from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[4]
TRACEABILITY = REPO_ROOT / "docs/acceptance/requirements-traceability.md"
SESSION_TEMPLATE = REPO_ROOT / "docs/acceptance/test-session-template.md"
NON_DEVELOPER_GUIDE = (
    REPO_ROOT / "docs/acceptance/non-developer-test-guide.md"
)
EVIDENCE_README = REPO_ROOT / "docs/acceptance/evidence/README.md"
FULL_LOOP = REPO_ROOT / "tests/e2e/full-loop.spec.ts"
BACKUP_RESTORE = REPO_ROOT / "tests/e2e/backup-restore.spec.ts"


def test_traceability_maps_all_seventeen_acceptance_requirements_exactly() -> None:
    text = TRACEABILITY.read_text(encoding="utf-8")
    requirement_ids = re.findall(r"^## (AC-\d{2})\b", text, re.MULTILINE)

    assert requirement_ids == [f"AC-{number:02d}" for number in range(1, 18)]
    for section in re.split(r"^## AC-\d{2}\b", text, flags=re.MULTILINE)[1:]:
        for label in (
            "原始需求文字",
            "对应模块",
            "精确自动测试",
            "人工验收步骤",
            "证据路径",
            "当前结果",
            "已知限制",
            "最后验证日期",
            "验证环境",
        ):
            assert label in section

    assert "independent_non_developer_session_pending" in text
    assert "真实千问 API 尚未运行" in text
    assert "真实抖音/小红书页面尚未验证" in text
    assert "text-embedding-v4 没有确认的日期快照" in text
    assert "independent_non_developer_agent_session_pending" in text


def test_non_developer_materials_are_templates_not_fabricated_evidence() -> None:
    template = SESSION_TEMPLATE.read_text(encoding="utf-8")
    guide = NON_DEVELOPER_GUIDE.read_text(encoding="utf-8")
    evidence = EVIDENCE_README.read_text(encoding="utf-8")

    for required in (
        "测试者匿名编号",
        "首次分析耗时",
        "采集耗时",
        "blocking",
        "major",
        "minor",
        "suggestion",
        "禁止事后补写虚假时间",
    ):
        assert required in template
    assert "participant-01" in guide
    assert "Mock 模型" in guide
    assert "不代表真实千问效果" in guide
    assert "不进入真实创作者后台" in guide
    assert "non-developer-session-<date>-participant-01.md" in evidence
    assert "不得在 Task 9A 创建已执行的人工验收记录" in evidence


def test_task9_e2e_specs_keep_mock_and_synthetic_boundaries_explicit() -> None:
    full_loop = FULL_LOOP.read_text(encoding="utf-8")
    backup_restore = BACKUP_RESTORE.read_text(encoding="utf-8")

    for phrase in (
        "Mock Provider",
        "synthetic",
        "douyin",
        "xiaohongshu",
        "otherWorkspace",
        "CSV",
        "Markdown",
        "JSON",
        "ZIP",
    ):
        assert phrase in full_loop
    for phrase in (
        "checksums.json",
        "manifest.json",
        "configuration_required",
        "tampered",
        "idempot",
        "sourceWorkspace",
        "target_workspace_id",
    ):
        assert phrase in backup_restore
