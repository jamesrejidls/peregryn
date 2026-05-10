"""
Natural Language Query — founder asks 'why are users churning?', the LLM answers
using only this dataset's feedback, with citations.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth import get_current_user
from .llm_client import answer_query
from .database import Dataset, FeedbackItem, User, get_db

router = APIRouter(prefix="/query", tags=["query"])

MAX_ITEMS_PER_QUERY = 200


class QueryRequest(BaseModel):
    dataset_id: int
    question: str


class CitationItem(BaseModel):
    id: int
    content: str
    user_label: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    key_points: List[str]
    citations: List[CitationItem]


@router.post("/ask", response_model=QueryResponse)
def ask(req: QueryRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question is empty")

    dataset = db.query(Dataset).filter(Dataset.id == req.dataset_id, Dataset.user_id == current_user.id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    items = db.query(FeedbackItem).filter(FeedbackItem.dataset_id == req.dataset_id).limit(MAX_ITEMS_PER_QUERY).all()
    if not items:
        raise HTTPException(status_code=400, detail="Dataset has no feedback items")

    payload = [{"id": it.id, "content": it.content, "user_label": it.user_label} for it in items]

    try:
        result = answer_query(payload, req.question.strip())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {e}")

    lookup = {it.id: it for it in items}
    citations = []
    for cid in result.get("citations") or []:
        # Handle int, "19", or "ID 19" defensively.
        cid_int = None
        if isinstance(cid, int):
            cid_int = cid
        elif isinstance(cid, str):
            s = cid.strip()
            if s.upper().startswith("ID "):
                s = s[3:].strip()
            try:
                cid_int = int(s)
            except (TypeError, ValueError):
                continue
        if cid_int is not None and cid_int in lookup:
            it = lookup[cid_int]
            citations.append(CitationItem(id=it.id, content=it.content, user_label=it.user_label))

    return QueryResponse(
        answer=str(result.get("answer", "")),
        key_points=[str(k) for k in (result.get("key_points") or [])],
        citations=citations,
    )
