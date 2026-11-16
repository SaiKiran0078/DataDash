from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, owned_dataset
from app.db.models import AnalysisReport, User
from app.schemas import AnalysisReportIn

router = APIRouter(prefix="/datasets", tags=["analysis reports"])


def present(report: AnalysisReport) -> dict:
    return {
        "id": report.id,
        "dataset_id": report.dataset_id,
        "title": report.title,
        "business_question": report.business_question,
        "audience": report.audience,
        "row_grain": report.row_grain,
        "executive_summary": report.executive_summary,
        "findings": report.findings or [],
        "recommendations": report.recommendations or [],
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
    }


@router.get("/{dataset_id}/reports")
def list_reports(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_dataset(db, user, dataset_id)
    rows = db.scalars(
        select(AnalysisReport)
        .where(AnalysisReport.owner_id == user.id, AnalysisReport.dataset_id == dataset_id)
        .order_by(AnalysisReport.updated_at.desc())
    ).all()
    return {"reports": [present(row) for row in rows]}


@router.post("/{dataset_id}/reports", status_code=201)
def create_report(dataset_id: int, body: AnalysisReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_dataset(db, user, dataset_id)
    report = AnalysisReport(
        owner_id=user.id,
        dataset_id=dataset_id,
        title=body.title.strip(),
        business_question=body.business_question,
        audience=body.audience,
        row_grain=body.row_grain,
        executive_summary=body.executive_summary,
        findings=body.findings,
        recommendations=body.recommendations,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return present(report)


@router.put("/{dataset_id}/reports/{report_id}")
def update_report(dataset_id: int, report_id: int, body: AnalysisReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_dataset(db, user, dataset_id)
    report = db.scalar(select(AnalysisReport).where(
        AnalysisReport.id == report_id,
        AnalysisReport.dataset_id == dataset_id,
        AnalysisReport.owner_id == user.id,
    ))
    if report is None:
        raise HTTPException(404, "Report not found")
    report.title = body.title.strip()
    report.business_question = body.business_question
    report.audience = body.audience
    report.row_grain = body.row_grain
    report.executive_summary = body.executive_summary
    report.findings = body.findings
    report.recommendations = body.recommendations
    db.commit()
    db.refresh(report)
    return present(report)


@router.delete("/{dataset_id}/reports/{report_id}", status_code=204)
def delete_report(dataset_id: int, report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_dataset(db, user, dataset_id)
    report = db.scalar(select(AnalysisReport).where(
        AnalysisReport.id == report_id,
        AnalysisReport.dataset_id == dataset_id,
        AnalysisReport.owner_id == user.id,
    ))
    if report is None:
        raise HTTPException(404, "Report not found")
    db.delete(report)
    db.commit()
