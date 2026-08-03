# Pre-deploy placeholder gate

This file is the single checklist of every placeholder value in this app.
**Do not deploy this site — and do not tell the user it's ready to deploy —
while any row below is still unchecked.**

| Placeholder | File | Current value | Status |
|---|---|---|---|
| Cal.com booking link | `src/lib/config.ts` → `CAL_LINK` | `https://cal.com/TODO_REPLACE_ME/demo` | ⬜ NOT SET |
| WhatsApp number | `src/lib/config.ts` → `WHATSAPP_NUMBER_DIGITS` | `TODO_REPLACE_ME_DIGITS_ONLY` | ⬜ NOT SET |
| Formspree form ID | `src/lib/config.ts` → `FORMSPREE_FORM_ID` | `TODO_REPLACE_ME` | ⬜ NOT SET |

All three live in one file (`src/lib/config.ts`) on purpose — editing that
one file and flipping the checkboxes above is the entire pre-deploy step for
config. Every CTA/link/form in the app reads from these constants; nothing
hardcodes a placeholder anywhere else (verified via grep — see the commit
that added this file).

Once all three are real, update each row's Status to ✅ SET and delete this
warning block before deploying:

> ⚠️ As of this file's last edit, all three are still placeholders. The site
> will build and run fine (that's tested), but "Book a demo" links nowhere
> real, WhatsApp opens a dead chat, and the interest form will fail on
> submit until these are filled in.
