from sqlalchemy.orm import Session

from app.embeddings import generate_embedding
from app.models import Business, Embedding, Report, ReportSection


def generate_embeddings_for_report(db: Session, business: Business, report: Report) -> None:
    """Populates embeddings for RAG/chat (endpoints.md's internal
    /internal/generate-embeddings) -- one chunk per report_section, plus one
    for the combined executive summary + forecast."""
    summary_text = f"Executive Summary: {report.executive_summary}\nForecast: {report.forecast}"
    db.add(
        Embedding(
            business_id=business.id,
            source_type="report_summary",
            source_id=report.id,
            chunk_text=summary_text,
            vector=generate_embedding(summary_text),
        )
    )

    sections = db.query(ReportSection).filter(ReportSection.report_id == report.id).all()
    for section in sections:
        db.add(
            Embedding(
                business_id=business.id,
                source_type="report_section",
                source_id=section.id,
                chunk_text=section.content,
                vector=generate_embedding(section.content),
            )
        )


def delete_embeddings_for_report(db: Session, report_id) -> None:
    """embeddings has no FK to reports/report_sections (source_id is a
    plain UUID, polymorphic by source_type) -- deleting a report wouldn't
    fail without this, but the embeddings would be orphaned and keep
    feeding stale content into chat retrieval."""
    section_ids = [row.id for row in db.query(ReportSection.id).filter(ReportSection.report_id == report_id)]
    source_ids = [report_id, *section_ids]
    db.query(Embedding).filter(Embedding.source_id.in_(source_ids)).delete(synchronize_session=False)
