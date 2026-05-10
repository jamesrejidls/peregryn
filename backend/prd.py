"""
PRD Generator + Dev Task Generator + PDF Export.

PRD = one click on an insight produces a full Product Requirements Document.
Dev tasks = breakdown of that PRD into engineering tickets.
PDF export = downloadable PDF for sharing.
"""
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth import get_current_user
from .llm_client import generate_prd as llm_generate_prd, generate_tasks as llm_generate_tasks
from .database import Dataset, DevTask, FeedbackItem, Insight, PRD, User, get_db

router = APIRouter(prefix="/prd", tags=["prd"])


# ------------------------- response models -------------------------

class PRDResponse(BaseModel):
    id: int
    insight_id: int
    title: str
    problem_statement: str
    who_affected: str
    success_metrics: List[str]
    user_stories: List[str]
    acceptance_criteria: List[str]
    created_at: str


class DevTaskResponse(BaseModel):
    id: int
    prd_id: int
    title: str
    context: str
    acceptance_criteria: List[str]


# ------------------------- endpoints -------------------------

@router.post("/from-insight/{insight_id}", response_model=PRDResponse)
def create_prd_from_insight(
    insight_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    insight = db.query(Insight).filter(Insight.id == insight_id).first()
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    # Check ownership via dataset
    dataset = db.query(Dataset).filter(Dataset.id == insight.dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Insight not found")

    # Pull supporting quotes from cited feedback items.
    # Old insights (created before the citation parser fix) may have strings like "ID 1" stored;
    # parse defensively so re-running PRDs on legacy data works.
    raw_citations = insight.citations or []
    citation_ids: List[int] = []
    for raw in raw_citations:
        if isinstance(raw, int):
            citation_ids.append(raw)
        elif isinstance(raw, str):
            s = raw.strip()
            if s.upper().startswith("ID "):
                s = s[3:].strip()
            try:
                citation_ids.append(int(s))
            except (TypeError, ValueError):
                continue
    quotes: List[str] = []
    if citation_ids:
        items = db.query(FeedbackItem).filter(FeedbackItem.id.in_(citation_ids)).all()
        quotes = [it.content for it in items if it.content]

    insight_dict = {
        "title": insight.title,
        "description": insight.description,
        "affected_users": insight.affected_users,
        "emotional_tone": insight.emotional_tone,
        "recommendation": insight.recommendation,
    }
    try:
        result = llm_generate_prd(insight_dict, quotes)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e}")

    prd = PRD(
        insight_id=insight.id,
        title=str(result.get("title") or insight.title)[:500],
        problem_statement=str(result.get("problem_statement", "")),
        who_affected=str(result.get("who_affected", "")),
        success_metrics=[str(x) for x in (result.get("success_metrics") or [])],
        user_stories=[str(x) for x in (result.get("user_stories") or [])],
        acceptance_criteria=[str(x) for x in (result.get("acceptance_criteria") or [])],
    )
    db.add(prd)
    db.commit()
    db.refresh(prd)

    return _prd_to_response(prd)


@router.get("/{prd_id}", response_model=PRDResponse)
def get_prd(prd_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prd = _get_prd_owned(prd_id, current_user, db)
    return _prd_to_response(prd)


@router.get("/", response_model=List[PRDResponse])
def list_prds(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(PRD)
        .join(Insight, PRD.insight_id == Insight.id)
        .join(Dataset, Insight.dataset_id == Dataset.id)
        .filter(Dataset.user_id == current_user.id)
        .order_by(PRD.created_at.desc())
        .all()
    )
    return [_prd_to_response(p) for p in rows]


@router.delete("/{prd_id}")
def delete_prd(prd_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prd = _get_prd_owned(prd_id, current_user, db)
    db.delete(prd)
    db.commit()
    return {"ok": True}


# ---- Dev tasks ----

@router.post("/{prd_id}/tasks", response_model=List[DevTaskResponse])
def generate_dev_tasks(prd_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prd = _get_prd_owned(prd_id, current_user, db)

    prd_dict = {
        "title": prd.title,
        "problem_statement": prd.problem_statement,
        "who_affected": prd.who_affected,
        "success_metrics": prd.success_metrics or [],
        "user_stories": prd.user_stories or [],
        "acceptance_criteria": prd.acceptance_criteria or [],
    }
    try:
        result = llm_generate_tasks(prd_dict)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e}")

    # Replace any existing tasks (idempotent re-runs)
    db.query(DevTask).filter(DevTask.prd_id == prd.id).delete()
    db.flush()

    saved = []
    for t in result.get("tasks", []):
        task = DevTask(
            prd_id=prd.id,
            title=str(t.get("title", ""))[:500],
            context=str(t.get("context", "")),
            acceptance_criteria=[str(x) for x in (t.get("acceptance_criteria") or [])],
        )
        db.add(task)
        db.flush()
        saved.append(_task_to_response(task))
    db.commit()
    return saved


@router.get("/{prd_id}/tasks", response_model=List[DevTaskResponse])
def list_dev_tasks(prd_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prd = _get_prd_owned(prd_id, current_user, db)
    tasks = db.query(DevTask).filter(DevTask.prd_id == prd.id).all()
    return [_task_to_response(t) for t in tasks]


# ---- PDF export ----

@router.get("/{prd_id}/export.pdf")
def export_prd_pdf(prd_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prd = _get_prd_owned(prd_id, current_user, db)
    tasks = db.query(DevTask).filter(DevTask.prd_id == prd.id).all()

    pdf_bytes = _render_prd_pdf(prd, tasks)
    filename = f"PRD-{prd.id}-{_slug(prd.title)}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{prd_id}/export.md")
def export_prd_markdown(prd_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Markdown export — paste straight into Notion."""
    prd = _get_prd_owned(prd_id, current_user, db)
    tasks = db.query(DevTask).filter(DevTask.prd_id == prd.id).all()
    md = _render_prd_markdown(prd, tasks)
    filename = f"PRD-{prd.id}-{_slug(prd.title)}.md"
    return StreamingResponse(
        io.BytesIO(md.encode("utf-8")),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------- helpers -------------------------

def _get_prd_owned(prd_id: int, user: User, db: Session) -> PRD:
    prd = (
        db.query(PRD)
        .join(Insight, PRD.insight_id == Insight.id)
        .join(Dataset, Insight.dataset_id == Dataset.id)
        .filter(PRD.id == prd_id, Dataset.user_id == user.id)
        .first()
    )
    if not prd:
        raise HTTPException(status_code=404, detail="PRD not found")
    return prd


def _prd_to_response(prd: PRD) -> PRDResponse:
    return PRDResponse(
        id=prd.id,
        insight_id=prd.insight_id,
        title=prd.title or "",
        problem_statement=prd.problem_statement or "",
        who_affected=prd.who_affected or "",
        success_metrics=prd.success_metrics or [],
        user_stories=prd.user_stories or [],
        acceptance_criteria=prd.acceptance_criteria or [],
        created_at=prd.created_at.isoformat(),
    )


def _task_to_response(t: DevTask) -> DevTaskResponse:
    return DevTaskResponse(
        id=t.id,
        prd_id=t.prd_id,
        title=t.title or "",
        context=t.context or "",
        acceptance_criteria=t.acceptance_criteria or [],
    )


def _slug(s: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return "".join(c if c in keep else "-" for c in (s or "prd"))[:60].strip("-") or "prd"


def _render_prd_markdown(prd: PRD, tasks: List[DevTask]) -> str:
    lines = [f"# {prd.title}", "", "## Problem statement", prd.problem_statement or "", ""]
    lines += ["## Who is affected", prd.who_affected or "", ""]
    lines += ["## Success metrics"]
    for m in prd.success_metrics or []:
        lines.append(f"- {m}")
    lines += ["", "## User stories"]
    for s in prd.user_stories or []:
        lines.append(f"- {s}")
    lines += ["", "## Acceptance criteria"]
    for c in prd.acceptance_criteria or []:
        lines.append(f"- {c}")
    if tasks:
        lines += ["", "## Engineering tasks", ""]
        for i, t in enumerate(tasks, 1):
            lines.append(f"### {i}. {t.title}")
            lines.append("")
            lines.append(t.context or "")
            lines.append("")
            lines.append("**Acceptance criteria:**")
            for c in t.acceptance_criteria or []:
                lines.append(f"- {c}")
            lines.append("")
    return "\n".join(lines)


def _render_prd_pdf(prd: PRD, tasks: List[DevTask]) -> bytes:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, PageBreak,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        rightMargin=0.7 * inch, leftMargin=0.7 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title=prd.title or "PRD",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Title"], fontSize=22, leading=26,
        textColor=HexColor("#0f172a"), spaceAfter=12, alignment=TA_LEFT,
    )
    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontSize=14, leading=18,
        textColor=HexColor("#1e293b"), spaceBefore=14, spaceAfter=6,
    )
    h3 = ParagraphStyle(
        "H3", parent=styles["Heading3"], fontSize=12, leading=16,
        textColor=HexColor("#334155"), spaceBefore=10, spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontSize=10.5, leading=15,
        textColor=HexColor("#0f172a"),
    )
    bullet = ParagraphStyle(
        "Bullet", parent=body, leftIndent=12, spaceAfter=2,
    )

    story = [Paragraph(_escape(prd.title or "Product Requirements Document"), title_style)]
    story.append(Paragraph(f"Generated {prd.created_at.strftime('%Y-%m-%d %H:%M UTC')}", body))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Problem statement", h2))
    story.append(Paragraph(_escape(prd.problem_statement or "—"), body))

    story.append(Paragraph("Who is affected", h2))
    story.append(Paragraph(_escape(prd.who_affected or "—"), body))

    story.append(Paragraph("Success metrics", h2))
    story.append(_bullet_list(prd.success_metrics or [], bullet))

    story.append(Paragraph("User stories", h2))
    story.append(_bullet_list(prd.user_stories or [], bullet))

    story.append(Paragraph("Acceptance criteria", h2))
    story.append(_bullet_list(prd.acceptance_criteria or [], bullet))

    if tasks:
        story.append(PageBreak())
        story.append(Paragraph("Engineering tasks", h2))
        for i, t in enumerate(tasks, 1):
            story.append(Paragraph(f"{i}. {_escape(t.title)}", h3))
            if t.context:
                story.append(Paragraph(_escape(t.context), body))
            if t.acceptance_criteria:
                story.append(Paragraph("Acceptance criteria:", body))
                story.append(_bullet_list(t.acceptance_criteria, bullet))
            story.append(Spacer(1, 6))

    doc.build(story)
    return buffer.getvalue()


def _escape(s: str) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bullet_list(items, style):
    from reportlab.platypus import ListFlowable, ListItem, Paragraph
    if not items:
        return Paragraph("—", style)
    flow = [ListItem(Paragraph(_escape(str(x)), style), leftIndent=10) for x in items]
    return ListFlowable(flow, bulletType="bullet", start="•", leftIndent=14)
