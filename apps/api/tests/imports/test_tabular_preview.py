from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.content.models import Content
from app.modules.metrics.models import DataSnapshot
from tests.imports.helpers import configured_client, create_workspace_account


FIXTURES = Path(__file__).parents[1] / "fixtures" / "imports"


def test_csv_preview_maps_headers_parses_formats_and_keeps_bad_rows_staged() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        fixture = FIXTURES / "douyin_mixed.csv"

        with fixture.open("rb") as source:
            response = client.post(
                f"/v1/workspaces/{workspace_id}/imports/tabular/preview",
                headers={"X-CSRF-Token": csrf},
                data={
                    "account_id": account["id"],
                    "platform": "douyin",
                    "content_type": "video",
                },
                files={"file": (fixture.name, source, "text/csv")},
            )

        assert response.status_code == 201, response.text
        preview = response.json()
        mappings = {
            item["source_header"]: item for item in preview["header_mappings"]
        }
        assert mappings["作品ID"]["target_field"] == "platform_content_id"
        assert mappings["播放量"]["target_field"] == "metric.views"
        assert mappings["播放量"]["high_confidence"] is True
        assert preview["summary"] == {
            "new": 2,
            "update": 0,
            "suspected_duplicate": 0,
            "failed": 1,
        }

        first = preview["rows"][0]
        assert first["status"] == "new"
        assert Decimal(first["normalized_data"]["metrics"]["views"]) == Decimal(
            "12000"
        )
        assert Decimal(first["normalized_data"]["metrics"]["likes"]) == Decimal(
            "1234"
        )
        assert Decimal(
            first["normalized_data"]["metrics"]["completion_rate_5s"]
        ) == Decimal("0.125")
        assert first["normalized_data"]["published_at"].endswith("+00:00")

        failed = preview["rows"][1]
        assert failed["status"] == "failed"
        assert {error["field"] for error in failed["errors"]} == {
            "title",
            "metric.comments",
        }

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Content)) == 0
            assert session.scalar(select(func.count()).select_from(DataSnapshot)) == 0


def test_xlsx_preview_preserves_typed_dates_percentages_and_platform_fields() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(
            client, platform="xiaohongshu"
        )
        fixture = FIXTURES / "xiaohongshu_typed.xlsx"

        with fixture.open("rb") as source:
            response = client.post(
                f"/v1/workspaces/{workspace_id}/imports/tabular/preview",
                headers={"X-CSRF-Token": csrf},
                data={
                    "account_id": account["id"],
                    "platform": "xiaohongshu",
                    "content_type": "image_text",
                },
                files={
                    "file": (
                        fixture.name,
                        source,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert response.status_code == 201, response.text
        preview = response.json()
        assert preview["summary"]["new"] == 2
        first = preview["rows"][0]["normalized_data"]
        assert first["platform_content_id"] == "XHS-001"
        assert Decimal(first["metrics"]["impressions"]) == Decimal("2500")
        assert Decimal(first["metrics"]["views"]) == Decimal("1800")
        assert Decimal(first["metrics"]["cover_click_rate"]) == Decimal("0.185")
        assert first["published_at"].endswith("+00:00")


def test_mapping_correction_reprocesses_rows_without_formal_writes() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        csv_bytes = (
            "名称,发布时间,数据时间,播放量\n"
            "修正后的标题,2026-07-20T10:00:00+08:00,"
            "2026-07-21T10:00:00+08:00,100\n"
        ).encode()
        response = client.post(
            f"/v1/workspaces/{workspace_id}/imports/tabular/preview",
            headers={"X-CSRF-Token": csrf},
            data={
                "account_id": account["id"],
                "platform": "douyin",
                "content_type": "video",
            },
            files={"file": ("ambiguous.csv", csv_bytes, "text/csv")},
        )
        assert response.status_code == 201
        preview = response.json()
        assert preview["rows"][0]["status"] == "failed"

        corrected = client.patch(
            f"/v1/imports/{preview['id']}/mapping",
            headers={"X-CSRF-Token": csrf},
            json={"mapping": {"名称": "title"}},
        )

        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["rows"][0]["status"] == "new"
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Content)) == 0
