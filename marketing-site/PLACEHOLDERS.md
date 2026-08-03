# Pre-deploy placeholder gate

Single checklist of every placeholder value in this app. All values below
are now real.

| Placeholder | File | Current value | Status |
|---|---|---|---|
| Cal.com booking link | `src/lib/config.ts` → `CAL_LINK` | `https://cal.com/wunomo/demo` | ✅ SET |
| WhatsApp — Pratyaksh Soni | `src/lib/config.ts` → `CONTACTS[0]` | `+91 77376 72577` | ✅ SET |
| WhatsApp — Daksh Gupta | `src/lib/config.ts` → `CONTACTS[1]` | `+91 94616 65538` | ✅ SET |
| Formspree form ID | `src/lib/config.ts` → `FORMSPREE_FORM_ID` | `mlgqqyon` | ✅ SET |
| Contact emails | `src/lib/config.ts` → `CONTACTS[*].email` | `pratyakshsoni2005@gmail.com`, `guptadaksh1509@gmail.com` | ✅ SET |

All config lives in one file (`src/lib/config.ts`) — nothing hardcodes any
of these values anywhere else (verified via grep).

**Config-level gate: cleared.** This alone doesn't mean the site is fully
deploy-ready — build cleanliness, live link verification, and visual parity
with the product app all had to hold too. See the commit that last touched
this file for the explicit deploy-readiness verdict.
