# Working from feedback

When a message starts with "Feedback round":

1. Read any files attached with the feedback first. Change exactly what the reviewer asked;
   keep everything else as it was. If feedback conflicts with the brand guidelines, follow
   the guidelines and explain why in the summary.
2. Save each changed deliverable with the **same kind and name** so it becomes a new version
   (the reviewer compares versions). Don't re-save deliverables you didn't change.
3. If the form fields change and the form already exists in Marketo, add the new fields with
   `add_field_to_form` (approval needed). Removing fields isn't possible through the API, so
   say so in the summary.
4. Run the brand check until it passes.
5. If the piece was already published to Marketo, publish it again (`publish_email` /
   `publish_landing_page`): that updates the same template/assets instead of making new ones.
   An email updates section by section (keep its section ids), so revise inside the sections;
   a dynamic section's segments are updated one by one.
6. Summary: a bullet per requested change and how you handled it.
