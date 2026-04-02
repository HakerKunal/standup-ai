import os
import json
from pathlib import Path
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, Response
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent

# load_dotenv only for local dev — Vercel injects env vars directly
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
except Exception:
    pass

app = FastAPI(title="AI Standup Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL = "llama-3.3-70b-versatile"

def get_client():
    """Lazy client init so missing API key crashes at request time, not on startup."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is not set in environment variables.")
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

FORMAT_INSTRUCTIONS = {
    "professional": """Generate a detailed, professional standup update in paragraph form.

Structure:
1. What I worked on today (specific tasks, tickets, PRs)
2. Any blockers or issues encountered
3. What I plan to work on tomorrow

Rules:
- Write in first person, past tense for today, future for tomorrow
- Expand ticket/PR numbers into meaningful descriptions when possible
- Mention teammates by name if referenced
- 3-5 sentences per section, natural not robotic""",

    "short": """Generate a concise bullet-point standup.

Format:
• [Task completed/worked on]
• [Another task]
• Blockers: [if any, else skip this line]
• Next: [tomorrow's plan]

Rules:
- Max 6-8 bullets total
- Each bullet is 1 short line
- Lead with the most important items""",

    "slack": """Generate a Slack-formatted standup update.

Format:
*Today's Update*
• [task 1]
• [task 2]

*Blockers* (only include if there are actual blockers)
• [blocker]

*Next*
• [plan]

Rules:
- Use Slack bold syntax (*text*)
- Keep each bullet crisp and 1 line
- Action-oriented language""",

    "daily_summary": """Generate an end-of-day summary for a manager or team lead.

Format:
**Summary:** 1-2 sentence overview
**Completed:** What was finished
**In Progress:** What is ongoing
**Blockers:** Issues needing attention (omit if none)
**Next Steps:** Plan for tomorrow

Rules:
- Use **bold** markdown headers
- Be concise but complete
- Highlight blockers prominently if any""",

    "weekly": """Generate a weekly summary from these notes.

Format:
**This Week:**
- [grouped work items]

**Completed:**
- [finished items]

**In Progress:**
- [ongoing items]

**Blockers:**
- [issues] (omit section if none)

**Next Week:**
- [upcoming priorities]

Rules:
- Group related tickets/tasks together
- Show progress and momentum""",

    "sprint": """Generate a sprint summary.

Format:
## Sprint Summary

**Completed:**
- [ticket]: [brief description] ✅

**In Progress:**
- [ticket]: [brief description] 🔄

**Blocked:**
- [ticket]: [reason] ⚠️ (omit if none)

**Key Highlights:**
[2-3 sentences on achievements or notable work]

**Next Sprint:**
[Brief outlook]

Rules:
- Use emoji status indicators
- Group by status, lead with wins""",
}

SYSTEM_PROMPT = """You are an expert technical writer who transforms rough developer notes into polished standup updates.

You understand:
- Jira/Linear ticket formats (e.g., PDEV-21730, ENG-123)
- Developer terminology (PR, QA, deploy, hotfix, refactor, etc.)
- How to infer context from short notes
- When something is a blocker vs. just an update

Always:
- Keep the developer's voice — natural, not corporate-speak
- Expand ticket numbers into meaningful descriptions when possible
- Identify blockers and call them out clearly
- Convert casual teammate references (e.g., "dan") to proper names
- Fix grammar and improve clarity while preserving meaning

Output only the standup text — no preamble, no explanation."""


class StandupRequest(BaseModel):
    notes: str
    format: str = "professional"
    extra_context: str = ""


def build_user_prompt(notes: str, format_type: str, extra_context: str) -> str:
    format_instruction = FORMAT_INSTRUCTIONS.get(
        format_type, FORMAT_INSTRUCTIONS["professional"]
    )
    extra = f"\n\nAdditional context: {extra_context}" if extra_context.strip() else ""
    return f"""Transform these rough notes into a standup update.

{format_instruction}

Raw notes:
{notes}{extra}

Generate the standup now:"""


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL}


@app.get("/formats")
async def get_formats():
    return {
        "formats": [
            {"id": "professional",  "label": "Professional",  "icon": "📝"},
            {"id": "short",         "label": "Quick Bullets", "icon": "⚡"},
            {"id": "slack",         "label": "Slack",         "icon": "💬"},
            {"id": "daily_summary", "label": "Daily Summary", "icon": "📊"},
            {"id": "weekly",        "label": "Weekly",        "icon": "📅"},
            {"id": "sprint",        "label": "Sprint",        "icon": "🚀"},
        ]
    }


@app.post("/generate")
async def generate_standup(request: StandupRequest):
    if not request.notes.strip():
        raise HTTPException(status_code=400, detail="Notes cannot be empty")
    if request.format not in FORMAT_INSTRUCTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown format: {request.format}")

    user_prompt = build_user_prompt(request.notes, request.format, request.extra_context)

    groq = get_client()

    def stream_generator():
        try:
            stream = groq.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=1024,
                temperature=0.7,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            error_msg = str(e)
            if "auth" in error_msg.lower() or "401" in error_msg:
                msg = "Invalid Groq API key."
            elif "rate" in error_msg.lower() or "429" in error_msg:
                msg = "Rate limit reached. Please wait and try again."
            else:
                msg = f"Error: {error_msg}"
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Serve frontend files ──────────────────────────────────
@app.get("/")
async def index():
    return HTMLResponse((ROOT / "index.html").read_text())

@app.get("/style.css")
async def css():
    return Response((ROOT / "style.css").read_text(), media_type="text/css")

@app.get("/app.js")
async def js():
    return Response((ROOT / "app.js").read_text(), media_type="application/javascript")
