"""The browser workflow shares real readers and protects the local service."""

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook


@pytest.fixture
def client():
    from tableproof.web import create_app
    with TestClient(create_app(), base_url="http://127.0.0.1:8765") as client:
        yield client


def payload():
    workbook = Workbook()
    workbook.active.title = "数据"
    workbook.active.append(["名称", "数量"])
    workbook.active.append(["样例", 12])
    output = BytesIO()
    workbook.save(output)
    return {"xlsx_base64": base64.b64encode(output.getvalue()).decode(),
            "markdown": "| 名称 | 数量 |\n| --- | --- |\n| 样例 | 12 |",
            "sheet": "数据", "range_ref": "A1:B2", "table_index": 0, "header": True}


def test_local_page_served_with_security_headers(client):
    result = client.get("/")
    assert result.status_code == 200
    assert "TableProof" in result.text
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "localhost.evil.example"])
def test_rejects_remote_host(client, host):
    assert client.get("/", headers={"host": host}).status_code == 403


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:8765",
                                   "http://127.0.0.1:9999", "https://127.0.0.1:8765"])
def test_rejects_cross_origin_requests(client, origin):
    assert client.post("/api/inspect", json=payload(), headers={"origin": origin}).status_code == 403


def test_accepts_same_origin_inspection_and_lists_markdown_tables(client):
    result = client.post("/api/inspect", json=payload(), headers={"origin": "http://127.0.0.1:8765"})
    assert result.status_code == 200
    assert result.json()["sheets"][0]["name"] == "数据"
    assert result.json()["tables"][0]["columns"] == 2


def test_body_only_preview_and_audit_ignore_header_styles(client):
    data = {**payload(), "range_ref": "A2:B2", "header": False,
            "markdown": "| **名称** | 数量 |\n| --- | --- |\n| 样例 | 12 |"}
    preview = client.post("/api/preview", json=data).json()
    assert preview["issues"] == []
    assert preview["markdown_preview"] == [["样例", "12"]]
    audited = client.post("/api/audit", json={**data, "confirmed": True, "mapping_token": preview["mapping_token"]})
    assert audited.json()["status"] == "PASS"


def test_preview_confirmation_is_bound_to_exact_input(client):
    data = payload()
    denied = client.post("/api/audit", json=data)
    assert denied.status_code == 400
    preview = client.post("/api/preview", json=data)
    assert preview.status_code == 200
    assert preview.json()["source_preview"][1][0]["coordinate"] == "A2"
    data.update(confirmed=True, mapping_token=preview.json()["mapping_token"])
    audited = client.post("/api/audit", json=data)
    assert audited.status_code == 200
    assert audited.json()["status"] == "PASS"
    data["markdown"] = data["markdown"].replace("12", "13")
    assert client.post("/api/audit", json=data).status_code == 400


def test_invalid_input_and_request_size_are_friendly(client):
    invalid = client.post("/api/inspect", json={"xlsx_base64": "not-base64"})
    assert invalid.status_code == 400
    assert isinstance(invalid.json()["detail"], str)
    oversized = client.post("/api/inspect", content=b"{}", headers={"content-length": "100000000"})
    assert oversized.status_code == 413


def test_empty_or_invalid_sheet_range_and_table_selection_do_not_return_500(client):
    data = payload()
    for changes in ({"sheet": "missing"}, {"range_ref": "not-range"}, {"table_index": 99}):
        result = client.post("/api/preview", json={**data, **changes})
        assert result.status_code == 400
        assert isinstance(result.json()["detail"], str)


def test_demo_audits_synthetic_changes_and_exports_redacted_report(client):
    demo = client.get("/api/demo")
    assert demo.status_code == 200
    data = demo.json()
    preview = client.post("/api/preview", json=data)
    assert preview.status_code == 200
    data.update(confirmed=True, mapping_token=preview.json()["mapping_token"])
    audited = client.post("/api/audit", json=data)
    assert audited.status_code == 200
    assert audited.json()["status"] == "FAIL"
    exported = client.post("/api/export?format=json&redact=true", json={"report": audited.json()})
    assert exported.status_code == 200
    assert exported.json()["scope"]["sheet"] != data["sheet"]
    assert all(cell["source_value"] == "[已隐藏]" for cell in exported.json()["cells"])
    html = client.post("/api/export?format=html&redact=true", json={"report": audited.json()})
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]


def test_deep_json_returns_input_error_instead_of_crashing(client):
    response = client.post("/api/inspect", content=b'{"nested":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}',
                           headers={"content-type": "application/json"})
    assert response.status_code == 400


def test_invalid_unicode_and_non_ascii_confirmation_are_input_errors(client):
    data = payload()
    for path, changes in [("/api/inspect", {"markdown": "\ud800"}),
                          ("/api/preview", {"sheet": "\ud800"}),
                          ("/api/audit", {"confirmed": True, "mapping_token": "无效"})]:
        import json
        response = client.post(path, content=json.dumps({**data, **changes}),
                               headers={"content-type": "application/json"})
        assert response.status_code == 400


def test_export_invalid_unicode_is_input_error(client):
    response = client.post("/api/export", content='{"report":{"scope":{},"summary":{},"cells":[],"issues":["\\ud800"]}}',
                           headers={"content-type": "application/json"})
    assert response.status_code == 400


def test_streamed_body_limit_cannot_be_bypassed_by_omitting_content_length(client, monkeypatch):
    monkeypatch.setattr("tableproof.web.MAX_BODY_BYTES", 1024)
    response = client.post("/api/inspect", content=iter([b"x" * 600, b"x" * 600]),
                           headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_no_header_preview_maps_only_markdown_body(client):
    data = payload()
    data.update(header=False, range_ref="A2:B2")
    preview = client.post("/api/preview", json=data)
    assert preview.status_code == 200
    result = preview.json()
    assert result["source_rows"] == 1
    assert result["markdown_rows"] == 1
    assert result["markdown_preview"] == [["样例", "12"]]
    data.update(confirmed=True, mapping_token=result["mapping_token"])
    audited = client.post("/api/audit", json=data)
    assert audited.status_code == 200
    assert audited.json()["status"] == "PASS"
