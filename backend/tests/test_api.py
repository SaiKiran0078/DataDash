"""End-to-end API tests. Skipped automatically if FastAPI is not installed (CI installs it)."""
import pytest
from pathlib import Path

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

from app.db.models import Dataset, DatasetFile

from .sample_data import sales_csv, xlsx_bytes


def signup(client, email="asha@example.com", password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def upload(client, headers, content=None, name="sales.csv"):
    res = client.post("/api/datasets", headers=headers, files={"file": (name, content or sales_csv(), "text/csv")})
    assert res.status_code == 201, res.text
    return res.json()


# ------------------------------------------------------------------ auth
def test_register_login_me(client):
    h = signup(client)
    assert client.get("/api/auth/me", headers=h).json()["user"]["email"] == "asha@example.com"
    ok = client.post("/api/auth/login", json={"email": "ASHA@example.com", "password": "password123"})
    assert ok.status_code == 200 and ok.json()["token"]
    assert client.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "password123"}).status_code == 401


def test_register_validation_and_duplicates(client):
    signup(client)
    assert client.post("/api/auth/register", json={"email": "asha@example.com", "password": "password123"}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "not-an-email", "password": "password123"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "b@example.com", "password": "short"}).status_code == 422


def test_protected_routes_need_a_token(client):
    for path in ("/api/datasets", "/api/dashboards", "/api/auth/me"):
        assert client.get(path).status_code == 401
    assert client.get("/api/datasets", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_auth_is_rate_limited(make_client):
    client = make_client(rate_limit_enabled=True)
    codes = [client.post("/api/auth/login", json={"email": "x@example.com", "password": "password123"}).status_code for _ in range(25)]
    assert codes[0] == 401 and codes[-1] == 429


def test_openapi_reports_current_application_version(client):
    spec = client.get("/api/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["version"] == "6.0.11"


def test_security_headers_and_health(client):
    res = client.get("/api/health")
    assert res.json() == {"status": "ok"}
    assert res.headers["x-content-type-options"] == "nosniff" and res.headers["x-frame-options"] == "DENY"


# ------------------------------------------------------------------ datasets
def test_upload_returns_schema_and_profile(client):
    h = signup(client)
    ds = upload(client, h)
    kinds = {c["name"]: c["kind"] for c in ds["schema"]}
    assert ds["rows"] == 120 and kinds["revenue"] == "numeric" and kinds["order_date"] == "datetime"
    assert ds["profile"]["column_profiles"] and ds["name"] == "sales"
    assert [d["id"] for d in client.get("/api/datasets", headers=h).json()["datasets"]] == [ds["id"]]


def test_upload_xlsx_and_rejections(client):
    h = signup(client)
    assert upload(client, h, xlsx_bytes(), "scores.xlsx")["rows"] == 12
    bad = client.post("/api/datasets", headers=h, files={"file": ("virus.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 415
    empty = client.post("/api/datasets", headers=h, files={"file": ("empty.csv", b"", "text/csv")})
    assert empty.status_code == 400


def test_upload_size_limit(make_client):
    client = make_client(max_upload_mb=1)
    h = signup(client)
    big = b"a,b\n" + b"1,2\n" * 400_000
    res = client.post("/api/datasets", headers=h, files={"file": ("big.csv", big, "text/csv")})
    assert res.status_code == 413


def test_dataset_quota(make_client):
    client = make_client(max_datasets_per_user=2)
    h = signup(client)
    upload(client, h)
    upload(client, h)
    res = client.post("/api/datasets", headers=h, files={"file": ("x.csv", sales_csv(), "text/csv")})
    assert res.status_code == 409


def test_users_cannot_see_each_others_data(client):
    a, b = signup(client, "a@example.com"), signup(client, "b@example.com")
    ds = upload(client, a)
    base = f"/api/datasets/{ds['id']}"
    assert client.get(base, headers=b).status_code == 404
    assert client.get(base + "/suggestions", headers=b).status_code == 404
    assert client.post(base + "/rows", headers=b).status_code == 404
    assert client.delete(base, headers=b).status_code == 404
    assert client.get("/api/datasets", headers=b).json()["datasets"] == []


def test_repository_sales_sample_produces_business_metrics_and_return_insights(client):
    h = signup(client)
    sample_path = Path(__file__).resolve().parents[2] / "sample_data" / "sales.csv"
    ds = upload(client, h, sample_path.read_bytes(), "sales.csv")
    response = client.get(f"/api/datasets/{ds['id']}/analysis", headers=h)
    assert response.status_code == 200, response.text
    analysis = response.json()

    metrics = {item["column"]: item for item in analysis["metric_candidates"]}
    assert metrics["revenue"]["suggested_aggregation"] == "sum"
    assert metrics["units"]["suggested_aggregation"] == "sum"
    assert metrics["unit_price"]["suggested_aggregation"] == "mean"
    assert metrics["rating"]["suggested_aggregation"] == "mean"

    returned = next(item for item in analysis["business_insights"] if item["type"] == "outcome_overview" and item["measure"] == "returned")
    assert returned["outcome_direction"] == "adverse"
    assert returned["rate_pct"] >= 0
    assert any(item["spec"].get("metric") == "outcome_count" and item["data"] for item in analysis["suggested_visuals"])
    assert any(item["spec"].get("y") == "unit_price" and item["data"] for item in analysis["suggested_visuals"])
    assert all(item["data"] for item in analysis["suggested_visuals"])
    assert all("order_id" not in str(item).lower() for item in analysis["business_insights"])
    assert all("order_id" not in str(item).lower() for item in analysis["suggested_visuals"])


def test_analysis_adapts_to_non_financial_dataset(client):
    """HR/survey-style data should produce field-specific metrics and evidence, not finance KPIs."""
    h = signup(client)
    content = (
        b"employee_id,department,engagement_score,tenure_months,remote\n"
        b"1,Engineering,8,24,yes\n"
        b"2,Engineering,9,36,yes\n"
        b"3,Engineering,7,18,no\n"
        b"4,Support,5,12,no\n"
        b"5,Support,6,9,yes\n"
        b"6,Support,4,6,no\n"
        b"7,Sales,8,30,yes\n"
        b"8,Sales,7,20,no\n"
        b"9,Sales,9,42,yes\n"
    )
    ds = upload(client, h, content, "employee_survey.csv")
    response = client.get(f"/api/datasets/{ds['id']}/analysis", headers=h)
    assert response.status_code == 200, response.text
    analysis = response.json()
    metrics = {item["column"]: item for item in analysis["metric_candidates"]}
    assert "engagement_score" in metrics
    assert "tenure_months" in metrics
    assert "employee_id" not in metrics
    assert metrics["engagement_score"]["suggested_aggregation"] == "mean"
    assert metrics["tenure_months"]["suggested_aggregation"] == "mean"
    assert analysis["business_insights"]
    assert any(item["type"] == "segment_comparison" for item in analysis["business_insights"])
    combined = " ".join(
        [item["title"] + " " + item["evidence"] for item in analysis["business_insights"]]
    ).lower()
    assert "profit" not in combined and "revenue" not in combined


def test_suggestions_chart_rows_outliers(client):
    h = signup(client)
    ds = upload(client, h)
    base = f"/api/datasets/{ds['id']}"

    sug = client.get(base + "/suggestions", headers=h).json()["suggestions"]
    assert sug and sug[0]["spec"]["type"] == "line"

    chart = client.post(base + "/chart", headers=h, json={
        "spec": {"type": "bar", "x": "product", "y": "units", "agg": "sum"},
        "filters": [{"column": "region", "op": "eq", "value": "North"}],
    })
    assert chart.status_code == 200 and chart.json()["meta"]["filtered_rows"] == 30

    page = client.post(base + "/rows?page=2&page_size=10&sort_by=revenue&descending=true", headers=h, json={"filters": []})
    assert page.status_code == 200 and page.json()["total"] == 120 and len(page.json()["rows"]) == 10

    out = client.get(base + "/outliers", params={"column": "revenue"}, headers=h).json()
    assert out["count"] >= 1 and out["rows"][0]["value"] == 900000


def test_bad_chart_requests_are_400_or_422(client):
    h = signup(client)
    base = f"/api/datasets/{upload(client, h)['id']}"
    def chart(spec, filters=None):
        return client.post(base + "/chart", headers=h, json={"spec": spec, "filters": filters or []}).status_code
    assert chart({"type": "donut", "x": "region"}) == 422                        # not an allowed chart type
    assert chart({"type": "bar", "x": "nope"}) == 400                            # unknown column
    assert chart({"type": "bar", "x": "region", "agg": "sum", "y": "region"}) == 400
    assert chart({"type": "bar", "x": "region"}, [{"column": "units", "op": "DROP", "value": 1}]) == 422
    assert chart({"type": "bar", "x": "region", "evil": 1}) == 422               # unknown fields rejected
    assert client.get(base + "/outliers", params={"column": "region"}, headers=h).status_code == 400


def test_delete_dataset_removes_persisted_content_and_dashboards(client):
    h = signup(client)
    ds = upload(client, h)
    dash = client.post("/api/dashboards", headers=h, json={"name": "D", "dataset_id": ds["id"], "widgets": []}).json()
    with client.app.state.session_factory() as db:
        dataset = db.get(Dataset, ds["id"])
        stored_name = dataset.stored_name
        assert db.get(DatasetFile, stored_name) is not None
    assert client.delete(f"/api/datasets/{ds['id']}", headers=h).status_code == 204
    with client.app.state.session_factory() as db:
        assert db.get(DatasetFile, stored_name) is None
    assert client.get(f"/api/dashboards/{dash['id']}", headers=h).status_code == 404


# ------------------------------------------------------------------ dashboards & sharing
WIDGETS = [
    {"id": "w1", "title": "Units by product", "spec": {"type": "bar", "x": "product", "y": "units", "agg": "sum"}},
    {"id": "w2", "title": "Revenue over time", "spec": {"type": "line", "x": "order_date", "y": "revenue", "agg": "sum", "time_grain": "month"}},
]


def test_dashboard_lifecycle_and_validation(client):
    h = signup(client)
    ds = upload(client, h)
    created = client.post("/api/dashboards", headers=h, json={"name": "Sales", "dataset_id": ds["id"], "widgets": WIDGETS})
    assert created.status_code == 201
    did = created.json()["id"]

    data = client.get(f"/api/dashboards/{did}/data", headers=h).json()["widgets"]
    assert [w["id"] for w in data] == ["w1", "w2"] and "labels" in data[0]["data"]

    bad = [{"id": "w9", "title": "Oops", "spec": {"type": "bar", "x": "ghost"}}]
    res = client.put(f"/api/dashboards/{did}", headers=h, json={"name": "Sales", "dataset_id": ds["id"], "widgets": bad})
    assert res.status_code == 422 and "Oops" in res.json()["detail"]

    dup = client.post("/api/dashboards", headers=h, json={"name": "X", "dataset_id": ds["id"], "widgets": WIDGETS + WIDGETS[:1]})
    assert dup.status_code == 422

    assert client.delete(f"/api/dashboards/{did}", headers=h).status_code == 204


def test_cannot_build_dashboard_on_someone_elses_dataset(client):
    a, b = signup(client, "a@example.com"), signup(client, "b@example.com")
    ds = upload(client, a)
    assert client.post("/api/dashboards", headers=b, json={"name": "Stolen", "dataset_id": ds["id"], "widgets": []}).status_code == 404


def test_sharing_flow(client):
    h = signup(client)
    ds = upload(client, h)
    did = client.post("/api/dashboards", headers=h, json={
        "name": "Sales", "dataset_id": ds["id"], "widgets": WIDGETS,
        "filters": [{"column": "region", "op": "eq", "value": "North"}],
    }).json()["id"]

    assert client.get("/api/shared/" + "x" * 32).status_code == 404         # nothing shared yet

    token = client.post(f"/api/dashboards/{did}/share", headers=h).json()["share_token"]
    public = client.get(f"/api/shared/{token}")                              # no Authorization header
    body = public.json()
    assert public.status_code == 200 and body["name"] == "Sales" and len(body["widgets"]) == 2
    assert public.headers["cache-control"] == "no-store" and "noindex" in public.headers["x-robots-tag"]
    assert set(body) == {"name", "widgets"}                                  # no schema, rows, or owner leaked
    assert sum(body["widgets"][0]["data"]["datasets"][0]["data"]) == sum(  # dashboard filter applied (North only)
        client.post(f"/api/datasets/{ds['id']}/chart", headers=h, json={
            "spec": WIDGETS[0]["spec"], "filters": [{"column": "region", "op": "eq", "value": "North"}]}).json()["datasets"][0]["data"])

    new_token = client.post(f"/api/dashboards/{did}/share", headers=h).json()["share_token"]
    assert new_token != token and client.get(f"/api/shared/{token}").status_code == 404   # rotating revokes the old link

    client.delete(f"/api/dashboards/{did}/share", headers=h)
    assert client.get(f"/api/shared/{new_token}").status_code == 404


def test_clean_preview_apply_and_export(client):
    h = signup(client)
    content = b"customer,amount\n Alice ,10\nAlice,\nBob,30\n"
    ds = upload(client, h, content, "messy.csv")
    base = f"/api/datasets/{ds['id']}"
    operations = [
        {"type": "trim_text"},
        {"type": "fill_missing", "column": "amount", "strategy": "median"},
    ]
    preview = client.post(base + "/clean/preview", headers=h, json={"operations": operations})
    assert preview.status_code == 200, preview.text
    assert preview.json()["before"]["missing"] == 1
    assert preview.json()["after"]["missing"] == 0
    # Preview is non-destructive until Apply is requested.
    assert client.get(base, headers=h).json()["profile"]["missing_cells"] == 1
    applied = client.post(base + "/clean/apply", headers=h, json={"operations": operations})
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile"]["missing_cells"] == 0
    exported = client.get(base + "/export", headers=h)
    assert exported.status_code == 200 and b"customer,amount" in exported.content


def test_clean_rename_keeps_dashboard_chart_working(client):
    h = signup(client)
    ds = upload(client, h)
    dashboard = client.post("/api/dashboards", headers=h, json={
        "name": "Region report", "dataset_id": ds["id"],
        "widgets": [{"id": "region", "title": "Orders by region", "spec": {"type": "bar", "x": "region", "agg": "count"}}],
    }).json()
    cleaned = client.post(f"/api/datasets/{ds['id']}/clean/apply", headers=h, json={
        "operations": [{"type": "rename_column", "column": "region", "new_name": "territory"}]
    })
    assert cleaned.status_code == 200, cleaned.text
    updated = client.get(f"/api/dashboards/{dashboard['id']}", headers=h).json()
    assert updated["widgets"][0]["spec"]["x"] == "territory"
    rendered = client.get(f"/api/dashboards/{dashboard['id']}/data", headers=h)
    assert rendered.status_code == 200 and rendered.json()["widgets"][0]["data"]["labels"]


def test_clean_apply_tolerates_legacy_dashboard_widgets_with_null_specs(client):
    """Malformed legacy chart metadata must not break an otherwise valid clean apply."""
    from app.db.models import Dashboard

    h = signup(client, "legacy-widget@example.com")
    ds = upload(client, h)
    created = client.post("/api/dashboards", headers=h, json={
        "name": "Legacy dashboard", "dataset_id": ds["id"], "widgets": []
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]

    # Simulate older persisted records that can exist after partial saves/migrations.
    with client.app.state.session_factory() as session:
        dashboard = session.get(Dashboard, dashboard_id)
        dashboard.widgets = [
            {"id": "broken", "title": "Old broken chart", "spec": None, "filters": None},
            {"id": "valid", "title": "Orders by region",
             "spec": {"type": "bar", "x": "region", "agg": "count"}, "filters": []},
        ]
        dashboard.filters = None
        session.commit()

    response = client.post(
        f"/api/datasets/{ds['id']}/clean/apply",
        headers=h,
        json={"operations": [{"type": "trim_text"}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == ds["rows"]

    saved = client.get(f"/api/dashboards/{dashboard_id}", headers=h)
    assert saved.status_code == 200, saved.text
    widgets = saved.json()["widgets"]
    assert [widget["id"] for widget in widgets] == ["valid"]


def test_analyst_analysis_returns_grounded_summary_and_recommendations(client):
    h = signup(client)
    ds = upload(client, h)
    response = client.get(f"/api/datasets/{ds['id']}/analysis", headers=h)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset"]["rows"] == 120
    assert body["numeric_summary"]
    assert body["category_summary"]
    assert body["segment_analysis"]
    assert body["time_series"]
    assert body["findings"]
    assert body["recommendations"]
    assert "data_quality" in body
    assert body["data_quality"]["missing_by_column"]
    region = next(item for item in body["data_quality"]["missing_by_column"] if item["column"] == "region")
    assert region["missing"] == 1
    assert region["sample_rows"]
    assert region["suggested_strategy"] == "mode"
    assert any("correlation" in note.lower() for note in body["method_notes"])


def test_analysis_report_create_update_list_delete_and_ownership(client):
    owner = signup(client, "report-owner@example.com")
    other = signup(client, "report-other@example.com")
    ds = upload(client, owner)
    base = f"/api/datasets/{ds['id']}/reports"
    body = {
        "title": "Quarterly sales review",
        "business_question": "Which regions contribute the most revenue?",
        "audience": "Sales leadership",
        "row_grain": "One row per order line",
        "executive_summary": "Revenue and volume were reviewed.",
        "findings": [{"title": "Regional mix", "evidence": "North is the largest segment."}],
        "recommendations": [{"title": "Review margin", "action": "Compare profit by segment.", "priority": "high"}],
    }
    created = client.post(base, headers=owner, json=body)
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]
    assert created.json()["title"] == body["title"]
    assert created.json()["business_question"] == body["business_question"]
    assert client.get(base, headers=owner).json()["reports"][0]["id"] == report_id
    assert client.get(base, headers=other).status_code == 404
    updated = {**body, "title": "Updated sales review", "audience": "Regional managers"}
    updated_response = client.put(f"{base}/{report_id}", headers=owner, json=updated)
    assert updated_response.json()["title"] == updated["title"]
    assert updated_response.json()["audience"] == "Regional managers"
    assert client.put(f"{base}/{report_id}", headers=other, json=updated).status_code == 404
    assert client.delete(f"{base}/{report_id}", headers=owner).status_code == 204
    assert client.get(base, headers=owner).json()["reports"] == []


def test_analysis_reports_are_removed_when_dataset_is_deleted(client):
    h = signup(client, "report-cascade@example.com")
    ds = upload(client, h)
    base = f"/api/datasets/{ds['id']}/reports"
    report = client.post(base, headers=h, json={"title": "Temporary report"})
    assert report.status_code == 201
    report_id = report.json()["id"]
    assert client.delete(f"/api/datasets/{ds['id']}", headers=h).status_code == 204
    assert client.get(base, headers=h).status_code == 404
    from app.db.models import AnalysisReport
    from sqlalchemy import select
    with client.app.state.session_factory() as session:
        assert session.scalar(select(AnalysisReport).where(AnalysisReport.id == report_id)) is None


def test_quality_report_identifies_missing_score_fields_without_auto_imputing(client):
    h = signup(client, "quality-review@example.com")
    payload = b"order_id,rating,amount\n1,5,100\n2,,120\n3,4,90\n4,,110\n"
    response = client.post("/api/datasets", headers=h, files={"file": ("ratings.csv", payload, "text/csv")})
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]
    result = client.get(f"/api/datasets/{dataset_id}/analysis", headers=h)
    assert result.status_code == 200, result.text
    body = result.json()
    rating = next(item for item in body["data_quality"]["missing_by_column"] if item["column"] == "rating")
    assert rating["missing"] == 2
    assert rating["suggested_strategy"] == "review"
    assert rating["recommended_operation"] is None
    assert "rated records only" in rating["suggestion"]


def test_calculated_column_preview_apply_and_undo_redo(client):
    h = signup(client)
    ds = upload(client, h)
    base = f"/api/datasets/{ds['id']}"
    preview = client.post(base + "/clean/preview", headers=h, json={"operations": [
        {"type": "calculated_column", "new_name": "revenue_per_unit", "formula": "revenue / units"}
    ]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["after"]["columns"] == preview.json()["before"]["columns"] + 1
    applied = client.post(base + "/clean/apply", headers=h, json={"operations": [
        {"type": "calculated_column", "new_name": "revenue_per_unit", "formula": "revenue / units"}
    ]})
    assert applied.status_code == 200, applied.text
    assert any(c["name"] == "revenue_per_unit" for c in applied.json()["schema"])
    assert client.get(base + "/history", headers=h).json()["undo"]
    undone = client.post(base + "/undo", headers=h)
    assert undone.status_code == 200, undone.text
    assert all(c["name"] != "revenue_per_unit" for c in undone.json()["dataset"]["schema"])
    redone = client.post(base + "/redo", headers=h)
    assert redone.status_code == 200, redone.text
    assert any(c["name"] == "revenue_per_unit" for c in redone.json()["dataset"]["schema"])


def test_pivot_table_is_aggregated_and_non_destructive(client):
    h = signup(client)
    ds = upload(client, h)
    base = f"/api/datasets/{ds['id']}"
    result = client.post(base + "/pivot", headers=h, json={"rows": ["region"], "columns": [], "measure": "revenue", "aggregation": "sum"})
    assert result.status_code == 200, result.text
    assert result.json()["row_count"] > 0
    assert "sum_revenue" in result.json()["columns"]
    assert client.get(base, headers=h).json()["profile"]["rows"] == ds["profile"]["rows"]


def test_pivot_table_supports_multiple_dimensions_and_count(client):
    h = signup(client)
    ds = upload(client, h)
    base = f"/api/datasets/{ds['id']}"
    result = client.post(base + "/pivot", headers=h, json={
        "rows": ["region", "product"], "columns": [], "measure": None, "aggregation": "count"
    })
    assert result.status_code == 200, result.text
    payload = result.json()
    assert {"region", "product", "count_records"}.issubset(payload["columns"])
    assert payload["row_count"] > 1


def test_formula_rejects_unsafe_expressions(client):
    h = signup(client)
    ds = upload(client, h)
    response = client.post(f"/api/datasets/{ds['id']}/clean/preview", headers=h, json={"operations": [
        {"type": "calculated_column", "new_name": "bad", "formula": "__import__('os').system('whoami')"}
    ]})
    assert response.status_code == 400


def test_automated_analyst_pipeline_creates_report_and_multipage_dashboard(client):
    h = signup(client, "auto-analyst@example.com")
    ds = upload(client, h)
    base = f"/api/datasets/{ds['id']}"
    result = client.post(base + "/auto-build", headers=h, json={
        "business_question": "Which products and regions drive revenue?",
        "audience": "Sales leadership",
        "row_grain": "One row per order line",
    })
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["status"] == "completed"
    assert payload["dashboard"]["widgets"] > 0
    assert payload["dashboard"]["pages"]
    assert payload["report"]["id"]
    assert any(step["step"] == "Statistical analysis" for step in payload["applied_steps"])
    dashboard = client.get(f"/api/dashboards/{payload['dashboard']['id']}", headers=h).json()
    assert all(widget.get("page") for widget in dashboard["widgets"])
    assert any(widget.get("display_type") == "table" for widget in dashboard["widgets"])
    rendered = client.get(f"/api/dashboards/{payload['dashboard']['id']}/data", headers=h).json()["widgets"]
    assert any(widget.get("display_type") == "table" and widget.get("table_rows") for widget in rendered)
    saved = client.put(f"/api/dashboards/{payload['dashboard']['id']}", headers=h, json={
        "name": dashboard["name"], "dataset_id": ds["id"], "widgets": dashboard["widgets"], "filters": [],
    })
    assert saved.status_code == 200, saved.text
    reports = client.get(base + "/reports", headers=h).json()["reports"]
    assert any(report["id"] == payload["report"]["id"] for report in reports)


def test_automated_analyst_pipeline_is_idempotent(client):
    h = signup(client, "auto-repeat@example.com")
    ds = upload(client, h)
    base = f"/api/datasets/{ds['id']}/auto-build"
    first = client.post(base, headers=h, json={}).json()
    second = client.post(base, headers=h, json={}).json()
    assert first["dashboard"]["id"] == second["dashboard"]["id"]
    assert first["report"]["id"] == second["report"]["id"]


def test_auto_build_only_applies_safe_whitespace_cleanup_and_keeps_undo(client):
    h = signup(client, "auto-clean@example.com")
    payload = b"order_date,region,revenue\n2025-01-01, North ,100\n2025-02-01,South,120\n2025-03-01,North,90\n2025-04-01,South,110\n"
    response = client.post("/api/datasets", headers=h, files={"file": ("whitespace.csv", payload, "text/csv")})
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]
    result = client.post(f"/api/datasets/{dataset_id}/auto-build", headers=h, json={})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "completed"
    assert any(step["step"] == "Normalize text whitespace" for step in body["applied_steps"])
    # The ingestion pipeline already trims ordinary uploaded CSV values. Verify the automatic
    # cleaner itself on a deliberately unnormalized in-memory frame as well.
    import pandas as pd
    from app.api.routes.datasets import _clean_frame
    cleaned, log = _clean_frame(pd.DataFrame({"region": [" North ", "South", "   "]}), [{"type": "trim_text"}])
    assert cleaned["region"].iloc[0] == "North"
    assert pd.isna(cleaned["region"].iloc[2])
    assert log[0]["type"] == "trim_text"


def test_dashboard_portable_exports(client):
    import io
    import json
    import zipfile

    from openpyxl import load_workbook

    h = signup(client)
    ds = upload(client, h)
    created = client.post("/api/dashboards", headers=h, json={
        "name": "Sales Export", "dataset_id": ds["id"], "widgets": WIDGETS,
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]

    powerbi = client.get(f"/api/dashboards/{dashboard_id}/export/powerbi", headers=h)
    assert powerbi.status_code == 200
    with zipfile.ZipFile(io.BytesIO(powerbi.content)) as archive:
        names = archive.namelist()
        assert any(name.endswith("Data.csv") for name in names)
        assert any(name.endswith("Power_Query_Import.m") for name in names)
        assert any(name.endswith("DAX_Measures.dax") for name in names)
        model_name = next(name for name in names if name.endswith("Dashboard_Model.json"))
        model = json.loads(archive.read(model_name))
        assert model["table_name"] == "DataDashData"
        assert len(model["widgets"]) == 2

    project = client.get(f"/api/dashboards/{dashboard_id}/export/powerbi-project", headers=h)
    assert project.status_code == 200, project.text
    with zipfile.ZipFile(io.BytesIO(project.content)) as archive:
        names = archive.namelist()
        assert any(name.endswith(".pbip") for name in names)
        assert any(name.endswith("definition.pbir") for name in names)
        assert any(name.endswith("model.bim") for name in names)
        assert any(name.endswith("visual.json") for name in names)
        model_name = next(name for name in names if name.endswith("model.bim"))
        model = json.loads(archive.read(model_name))
        assert model["model"]["tables"][0]["name"] == "DataDashData"
        for name in names:
            if name.endswith((".json", ".pbip")):
                json.loads(archive.read(name))

    tableau = client.get(f"/api/dashboards/{dashboard_id}/export/tableau", headers=h)
    assert tableau.status_code == 200
    with zipfile.ZipFile(io.BytesIO(tableau.content)) as archive:
        assert any(name.endswith("Dashboard_Layout.json") for name in archive.namelist())
        assert any("Visual_Data" in name for name in archive.namelist())

    excel = client.get(f"/api/dashboards/{dashboard_id}/export/excel", headers=h)
    assert excel.status_code == 200
    workbook = load_workbook(io.BytesIO(excel.content), read_only=True)
    assert {"Data", "Field Dictionary", "KPI Summary", "Dashboard Pages"}.issubset(set(workbook.sheetnames))
    assert sum(1 for _ in workbook["Data"].iter_rows()) == ds["rows"] + 1
    workbook.close()


def test_dashboard_portable_exports_are_owner_scoped(client):
    owner = signup(client, "owner@example.com")
    other = signup(client, "other@example.com")
    ds = upload(client, owner)
    dashboard = client.post("/api/dashboards", headers=owner, json={"name": "Private", "dataset_id": ds["id"], "widgets": []}).json()
    assert client.get(f"/api/dashboards/{dashboard['id']}/export/powerbi", headers=other).status_code == 404
    assert client.get(f"/api/dashboards/{dashboard['id']}/export/excel", headers=other).status_code == 404


def test_dashboard_interactive_query_cross_filters_all_widgets(client):
    h = signup(client)
    ds = upload(client, h)
    created = client.post("/api/dashboards", headers=h, json={
        "name": "Interactive", "dataset_id": ds["id"], "widgets": WIDGETS,
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    response = client.post(f"/api/dashboards/{dashboard_id}/query", headers=h, json={
        "filters": [{"column": "region", "op": "eq", "value": "North"}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["widgets"]
    assert response.json()["summary"]["rows"] == 30
    for widget in response.json()["widgets"]:
        if widget["display_type"] == "chart" and widget["data"]:
            assert widget["data"]["meta"]["filtered_rows"] <= ds["rows"]


def test_powerbi_project_is_self_contained_and_has_pbip_structure(client):
    import io
    import json
    import zipfile
    h = signup(client); ds = upload(client, h)
    created = client.post("/api/dashboards", headers=h, json={"name": "PBIP", "dataset_id": ds["id"], "widgets": WIDGETS})
    assert created.status_code == 201, created.text
    response = client.get(f"/api/dashboards/{created.json()['id']}/export/powerbi-project", headers=h)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        pbip = next(n for n in names if n.endswith(".pbip"))
        model = next(n for n in names if n.endswith("model.bim"))
        source = json.loads(archive.read(model))
        expression = source["model"]["tables"][0]["partitions"][0]["source"]["expression"]
        assert any("Binary.FromText" in line for line in expression)
        assert not any("File.Contents" in line for line in expression)
        assert any(n.endswith("definition.pbir") for n in names)
        assert any(n.endswith("definition.pbism") for n in names)
        assert any(".Report/definition/pages/" in n and n.endswith("visual.json") for n in names)
        assert archive.read(pbip)


def test_tableau_package_and_powerpoint_export_are_generated(client):
    import io
    import zipfile

    from pptx import Presentation
    h = signup(client); ds = upload(client, h)
    created = client.post("/api/dashboards", headers=h, json={"name": "Exports", "dataset_id": ds["id"], "widgets": WIDGETS})
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    tableau = client.get(f"/api/dashboards/{dashboard_id}/export/tableau", headers=h)
    assert tableau.status_code == 200
    with zipfile.ZipFile(io.BytesIO(tableau.content)) as archive:
        assert any(n.endswith(".twb") for n in archive.namelist())
        assert "Data/Data.csv" in archive.namelist()
    pptx = client.get(f"/api/dashboards/{dashboard_id}/export/powerpoint", headers=h)
    assert pptx.status_code == 200
    deck = Presentation(io.BytesIO(pptx.content))
    assert len(deck.slides) >= 3


def test_append_dataset_creates_new_dataset_and_preserves_sources(client):
    h = signup(client); first = upload(client, h); second = upload(client, h)
    response = client.post(f"/api/datasets/{first['id']}/combine", headers=h, json={"mode": "append", "other_dataset_id": second["id"]})
    assert response.status_code == 201, response.text
    derived = response.json()
    assert derived["rows"] == first["rows"] + second["rows"]
    assert client.get(f"/api/datasets/{first['id']}", headers=h).json()["rows"] == first["rows"]
    assert client.get(f"/api/datasets/{second['id']}", headers=h).json()["rows"] == second["rows"]


def test_date_drilldown_values_are_month_buckets(client):
    h = signup(client); ds = upload(client, h)
    response = client.get(f"/api/datasets/{ds['id']}/values", headers=h, params={"column": "order_date"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["grain"] == "month"
    assert payload["values"] and all(len(item["value"]) == 7 for item in payload["values"])


def test_join_dataset_creates_derived_copy_without_changing_sources(client):
    h = signup(client); first = upload(client, h); second = upload(client, h)
    response = client.post(f"/api/datasets/{first['id']}/combine", headers=h, json={
        "mode": "join", "other_dataset_id": second["id"], "left_key": "order_id", "right_key": "order_id", "join_type": "left",
    })
    assert response.status_code == 201, response.text
    assert response.json()["rows"] == first["rows"]
    assert client.get(f"/api/datasets/{first['id']}", headers=h).json()["rows"] == first["rows"]
    assert client.get(f"/api/datasets/{second['id']}", headers=h).json()["rows"] == second["rows"]



def test_date_fill_preview_returns_validation_error_not_server_error(client):
    h = signup(client, "date-fill@example.com")
    payload = b"ClaimDate,ClaimAmount\n2024-01-01,100\n,200\n2024-01-03,300\n"
    ds = client.post("/api/datasets", headers=h, files={"file": ("claims.csv", payload, "text/csv")}).json()
    base = f"/api/datasets/{ds['id']}/clean/preview"
    invalid = client.post(base, headers=h, json={"operations": [
        {"type": "fill_missing", "column": "ClaimDate", "strategy": "value", "value": "Unknown"}
    ]})
    assert invalid.status_code == 400
    assert "not a valid date" in invalid.json()["detail"]

    valid = client.post(base, headers=h, json={"operations": [
        {"type": "fill_missing", "column": "ClaimDate", "strategy": "ffill"}
    ]})
    assert valid.status_code == 200, valid.text
    operation = valid.json()["operations"][0]
    assert operation["cells_filled"] == 1
    assert operation["missing_before"] == 1 and operation["missing_after"] == 0


def test_numeric_relationships_are_evidence_aware_and_owner_scoped(client):
    headers = signup(client)
    ds = upload(client, headers)
    response = client.get(f"/api/datasets/{ds['id']}/relationships", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["method"].startswith("Pearson correlation")
    assert isinstance(body["pairs"], list)
    assert body["pairs"], "The sample sales dataset has two varying numeric fields and should yield a pair."
    if body["pairs"]:
        pair = body["pairs"][0]
        assert {"x", "y", "correlation", "sample_count", "direction", "strength"} <= set(pair)
        assert -1 <= pair["correlation"] <= 1
        assert pair["sample_count"] >= 3
    other = signup(client, email="other@example.com")
    assert client.get(f"/api/datasets/{ds['id']}/relationships", headers=other).status_code == 404


def test_workbook_inspection_and_selected_sheet_import(client):
    from .sample_data import multi_sheet_xlsx_bytes

    h = signup(client)
    content = multi_sheet_xlsx_bytes()
    inspected = client.post("/api/datasets/workbook/sheets", headers=h,
        files={"file": ("business.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert inspected.status_code == 200, inspected.text
    assert [s["name"] for s in inspected.json()["sheets"]] == ["Sales", "Customers"]

    imported = client.post("/api/datasets/workbook/import", headers=h,
        files={"file": ("business.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"sheet_names": '["Customers"]'})
    assert imported.status_code == 201, imported.text
    datasets = imported.json()["datasets"]
    assert len(datasets) == 1 and datasets[0]["name"].endswith("— Customers")
    assert datasets[0]["rows"] == 2
    assert {c["name"] for c in datasets[0]["schema"]} == {"Customer", "Region"}


def test_workbook_import_all_sheets_as_independent_datasets(client):
    from .sample_data import multi_sheet_xlsx_bytes

    h = signup(client)
    content = multi_sheet_xlsx_bytes()
    response = client.post("/api/datasets/workbook/import", headers=h,
        files={"file": ("business.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"sheet_names": '["Sales", "Customers"]'})
    assert response.status_code == 201, response.text
    created = response.json()["datasets"]
    assert len(created) == 2
    assert created[0]["id"] != created[1]["id"]
    assert created[0]["columns"] == created[1]["columns"] == 2
    assert created[0]["name"].endswith("— Sales")
    assert created[1]["name"].endswith("— Customers")


def test_workbook_import_rejects_unknown_and_duplicate_sheets(client):
    from .sample_data import multi_sheet_xlsx_bytes

    h = signup(client)
    content = multi_sheet_xlsx_bytes()
    def post(names):
        return client.post("/api/datasets/workbook/import", headers=h,
            files={"file": ("business.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"sheet_names": names})
    assert post('["Missing"]').status_code == 422
    assert post('["Sales", "Sales"]').status_code == 422
    assert post('[]').status_code == 422


def test_workbook_import_respects_dataset_quota_atomically(make_client):
    from .sample_data import multi_sheet_xlsx_bytes

    client = make_client(max_datasets_per_user=1)
    h = signup(client)
    content = multi_sheet_xlsx_bytes()
    response = client.post("/api/datasets/workbook/import", headers=h,
        files={"file": ("business.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"sheet_names": '["Sales", "Customers"]'})
    assert response.status_code == 409
    assert client.get("/api/datasets", headers=h).json()["datasets"] == []
