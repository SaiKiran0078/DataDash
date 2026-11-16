import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, get_store, owned_dashboard, owned_dataset
from app.core.security import new_share_token
from app.db.models import Dashboard, User
from app.schemas import DashboardIn, RowsRequest
from app.services.dashboards import render_widgets, validate_widgets
from app.services.dataset_store import DatasetStore

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def present(d: Dashboard) -> dict:
    return {
        "id": d.id, "name": d.name, "dataset_id": d.dataset_id, "widgets": d.widgets, "filters": d.filters,
        "shared": d.share_token is not None, "share_token": d.share_token,
        "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat(),
    }


def _dump(body: DashboardIn) -> tuple[list[dict], list[dict]]:
    widgets = [
        {"id": w.id, "title": w.title, "spec": w.spec.clean() if w.spec else None,
         "filters": [f.model_dump() for f in w.filters], "page": w.page,
         "display_type": w.display_type, "table_columns": w.table_columns, "table_rows": w.table_rows}
        for w in body.widgets
    ]
    if len({w["id"] for w in widgets}) != len(widgets):
        raise HTTPException(422, "Widget ids must be unique")
    return widgets, [f.model_dump() for f in body.filters]


@router.post("", status_code=201)
def create(
    body: DashboardIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    ds = owned_dataset(db, user, body.dataset_id)
    widgets, filters = _dump(body)
    validate_widgets(store.load(ds), ds.schema_json, widgets, filters)
    d = Dashboard(owner_id=user.id, dataset_id=ds.id, name=body.name.strip(), widgets=widgets, filters=filters)
    db.add(d)
    db.commit()
    return present(d)


@router.get("")
def list_dashboards(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Dashboard).where(Dashboard.owner_id == user.id).order_by(Dashboard.id.desc())).all()
    return {"dashboards": [present(d) for d in rows]}


@router.get("/{dashboard_id}")
def get_one(dashboard_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return present(owned_dashboard(db, user, dashboard_id))


@router.put("/{dashboard_id}")
def update(
    dashboard_id: int,
    body: DashboardIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    d = owned_dashboard(db, user, dashboard_id)
    ds = owned_dataset(db, user, body.dataset_id)
    widgets, filters = _dump(body)
    validate_widgets(store.load(ds), ds.schema_json, widgets, filters)
    d.name, d.dataset_id, d.widgets, d.filters = body.name.strip(), ds.id, widgets, filters
    db.commit()
    return present(d)


@router.delete("/{dashboard_id}", status_code=204)
def delete(dashboard_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_dashboard(db, user, dashboard_id))
    db.commit()


@router.get("/{dashboard_id}/data")
def data(
    dashboard_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    d = owned_dashboard(db, user, dashboard_id)
    return {"widgets": render_widgets(store.load(d.dataset), d.dataset.schema_json, d.widgets, d.filters)}


@router.post("/{dashboard_id}/query")
def query_dashboard(
    dashboard_id: int,
    body: RowsRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    """Render every saved visual against temporary interactive cross-filters."""
    dashboard = owned_dashboard(db, user, dashboard_id)
    import pandas as pd

    from app.engine.query import apply_filters
    filters = [f.model_dump() for f in body.filters]
    frame = store.load(dashboard.dataset)
    widgets = render_widgets(frame, dashboard.dataset.schema_json, dashboard.widgets, filters)
    filtered = apply_filters(frame, dashboard.dataset.schema_json, filters)
    numeric_summary = []
    for column in dashboard.dataset.schema_json:
        if column.get("kind") != "numeric":
            continue
        values = pd.to_numeric(filtered[column["name"]], errors="coerce").dropna()
        if not values.empty:
            numeric_summary.append({"column": column["name"], "count": int(values.count()), "sum": float(values.sum()), "mean": float(values.mean()), "median": float(values.median())})
    cells = int(filtered.shape[0] * filtered.shape[1])
    missing = int(filtered.isna().sum().sum())
    summary = {"rows": len(filtered), "missing_cells": missing, "completeness_pct": round(100 * (cells - missing) / cells, 4) if cells else 100.0, "numeric_summary": numeric_summary}
    return {"widgets": widgets, "summary": summary}


@router.post("/{dashboard_id}/share")
def enable_sharing(dashboard_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Creates (or rotates) the secret read-only link token."""
    d = owned_dashboard(db, user, dashboard_id)
    d.share_token = new_share_token()
    db.commit()
    return present(d)


@router.delete("/{dashboard_id}/share")
def disable_sharing(dashboard_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned_dashboard(db, user, dashboard_id)
    d.share_token = None
    db.commit()
    return present(d)


# ------------------------------------------------------------------ portable dashboard exports

def _safe_export_name(value: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "datadash"


def _json_default(value):
    import pandas as pd
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _field_dictionary(frame, schema: list[dict]) -> list[dict]:
    rows = []
    for column in schema:
        name = column["name"]
        series = frame[name]
        examples = [str(value) for value in series.dropna().head(3).tolist()]
        missing = int(series.isna().sum())
        rows.append({
            "field": name,
            "detected_type": column.get("kind", "text"),
            "row_count": len(frame),
            "non_empty_count": int(len(frame) - missing),
            "missing_count": missing,
            "missing_pct": round(100 * missing / max(len(frame), 1), 2),
            "unique_count": int(series.nunique(dropna=True)),
            "example_values": " | ".join(examples),
        })
    return rows


def _widget_export_rows(widget: dict, rendered: dict) -> tuple[list[str], list[list[object]]]:
    if widget.get("display_type") == "table":
        columns = list(widget.get("table_columns") or rendered.get("table_columns") or [])
        records = rendered.get("table_rows") or widget.get("table_rows") or []
        return columns, [[record.get(column) for column in columns] for record in records]
    chart = rendered.get("data") or {}
    if chart.get("labels") is not None:
        datasets = chart.get("datasets") or []
        headers = ["Category"] + [str(item.get("label") or f"Series {index + 1}") for index, item in enumerate(datasets)]
        rows = []
        for index, label in enumerate(chart.get("labels") or []):
            rows.append([label] + [((item.get("data") or [])[index] if index < len(item.get("data") or []) else None) for item in datasets])
        return headers, rows
    if chart.get("points") is not None:
        meta = chart.get("meta") or {}
        return [str(meta.get("x") or "X"), str(meta.get("y") or "Y")], [[p.get("x"), p.get("y")] for p in chart.get("points") or []]
    return ["Status"], [[chart.get("error") or "No chart data"]]


def _power_query_m(schema: list[dict]) -> str:
    type_map = {"numeric": "type number", "datetime": "type datetime", "boolean": "type logical", "categorical": "type text", "text": "type text", "id": "type text"}
    pairs = []
    for column in schema:
        name = str(column["name"]).replace('"', '""')
        pairs.append(f'{{"{name}", {type_map.get(column.get("kind"), "type text")}}}')
    return "\n".join([
        "let",
        '    Source = Csv.Document(File.Contents("Data.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        "    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {" + ", ".join(pairs) + "})",
        "in",
        "    ChangedTypes",
    ]) + "\n"


def _dax_measures(schema: list[dict]) -> str:
    measures = [
        "// DataDash starter measures for the imported DataDashData table.",
        "// Review business definitions and format strings before publishing.",
        "Record Count = COUNTROWS('DataDashData')",
    ]
    for column in schema:
        if column.get("kind") != "numeric":
            continue
        name = str(column["name"])
        dax_column = name.replace("]", "]]" )
        measure_name = re.sub(r"[^A-Za-z0-9_ ]+", "_", name).strip() or "Numeric Field"
        measures.extend([
            f"Total {measure_name} = SUM('DataDashData'[{dax_column}])",
            f"Average {measure_name} = AVERAGE('DataDashData'[{dax_column}])",
            f"Median {measure_name} = MEDIAN('DataDashData'[{dax_column}])",
        ])
    return "\n\n".join(measures) + "\n"


def _make_powerbi_package(dashboard, dataset, frame, rendered: list[dict]) -> bytes:
    import csv
    import io
    import json
    import zipfile

    output = io.BytesIO()
    base = _safe_export_name(dataset.name)
    csv_buffer = io.StringIO(newline="")
    frame.to_csv(csv_buffer, index=False)
    fields = _field_dictionary(frame, dataset.schema_json)
    pages = sorted({widget.get("page") or "Overview" for widget in dashboard.widgets})
    model = {
        "format": "DataDash Power BI starter package",
        "dataset": {"name": dataset.name, "rows": len(frame), "columns": len(frame.columns)},
        "table_name": "DataDashData",
        "pages": pages,
        "widgets": dashboard.widgets,
        "filters": dashboard.filters,
        "notes": ["This is an import-ready starter package, not a native PBIX/PBIP file.", "Visual specifications are provided as portable metadata; recreate or refine visuals in Power BI Desktop."],
    }
    rendered_by_id = {item["id"]: item for item in rendered}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{base}/Data.csv", csv_buffer.getvalue().encode("utf-8-sig"))
        archive.writestr(f"{base}/Field_Dictionary.csv", pd_to_csv_bytes(fields))
        archive.writestr(f"{base}/Dashboard_Model.json", json.dumps(model, indent=2, default=_json_default))
        archive.writestr(f"{base}/Power_Query_Import.m", _power_query_m(dataset.schema_json))
        archive.writestr(f"{base}/DAX_Measures.dax", _dax_measures(dataset.schema_json))
        for index, widget in enumerate(dashboard.widgets, 1):
            rendered_widget = rendered_by_id.get(widget["id"], {})
            headers, rows = _widget_export_rows(widget, rendered_widget)
            visual_csv = io.StringIO(newline="")
            writer = csv.writer(visual_csv)
            writer.writerow(headers)
            writer.writerows(rows)
            filename = _safe_export_name(widget.get("title") or f"Visual_{index}")
            archive.writestr(f"{base}/Visual_Data/{index:02d}_{filename}.csv", visual_csv.getvalue().encode("utf-8-sig"))
        readme = f"""# {dataset.name} — Power BI starter package\n\n## Import\n1. Extract this ZIP to a folder.\n2. In Power BI Desktop choose **Get data → Text/CSV** and select `Data.csv`.\n3. For typed import, open **Transform data → Advanced Editor** and adapt `Power_Query_Import.m`; update the file path to the extracted `Data.csv`.\n4. Create a table named `DataDashData` or change the table name in `DAX_Measures.dax`.\n5. Copy the suggested measures from `DAX_Measures.dax` into the model.\n6. Use `Dashboard_Model.json` and `Visual_Data/` to recreate the pages and chart configurations.\n\nThis is a portable data/model starter pack, not a native `.pbix` or `.pbip` project. Validate units, aggregation rules, relationships and business definitions before publishing.\n"""
        archive.writestr(f"{base}/README_PowerBI.md", readme)
    return output.getvalue()


def pd_to_csv_bytes(rows: list[dict]) -> bytes:
    import pandas as pd
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


def _make_tableau_package(dashboard, dataset, frame, rendered: list[dict]) -> bytes:
    """Build a Tableau packaged workbook (.twbx) with an embedded CSV text source and worksheets."""
    import csv
    import io
    import json
    import xml.etree.ElementTree as ET
    import zipfile

    output = io.BytesIO()
    base = _safe_export_name(dataset.name)
    pages = list(dict.fromkeys(["Overview"] + [w.get("page") or "Overview" for w in dashboard.widgets]))
    workbook = ET.Element("workbook", {"version": "18.1", "original-version": "18.1", "source-build": "2024.2.0", "xmlns:user": "http://www.tableausoftware.com/xml/user"})
    datasources = ET.SubElement(workbook, "datasources")
    datasource = ET.SubElement(datasources, "datasource", {"caption": dataset.name, "inline": "true", "name": "federated.0", "version": "18.1"})
    connection = ET.SubElement(datasource, "connection", {"class": "textscan", "filename": "Data/Data.csv", "interpretationMode": "standard"})
    ET.SubElement(connection, "relation", {"name": "Data.csv", "table": "Data.csv", "type": "table"})
    type_map = {"numeric": ("real", "quantitative", "measure"), "datetime": ("date", "ordinal", "dimension"), "boolean": ("boolean", "nominal", "dimension"), "id": ("string", "nominal", "dimension"), "text": ("string", "nominal", "dimension"), "categorical": ("string", "nominal", "dimension")}
    for col in dataset.schema_json:
        name = str(col["name"]); dtype, role_type, role = type_map.get(col.get("kind"), ("string", "nominal", "dimension"))
        ET.SubElement(datasource, "column", {"caption": name, "datatype": dtype, "name": f"[{name}]", "role": role, "type": role_type})
    worksheets = ET.SubElement(workbook, "worksheets")
    rendered_by_id = {x["id"]: x for x in rendered}
    widget_entries = list(dashboard.widgets)
    for index, widget in enumerate(widget_entries, 1):
        title = str(widget.get("title") or f"Visual {index}")
        sheet_name = _safe_export_name(title)[:40] or f"Visual_{index}"
        spec = widget.get("spec") or {}
        x_name, y_name = spec.get("x"), spec.get("y")
        chart_type = str(spec.get("type") or "bar").lower()
        worksheet = ET.SubElement(worksheets, "worksheet", {"name": sheet_name})
        table = ET.SubElement(worksheet, "table")
        view = ET.SubElement(table, "view")
        source_refs = ET.SubElement(view, "datasources"); ET.SubElement(source_refs, "datasource", {"name": "federated.0"})
        dependencies = ET.SubElement(view, "datasource-dependencies", {"datasource": "federated.0"})
        for field in [x_name, y_name]:
            if field and field in frame.columns:
                ET.SubElement(dependencies, "column", {"datatype": "string", "name": f"[{field}]", "role": "dimension", "type": "nominal"})
        panes = ET.SubElement(table, "panes"); pane = ET.SubElement(panes, "pane", {"name": "pane", "id": "1"})
        ET.SubElement(pane, "view")
        mark = "Pie" if chart_type == "pie" else "Line" if chart_type == "line" else "Bar"
        ET.SubElement(pane, "mark", {"class": mark})
        encodings = ET.SubElement(pane, "encodings")
        if x_name: ET.SubElement(encodings, "color", {"column": f"[{x_name}]"})
        if y_name: ET.SubElement(encodings, "size", {"column": f"[{y_name}]"})
        ET.SubElement(table, "rows"); ET.SubElement(table, "cols")
        ET.SubElement(worksheet, "simple-id", {"uuid": f"{{{index:08x}-0000-4000-8000-{index:012x}}}"})
    dashboards = ET.SubElement(workbook, "dashboards")
    for page_index, page_name in enumerate(pages, 1):
        dashboard_node = ET.SubElement(dashboards, "dashboard", {"name": _safe_export_name(page_name)[:40] or f"Page_{page_index}", "show-tabs": "true"})
        zones = ET.SubElement(dashboard_node, "zones")
        page_widgets = [w for w in widget_entries if (w.get("page") or "Overview") == page_name]
        for z, widget in enumerate(page_widgets, 1):
            sheet = _safe_export_name(widget.get("title") or f"Visual_{z}")[:40] or f"Visual_{z}"
            ET.SubElement(zones, "zone", {"name": sheet, "type": "worksheet", "x": str(((z-1)%2)*500), "y": str(((z-1)//2)*330), "w": "500", "h": "330", "param": sheet})
    xml_bytes = ET.tostring(workbook, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{base}.twb", xml_bytes)
        archive.writestr("Data/Data.csv", frame.to_csv(index=False).encode("utf-8-sig"))
        archive.writestr("Data/Field_Dictionary.csv", pd_to_csv_bytes(_field_dictionary(frame, dataset.schema_json)))
        archive.writestr("Data/Dashboard_Layout.json", json.dumps({"name": dashboard.name, "pages": pages, "widgets": dashboard.widgets, "filters": dashboard.filters}, indent=2, default=_json_default))
        for index, widget in enumerate(widget_entries, 1):
            headers, rows = _widget_export_rows(widget, rendered_by_id.get(widget["id"], {}))
            visual_csv = io.StringIO(newline="")
            writer = csv.writer(visual_csv); writer.writerow(headers); writer.writerows(rows)
            archive.writestr(f"Data/Visual_Data/{index:02d}_{_safe_export_name(widget.get('title') or 'Visual')}.csv", visual_csv.getvalue().encode("utf-8-sig"))
        archive.writestr("README_OPEN_IN_TABLEAU.md", f"# {dashboard.name} — Tableau packaged workbook\n\nOpen the `{base}.twb` file inside this packaged workbook using Tableau Desktop or Tableau Reader. The packaged workbook includes its CSV data source under `Data/Data.csv`, so it does not depend on the exporting computer's source path. The workbook includes generated worksheets and dashboard pages based on DataDash's saved visual definitions. Validate the workbook in your installed Tableau version before publication.\n")
    return output.getvalue()


def _make_excel_workbook(dashboard, dataset, frame, rendered: list[dict]) -> bytes:
    import io
    import json

    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    output = io.BytesIO()
    workbook = Workbook(write_only=True)
    header_fill = PatternFill("solid", fgColor="253858")
    header_font = Font(color="FFFFFF", bold=True)

    def add_sheet(title, headers, rows):
        ws = workbook.create_sheet(title=title[:31])
        if headers:
            cells = []
            for value in headers:
                cell = WriteOnlyCell(ws, value=str(value))
                cell.fill = header_fill; cell.font = header_font
                cells.append(cell)
            ws.append(cells)
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = f"A1:{chr(64 + min(len(headers), 26))}1"
        row_count = 0
        for row in rows:
            ws.append([_json_default(value) if value is not None else None for value in row])
            row_count += 1
        if headers and row_count:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{row_count + 1}"
        return ws

    add_sheet("Data", list(frame.columns), frame.itertuples(index=False, name=None))
    dictionary = _field_dictionary(frame, dataset.schema_json)
    add_sheet("Field Dictionary", list(dictionary[0].keys()) if dictionary else [], [[item[k] for k in dictionary[0]] for item in dictionary] if dictionary else [])

    total_cells = int(frame.shape[0] * frame.shape[1])
    missing_cells = int(frame.isna().sum().sum())
    kpis = [["Records", len(frame)], ["Fields", len(frame.columns)], ["Missing cells", missing_cells], ["Completeness %", round(100 * (total_cells - missing_cells) / max(total_cells, 1), 2)]]
    for column in dataset.schema_json:
        if column.get("kind") != "numeric":
            continue
        values = pd.to_numeric(frame[column["name"]], errors="coerce").dropna()
        if not values.empty:
            kpis.extend([[f"{column['name']} — Sum", float(values.sum())], [f"{column['name']} — Average", float(values.mean())], [f"{column['name']} — Median", float(values.median())]])
    add_sheet("KPI Summary", ["Metric", "Value"], kpis)

    rendered_by_id = {item["id"]: item for item in rendered}
    page_rows = []
    for widget in dashboard.widgets:
        page_rows.append([widget.get("page") or "Overview", widget.get("title"), widget.get("display_type") or (widget.get("spec") or {}).get("type", "chart"), json.dumps(widget.get("spec") or {}, default=_json_default)])
    add_sheet("Dashboard Pages", ["Page", "Visual", "Type", "Configuration JSON"], page_rows)
    used = {"Data", "Field Dictionary", "KPI Summary", "Dashboard Pages"}
    for index, widget in enumerate(dashboard.widgets, 1):
        headers, rows = _widget_export_rows(widget, rendered_by_id.get(widget["id"], {}))
        base_name = re.sub(r"[^A-Za-z0-9 _-]+", "", widget.get("title") or f"Visual {index}")[:24].strip() or f"Visual {index}"
        sheet_name = base_name
        suffix = 2
        while sheet_name in used:
            sheet_name = f"{base_name[:26]} {suffix}"; suffix += 1
        used.add(sheet_name)
        add_sheet(sheet_name, headers, rows)
    workbook.save(output)
    return output.getvalue()



def _powerbi_project_package(dashboard, dataset, frame, rendered: list[dict]) -> bytes:
    """Create an editable PBIP/PBIR project scaffold with a typed import model and report pages.

    The project uses the documented PBIP folder structure. Data source path is intentionally
    explicit and documented so a user can point Power Query at the extracted Data.csv file.
    """
    import base64
    import io
    import json
    import uuid
    import zipfile

    output = io.BytesIO()
    base = _safe_export_name(dataset.name) or "DataDash"
    project = base
    report_dir = f"{project}.Report"
    model_dir = f"{project}.SemanticModel"
    pages = sorted({widget.get("page") or "Overview" for widget in dashboard.widgets}) or ["Overview"]
    schema_by_name = {item["name"]: item for item in dataset.schema_json}

    # TMSL semantic model. Power BI Desktop will load the CSV through the editable M partition.
    type_map = {"numeric": "double", "datetime": "dateTime", "boolean": "boolean", "id": "string", "text": "string", "categorical": "string"}
    columns = []
    for column in dataset.schema_json:
        name = str(column["name"])
        columns.append({"name": name, "dataType": type_map.get(column.get("kind"), "string"),
                        "sourceColumn": name, "summarizeBy": "none" if column.get("kind") not in {"numeric"} else "sum"})
    measures = [{"name": "Record Count", "expression": "COUNTROWS('DataDashData')", "formatString": "#,0"}]
    if dataset.schema_json:
        nonblank_terms = [f"COUNT('DataDashData'[{str(c['name']).replace(']', ']]')}])" for c in dataset.schema_json]
        measures.append({"name": "Data Completeness %", "expression": f"DIVIDE({' + '.join(nonblank_terms)}, COUNTROWS('DataDashData') * {len(dataset.schema_json)})", "formatString": "0.0%"})
    for column in dataset.schema_json:
        if column.get("kind") != "numeric":
            continue
        name = str(column["name"])
        escaped = name.replace("]", "]]" )
        safe_measure = re.sub(r"[^A-Za-z0-9_ ]+", "_", name).strip() or "Numeric Field"
        measures.extend([
            {"name": f"Total {safe_measure}", "expression": f"SUM('DataDashData'[{escaped}])", "formatString": "#,##0.00"},
            {"name": f"Average {safe_measure}", "expression": f"AVERAGE('DataDashData'[{escaped}])", "formatString": "#,##0.00"},
            {"name": f"Median {safe_measure}", "expression": f"MEDIAN('DataDashData'[{escaped}])", "formatString": "#,##0.00"},
        ])
    m_types = {"numeric": "type number", "datetime": "type datetime", "boolean": "type logical", "id": "type text", "text": "type text", "categorical": "type text"}
    type_pairs = ", ".join("{\"" + str(c["name"]).replace('"','""') + "\", " + m_types.get(c.get("kind"), "type text") + "}" for c in dataset.schema_json)
    csv_payload = base64.b64encode(frame.to_csv(index=False).encode("utf-8-sig")).decode("ascii")
    m_expression = [
        "let",
        f'    SourceBinary = Binary.FromText("{csv_payload}", BinaryEncoding.Base64),',
        '    Source = Csv.Document(SourceBinary, [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f"    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders, {{{type_pairs}}})",
        "in",
        "    ChangedTypes",
    ]
    model_bim = {
        "name": project,
        "compatibilityLevel": 1604,
        "model": {
            "culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US", "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
            "tables": [{"name": "DataDashData", "columns": columns, "measures": measures,
                        "partitions": [{"name": "DataDashData", "mode": "import", "source": {"type": "m", "expression": m_expression}}]}]
        }
    }

    def col_field(name):
        return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "DataDashData"}}, "Property": name}},
                "queryRef": f"DataDashData.{name}", "nativeQueryRef": name}
    def measure_field(name):
        return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "DataDashData"}}, "Property": name}},
                "queryRef": f"DataDashData.{name}", "nativeQueryRef": name}

    # Recreate the same automatic overview visual intent shown by the DataDash UI.
    auto_widgets = []
    numeric_names = [c["name"] for c in dataset.schema_json if c.get("kind") == "numeric"]
    date_names = [c["name"] for c in dataset.schema_json if c.get("kind") == "datetime"]
    category_names = [c["name"] for c in dataset.schema_json if c.get("kind") in {"categorical", "boolean", "text"} and frame[c["name"]].nunique(dropna=True) > 1 and frame[c["name"]].nunique(dropna=True) <= 50]
    preferred_measure = next((n for n in numeric_names if any(t in n.lower() for t in ("revenue", "sales", "amount", "premium", "profit"))), numeric_names[0] if numeric_names else None)
    if date_names and preferred_measure:
        auto_widgets.append({"id":"dd_auto_trend","title":f"{preferred_measure} over time","page":"Overview","display_type":"chart","spec":{"type":"line","x":date_names[0],"y":preferred_measure,"agg":"sum","time_grain":"month"}})
    if category_names and preferred_measure:
        auto_widgets.append({"id":"dd_auto_segment","title":f"{preferred_measure} by {category_names[0]}","page":"Overview","display_type":"chart","spec":{"type":"bar","x":category_names[0],"y":preferred_measure,"agg":"sum","top_n":10,"sort":"value_desc"}})
    if category_names:
        auto_widgets.append({"id":"dd_auto_mix","title":f"{category_names[0]} distribution","page":"Overview","display_type":"chart","spec":{"type":"pie","x":category_names[0],"agg":"count","top_n":10}})
    export_widgets = auto_widgets + list(dashboard.widgets)
    pages = list(dict.fromkeys(["Overview"] + [w.get("page") or "Overview" for w in dashboard.widgets]))
    report_pages = []
    page_folders = []
    for page_index, page_name in enumerate(pages):
        page_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset.id}:{page_name}").hex[:20]
        page_folders.append(page_id)
        visuals = []
        page_widgets = [w for w in export_widgets if (w.get("page") or "Overview") == page_name]
        # KPI strip mirrors the DataDash executive snapshot.
        if page_index == 0:
            kpis = []
            if preferred_measure:
                safe_measure = re.sub(r"[^A-Za-z0-9_ ]+", "_", preferred_measure).strip() or "Numeric Field"
                kpis.append((f"Total {safe_measure}", f"Total {preferred_measure}"))
            kpis.append(("Record Count", "Orders / records"))
            if preferred_measure:
                kpis.append((f"Average {safe_measure}", "Average per record"))
            rating_measure = next((n for n in numeric_names if any(t in n.lower() for t in ("rating", "score", "satisfaction"))), None)
            if rating_measure:
                rating_safe = re.sub(r"[^A-Za-z0-9_ ]+", "_", rating_measure).strip() or "Rating"
                kpis.append((f"Average {rating_safe}", f"Average {rating_measure}"))
            else:
                kpis.append(("Data Completeness %", "Data completeness"))
            for ki, (measure_name, label) in enumerate(kpis):
                visuals.append(("cardVisual", {"Data": [measure_field(measure_name)]}, label, 20 + ki*305, 20, 285, 130))
        for widget in page_widgets:
            spec = widget.get("spec") or {}
            x_name, y_name = spec.get("x"), spec.get("y")
            chart_type = str(spec.get("type") or "bar").lower()
            if widget.get("display_type") == "table":
                visual_type = "tableEx"
                fields = [col_field(c) for c in (widget.get("table_columns") or []) if c in schema_by_name]
                if not fields:
                    continue
                query_state = {"Values": fields}
            elif chart_type in {"line", "area"}:
                visual_type = "lineChart" if chart_type == "line" else "areaChart"
                if x_name not in schema_by_name or y_name not in schema_by_name:
                    continue
                safe_measure = re.sub(r"[^A-Za-z0-9_ ]+", "_", y_name).strip() or "Numeric Field"
                query_state = {"Category": [col_field(x_name)], "Y": [measure_field(f"Total {safe_measure}")]}
            elif chart_type in {"pie", "doughnut"}:
                visual_type = "donutChart" if chart_type == "doughnut" else "pieChart"
                if x_name not in schema_by_name:
                    continue
                query_state = {"Category": [col_field(x_name)], "Y": [measure_field("Record Count")]}
            elif chart_type == "scatter":
                visual_type = "scatterChart"
                if x_name not in schema_by_name or y_name not in schema_by_name:
                    continue
                query_state = {"X": [col_field(x_name)], "Y": [col_field(y_name)]}
            else:
                visual_type = "clusteredBarChart" if chart_type == "bar" else "clusteredColumnChart"
                if x_name not in schema_by_name or y_name not in schema_by_name:
                    continue
                safe_measure = re.sub(r"[^A-Za-z0-9_ ]+", "_", y_name).strip() or "Numeric Field"
                query_state = {"Category": [col_field(x_name)], "Y": [measure_field(f"Total {safe_measure}")]}
            visuals.append((visual_type, query_state, widget.get("title") or "DataDash visual", 20 + ((len(visuals)-4 if page_index == 0 else len(visuals))%2)*620, (190 if page_index == 0 else 30) + ((len(visuals)-4 if page_index == 0 else len(visuals))//2)*330, 590, 300))

        report_pages.append({"id": page_id, "display": page_name, "visuals": visuals})

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        def write_json(path, obj):
            archive.writestr(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        archive.writestr(f"{project}.pbip", json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0", "artifacts": [{"report": {"path": f"./{report_dir}"}}], "settings": {"enableAutoRecovery": True}}, indent=2) + "\n")
        archive.writestr(f"{project}.gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
        archive.writestr(f"{project}/Data.csv", frame.to_csv(index=False).encode("utf-8-sig"))
        write_json(f"{model_dir}/definition.pbism", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json", "version": "1.0", "settings": {}})
        write_json(f"{model_dir}/model.bim", model_bim)
        write_json(f"{report_dir}/definition.pbir", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json", "version": "4.0", "datasetReference": {"byPath": {"path": f"../{model_dir}"}}})
        write_json(f"{report_dir}/definition/version.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
        write_json(f"{report_dir}/definition/report.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json", "themeCollection": {}, "filterConfig": {}, "objects": {}, "resourcePackages": [], "settings": {}, "annotations": []})
        write_json(f"{report_dir}/definition/pages/pages.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json", "pageOrder": page_folders, "activePageName": page_folders[0]})
        for page in report_pages:
            page_dir = f"{report_dir}/definition/pages/{page['id']}"
            write_json(f"{page_dir}/page.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json", "name": page["id"], "displayName": page["display"], "displayOption": "FitToPage", "height": 720, "width": 1280})
            for visual_index, (visual_type, query_state, title, x, y, width, height) in enumerate(page["visuals"]):
                visual_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{page['id']}:{visual_index}:{title}").hex[:20]
                visual = {
                    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json",
                    "name": visual_id,
                    "position": {"x": x, "y": y, "z": visual_index, "width": width, "height": height, "tabOrder": visual_index},
                    "visual": {"visualType": visual_type, "query": {"queryState": {role: {"projections": projections} for role, projections in query_state.items()}}, "drillFilterOtherVisuals": True},
                    "visualContainerObjects": {"title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}, "text": {"expr": {"Literal": {"Value": "'" + str(title).replace("'", "''") + "'"}}}}}]},
                    "filterConfig": {}
                }
                write_json(f"{page_dir}/visuals/{visual_id}/visual.json", visual)
        archive.writestr(f"{project}/README_OPEN_IN_POWER_BI.md", f"""# {dataset.name} — Power BI Project\n\nThis ZIP contains a Power BI Project (PBIP) with an editable semantic model (TMSL) and report definition (PBIR). PBIP is the editable project format; it is not a PBIX binary file. Microsoft documents PBIP as a folder-based project with a report folder and semantic-model folder.\n\n## Open\n1. Extract the ZIP to a normal folder.\n2. Open `{project}.pbip` in Power BI Desktop (use a recent Desktop release with PBIP/PBIR support).\n3. The semantic model embeds the CSV snapshot in its Power Query expression, so it does not depend on a source-file path or location setting.\n4. Refresh the model. Review the inferred field types and measures before publishing.\n\n## Included\n- `{project}.Report/`: editable report pages and visual definitions for the dashboard pages.\n- `{project}.SemanticModel/`: editable model, typed columns and DAX measures.\n- `{project}/Data.csv`: data snapshot used by the model.\n\nThe PBIP files are generated from DataDash's saved visual metadata and include an embedded data snapshot. The semantic model uses TMSL (`model.bim`) with the matching PBIP format version. The data query is self-contained and has no machine-specific path. Please validate the project in Power BI Desktop before production use; DataDash cannot run Power BI Desktop's native validation engine in the server container.\n""")
    return output.getvalue()



def _make_powerpoint_report(dashboard, dataset, frame, rendered: list[dict]) -> bytes:
    """Create an editable PowerPoint executive deck from dashboard data and findings."""
    import io

    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    navy = RGBColor(18, 29, 52); purple = RGBColor(105, 87, 230); muted = RGBColor(100, 116, 139)
    def title(slide, heading, sub=None):
        box = slide.shapes.add_textbox(Inches(.55), Inches(.35), Inches(12.2), Inches(.55))
        tf = box.text_frame; tf.text = heading; tf.paragraphs[0].font.size = Pt(25); tf.paragraphs[0].font.bold = True; tf.paragraphs[0].font.color.rgb = navy
        if sub:
            b = slide.shapes.add_textbox(Inches(.58), Inches(.95), Inches(12), Inches(.35)); b.text_frame.text = sub; b.text_frame.paragraphs[0].font.size = Pt(10); b.text_frame.paragraphs[0].font.color.rgb = muted
    def note(slide, text, y=6.95):
        b=slide.shapes.add_textbox(Inches(.6), Inches(y), Inches(12), Inches(.25)); b.text_frame.text=text; b.text_frame.paragraphs[0].font.size=Pt(8); b.text_frame.paragraphs[0].font.color.rgb=muted
    # Cover
    slide=prs.slides.add_slide(prs.slide_layouts[6]); slide.background.fill.solid(); slide.background.fill.fore_color.rgb=navy
    b=slide.shapes.add_textbox(Inches(.8), Inches(1.4), Inches(11.8), Inches(1.1)); b.text_frame.text=dashboard.name; b.text_frame.paragraphs[0].font.size=Pt(34); b.text_frame.paragraphs[0].font.bold=True; b.text_frame.paragraphs[0].font.color.rgb=RGBColor(255,255,255)
    b=slide.shapes.add_textbox(Inches(.85), Inches(2.55), Inches(11), Inches(.8)); b.text_frame.text=f"Executive analytics report · {dataset.name}\n{len(frame):,} records · {len(frame.columns)} fields · Generated {__import__('datetime').date.today().isoformat()}"; b.text_frame.paragraphs[0].font.size=Pt(16); b.text_frame.paragraphs[0].font.color.rgb=RGBColor(190,205,230)
    # KPI slide
    slide=prs.slides.add_slide(prs.slide_layouts[6]); title(slide,"Executive KPI snapshot",f"{dataset.name} · current saved dataset snapshot")
    numeric=[c for c in dataset.schema_json if c.get('kind')=='numeric']
    total_cells=max(len(frame)*max(len(frame.columns),1),1); complete=100*(1-int(frame.isna().sum().sum())/total_cells)
    kpis=[("Records",f"{len(frame):,}"),("Fields",str(len(frame.columns))),("Completeness",f"{complete:.1f}%")]
    if numeric:
        vals=__import__('pandas').to_numeric(frame[numeric[0]['name']],errors='coerce')
        kpis.append((f"Total {numeric[0]['name']}",f"{vals.sum():,.2f}"))
    for i,(label,value) in enumerate(kpis):
        x=.65+(i%2)*6.2; y=1.7+(i//2)*2.1
        sh=slide.shapes.add_shape(1, Inches(x), Inches(y), Inches(5.7), Inches(1.55)); sh.fill.solid(); sh.fill.fore_color.rgb=RGBColor(239,242,250); sh.line.color.rgb=purple
        tb=slide.shapes.add_textbox(Inches(x+.25), Inches(y+.2), Inches(5.2), Inches(1.1)); tf=tb.text_frame; tf.text=label; tf.paragraphs[0].font.size=Pt(13); tf.paragraphs[0].font.color.rgb=muted; p=tf.add_paragraph(); p.text=value; p.font.size=Pt(27); p.font.bold=True; p.font.color.rgb=navy
    # Dashboard chart slides (native editable charts)
    rendered_by_id={x['id']:x for x in rendered}
    for page in sorted({w.get('page') or 'Overview' for w in dashboard.widgets}):
        page_widgets=[w for w in dashboard.widgets if (w.get('page') or 'Overview')==page]
        for start in range(0,len(page_widgets),2):
            slide=prs.slides.add_slide(prs.slide_layouts[6]); title(slide,page,"Editable charts generated from saved DataDash visual specifications")
            for pos,w in enumerate(page_widgets[start:start+2]):
                r=rendered_by_id.get(w['id'],{}); chart=r.get('data') or {}; x=.6+pos*6.35
                if w.get('display_type')=='table':
                    cols=w.get('table_columns') or []; rows=r.get('table_rows') or w.get('table_rows') or []
                    tb=slide.shapes.add_textbox(Inches(x), Inches(1.6), Inches(6), Inches(4.9)); tf=tb.text_frame; tf.text=w.get('title','Summary')
                    for row in rows[:14]:
                        p=tf.add_paragraph(); p.text=' · '.join(str(row.get(c,'')) for c in cols[:5]); p.font.size=Pt(9)
                    continue
                labels=chart.get('labels') or []; sets=chart.get('datasets') or []
                if not labels or not sets: continue
                cd=CategoryChartData(); cd.categories=[str(v)[:50] for v in labels[:20]]
                for ds in sets[:3]: cd.add_series(str(ds.get('label') or 'Value'), (ds.get('data') or [])[:20])
                typ=(w.get('spec') or {}).get('type','bar')
                chart_type=XL_CHART_TYPE.LINE if typ=='line' else XL_CHART_TYPE.PIE if typ=='pie' else XL_CHART_TYPE.BAR_CLUSTERED
                ch=slide.shapes.add_chart(chart_type, Inches(x), Inches(1.55), Inches(6.05), Inches(4.9), cd).chart
                ch.has_title=True; ch.chart_title.text_frame.text=w.get('title','DataDash visual'); ch.has_legend=len(sets)>1 or typ=='pie'
                if ch.has_legend: ch.legend.position=XL_LEGEND_POSITION.BOTTOM
            note(slide,f"{dataset.name} · {page} · Values reflect the dataset snapshot at export time")
    # Evidence-led analyst findings: descriptive only, with no causal inference.
    slide=prs.slides.add_slide(prs.slide_layouts[6]); title(slide,"Analyst findings", "Descriptive evidence from the exported dataset snapshot")
    y_pos=1.45
    for column in [c for c in dataset.schema_json if c.get("kind")=="numeric"][:5]:
        series=__import__('pandas').to_numeric(frame[column["name"]],errors="coerce").dropna()
        if series.empty: continue
        text_line=f"{column['name']}: total {series.sum():,.2f} · average {series.mean():,.2f} · median {series.median():,.2f} · range {series.min():,.2f} to {series.max():,.2f} · {int(series.isna().sum())} missing in source"
        b=slide.shapes.add_textbox(Inches(.8), Inches(y_pos), Inches(11.7), Inches(.65)); b.text_frame.text=text_line; b.text_frame.paragraphs[0].font.size=Pt(14); b.text_frame.paragraphs[0].font.color.rgb=navy; y_pos += .82
    category = next((c for c in dataset.schema_json if c.get("kind") in {"categorical","text","boolean"} and frame[c["name"]].nunique(dropna=True)>1), None)
    if category and y_pos < 6.2:
        top=frame[category["name"]].astype("string").fillna("(Missing)").value_counts().head(5)
        b=slide.shapes.add_textbox(Inches(.8), Inches(y_pos), Inches(11.7), Inches(1.0)); b.text_frame.text=f"Largest {category['name']} groups: " + " · ".join(f"{k} ({v:,})" for k,v in top.items()); b.text_frame.paragraphs[0].font.size=Pt(14); b.text_frame.paragraphs[0].font.color.rgb=navy
    note(slide,"Interpret associations as descriptive, not causal. Validate metric definitions and the dataset grain.")

    # Findings and methodology
    slide=prs.slides.add_slide(prs.slide_layouts[6]); title(slide,"Data quality & analyst considerations")
    total_missing=int(frame.isna().sum().sum()); duplicates=int(frame.duplicated().sum())
    paragraphs=[f"Missing cells: {total_missing:,} ({100*total_missing/max(len(frame)*max(len(frame.columns),1),1):.2f}% of all cells).",f"Exact duplicate rows: {duplicates:,}.","Missing values and duplicates are reported, not silently deleted or imputed.","Review business definitions, units, row grain and exceptional values before publishing decisions."]
    for i,t in enumerate(paragraphs):
        b=slide.shapes.add_textbox(Inches(.8), Inches(1.55+i*.9), Inches(11.7), Inches(.65)); b.text_frame.text=t; b.text_frame.paragraphs[0].font.size=Pt(17 if i<2 else 14); b.text_frame.paragraphs[0].font.color.rgb=navy
    out=io.BytesIO(); prs.save(out); return out.getvalue()

@router.get("/{dashboard_id}/export/{platform}")
def export_dashboard_portable(
    dashboard_id: int,
    platform: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    store: DatasetStore = Depends(get_store),
):
    """Export a dashboard with data and metadata for Power BI, Tableau or Excel."""
    import io

    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse

    platform = platform.lower()
    if platform not in {"powerbi", "powerbi-project", "tableau", "excel", "powerpoint"}:
        raise HTTPException(404, "Supported exports are powerbi-project, tableau, excel and powerpoint")
    dashboard = owned_dashboard(db, user, dashboard_id)
    dataset = owned_dataset(db, user, dashboard.dataset_id)
    frame = store.load(dataset)
    rendered = render_widgets(frame, dataset.schema_json, dashboard.widgets, dashboard.filters)
    safe_name = _safe_export_name(dashboard.name)
    if platform == "powerbi":
        payload = _make_powerbi_package(dashboard, dataset, frame, rendered)
        media_type, extension = "application/zip", "powerbi_starter.zip"
    elif platform == "powerbi-project":
        payload = _powerbi_project_package(dashboard, dataset, frame, rendered)
        media_type, extension = "application/zip", "powerbi_project.zip"
    elif platform == "tableau":
        payload = _make_tableau_package(dashboard, dataset, frame, rendered)
        media_type, extension = "application/zip", "tableau.twbx"
    elif platform == "powerpoint":
        payload = _make_powerpoint_report(dashboard, dataset, frame, rendered)
        media_type, extension = "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"
    else:
        payload = _make_excel_workbook(dashboard, dataset, frame, rendered)
        media_type, extension = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return StreamingResponse(io.BytesIO(payload), media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{safe_name}_{extension}"', "Cache-Control": "no-store"})
