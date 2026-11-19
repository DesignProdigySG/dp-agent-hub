"""An email's editable sections: the parts of its template an email fills in on its own.

A section is an element with class `mktoText` (or the older `mktEditable`) and a unique `id`,
e.g. `<div class="mktoText" id="hero-body" mktoName="Hero Body">...</div>`. The template holds
the layout around the sections; each email built from it fills them in, by section:

  * a plain section:   POST email/{id}/content/{htmlId}.json   type=Text, value=<html>
  * a dynamic section: the same call with type=DynamicContent, value=<segmentation id>, then
                       POST email/{id}/dynamicContent/{contentId}.json per segment
                       (segment=<name>, type=HTML, value=<html>)

So updating an email never replaces its whole HTML (fullContent fails with error 709 on any
email built from a template). A layout change goes to the template, and approving the template
carries it into the email; the email keeps its own section content.
"""

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser

SECTION_CLASSES = ("mktoText", "mktEditable")
MAX_DYNAMIC = 20  # Adobe's guidance: more dynamic sections slow rendering and sends
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
        "track", "wbr"}
TEMPLATE_VARIABLE = re.compile(r"\$\{[^}]+\}")  # mktoString etc.: not resolved in dynamic content


@dataclass
class Section:
    id: str
    name: str
    inner: str  # the section's own HTML, between its tags
    start: int  # offsets of `inner` in the document
    end: int


class _Finder(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self._line_at = [0]  # offset of each line's start (the parser counts \n only)
        for line in html.split("\n"):
            self._line_at.append(self._line_at[-1] + len(line) + 1)
        self.stack: list[tuple[str, dict | None]] = []  # (tag, open section or None)
        self.found: list[Section] = []
        self.problems: list[str] = []

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_at[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        a = {k.lower(): v or "" for k, v in attrs}
        classes = a.get("class", "").split()
        section = None
        if any(c in classes for c in SECTION_CLASSES):
            if any(open_ for _, open_ in self.stack):
                self.problems.append(f"section {a.get('id') or '(no id)'} is inside another "
                                     "section; sections can't be nested")
            text = self.get_starttag_text() or ""
            section = {"id": a.get("id", ""), "name": a.get("mktoname", ""),
                       "start": self._offset() + len(text)}
        self.stack.append((tag, section))

    def handle_startendtag(self, tag, attrs):
        pass  # <br/>, <img/>: no content

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        # close up to the matching tag (tolerates unclosed <p>, <td> and the like)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _, section in self.stack[i + 1:]:
                    if section:
                        self.problems.append(f"section {section['id'] or '(no id)'} isn't "
                                             "closed properly")
                _, section = self.stack[i]
                del self.stack[i:]
                if section:
                    end = self._offset()
                    self.found.append(Section(section["id"], section["name"],
                                              self.html[section["start"]:end],
                                              section["start"], end))
                return


def sections(html: str) -> list[Section]:
    """The editable sections, in document order."""
    f = _Finder(html)
    f.feed(html)
    f.close()
    return sorted(f.found, key=lambda s: s.start)


def layout(html: str) -> str:
    """The template's layout: the HTML with every section emptied. Two versions of an email
    with the same layout differ only inside their sections."""
    out, last = [], 0
    for s in sections(html):
        out.append(html[last:s.start])
        last = s.end
    out.append(html[last:])
    return "".join(out)


def layout_hash(html: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", layout(html)).encode()).hexdigest()[:16]


def check(html: str, dynamic: dict[str, dict] | None = None) -> tuple[list[str], list[str]]:
    """Errors and warnings for an email's sections and its dynamic content."""
    errors: list[str] = []
    warnings: list[str] = []
    f = _Finder(html)
    f.feed(html)
    f.close()
    errors += f.problems
    found = f.found
    if not found:
        errors.append('no editable sections: wrap each part the email fills in (headline, body, '
                      'details, button...) in an element with class="mktoText", a unique id and '
                      'a mktoName, e.g. <div class="mktoText" id="body" mktoName="Body">...</div>. '
                      "Marketo updates an email by section, never its whole HTML")
    ids = [s.id for s in found]
    if any(not i for i in ids):
        errors.append("every mktoText section needs an id")
    if dupes := sorted({i for i in ids if i and ids.count(i) > 1}):
        errors.append(f"section ids must be unique: {', '.join(dupes)}")
    if bad := [i for i in ids if i and not re.fullmatch(r"[A-Za-z][\w-]*", i)]:
        errors.append(f"section ids may use letters, digits, - and _ only: {', '.join(bad)}")
    if unnamed := [s.id for s in found if s.id and not s.name]:
        warnings.append(f"sections without a mktoName (Marketo shows the id instead): "
                        f"{', '.join(unnamed)}")
    for sid, spec in (dynamic or {}).items():
        if sid not in ids:
            errors.append(f"dynamic content for {sid!r}, but the email has no section with that "
                          f"id (sections: {', '.join(i for i in ids if i) or 'none'})")
        segments = spec.get("segments") or {}
        if not spec.get("segmentation"):
            errors.append(f"dynamic section {sid!r}: name its segmentation")
        if "Default" not in segments:
            errors.append(f"dynamic section {sid!r}: give the Default segment's content (people "
                          "in no segment see it)")
        for seg, body in segments.items():
            if TEMPLATE_VARIABLE.search(body or ""):
                errors.append(f"dynamic section {sid!r}, segment {seg!r}: template variables "
                              "(${...}) aren't resolved in dynamic content; write the value in")
    if len(dynamic or {}) > MAX_DYNAMIC:
        errors.append(f"{len(dynamic)} dynamic sections; keep it to {MAX_DYNAMIC} or fewer")
    return errors, warnings
