# Your brand pack (optional)

The Designer tools (`save_design`, `brand_images`, `publish_email`, `publish_landing_page`)
read this folder to keep pages and emails on brand. Everything here is optional: whatever
you add is checked, and whatever you leave out isn't.

With this folder empty the Designer still works: any image and any colour are allowed,
previews use Tailwind's default palette, and `publish_email` needs a sender passed to it.

## The files

Put them directly in this folder (`backend/brand/`). The `example/` folder has a working
sample of each one; copy what you need and edit it.

| File | What it does |
|---|---|
| `brand.json` | Your brand's name, the default email sender (`from_name`, `from_email`, `reply_email`), the `footer_address` every email must include, your `privacy_url`, and `banned_words` the voice check warns about. Every key is optional. |
| `design_system.md` | Your design system in Markdown. The hex values under a heading called **Colour tokens** (or **Color tokens**) become the only colours allowed in pages and emails. A `<script>tailwind.config = {...}</script>` block, if present, is used in previews. The whole file becomes a knowledge document for the Designer. |
| `brand_guidelines.md` | Tone of voice, logo rules, do's and don'ts. Becomes a knowledge document for the Designer. |
| `images.json` | The approved image library: `{"images": [{"id", "url", "alt", "tags", "uses", "photographer"}]}`. When present, pages and emails may only use these images (matched by URL, ignoring `?size` parameters). The `brand_images` tool searches it. |
| `form_style.js` | A script added after every embedded Marketo form, e.g. to restyle the form to match your pages. |

## Using it

1. Add your files here.
2. Restart the backend.
3. Install the Designer preset, which attaches your brand files as knowledge:
   `cd backend && .venv/bin/python -m app.presets designer`
   (or create your own designer on the Agents page and attach the documents yourself).

If you change the files later, run the preset again to refresh the knowledge documents.

To keep your brand somewhere else, set `BRAND_DIR=/path/to/folder` in `.env`.
