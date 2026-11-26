"""Ready-made agents: an agent definition plus the skills and knowledge it relies on.

Installing a preset creates (or refreshes) its skills and knowledge documents by name, then
creates the agent if it doesn't exist yet. Everything stays editable on the Agents page.

    python -m app.presets data_doctor        # a Data Doctor agent
    python -m app.presets data_health_scan   # add the full data health scan to it
    python -m app.presets designer           # a Designer agent (uses backend/brand if present)
    python -m app.presets lead_finder        # a Lead Finder (needs a Brave Search key)
    python -m app.presets icp_finder         # an ICP Finder: client brief -> target companies

The Reader-First team (DP's moments-based messaging; fetch_page and the client library):

    python -m app.presets reader_researcher  # client + persona -> a Reader Profile
    python -m app.presets proof_librarian    # client material -> a tagged Proof Bank
    python -m app.presets moment_scout       # target accounts -> verified moment cards
    python -m app.presets moment_writer      # a moment -> LinkedIn, emails, exec brief, video

An "add-on" preset (`addon=True`) never replaces anything: it adds its skills and its task
template to an existing agent and leaves the rest of the agent as it is.

To add your own, write a `Preset` below and list it in PRESETS.
"""

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlmodel import select

from app import client_library
from app.agents import registry
from app.db import AgentDef, KnowledgeDoc, Skill, audit, init_db, session
from app.events.schema import TaskTemplate, Zone, utcnow
from app.settings_store import get_store
from app.workflows.data_health.config import ScanConfig

TEXT = Path(__file__).parent / "preset_text"


def _text(name: str) -> str:
    return (TEXT / f"{name}.md").read_text().strip()


@dataclass
class Preset:
    agent: dict[str, Any]
    skills: list[dict[str, str]] = field(default_factory=list)  # name, description, body
    docs: list[dict[str, str]] = field(default_factory=list)  # title, content
    # knowledge documents worked out at install time (e.g. from the brand folder)
    docs_from: Callable[[], list[dict[str, str]]] | None = None
    workflow: str = ""  # a code-defined workflow (app/workflows) the agent runs
    addon: bool = False  # add skills + templates to the existing agent; replace nothing
    # add-on extras: tools appended, instructions only if the agent has none, a step floor
    tools: list[str] = field(default_factory=list)
    min_steps: int = 0
    # knowledge documents (by title) to take off the agent; they stay in the library
    detach_docs: list[str] = field(default_factory=list)


DATA_DOCTOR = Preset(
    agent={
        "id": "data_doctor",
        "name": "Data Doctor",
        "title": "Keeps the lead database clean",
        "color": "#2a9d8f",
        "character": "the-data-doctor",
        "home_zone": Zone.DATABASE,
        "model_tier": "standard",
        "instructions": _text("data_doctor"),
        "max_steps": 20,
    },
    tools=["rest_get_leads", "rest_update_leads", "rest_merge_leads", "recent_activities",
           "lead_engagement", "activity_summary", "kpi_history"],
)

DH_SKILLS = Path(__file__).parent / "workflows" / "data_health" / "skills"

DATA_HEALTH_SCAN = Preset(
    agent={
        "id": "data_doctor",
        "templates": [TaskTemplate(
            title="Full data health scan",
            description="Copy every lead and 18 months of engagement into the hub, score each "
                        "lead on the seven data health dimensions and report database-wide "
                        "KPIs. Resumes where it stopped if interrupted.",
            params={"workflow": "data_health_scan",
                    **ScanConfig().model_dump(mode="json", exclude={"max_lead_id"})},
        )],
    },
    addon=True,
    skills=[
        {"name": "Data health check (7 dimensions)",
         "description": "How the data health scan scores uniqueness, completeness, "
                        "normalization, accuracy, contactability, recency and engagement, and "
                        "how to act on the results.",
         "body": (DH_SKILLS / "data_health_check.md").read_text()},
        {"name": "Email verification (ZeroBounce)",
         "description": "Lets the data health scan verify email deliverability with "
                        "ZeroBounce (paid, cached). Needs the API key in Settings.",
         "body": (DH_SKILLS / "zerobounce.md").read_text()},
        {"name": "Phone verification (Twilio Lookup)",
         "description": "Lets the data health scan validate phone numbers with Twilio Lookup "
                        "v2. Needs the Twilio credentials in Settings.",
         "body": (DH_SKILLS / "twilio.md").read_text()},
    ],
)

def _designer_docs() -> list[dict[str, str]]:
    """Whatever the brand folder holds (backend/brand; see its README) as knowledge."""
    from app import design

    name = design.brand().get("name", "Brand")
    docs = []
    for file, title in (("brand_guidelines.md", "Brand Guidelines"),
                        ("design_system.md", "Design System")):
        if text := design._read(file):
            docs.append({"title": f"{name} {title}", "content": text})
    if design.images():
        docs.append({"title": f"{name} Approved Images", "content": design.images_markdown()})
    return docs


DESIGNER = Preset(
    agent={
        "id": "designer",
        "name": "Designer",
        "title": "Landing pages, forms and emails",
        "color": "#e9c46a",
        "character": "the-designer",
        "home_zone": Zone.DESIGN_STUDIO,
        "model_tier": "strong",
        "instructions": _text("designer"),
        "max_steps": 30,
        "templates": [TaskTemplate(
            title="Event landing page, registration form and invitation email",
            description="Create the event's landing page with a registration form, create the "
                        "form in Marketo, and write the invitation email. Attach the event "
                        "brief (date, venue, agenda, who's invited, registration fields).",
            params={"deliverables": ["landing_page", "form", "email"]},
        )],
    },
    docs_from=_designer_docs,
    tools=["brand_images", "save_design", "list_segmentations", "publish_email",
           "publish_landing_page",
           "asset_get_folder", "asset_get_folder_by_name", "asset_get_folder_content",
           "asset_get_email_by_id", "asset_get_landing_page_by_id",
           "browse_folders", "get_folder_by_name", "get_form_field_metadata", "browse_forms",
           "create_form", "add_field_to_form", "create_snippet", "update_snippet_content"],
    skills=[
        {"name": "Landing page with a Marketo form",
         "description": "Build an event or offer landing page with {{marketo_form}}, save the "
                        "form spec, and create the form in Marketo.",
         "body": _text("designer_landing_page")},
        {"name": "Invitation email",
         "description": "Write and build a 600px Marketo email with subject, preheader, "
                        "editable sections, tokens and the required footer.",
         "body": _text("designer_email")},
        {"name": "Working from feedback",
         "description": "How to handle a feedback round: change what was asked, save new "
                        "versions, summarise the changes.",
         "body": _text("designer_feedback")},
    ],
)

LEAD_FINDER = Preset(
    agent={
        "id": "lead_finder",
        "name": "Lead Finder",
        "title": "Researches new prospects on the web",
        "color": "#e76f51",
        "character": "the-data-doctor",
        "home_zone": Zone.CAMPAIGNS,
        "model_tier": "standard",
        "instructions": _text("lead_finder"),
        "max_steps": 30,
        "templates": [TaskTemplate(
            title="Find prospects",
            description="Find 10 prospects that fit this profile: [industry, company size, "
                        "region, job titles]. Rank them and say why each fits.",
        )],
    },
    tools=["web_search", "rest_get_leads"],
)

ICP_FINDER = Preset(
    agent={
        "id": "icp_finder",
        "name": "ICP Finder",
        "title": "Turns a client brief into a ranked list of target companies",
        "color": "#8e6bbf",
        "character": "the-data-doctor",
        "home_zone": Zone.CAMPAIGNS,
        "model_tier": "standard",
        "instructions": _text("icp_finder"),
        "max_steps": 40,
        "templates": [TaskTemplate(
            title="Find target companies for a client",
            description=(
                "Client: VAIO (example; replace with your client)\n"
                "What they sell: premium lightweight, durable business laptops\n"
                "Regions: Singapore, Malaysia, Indonesia, Thailand, Philippines, Vietnam\n"
                "A worthwhile deal: 20+ units; bulk orders are best, small B2B orders still count\n"
                "Exclude: consumers, companies under 10 staff, heavy BYOD companies\n"
                "Ideas to start from (correct them): Japanese-owned regional offices, "
                "mobile-heavy professional firms, engineering and design teams\n"
                "How many: 20"),
        )],
    },
    tools=["web_search", "rest_get_leads"],
)

# --- Reader-First agents: research a client's buyers, spot moments, write for them ----------

READER_FIRST_DOCS = [
    {"title": "Reader-First Framework", "content": _text("reader_first_framework")},
    {"title": "B2B Moments Library", "content": _text("moments_library")},
]
LENS_SKILLS = [
    {"name": "lens_horizon",
     "description": "Lens 1: the buyer's existing beliefs, past burns and the competitor "
                    "clichés to ban (reviews, competitor homepages).",
     "body": _text("lens_horizon")},
    {"name": "lens_moment",
     "description": "Lens 2: the triggers that make this persona act, the buying stage and "
                    "their reading posture (case studies, forums).",
     "body": _text("lens_moment")},
    {"name": "lens_tribe",
     "description": "Lens 3: the tribe's insider terms, the KPIs they're judged on and their "
                    "hidden career risk (job descriptions).",
     "body": _text("lens_tribe")},
    {"name": "lens_gap",
     "description": "Lens 4: the insight to reveal and what to hold back so a call feels "
                    "natural (the client's deck and proof).",
     "body": _text("lens_gap")},
]
FORMAT_SKILLS = [
    {"name": "format_linkedin",
     "description": "LinkedIn post or 6-8 slide carousel built from a moment hook and proof.",
     "body": _text("format_linkedin")},
    {"name": "format_email_3",
     "description": "3-email outreach sequence: the moment, the proof, the gap.",
     "body": _text("format_email_3")},
    {"name": "format_exec_brief",
     "description": "One-page executive briefing that arms the champion (Internal Sell).",
     "body": _text("format_exec_brief")},
    {"name": "format_video_script",
     "description": "30-60 second video script with timings and two alternative hooks.",
     "body": _text("format_video_script")},
]

READER_RESEARCHER = Preset(
    agent={
        "id": "reader_researcher",
        "name": "Reader Researcher",
        "title": "Researches how a client's buyers think (Reader-First)",
        "color": "#457b9d",
        "character": "the-private-investigator",
        "home_zone": Zone.CAMPAIGNS,
        "model_tier": "standard",
        "instructions": _text("reader_researcher"),
        "max_steps": 50,  # the hub's ceiling
        "templates": [TaskTemplate(
            title="Reader Profile for a client persona",
            description=(
                "Client: VAIO (example; replace with your client)\n"
                "What they sell: premium lightweight, durable business laptops\n"
                "Persona: IT Director / Head of IT at mid-size companies\n"
                "Regions: Singapore and Malaysia\n"
                "Competitors (correct them): Lenovo ThinkPad, Dell Latitude, HP EliteBook\n"
                "Attach the client's deck if you have it."),
        )],
    },
    docs=READER_FIRST_DOCS,
    skills=LENS_SKILLS,
    tools=["web_search", "fetch_page", "find_client_docs", "save_client_doc"],
)

PROOF_LIBRARIAN = Preset(
    agent={
        "id": "proof_librarian",
        "name": "Proof Librarian",
        "title": "Keeps each client's tagged proof bank",
        "color": "#6a994e",
        "character": "the-auditor",
        "home_zone": Zone.DATABASE,
        "model_tier": "standard",
        "instructions": _text("proof_librarian"),
        "max_steps": 40,
        "templates": [TaskTemplate(
            title="Build or update a client's proof bank",
            description=(
                "Client: VAIO (example; replace with your client)\n"
                "Website: https://us.vaio.com (replace with the client's regional site)\n"
                "Attach: case studies, decks, spec sheets, award or certification lists.\n"
                "Focus: proof for IT Directors and Finance in SEA"),
        )],
    },
    docs=READER_FIRST_DOCS,
    tools=["fetch_page", "web_search", "find_client_docs", "save_client_doc"],
)

MOMENT_SCOUT = Preset(
    agent={
        "id": "moment_scout",
        "name": "Moment Scout",
        "title": "Spots fresh buyer moments across target accounts",
        "color": "#f4a261",
        "character": "the-qualifier",
        "home_zone": Zone.CAMPAIGNS,
        "model_tier": "standard",
        "instructions": _text("moment_scout"),
        "max_steps": 50,
        "templates": [TaskTemplate(
            title="Scan target accounts for moments",
            description=(
                "Client: VAIO (example; replace with your client)\n"
                "Personas: IT Director, Finance Director\n"
                "Accounts (paste a list or attach the ICP Finder CSV):\n"
                "- Company A, website\n- Company B, website\n"
                "Also scan: new regulations, budget cycles and events in Singapore/Malaysia\n"
                "Look back: past month\n"
                "Hand strong moments to the Moment Writer: yes / no"),
        )],
    },
    docs=READER_FIRST_DOCS,
    tools=["web_search", "fetch_page", "find_client_docs", "hand_off"],
)

MOMENT_WRITER = Preset(
    agent={
        "id": "moment_writer",
        "name": "Moment Writer",
        "title": "Writes reader-first content for a buyer moment",
        "color": "#d1495b",
        "character": "the-campaigner",
        "home_zone": Zone.DESIGN_STUDIO,
        "model_tier": "standard",
        "instructions": _text("moment_writer"),
        "max_steps": 40,
        "templates": [TaskTemplate(
            title="Write content for a moment",
            description=(
                "Client: VAIO (example; replace with your client)\n"
                "Persona: IT Director\n"
                "Moment: <what happened, with the link and date>\n"
                "Account (optional): <company>\n"
                "Formats: LinkedIn carousel, 3-email sequence, one-page exec brief, "
                "video script (delete the ones you don't need)"),
        )],
    },
    docs=READER_FIRST_DOCS,
    skills=FORMAT_SKILLS,
    tools=["find_client_docs", "save_client_doc"],
)

PRESETS = {"data_doctor": DATA_DOCTOR,
           "data_health_scan": DATA_HEALTH_SCAN,
           "designer": DESIGNER,
           "lead_finder": LEAD_FINDER,
           "icp_finder": ICP_FINDER,
           "reader_researcher": READER_RESEARCHER,
           "proof_librarian": PROOF_LIBRARIAN,
           "moment_scout": MOMENT_SCOUT,
           "moment_writer": MOMENT_WRITER}
READER_FIRST = ("reader_researcher", "proof_librarian", "moment_scout", "moment_writer")

# What converting an existing agent to a workflow preset replaces; its identity (name,
# character, color, home zone, enabled) is kept.
WORKFLOW_FIELDS = ("title", "model_tier", "instructions", "tools", "skill_ids", "knowledge_ids",
                   "memory_enabled", "templates")


def _upsert_skill(spec: dict[str, str]) -> str:
    with session() as s:
        skill = s.exec(select(Skill).where(Skill.name == spec["name"])).first()
        if skill is None:
            skill = Skill(**spec)
        else:
            skill.description, skill.body, skill.updated_at = (spec["description"],
                                                               spec["body"], utcnow())
        s.add(skill)
        s.commit()
        return skill.id


_upsert_doc = client_library.upsert_doc


async def install(name: str) -> tuple[str, str]:
    """Install a preset. Returns (agent id, "created" | "converted" | "unchanged").

    A workflow preset whose agent already exists converts that agent in place: it keeps its
    name, character, color, home zone and Enabled setting, and the fields it replaces are
    recorded in the audit log first so nothing is lost.
    """
    preset = PRESETS[name]
    if preset.addon:
        return await _add_on(name, preset), "added"
    skill_ids = [_upsert_skill(k) for k in preset.skills]
    docs = [*preset.docs, *(preset.docs_from() if preset.docs_from else [])]
    doc_ids = [await _upsert_doc(d) for d in docs]
    agent_id = preset.agent["id"]
    body = registry.AgentIn(**preset.agent, skill_ids=skill_ids, knowledge_ids=doc_ids,
                            tools=preset.tools)
    existing = registry.get(agent_id)
    if existing is None:
        # MCP and Asset API tool names are only known once Marketo is connected, so they
        # aren't checked here; a run skips any tool the hub doesn't currently offer.
        registry.create(body, None)
        outcome = "created"
    elif preset.workflow and existing.workflow != preset.workflow:
        before = {k: getattr(existing, k) for k in WORKFLOW_FIELDS}
        audit("agent_converted", f"{existing.name} now runs the {preset.workflow} workflow "
              f"(preset {name}); previous settings are in this entry", agent_id=agent_id,
              data={"previous": before, "workflow": preset.workflow})
        new = body.model_dump(mode="json")
        registry.update(agent_id, {k: new[k] for k in WORKFLOW_FIELDS}, None)
        outcome = "converted"
    else:
        return agent_id, "unchanged"
    if preset.workflow:
        with session() as s:
            d = s.get(AgentDef, agent_id)
            d.workflow = preset.workflow
            s.add(d)
            s.commit()
    if outcome == "created":
        audit("agent_created", f"{body.name} (preset {name})", agent_id=agent_id)
    return agent_id, outcome


async def _add_on(name: str, preset: Preset) -> str:
    agent_id = preset.agent["id"]
    d = registry.get(agent_id)
    if d is None:
        raise SystemExit(f"preset {name} adds to the {agent_id!r} agent, which doesn't exist")
    skill_ids = [_upsert_skill(k) for k in preset.skills]
    docs = [*preset.docs, *(preset.docs_from() if preset.docs_from else [])]
    doc_ids = [await _upsert_doc(doc) for doc in docs]
    # the preset's own templates (by title) are refreshed; the agent's others are kept
    added_templates = [t.model_dump(mode="json") for t in preset.agent.get("templates", [])]
    ours = {t["title"] for t in added_templates}
    templates = [t for t in d.templates if t.get("title") not in ours]
    with session() as s:
        detach = {k.id for k in s.exec(select(KnowledgeDoc).where(
            KnowledgeDoc.title.in_(preset.detach_docs or [""])))}
    changes: dict[str, Any] = {
        "skill_ids": list(dict.fromkeys([*d.skill_ids, *skill_ids])),
        "knowledge_ids": [i for i in dict.fromkeys([*d.knowledge_ids, *doc_ids])
                          if i not in detach],
        "tools": list(dict.fromkeys([*d.tools, *preset.tools])),
        "templates": templates + added_templates}
    if extra := preset.agent.get("instructions", ""):
        heading = f"## Preset ({name})"
        mine = d.instructions.strip()
        if heading in mine:  # an earlier install: replace our section, keep theirs
            mine = mine[:mine.index(heading)].rstrip()
        elif mine.startswith(extra.split("\n", 1)[0]):  # ours was all of it
            mine = ""
        updated = f"{mine}\n\n{heading}\n\n{extra}" if mine else extra
        if updated != d.instructions.strip():
            changes["instructions"] = updated
    if preset.min_steps and d.max_steps < preset.min_steps:
        changes["max_steps"] = preset.min_steps
    registry.update(agent_id, changes, None)
    audit("agent_updated", f"{d.name}: added preset {name} (skills: "
          f"{', '.join(k['name'] for k in preset.skills) or 'none'}; knowledge: "
          f"{', '.join(doc['title'] for doc in docs) or 'none'}; tools: "
          f"{', '.join(preset.tools) or 'none'}; "
          + (f"detached: {', '.join(preset.detach_docs)}; " if detach & set(d.knowledge_ids)
             else "") + "templates: "
          f"{', '.join(t['title'] for t in added_templates) or 'none'})",
          agent_id=agent_id, data={"previous": {k: getattr(d, k) for k in (
              "skill_ids", "knowledge_ids", "tools", "templates", "instructions",
              "max_steps")}})
    return agent_id


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in PRESETS:
        print(f"usage: python -m app.presets {{{','.join(PRESETS)}}}")
        return 2
    init_db()
    get_store().load()  # UI settings, e.g. the embedding model for the knowledge doc
    agent_id, outcome = asyncio.run(install(argv[0]))
    print(f"{outcome}: {agent_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
