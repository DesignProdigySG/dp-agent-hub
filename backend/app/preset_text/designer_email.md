# Invitation email

1. Take every fact from the task's brief and attachments. Follow the brand guidelines' tone of
   voice when you have them.
2. **Subject** (60 characters or fewer) and **preheader** (40–90 characters, adds new
   information). Write three subject options in your summary and use the strongest.
3. **Structure** (600 px, tables, inline styles, email tokens from the design system if it
   has them): header band → hero image (`brand_images`, use "email-header", `width="600"`, alt
   text) → greeting `Hi {{lead.First Name:default=there}},` → two short paragraphs → a details
   block (date, time with time zone, place) → one bulletproof button linking to the landing
   page (the URL in the brief or the task's landing_page_url) → sign-off → the required footer
   with `{{system.unsubscribeLink}}`, your physical address and a privacy policy link.
4. **Editable sections.** The HTML becomes a Marketo email template, so mark every part the
   email fills in as a section: `<div class="mktoText" id="hero-body" mktoName="Hero Body">…</div>`
   with a unique id (letters, digits, - and _). Typically: headline, greeting and body, details
   block, button, sign-off. The header band and the footer stay outside sections (they're the
   layout). Sections can't nest.
5. **Dynamic content (when the brief asks for versions by audience):** `list_segmentations`
   shows the approved segmentations and their segments. Pick the sections that change (keep
   it to a few, never more than 20) and pass `dynamic` to `save_design`:
   `{"hero-body": {"segmentation": "<name>", "segments": {"<segment>": "<html>", …,
   "Default": "<html>"}}}`. Default is for everyone else; the section's own HTML matches it.
   Write values in: no `${…}` template variables inside dynamic content.
6. No scripts, no Tailwind classes, no background images (Outlook), no text inside images.
7. **Save:** `save_design(kind="email", name="<Event> invitation", subject=…, preheader=…,
   html=…, dynamic=…)`. Fix every error and save again.
8. **Publish to Marketo** (needs approval): `publish_email(name=<email name>,
   folder_id=<program or folder id>, folder_type=...)` creates the template, approves it, and
   creates a draft email from it with the subject, preheader and sender, then fills in every
   section (dynamic ones per segment). Publishing again updates the same email section by
   section; a layout change goes to the template. Never replace an email's whole HTML.
   Don't approve or send the email unless the task says so.
