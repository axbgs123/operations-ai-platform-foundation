# 第三方资产与内容边界

下表是发布树中所有 PNG、XLSX、SVG 与截图样例的逐项台账。它们均为人工合成的测试或 Demo 材料；没有真实用户数据、平台页面截图、邀请码、私有知识或生产凭据。

| 路径 | 类型/用途 | 来源、许可与发布结论 |
| --- | --- | --- |
| `docs/assets/public-workbench-overview-synthetic-v1.png` | PNG，README 当前工作台总览 | 由隔离 Mock Compose 环境和 `workbench-visual.spec.ts` 的合成工作区生成；相邻 provenance 固定 SHA-256、捕获模式、路由模板和视觉基准来源。截图只展示合成账号与 Mock 数据，不代表真实平台页面或生产指标。 |
| `apps/api/tests/fixtures/golden-covers/template-1080x1080.png` | PNG 回归基准 | `golden-covers/generate.py` 生成的合成封面；见同目录 README，可公开发布。 |
| `apps/api/tests/fixtures/golden-covers/template-1080x1440.png` | PNG 回归基准 | 同上，合成且仅用于版式回归。 |
| `apps/api/tests/fixtures/golden-covers/template-1080x1920.png` | PNG 回归基准 | 同上，合成且仅用于版式回归。 |
| `apps/api/tests/fixtures/imports/xiaohongshu_typed.xlsx` | XLSX 导入测试 | 人工键入的合成字段与测试数据；无平台导出或用户数据。 |
| `apps/api/tests/fixtures/imports/mock_screenshot.png.b64` | Base64 编码的合成截图 fixture | 文本 fixture，不是发布 PNG；仅验证导入边界。 |
| `apps/api/tests/fixtures/imports/douyin_mixed.csv` | CSV 导入测试 | 人工合成测试输入；列在此处以避免把非图像 fixture 误当成平台数据。 |

`apps/web/public/{file,globe,next,vercel,window}.svg` 曾是 Next 默认占位图。经全仓引用搜索确认没有运行时或文档引用，已从发布树删除，而不是将来源不明的默认素材带入公开版本。运行环境中的 Noto CJK 字体另见[许可证决定](license-decision.md)。

提交者必须记录每张新图片、字体、数据集或文本的来源、授权、范围与再分发条件。无法确认的资产必须从发布材料排除，或列入[发布清单](release-checklist.md)阻断项。用户上传、平台页面、真实运营资料和第三方文章全文一律不是本仓库发布资产。
