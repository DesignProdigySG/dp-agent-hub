# Email verification (ZeroBounce)

Attach this skill to let the Data Doctor's data health scan verify email deliverability with
ZeroBounce. Without it, emails are only checked for free (format, placeholder and disposable
domains, DNS, Marketo's own flags and hard bounces).

- Needs the ZeroBounce API key in Settings > Email & phone verification.
- Costs about USD 0.008 per email. Only emails that pass every free check are sent, at most
  "Max paid checks per scan" per scan, and every result is cached for 90 days, so the same
  address is never paid for twice.
- `valid` and `catch-all` count as deliverable. `invalid`, `spamtrap`, `abuse`, `do_not_mail`
  and `unknown` make the lead unreachable by email (Contactability).
- Results show in the scan report under "How this scan ran".
