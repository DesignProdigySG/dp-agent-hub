"""The Designer's tools, and how its deliverables are checked and previewed.

Your brand pack is an optional folder (`BRAND_DIR`, default backend/brand; see its README):
an approved image library, the design system's colour tokens and Tailwind config, and a few
rules (email footer address, privacy link, words to avoid, default sender). Whatever it
holds is enforced; whatever it leaves out isn't checked. With no brand folder the Designer
still works: any image, any colour, Tailwind's default palette in previews.

`save_design` stores each landing page, email or form spec as a new version and checks it:
images from the library (when there is one), palette colours (when there is a palette), alt
text, the email footer and unsubscribe link, one Marketo form placeholder per landing page.
The checks go back to the agent, which fixes what fails and saves again.

Landing pages hold `{{marketo_form}}` where the registration form goes. The preview swaps in
a styled mock of the form spec; the export swaps in the Forms 2.0 embed once the form exists
in Marketo.

Emails are templates with editable sections (app/marketo/email_sections.py): the template holds
the layout, the email fills in each section, and a section can be dynamic content (one version
per segment of a segmentation). Publishing updates an email section by section, never its
whole HTML.
"""

import functools
import html as htmlmod
import json
import re
from pathlib import Path
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlmodel import select

from app.config import get_settings
from app.db import DesignDeliverable, session
from app.marketo import email_sections

FORM_PLACEHOLDER = "{{marketo_form}}"
AUTO_FIELDS = ["FirstName", "LastName", "Email"]  # every new Marketo form has these
FIELD_TYPES = ("text", "email", "tel", "select", "textarea", "checkbox")
# Words the brand voice check flags when brand.json doesn't list its own.
DEFAULT_BANNED = ["click here", "revolutionary", "game-changing", "game changing",
                  "best-in-class", "best in class", "cutting-edge", "cutting edge", "synergy"]
NOT_COLOUR = re.compile(r"""\b(?:href|id|for|name|aria-[a-z]+|data-[a-z-]+)\s*=\s*["'][^"']*["']""",
                        re.I)
HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
IMG_SRC = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+\.(?:jpe?g|png|webp|gif)[^"']*|"""
                     r"""https?://(?:images|plus)\.unsplash\.com/[^"']+)["']""", re.I)
CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", re.I)
UNSPLASH_PHOTO = re.compile(r"(?:images|plus)\.unsplash\.com/(photo-[0-9a-f-]+|premium_photo-"
                            r"[0-9a-f-]+)")
TOKEN = re.compile(r"\{\{\s*(lead|my|system|company)\.([^}:]+?)(?::default=([^}]*))?\s*\}\}")


# --- brand pack (optional) ---------------------------------------------------------------------


def brand_dir() -> Path:
    return Path(get_settings().brand_dir)


def _read(name: str) -> str:
    path = brand_dir() / name
    return path.read_text() if path.is_file() else ""


@functools.lru_cache(maxsize=8)
def _brand_json(directory: str) -> dict[str, Any]:
    path = Path(directory) / "brand.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def brand() -> dict[str, Any]:
    """brand.json: name, from_name, from_email, reply_email, footer_address, privacy_url,
    banned_words. Every key is optional."""
    return _brand_json(str(brand_dir()))


@functools.lru_cache(maxsize=8)
def _images(directory: str) -> tuple[dict[str, Any], ...]:
    path = Path(directory) / "images.json"
    return tuple(json.loads(path.read_text()).get("images", [])) if path.is_file() else ()


def images() -> list[dict[str, Any]]:
    """The approved image library (images.json); empty when the brand has none."""
    return list(_images(str(brand_dir())))


def palette() -> set[str]:
    """Every hex value in the design system's colour token section ("Colour tokens" or
    "Color tokens" heading); empty (no colour check) without one."""
    text = _read("design_system.md")
    m = re.search(r"^#+\s*(?:\d+\.\s*)?colou?r tokens\b.*?$(.*?)(?=^#{1,2}\s|\Z)", text,
                  re.I | re.M | re.S)
    return {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}", m.group(1))} if m else set()


def _banned() -> re.Pattern | None:
    words = brand().get("banned_words", DEFAULT_BANNED)
    if not words:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)


def _expand(h: str) -> str:
    h = h.upper()
    return "#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h


def _base(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0].rstrip("/")


def _approved(url: str, library: list[dict[str, Any]]) -> bool:
    if _base(url) in {_base(i.get("url", "")) for i in library}:
        return True
    m = UNSPLASH_PHOTO.search(url)  # Unsplash photos match by ID, whatever the size params
    return bool(m and m.group(1) in {i.get("photo") for i in library})


def images_markdown() -> str:
    """The image library as a knowledge document."""
    name = brand().get("name", "Brand")
    lines = [f"# {name} Approved Images", "",
             "*The only images designs may use. Use the `brand_images` tool to search.*", "",
             "| ID | Shows | Tags | Approved for | Credit |", "|---|---|---|---|---|"]
    lines += [f"| `{i['id']}` | {i.get('alt', '')} | {', '.join(i.get('tags', []))} | "
              f"{', '.join(i.get('uses', []))} | {i.get('photographer', '')} |"
              for i in images()]
    lines += ["", "Image URLs:", ""]
    lines += [f"- `{i['id']}`: {i['url']}" for i in images()]
    return "\n".join(lines)


# --- checks ------------------------------------------------------------------------------------


def _image_urls(markup: str) -> list[str]:
    urls = [m.group(1) for m in IMG_SRC.finditer(markup)]
    urls += [u for u in CSS_URL.findall(markup) if not u.startswith(("#", "data:image/svg"))]
    return [u for u in urls if not u.startswith("data:image/svg")]


def check(kind: str, markup: str = "", subject: str = "", preheader: str = "",
          fields: list[dict[str, Any]] | None = None,
          form_on_task: bool = False,
          dynamic: dict[str, dict] | None = None) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    library, colours, banned = images(), palette(), _banned()
    if kind in ("landing_page", "email", "fragment"):  # fragment: a dynamic segment's HTML
        if not markup.strip():
            errors.append("html is empty")
        if library:  # no image library in the brand pack: any image is allowed
            for url in _image_urls(markup):
                if not _approved(url, library):
                    errors.append(f"image not in the approved library: {url[:120]}")
        for tag in re.findall(r"<img\b[^>]*>", markup, re.I):
            if not re.search(r"\balt\s*=", tag, re.I):
                errors.append(f"image without alt text: {tag[:100]}")
        if colours:  # no palette in the brand pack: any colour is allowed
            styling = NOT_COLOUR.sub("", markup)  # anchors (#register) and ids aren't colours
            off = sorted({_expand(m.group(0)) for m in HEX.finditer(styling)} - colours)
            if off:
                errors.append("colours not in the design system: " + ", ".join(off)
                              + ". Use the colour tokens in the design system.")
        text = re.sub(r"<[^>]+>", " ", markup)
        for word in sorted({w.lower() for w in banned.findall(text)} if banned else ()):
            warnings.append(f"brand voice: avoid {word!r}")
    if kind == "landing_page":
        if not re.search(r"<title>[^<]+</title>", markup, re.I):
            errors.append("missing <title>")
        if not re.search(r'name=["\']viewport', markup, re.I):
            errors.append('missing <meta name="viewport">: pages must work on mobile')
        n = markup.count(FORM_PLACEHOLDER)
        if n > 1:
            errors.append(f"{FORM_PLACEHOLDER} appears {n} times; use it once")
        elif n == 0 and form_on_task:
            errors.append(f"this task has a form: put {FORM_PLACEHOLDER} where it goes")
        if re.search(r"<form\b", markup, re.I):
            errors.append(f"don't hand-code a <form>; use {FORM_PLACEHOLDER} (Marketo renders "
                          "it)")
    if kind == "email":
        if "{{system.unsubscribeLink}}" not in markup:
            errors.append("missing the unsubscribe link {{system.unsubscribeLink}}")
        address = brand().get("footer_address", "")
        if address and address not in markup:
            errors.append(f"missing the physical address in the footer ({address})")
        privacy = brand().get("privacy_url", "")
        if privacy and privacy not in markup:
            warnings.append(f"no privacy policy link in the footer ({privacy})")
        elif not privacy and "privacy" not in markup.lower():
            warnings.append("no privacy policy link in the footer")
        if re.search(r"<script\b", markup, re.I):
            errors.append("emails can't contain scripts")
        if "cdn.tailwindcss.com" in markup or re.search(r'class="[^"]*\b(bg|text|p[xy]?)-',
                                                        markup):
            warnings.append("emails need inline styles; Tailwind classes won't render")
        if not subject.strip():
            errors.append("subject is empty")
        elif len(subject) > 60:
            errors.append(f"subject is {len(subject)} characters; keep it to 60")
        if not 40 <= len(preheader.strip()) <= 90:
            warnings.append(f"preheader is {len(preheader.strip())} characters; aim for 40-90")
        if re.search(r"\{\{lead\.[^}:]+\}\}", markup + subject):
            warnings.append("lead tokens need a default, e.g. {{lead.First Name:default=there}}")
        e, w = email_sections.check(markup, dynamic)
        errors += e
        warnings += w
        for sid, spec in (dynamic or {}).items():  # each segment's HTML meets the brand too
            for seg, body in (spec.get("segments") or {}).items():
                sub = check("fragment", body)
                errors += [f"dynamic section {sid!r}, segment {seg!r}: {x}" for x in sub["errors"]]
    if kind == "form":
        ids = [str(f.get("fieldId", "")) for f in fields or []]
        if not fields:
            warnings.append("no fields beyond first name, last name and email")
        for f in fields or []:
            fid = str(f.get("fieldId", ""))
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", fid):
                errors.append(f"field {fid!r}: use the Marketo field ID, e.g. Company, Phone")
            if fid in AUTO_FIELDS:
                errors.append(f"{fid} is added to every Marketo form automatically; remove it")
            if f.get("type", "text") not in FIELD_TYPES:
                errors.append(f"field {fid}: type must be one of {', '.join(FIELD_TYPES)}")
            if f.get("type") == "select" and not f.get("options"):
                errors.append(f"field {fid}: a select needs options")
        if len(set(ids)) != len(ids):
            errors.append("duplicate fields")
    return {"errors": errors, "warnings": warnings}


# --- preview / export ---------------------------------------------------------------------------


TOKEN_MARK = ("background:#fff3c4;border-bottom:1px dashed #b58a00;border-radius:2px;"
              "padding:0 2px")


def _tokens(markup: str, values: dict[str, str] | None = None) -> str:
    """Marketo tokens in the preview: the value Marketo will fill in (the program's My Token
    value when known, else the token's default), highlighted so a reviewer can see it's a
    token. A token with neither shows as itself, e.g. {{my.Event Name}}, never as a
    "[placeholder]". Inside tags (links, attributes) the value goes in unmarked."""
    values = values or {}

    def value(m: re.Match) -> tuple[str, bool]:
        scope, name = m.group(1), m.group(2).strip()
        if scope == "system" and name == "unsubscribeLink":
            return "#unsubscribe", True
        if scope == "my" and name in values:
            return values[name], True
        if m.group(3) is not None:
            return m.group(3), True
        return m.group(0), False

    def in_tag(m: re.Match) -> str:
        return htmlmod.escape(value(m)[0], quote=True)

    def in_text(m: re.Match) -> str:
        text, known = value(m)
        tip = htmlmod.escape(f"Marketo token {m.group(0)}", quote=True)
        return (f'<span style="{TOKEN_MARK}" title="{tip}">{htmlmod.escape(text)}</span>'
                if known else f'<span style="{TOKEN_MARK};font-family:monospace" '
                              f'title="{tip}: Marketo fills this in">{htmlmod.escape(text)}</span>')

    parts = re.split(r"(<[^>]+>)", markup)
    return "".join(TOKEN.sub(in_tag if p.startswith("<") else in_text, p) for p in parts)


def plain_tokens(text: str, task_id: str) -> str:
    """Text (e.g. a subject line) with its My Tokens filled in from the work they belong to;
    unknown tokens stay as written."""
    values = _token_values(task_id)

    def sub(m: re.Match) -> str:
        name = m.group(2).strip()
        return values.get(name, m.group(3) if m.group(3) is not None else m.group(0)) \
            if m.group(1) == "my" else m.group(0)
    return TOKEN.sub(sub, text or "")


def _token_values(task_id: str) -> dict[str, str]:
    """My Token values for the work this design belongs to (`params.shared.my_tokens`)."""
    from app.db import Task

    with session() as s:
        task = s.get(Task, task_id)
    shared = ((task.params or {}).get("shared") or {}) if task else {}
    return {str(k): str(v) for k, v in (shared.get("my_tokens") or {}).items()}


def _label(fid: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r" \1", fid).replace("_", " ").strip().capitalize()


def mock_form(fields: list[dict[str, Any]], button: str = "Register") -> str:
    """The form spec as styled HTML (preview only; Marketo renders the real form). Uses
    Tailwind's default palette so it looks right with or without a brand config."""
    rows = [{"fieldId": f, "label": _label(f), "required": True,
             "type": "email" if f == "Email" else "text"} for f in AUTO_FIELDS] + list(fields)
    cls = ("mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 "
           "text-slate-900 focus:border-indigo-600 focus:outline-none focus:ring-2 "
           "focus:ring-indigo-100")
    out = ['<div class="space-y-4" data-preview="marketo-form">']
    for f in rows:
        label = htmlmod.escape(str(f.get("label") or _label(f["fieldId"])))
        star = ' <span class="text-red-600">*</span>' if f.get("required") else ""
        hint = htmlmod.escape(str(f.get("hint", "")))
        t = f.get("type", "text")
        if t == "select":
            opts = "".join(f"<option>{htmlmod.escape(str(o))}</option>"
                           for o in f.get("options", []))
            control = f'<select class="{cls}"><option>Select…</option>{opts}</select>'
        elif t == "textarea":
            control = f'<textarea rows="3" class="{cls}" placeholder="{hint}"></textarea>'
        elif t == "checkbox":
            out.append(f'<label class="flex items-start gap-2 text-sm text-slate-600">'
                       f'<input type="checkbox" class="mt-1"> {label}{star}</label>')
            continue
        else:
            control = f'<input type="{t}" class="{cls}" placeholder="{hint}">'
        out.append(f'<label class="block text-sm font-semibold text-slate-700">{label}{star}'
                   f'{control}</label>')
    out.append('<button type="button" class="w-full rounded-md bg-indigo-600 px-6 py-3 '
               f'font-semibold text-white">{htmlmod.escape(button)}</button>'
               '<p class="text-xs text-slate-500">Preview: Marketo renders the live form.</p>'
               "</div>")
    return "".join(out)


def form_style_js() -> str:
    """Optional script (form_style.js in the brand pack) that restyles Marketo's rendered
    form to match your pages; empty when there is none."""
    return _read("form_style.js")


def form_embed(form_id: int) -> str:
    munchkin = get_settings().marketo_munchkin_id or "000-AAA-000"
    base = f"//{munchkin.lower()}.mktoweb.com"
    style = form_style_js()
    return (f'<script src="{base}/js/forms2/js/forms2.min.js"></script>'
            f'<form id="mktoForm_{form_id}"></form>'
            f'<script>MktoForms2.loadForm("{base}", "{munchkin}", {form_id});</script>'
            + (f'<script>{style}</script>' if style else ""))


def latest(task_id: str) -> dict[tuple[str, str], DesignDeliverable]:
    with session() as s:
        rows = s.exec(select(DesignDeliverable).where(DesignDeliverable.task_id == task_id)
                      .order_by(DesignDeliverable.version))
        return {(r.kind, r.name): r for r in rows}


def render(d: DesignDeliverable, mode: Literal["preview", "export"] = "preview") -> str:
    """A deliverable's HTML for the preview iframe, or ready to paste into Marketo."""
    if d.kind == "form":
        return ("<!doctype html><html><head><meta name='viewport' content='width=device-width'>"
                "<script src='https://cdn.tailwindcss.com'></script><script>"
                + tailwind_config_js() + "</script></head><body class='bg-slate-50 p-6'>"
                "<div class='mx-auto max-w-md rounded-xl bg-white p-8 shadow'>"
                + mock_form(d.spec.get("fields", []), d.spec.get("button") or "Register")
                + "</div></body></html>")
    markup = d.html
    if d.kind == "landing_page" and FORM_PLACEHOLDER in markup:
        form = next((f for (k, _), f in latest(d.task_id).items() if k == "form"), None)
        if mode == "export" and form and form.marketo.get("form_id"):
            markup = markup.replace(FORM_PLACEHOLDER, form_embed(int(form.marketo["form_id"])))
        elif mode == "preview":
            markup = markup.replace(FORM_PLACEHOLDER, mock_form(
                form.spec.get("fields", []) if form else [],
                (form.spec.get("button") if form else None) or "Register"))
    if d.kind == "email" and d.spec.get("dynamic"):
        markup = _with_dynamic(markup, d.spec["dynamic"], label=mode == "preview")
    return _tokens(markup, _token_values(d.task_id)) if mode == "preview" else markup


DYNAMIC_MARK = ("outline:2px dashed #b58a00;outline-offset:2px;position:relative")
DYNAMIC_LABEL = ("display:inline-block;margin:0 0 6px;padding:2px 8px;border-radius:9px;"
                 "background:#fff3c4;color:#5c4400;font:600 11px/1.4 sans-serif")


def _with_dynamic(markup: str, dynamic: dict[str, dict], label: bool) -> str:
    """Dynamic sections hold their Default segment (what the template starts with). In the
    preview each is outlined and labelled with its segments."""
    out, last = [], 0
    for sec in email_sections.sections(markup):
        spec = dynamic.get(sec.id)
        if not spec:
            continue
        segs = spec.get("segments") or {}
        body = segs.get("Default", sec.inner)
        if label:
            names = ", ".join(n for n in segs if n != "Default")
            body = (f'<div style="{DYNAMIC_MARK}"><span style="{DYNAMIC_LABEL}">Dynamic content · '
                    f'{htmlmod.escape(spec.get("segmentation", ""))}: showing Default'
                    + (f"; also {htmlmod.escape(names)}" if names else "")
                    + f"</span>{body}</div>")
        out += [markup[last:sec.start], body]
        last = sec.end
    return "".join(out) + markup[last:]


def tailwind_config_js() -> str:
    """The design system's `tailwind.config = {...}` (for previews that need it); empty
    without one, so previews use Tailwind's defaults."""
    text = _read("design_system.md")
    m = re.search(r"<script>\s*(tailwind\.config = \{.*?\n\})\s*</script>", text, re.S)
    return m.group(1) if m else ""


# --- tools -------------------------------------------------------------------------------------


@tool
def brand_images(query: str = "", use: str = "", limit: int = 12) -> list:
    """Search the brand's approved image library (when it has one, the only images you may
    use). `query` matches words in the id, description and tags; `use` filters by approved
    use (e.g. hero, section, product, event, email-header, email-body). Returns id, url, alt
    text, tags, uses and the credit. An empty list with a note means the brand pack has no
    image library: use images the task provides, or leave a clearly marked placeholder."""
    library = images()
    if not library:
        return [{"note": "No image library in the brand pack (backend/brand/images.json). "
                         "Use images given in the task or its attachments, or a placeholder "
                         "marked [TBC: image]."}]
    words = [w for w in query.lower().split() if w]
    out = []
    for i in library:
        hay = " ".join([i.get("id", ""), i.get("alt", ""), *i.get("tags", [])]).lower()
        if words and not any(w in hay for w in words):
            continue
        if use and use not in i.get("uses", []):
            continue
        out.append({k: i.get(k) for k in ("id", "url", "alt", "tags", "uses", "photographer",
                                          "page") if k in i})
    return out[:max(1, min(limit, 40))]


class FormField(BaseModel):
    fieldId: str = Field(description="Marketo form field ID, e.g. Company, Title, Phone, "
                                     "MobilePhone, or a custom field ID. Not FirstName / "
                                     "LastName / Email: those are automatic.")
    label: str
    required: bool = False
    type: str = Field("text", description="text | email | tel | select | textarea | checkbox")
    options: list[str] = Field(default_factory=list, description="for select")
    hint: str = ""


class DynamicSection(BaseModel):
    segmentation: str = Field(description="Name of an approved Marketo segmentation (see "
                                          "list_segmentations)")
    segments: dict[str, str] = Field(description="Segment name -> that segment's HTML for the "
                                                 "section. Include Default (everyone else).")


@tool
def save_design(kind: Literal["landing_page", "email", "form"], name: str, runtime: ToolRuntime,
                html: str = "", subject: str = "", preheader: str = "",
                fields: list[FormField] | None = None, button: str = "",
                marketo_form_id: int | None = None, notes: str = "",
                dynamic: dict[str, DynamicSection] | None = None) -> dict:
    """Save a deliverable so it shows in the task's Results with a live preview. Saving the
    same kind + name again adds a new version (earlier versions are kept).

    kind="landing_page": full HTML document using the design system's Tailwind config;
      put {{marketo_form}} where the registration form goes.
    kind="email": full HTML email (600px tables, inline styles), plus subject and preheader.
      It becomes a Marketo email template, so mark every part the email fills in as an
      editable section: an element with class="mktoText", a unique id and a mktoName, e.g.
      <div class="mktoText" id="hero-body" mktoName="Hero Body">...</div> (headline, body,
      details, button, sign-off; not the header band or the footer). Sections can't nest.
      To vary a section by segment, add it to `dynamic`: {"<section id>": {"segmentation":
      "<name>", "segments": {"<segment name>": "<html>", ..., "Default": "<html>"}}}; the
      section's own HTML should match Default. Write values in: no ${...} variables.
    kind="form": the registration form spec in `fields` (FirstName, LastName and Email are
      automatic) and the `button` label; after creating it in Marketo, save it again with
      marketo_form_id so the landing page export embeds the real form.

    Returns the brand check: fix every error and save again before you finish."""
    state = runtime.state
    task_id, agent_id = state.get("task_id", ""), state.get("agent_id", "")
    rnd = len((state.get("params") or {}).get("revisions", []))
    spec_fields = [f.model_dump() if isinstance(f, BaseModel) else dict(f)
                   for f in (fields or [])]
    existing = latest(task_id)
    form_on_task = any(k == "form" for k, _ in existing) or kind == "form"
    dyn = {k: (v.model_dump() if isinstance(v, BaseModel) else dict(v))
           for k, v in (dynamic or {}).items()}
    result = check(kind, html, subject, preheader, spec_fields, form_on_task, dyn)
    prev = existing.get((kind, name))
    marketo = dict(prev.marketo) if prev else {}
    if marketo_form_id:
        marketo["form_id"] = int(marketo_form_id)
    if kind == "form" and prev and not spec_fields:  # recording the Marketo ID only
        spec = dict(prev.spec)
        result = {"errors": [], "warnings": []}
    else:
        spec = {"fields": spec_fields, "button": button, "notes": notes,
                **({"dynamic": dyn} if dyn else {})}
    d = DesignDeliverable(task_id=task_id, agent_id=agent_id, kind=kind, name=name.strip()[:120],
                          version=(prev.version + 1) if prev else 1, round=rnd, html=html,
                          subject=subject.strip(), preheader=preheader.strip(), spec=spec,
                          marketo=marketo, checks=result)
    with session() as s:
        s.add(d)
        s.commit()
    status = "needs fixes" if result["errors"] else "passes the brand check"
    return {"saved": d.id, "kind": kind, "name": d.name, "version": d.version, "status": status,
            **result}


# --- publishing to Marketo (Asset API) -----------------------------------------------------------


def _latest_of(task_id: str, kind: str, name: str) -> DesignDeliverable | None:
    found = latest(task_id)
    return found.get((kind, name)) or next(
        (d for (k, n), d in found.items() if k == kind and n.lower() == name.strip().lower()),
        None)


async def _asset(op_name: str, **args: Any) -> dict[str, Any]:
    from app.deps import get_deps
    from app.marketo import asset_api

    op = asset_api.by_name()[op_name]
    body = await get_deps().marketo.asset(asset_api.split_args(op, args))
    result = (body or {}).get("result") or [{}]
    return result[0]


def _record(d: DesignDeliverable, **ids: Any) -> None:
    with session() as s:
        row = s.get(DesignDeliverable, d.id)
        row.marketo = {**row.marketo, **ids}
        s.add(row)
        s.commit()


def _folder(folder_id: int, folder_type: str) -> dict[str, Any]:
    return {"id": int(folder_id), "type": folder_type}


async def _segmentations() -> dict[str, dict[str, Any]]:
    """Approved segmentations by name: {name: {id, segments: [names]}}."""
    from app.deps import get_deps
    from app.marketo import asset_api

    ops = asset_api.by_name()
    marketo = get_deps().marketo
    body = await marketo.asset(asset_api.split_args(ops["asset_get_segmentation"],
                                                    {"status": "approved"}))
    out = {}
    for seg in (body or {}).get("result") or []:
        segs = await marketo.asset(asset_api.split_args(
            ops["asset_get_segments_for_segmentation"], {"id": seg["id"], "status": "approved"}))
        out[seg["name"]] = {"id": seg["id"],
                            "segments": [x["name"] for x in (segs or {}).get("result") or []]}
    return out


@tool
async def list_segmentations() -> dict:
    """The approved Marketo segmentations and their segments, for dynamic content in emails
    (save_design's `dynamic`). Segments are matched by name; every one has a Default."""
    found = await _segmentations()
    return {"segmentations": [{"name": n, **v} for n, v in found.items()]}


async def _sections_in_marketo(email_id: int) -> dict[str, dict[str, Any]]:
    """The email's sections as Marketo has them: {htmlId: {type, value}}."""
    from app.deps import get_deps
    from app.marketo import asset_api

    body = await get_deps().marketo.asset(asset_api.split_args(
        asset_api.by_name()["asset_get_email_content_by_id"], {"id": email_id,
                                                               "status": "draft"}))
    return {x["htmlId"]: {"type": x.get("contentType"), "value": x.get("value")}
            for x in (body or {}).get("result") or [] if x.get("htmlId")}


def _html_of(value: Any) -> str:
    """A plain section's HTML from Marketo's content read ([{type: HTML, value}, ...])."""
    if isinstance(value, list):
        return next((v.get("value", "") for v in value if v.get("type") == "HTML"), "")
    return value if isinstance(value, str) else ""


@tool
async def publish_email(name: str, folder_id: int, runtime: ToolRuntime,
                        folder_type: Literal["Folder", "Program"] = "Folder",
                        template_folder_id: int | None = None,
                        from_name: str = "", from_email: str = "",
                        reply_email: str = "") -> dict:
    """Publish a saved email design (kind="email", by name) to Marketo as a draft.

    The first time: creates an email template from the HTML (its mktoText sections become
    the editable sections), approves the template, and creates the email from it with the
    subject and sender. Then fills in each section: plain sections with their HTML, dynamic
    sections bound to their segmentation with one version per segment.

    Re-publishing updates the same email section by section (never its whole HTML, which
    Marketo refuses on emails built from a template). A layout change outside the sections
    goes to the template, and approving the template carries it into the email.

    `folder_id`: the program or folder for the email (find it with asset_get_folder_by_name);
    `template_folder_id`: a Design Studio email-template folder (defaults to folder_id).
    The sender defaults to the brand pack's from_name / from_email / reply_email."""
    task_id = runtime.state.get("task_id", "")
    b = brand()
    from_name = from_name or b.get("from_name", "")
    from_email = from_email or b.get("from_email", "")
    reply_email = reply_email or b.get("reply_email", "") or from_email
    if not (from_name and from_email):
        return {"error": "No sender: pass from_name and from_email, or set them in the brand "
                         "pack (backend/brand/brand.json)."}
    d = _latest_of(task_id, "email", name)
    if d is None:
        return {"error": f"No saved email design named {name!r}; save it with save_design."}
    if d.checks.get("errors"):
        return {"error": "Fix the brand-check errors and save again before publishing: "
                         + "; ".join(d.checks["errors"])}
    html = render(d, "export")
    dynamic = d.spec.get("dynamic") or {}
    secs = email_sections.sections(html)
    if not secs:
        return {"error": "The email has no editable sections (class=\"mktoText\" with an id); "
                         "add them, save again, then publish."}
    segmentations = await _segmentations() if dynamic else {}
    for sid, spec in dynamic.items():
        known = segmentations.get(spec["segmentation"])
        if known is None:
            return {"error": f"No approved segmentation named {spec['segmentation']!r}. "
                             f"Approved: {', '.join(segmentations) or 'none'}."}
        if unknown := [n for n in spec["segments"] if n not in known["segments"]]:
            return {"error": f"Section {sid!r}: {spec['segmentation']} has no segment "
                             f"{', '.join(unknown)} (its segments: "
                             f"{', '.join(known['segments'])})."}
    folder = _folder(folder_id, folder_type)
    ids = dict(d.marketo)
    layout = email_sections.layout_hash(html)
    template = "unchanged"
    # Marketo builds emails only from an approved template; the template is this design's
    # layout, so it's approved here. The email itself stays a draft.
    if not ids.get("email_template_id"):
        t = await _asset("asset_create_email_template", name=f"{d.name} (template)",
                         folder=_folder(template_folder_id, "Folder") if template_folder_id
                         else folder, content=html,
                         description="Created by the Designer agent")
        ids["email_template_id"] = t.get("id")
        _record(d, **ids)  # kept even if creating the email fails: a retry updates it
        await _asset("asset_approve_draft_email_template", id=ids["email_template_id"])
        ids["layout"], template = layout, "created"
        _record(d, **ids)
    elif ids.get("layout") != layout:  # new layout: the template changes, the email follows
        await _asset("asset_update_email_template_content", id=ids["email_template_id"],
                     content=html)
        await _asset("asset_approve_draft_email_template", id=ids["email_template_id"])
        ids["layout"], template = layout, "layout updated"
        _record(d, **ids)
    if ids.get("email_id"):  # the subject and sender may have changed
        text = lambda v: {"type": "Text", "value": v}  # noqa: E731 (Marketo's header field)
        await _asset("asset_update_email_content", id=ids["email_id"], subject=text(d.subject),
                     fromName=text(from_name), fromEmail=text(from_email),
                     replyTO=text(reply_email))
    else:  # creating it sets the subject and sender
        e = await _asset("asset_create_email", name=d.name, folder=folder,
                         template=ids["email_template_id"], subject=d.subject,
                         fromName=from_name, fromEmail=from_email, replyEmail=reply_email,
                         description="Created by the Designer agent")
        ids["email_id"] = e.get("id")
        _record(d, **ids)
    if d.preheader:
        await _asset("asset_update_email", id=ids["email_id"], preHeader=d.preheader)
    current = await _sections_in_marketo(ids["email_id"])
    done: dict[str, list[str]] = {"updated": [], "unchanged": [], "missing": []}
    dyn_out: dict[str, Any] = {}
    for sec in secs:
        have = current.get(sec.id)
        if have is None:
            done["missing"].append(sec.id)
            continue
        spec = dynamic.get(sec.id)
        if spec:
            seg = segmentations[spec["segmentation"]]
            content_id = have["value"] if have["type"] == "DynamicContent" else None
            if content_id is None or ids.get("segmentation", {}).get(sec.id) != seg["id"]:
                await _asset("asset_update_email_component_content", id=ids["email_id"],
                             htmlId=sec.id, type="DynamicContent", value=seg["id"])
                content_id = (await _sections_in_marketo(ids["email_id"]))[sec.id]["value"]
                ids.setdefault("segmentation", {})[sec.id] = seg["id"]
            for segment, body in spec["segments"].items():  # HTML; Marketo derives the text
                await _asset("asset_update_email_dynamic_content", id=ids["email_id"],
                             contentId=content_id, segment=segment, type="HTML", value=body)
            dyn_out[sec.id] = {"segmentation": spec["segmentation"],
                               "segments": list(spec["segments"])}
            done["updated"].append(sec.id)
        elif have["type"] == "Text" and _html_of(have["value"]).strip() == sec.inner.strip():
            done["unchanged"].append(sec.id)
        else:  # plain HTML (this also turns a once-dynamic section back into a plain one)
            await _asset("asset_update_email_component_content", id=ids["email_id"],
                         htmlId=sec.id, type="Text", value=sec.inner)
            ids.get("segmentation", {}).pop(sec.id, None)
            done["updated"].append(sec.id)
    _record(d, **{**ids, "email_version": d.version})
    return {"published": d.name, "version": d.version, "status": "draft in Marketo",
            "email_id": ids["email_id"], "email_template_id": ids["email_template_id"],
            "template": template, "sections": {k: v for k, v in done.items() if v},
            **({"dynamic": dyn_out} if dyn_out else {}),
            **({"warnings": [f"sections not in the Marketo email: {', '.join(done['missing'])}"]}
               if done["missing"] else {})}


@tool
async def publish_landing_page(name: str, folder_id: int, runtime: ToolRuntime,
                               folder_type: Literal["Folder", "Program"] = "Folder",
                               template_folder_id: int | None = None,
                               url_page_name: str = "") -> dict:
    """Publish a saved landing page design (kind="landing_page", by name) to Marketo as a
    draft: creates (or updates) a free-form landing page template with the HTML, with the
    Marketo form embedded once it exists, then a landing page from it. Re-publishing updates
    the template. `folder_id`: where the page goes; `template_folder_id`: a Design Studio
    folder for the template (defaults to folder_id)."""
    task_id = runtime.state.get("task_id", "")
    d = _latest_of(task_id, "landing_page", name)
    if d is None:
        return {"error": f"No saved landing page design named {name!r}."}
    if d.checks.get("errors"):
        return {"error": "Fix the brand-check errors and save again before publishing: "
                         + "; ".join(d.checks["errors"])}
    html = render(d, "export")
    if FORM_PLACEHOLDER in html:
        return {"error": "The page has a form placeholder but the form isn't in Marketo yet: "
                         "create it (create_form / add_field_to_form) and save the form spec "
                         "with marketo_form_id first."}
    ids = dict(d.marketo)
    # as for emails: pages are built only from an approved template; the page stays a draft
    if ids.get("landing_page_template_id"):
        await _asset("asset_update_landing_page_template_content",
                     id=ids["landing_page_template_id"], content=html)
        await _asset("asset_approve_landing_page_template", id=ids["landing_page_template_id"])
    else:
        t = await _asset("asset_create_lp_template", name=f"{d.name} (template)",
                         folder=_folder(template_folder_id or folder_id,
                                        "Folder" if template_folder_id else folder_type),
                         templateType="freeForm", description="Created by the Designer agent")
        ids["landing_page_template_id"] = t.get("id")
        _record(d, **ids)  # kept even if creating the page fails: a retry updates it
        await _asset("asset_update_landing_page_template_content",
                     id=ids["landing_page_template_id"], content=html)
        await _asset("asset_approve_landing_page_template", id=ids["landing_page_template_id"])
    if not ids.get("landing_page_id"):
        title = re.search(r"<title>([^<]+)</title>", html, re.I)
        page = await _asset("asset_create_landing_page", name=d.name,
                            folder=_folder(folder_id, folder_type),
                            template=ids["landing_page_template_id"],
                            title=title.group(1).strip() if title else d.name,
                            **({"urlPageName": url_page_name} if url_page_name else {}))
        ids["landing_page_id"] = page.get("id")
    _record(d, **ids, landing_page_version=d.version)
    return {"published": d.name, "version": d.version, "status": "draft in Marketo", **ids}
