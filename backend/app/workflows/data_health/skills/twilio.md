# Phone verification (Twilio Lookup)

Attach this skill to let the Data Doctor's data health scan validate phone numbers with
Twilio Lookup v2. Without it, numbers are only checked by rules (digit count per country,
North American area codes, placeholder digits, Do Not Call).

- Needs the Twilio Account SID and auth token in Settings > Email & phone verification.
- Uses Lookup's basic number validation, which Twilio doesn't charge for. Only numbers that
  pass the rules and can be written in +international form are sent, at most "Max paid checks
  per scan" per scan, and results are cached for 90 days.
- An invalid number makes the phone channel unusable (Contactability).
