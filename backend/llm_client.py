"""
LLM client for the application. Currently uses Google Gemini's free API.
All prompts are centralized here so they can be tuned in one place.
The quality of these prompts determines the quality of the product.

Get a free API key from: https://aistudio.google.com/apikey
"""
import os
import json
import re
from typing import List, Dict, Any
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

_client = None


def get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. "
                "Get a free key from https://aistudio.google.com/apikey and put it in your .env file."
            )
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of an LLM response, even if wrapped in prose or fences."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        raise ValueError(f"No JSON found in response: {text[:200]}")
    stack = []
    for i in range(start, len(text)):
        ch = text[i]
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
                if not stack:
                    return json.loads(text[start : i + 1])
    raise ValueError("Unbalanced JSON in response")


def _call_llm(system: str, user: str, max_tokens: int = 4096) -> str:
    client = get_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            temperature=0.4,
        ),
    )
    return (response.text or "").strip()


# ---------------------------------------------------------------------------
# 1. INSIGHT EXTRACTION — top 5 pain points + sentiment + trending topics
# ---------------------------------------------------------------------------

INSIGHT_SYSTEM = """You are a senior product analyst. You read raw customer feedback and surface what matters.

You ALWAYS:
- Ground every claim in actual feedback items (cite their IDs).
- Rank pain points by how many customers raise them, weighted by emotional intensity.
- Distinguish user types when the data supports it (e.g., new users vs power users).
- Recommend concrete actions, not platitudes.
- Return STRICT JSON, no prose, no markdown fences."""

INSIGHT_USER_TEMPLATE = """Analyze the customer feedback below. Each item has an ID and content.

Return a JSON object with this exact shape:
{{
  "pain_points": [
    {{
      "rank": 1,
      "title": "Short title (under 8 words)",
      "description": "2-3 sentence explanation of the pain point",
      "frequency": <integer count of items that mention this>,
      "affected_users": "Who is affected (e.g., 'Mobile users', 'Enterprise admins', 'New signups')",
      "emotional_tone": "One or two words (e.g., 'Frustrated', 'Confused', 'Disappointed')",
      "recommendation": "1-2 sentence concrete action the product team should take",
      "citations": [<feedback IDs that support this>]
    }},
    ... (up to 5 total, ranked by importance)
  ],
  "sentiment": {{
    "positive": <0-100 percent>,
    "neutral": <0-100 percent>,
    "negative": <0-100 percent>
  }},
  "trending_topics": ["topic 1", "topic 2", "topic 3", "topic 4", "topic 5"]
}}

Rules:
- "positive" + "neutral" + "negative" must sum to 100.
- Use only IDs that actually appear in the feedback below.
- Citations must be raw integers like 1, 9, 19 — NEVER strings like "ID 1" or "1".
- If there are fewer than 5 distinct pain points, return fewer.
- Trending topics are short noun phrases (2-4 words), most-mentioned first.

FEEDBACK:
{feedback_block}

Return ONLY the JSON object."""


def extract_insights(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    items: [{"id": int, "content": str, "user_label": str|None}, ...]
    Returns a dict with pain_points, sentiment, trending_topics.
    """
    if not items:
        return {"pain_points": [], "sentiment": {"positive": 0, "neutral": 100, "negative": 0}, "trending_topics": []}

    lines = []
    for it in items:
        content = (it["content"] or "").strip().replace("\n", " ")
        if len(content) > 800:
            content = content[:800] + "..."
        label = f" [{it['user_label']}]" if it.get("user_label") else ""
        lines.append(f"ID {it['id']}{label}: {content}")
    feedback_block = "\n".join(lines)

    user_msg = INSIGHT_USER_TEMPLATE.format(feedback_block=feedback_block)
    raw = _call_llm(INSIGHT_SYSTEM, user_msg, max_tokens=4096)
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# 2. NATURAL LANGUAGE QUERY — answer founder's question with citations
# ---------------------------------------------------------------------------

QUERY_SYSTEM = """You answer questions about customer feedback using ONLY the feedback provided.

Rules:
- Never invent quotes or users.
- Always cite the IDs of the feedback items that support your answer.
- If the feedback doesn't contain the answer, say so honestly.
- Return STRICT JSON, no prose outside the JSON."""

QUERY_USER_TEMPLATE = """Customer feedback:
{feedback_block}

Question: {question}

Return JSON of this shape:
{{
  "answer": "Your answer in 2-5 sentences, grounded in the feedback.",
  "key_points": ["point 1", "point 2", "point 3"],
  "citations": [<list of feedback IDs supporting your answer>]
}}

If the feedback doesn't address the question, set answer accordingly and citations to [].
Citations must be raw integers like 1, 9, 19 — NEVER strings like "ID 1" or "1"."""


def answer_query(items: List[Dict[str, Any]], question: str) -> Dict[str, Any]:
    if not items:
        return {"answer": "There is no feedback in this dataset to analyze.", "key_points": [], "citations": []}

    lines = []
    for it in items:
        content = (it["content"] or "").strip().replace("\n", " ")
        if len(content) > 800:
            content = content[:800] + "..."
        label = f" [{it['user_label']}]" if it.get("user_label") else ""
        lines.append(f"ID {it['id']}{label}: {content}")
    feedback_block = "\n".join(lines)

    user_msg = QUERY_USER_TEMPLATE.format(feedback_block=feedback_block, question=question)
    raw = _call_llm(QUERY_SYSTEM, user_msg, max_tokens=2048)
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# 3. PRD GENERATION — turn an insight into a real PRD
# ---------------------------------------------------------------------------

PRD_SYSTEM = """You are a senior product manager writing PRDs that engineers actually want to read.
You write tight problem statements, measurable success metrics, and user stories that pass the INVEST test.
Return STRICT JSON, no prose."""

PRD_USER_TEMPLATE = """Write a Product Requirements Document for this customer pain point.

INSIGHT:
Title: {title}
Description: {description}
Affected users: {affected_users}
Emotional tone: {tone}
Recommendation: {recommendation}

SUPPORTING USER QUOTES:
{quotes_block}

Return JSON of this exact shape:
{{
  "title": "Feature title",
  "problem_statement": "1-2 paragraphs describing the problem and why it matters now",
  "who_affected": "1-2 sentences describing the user segments and how many are affected",
  "success_metrics": [
    "Metric 1 (concrete and measurable, e.g., 'Reduce support tickets about X by 40% within 60 days')",
    "Metric 2",
    "Metric 3"
  ],
  "user_stories": [
    "As a <user type>, I want <capability> so that <benefit>",
    "...3-6 stories total"
  ],
  "acceptance_criteria": [
    "Concrete, testable criteria",
    "...4-8 criteria total"
  ]
}}"""


def generate_prd(insight: Dict[str, Any], quotes: List[str]) -> Dict[str, Any]:
    quotes_block = "\n".join(f'- "{q}"' for q in quotes[:10]) if quotes else "(no specific quotes)"
    user_msg = PRD_USER_TEMPLATE.format(
        title=insight.get("title", ""),
        description=insight.get("description", ""),
        affected_users=insight.get("affected_users", ""),
        tone=insight.get("emotional_tone", ""),
        recommendation=insight.get("recommendation", ""),
        quotes_block=quotes_block,
    )
    raw = _call_llm(PRD_SYSTEM, user_msg, max_tokens=3072)
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# 4. DEV TASK BREAKDOWN — turn a PRD into engineering tickets
# ---------------------------------------------------------------------------

TASKS_SYSTEM = """You are a tech lead breaking work into engineering tickets.
Each ticket should be small enough to ship in 1-3 days, with clear acceptance criteria.
Return STRICT JSON."""

TASKS_USER_TEMPLATE = """Break the PRD below into engineering tasks suitable for Jira/Linear.

PRD:
Title: {title}
Problem: {problem}
Who: {who}
Success metrics: {metrics}
User stories: {stories}
Acceptance criteria: {ac}

Return JSON of this shape:
{{
  "tasks": [
    {{
      "title": "Concrete ticket title (e.g., 'Add rate-limiting to /upload endpoint')",
      "context": "2-3 sentences. Why this matters + which user need it serves. Reference the PRD.",
      "acceptance_criteria": ["criterion 1", "criterion 2", "criterion 3"]
    }},
    ... 5-10 tasks total, ordered roughly by dependency
  ]
}}"""


def generate_tasks(prd: Dict[str, Any]) -> Dict[str, Any]:
    user_msg = TASKS_USER_TEMPLATE.format(
        title=prd.get("title", ""),
        problem=prd.get("problem_statement", ""),
        who=prd.get("who_affected", ""),
        metrics="; ".join(prd.get("success_metrics", []) or []),
        stories="; ".join(prd.get("user_stories", []) or []),
        ac="; ".join(prd.get("acceptance_criteria", []) or []),
    )
    raw = _call_llm(TASKS_SYSTEM, user_msg, max_tokens=3072)
    return _extract_json(raw)
