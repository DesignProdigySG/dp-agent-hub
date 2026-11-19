# Landing page with a Marketo registration form

1. **Read the brief and the facts.** The facts (dates, venue, agenda, fields) come from the
   task: its description and its attachments (via `read_attachment` / `search_attachments`
   when they're long). Search your knowledge for the brand guidelines and the design system.
   Use facts exactly; never invent dates, prices or names, and never reuse facts from earlier
   tasks. If a fact is missing, write "[TBC: …]" and list it in your summary.
2. **Pick images** with `brand_images` (e.g. use "hero"). If the brand has an image library,
   use only what it returns. If it has none, use images from the task, or a marked placeholder.
3. **Save the form spec first:** `save_design(kind="form", name="<Event> registration",
   fields=[…], button="Register")`. First name, last name and email are automatic; add only
   the fields the brief needs (Marketo field IDs: Company, Title, MobilePhone, Phone, or a
   custom field ID).
4. **Build the page** as one complete HTML document:
   - `<title>`, `<meta name="viewport" content="width=device-width, initial-scale=1">`, the
     Tailwind Play CDN script, and the brand's `tailwind.config` and fonts if the design
     system has them.
   - Hero → why attend (3 points) → details (when, where) → registration panel containing
     `{{marketo_form}}` exactly once → short FAQ → footer.
   - One primary button (it scrolls to `#register`).
   - When the design system has a palette, only its colours (no other hex values).
5. **Save it:** `save_design(kind="landing_page", name="<Event> landing page", html=…)`. Fix
   every error the check returns and save again. Warnings: fix them unless you have a reason.
6. **Create the form in Marketo** (needs approval):
   - The form lives in the event's program: `create_form(name, folder={"id": <program id>,
     "type": "Program"})`, then `add_field_to_form` once per extra field (never FirstName,
     LastName or Email).
   - Record the new ID: `save_design(kind="form", name=<same name>, marketo_form_id=<id>)`.
     The landing page then embeds the real form.
7. **Publish the page to Marketo** (needs approval): the page goes in the event's program
   (folder_type "Program"); only its template goes in Design Studio (`template_folder_id`). Find
   them with `asset_get_folder_by_name` (or `asset_get_folder` to browse), then
   `publish_landing_page(name=<page name>, folder_id=<id>, folder_type="Program" or "Folder")`.
   It creates a free-form landing page template and a draft landing page from it. Don't
   approve it: a person reviews and approves in Marketo.
   - If Marketo refuses (603), the API user's role lacks Asset permissions: say so plainly in
     the summary; the preview and "Copy for Marketo" still work.
8. **Finish** with a short summary: what you made, the images used, the Marketo IDs (form,
   template, landing page), any [TBC] items.
