import json
from pathlib import Path

from app.main import app


ROOT = Path(__file__).parents[4]


def test_openapi_has_unique_operations_and_typed_core_responses() -> None:
    schema = app.openapi()
    operation_ids: list[str] = []
    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method in {"get", "post", "patch", "delete"}:
                operation_ids.append(operation["operationId"])
    assert len(operation_ids) == len(set(operation_ids))

    expected_components = {
        "AccountRead",
        "AssetRead",
        "ContentRead",
        "DemoWorkspaceRead",
        "EffectiveConfigurationRead",
        "ModelConfigRead",
    }
    assert expected_components <= set(schema["components"]["schemas"])

    core_operations = [
        ("/v1/demo/workspace", "get", "200"),
        ("/v1/workspaces/{workspace_id}/accounts", "post", "201"),
        ("/v1/contents", "post", "201"),
        ("/v1/contents/{content_id}", "get", "200"),
        ("/v1/workspaces/{workspace_id}/model-configs", "post", "201"),
    ]
    for path, method, status in core_operations:
        response_schema = schema["paths"][path][method]["responses"][status][
            "content"
        ]["application/json"]["schema"]
        assert "$ref" in response_schema


def test_checked_in_openapi_document_matches_application() -> None:
    checked_in = ROOT / "packages" / "shared-schemas" / "openapi.json"
    assert checked_in.exists()
    assert json.loads(checked_in.read_text()) == app.openapi()


def test_web_api_consumers_use_generated_contracts() -> None:
    consumers = [
        ROOT / "apps" / "web" / "src" / "lib" / "workspace-api.ts",
        ROOT / "apps" / "web" / "src" / "lib" / "content-api.ts",
        ROOT / "apps" / "web" / "src" / "lib" / "account-api.ts",
        ROOT / "apps" / "web" / "src" / "lib" / "demo-api.ts",
        ROOT / "apps" / "web" / "src" / "components" / "demo-workspace.tsx",
    ]
    for consumer in consumers:
        assert '@operations-ai/shared-schemas' in consumer.read_text(), consumer

    required_contracts = {
        "content-api.ts": {"ContentCreate", "ContentUpdate", "AssetPresignRequest"},
        "account-api.ts": {"ConfigurationInput"},
        "demo-api.ts": {"DemoGenerateRequest", "DemoGenerateResponse", "DemoSessionCreated"},
    }
    for file_name, contracts in required_contracts.items():
        source = (ROOT / "apps" / "web" / "src" / "lib" / file_name).read_text()
        assert all(contract in source for contract in contracts), file_name
