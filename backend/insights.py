"""
AI Insight Engine — runs the LLM over a dataset to produce ranked pain points,
sentiment, trending topics, all with citations back to specific feedback items.
"""
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth import get_current_user
from .llm_client import extract_insights
from .database import Dataset, FeedbackItem, Insight, User, get_db

router = APIRouter(prefix="/insights", tags=["insights"])


# Cap how many feedback items we send to the LLM in one go to keep latency + cost reasonable.
# For larger datasets, you'd batch + merge — fine for an MVP at this size.
MAX_ITEMS_PER_RUN = 200


class CitationItem(BaseModel):
    id: int
    content: str
    user_label: Optional[str] = None


class PainPointResponse(BaseModel):
    id: int
    rank: int
    title: str
    description: str
    frequency: int
    affected_users: str
    emotional_tone: str
    recommendation: str
    citations: List[CitationItem]


class InsightReportResponse(BaseModel):
    dataset_id: int
    dataset_name: str
    total_feedback: int
    analyzed_count: int
    pain_points: List[PainPointResponse]
    sentiment: Dict[str, int]
    trending_topics: List[str]


def _build_citation_lookup(items: List[FeedbackItem]) -> Dict[int, FeedbackItem]:
    return {it.id: it for it in items}


def _parse_citation_ids(raw_ids) -> List[int]:
    """
    Defensively parse citation IDs from the LLM response into a clean list of ints.
    The LLM sometimes returns "ID 19" (with the prefix) or "19" (string) instead of 19.
    SQLite was forgiving about this; Postgres is not. So we normalize at the boundary.
    """
    if not raw_ids:
        return []
    out = []
    for raw in raw_ids:
        if isinstance(raw, int):
            out.append(raw)
            continue
        if isinstance(raw, str):
            # Strip "ID " prefix if present, then any whitespace, then convert.
            s = raw.strip()
            if s.upper().startswith("ID "):
                s = s[3:].strip()
            try:
                out.append(int(s))
            except (TypeError, ValueError):
                continue
    return out


def _hydrate_citations(citation_ids: List[int], lookup: Dict[int, FeedbackItem]) -> List[CitationItem]:
    out = []
    for cid in citation_ids or []:
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            continue
        item = lookup.get(cid_int)
        if item:
            out.append(CitationItem(id=item.id, content=item.content, user_label=item.user_label))
    return out


@router.post("/datasets/{dataset_id}/run", response_model=InsightReportResponse)
def run_analysis(dataset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run the LLM over the dataset and store the resulting insights."""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    items = db.query(FeedbackItem).filter(FeedbackItem.dataset_id == dataset_id).limit(MAX_ITEMS_PER_RUN).all()
    if not items:
        raise HTTPException(status_code=400, detail="Dataset has no feedback items")

    payload = [{"id": it.id, "content": it.content, "user_label": it.user_label} for it in items]

    try:
        result = extract_insights(payload)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e}")

    # Wipe any existing insights for this dataset (idempotent re-runs)
    db.query(Insight).filter(Insight.dataset_id == dataset_id).delete()
    db.flush()

    sentiment = result.get("sentiment") or {"positive": 0, "neutral": 100, "negative": 0}
    trending = result.get("trending_topics") or []

    lookup = _build_citation_lookup(items)
    saved_pain_points: List[PainPointResponse] = []

    for pp in result.get("pain_points", [])[:5]:
        ins = Insight(
            dataset_id=dataset_id,
            rank=int(pp.get("rank") or len(saved_pain_points) + 1),
            title=str(pp.get("title", "")).strip()[:500],
            description=str(pp.get("description", "")).strip(),
            frequency=int(pp.get("frequency") or 0),
            affected_users=str(pp.get("affected_users", "")).strip()[:500],
            emotional_tone=str(pp.get("emotional_tone", "")).strip()[:255],
            recommendation=str(pp.get("recommendation", "")).strip(),
            citations=_parse_citation_ids(pp.get("citations")),
            sentiment_summary=sentiment,
            trending_topics=trending,
        )
        db.add(ins)
        db.flush()
        saved_pain_points.append(PainPointResponse(
            id=ins.id,
            rank=ins.rank,
            title=ins.title,
            description=ins.description,
            frequency=ins.frequency,
            affected_users=ins.affected_users,
            emotional_tone=ins.emotional_tone,
            recommendation=ins.recommendation,
            citations=_hydrate_citations(ins.citations, lookup),
        ))

    db.commit()

    return InsightReportResponse(
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        total_feedback=db.query(FeedbackItem).filter(FeedbackItem.dataset_id == dataset_id).count(),
        analyzed_count=len(items),
        pain_points=saved_pain_points,
        sentiment=sentiment,
        trending_topics=trending,
    )


@router.get("/datasets/{dataset_id}", response_model=InsightReportResponse)
def get_report(dataset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch the most recent stored insight report for a dataset."""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    insights = db.query(Insight).filter(Insight.dataset_id == dataset_id).order_by(Insight.rank.asc()).all()
    if not insights:
        raise HTTPException(status_code=404, detail="No analysis yet — run /insights/datasets/{id}/run first")

    items = db.query(FeedbackItem).filter(FeedbackItem.dataset_id == dataset_id).all()
    lookup = _build_citation_lookup(items)

    sentiment = insights[0].sentiment_summary or {"positive": 0, "neutral": 100, "negative": 0}
    trending = insights[0].trending_topics or []

    pain_points = [
        PainPointResponse(
            id=ins.id,
            rank=ins.rank,
            title=ins.title,
            description=ins.description,
            frequency=ins.frequency,
            affected_users=ins.affected_users,
            emotional_tone=ins.emotional_tone,
            recommendation=ins.recommendation,
            citations=_hydrate_citations(ins.citations or [], lookup),
        )
        for ins in insights
    ]

    return InsightReportResponse(
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        total_feedback=len(items),
        analyzed_count=min(len(items), MAX_ITEMS_PER_RUN),
        pain_points=pain_points,
        sentiment=sentiment,
        trending_topics=trending,
    )
