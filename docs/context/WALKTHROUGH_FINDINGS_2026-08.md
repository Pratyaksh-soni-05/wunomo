# Walkthrough Findings — 2026-08 (index)

Source: `docs/context/WALKTHROUGH_FINDINGS_2026-08.docx` — the user's raw
notes from the first end-to-end self-test of the product, written against
the expanded `docs/SELF_TEST_GUIDE.md`, with 22 screenshots embedded.

**This file is an index, not a replacement for the docx.** The docx stays
the image record — screenshots are referenced here by filename
(`imageN.ext`, matching `word/media/` inside the docx) so a later session
can find the right picture, not reproduced here. Item text below is
transcribed verbatim from the docx: original wording, typos, and phrasing
preserved exactly, not fixed, not interpreted, not merged, not resolved
into proposed solutions. Numbering matches the docx exactly (1–28) —
later sessions should cite findings by this number.

**Items 29+ are not from the docx.** They're findings surfaced by later
sessions working in this codebase (each row says which one), appended to
keep one single numbered list rather than a second competing index. Same
rules apply: logged, not fixed, not interpreted beyond what's stated.

**Class** is a light categorization only (Bug / Feature / Untested /
Design / Unclear) — it does not imply anything about severity, root
cause, or fix approach. **Guide section** is filled in only where the
user explicitly cited a step/section number in their own text — nothing
was inferred or looked up on their behalf. **Status** starts at `Open`
for every item.

---

| # | Finding (verbatim) | Guide section | Class | Screenshot(s) | Status |
|---|---|---|---|---|---|
| 1 | After first sign up of user or after every login it asks to choose workspace remove that whole thing i dont wanna choose a workspace we enter into the workspace of the last login and then in the dashboard we can toggle the workspaces but remove that pop up at the start of every login to choose workspace we directly login into the dashboard of last logged in workspace. | — | Feature | image16.jpg | Open |
| 2 | in the backend; Date and time after profiling the data source is not correct. Add data source page closes sometimes own its own on tab switichin g | — | Bug | image5.jpg (first part only — no screenshot found for the "Add data source page closes on tab switching" part) | Open |
| 3 | pipeline feature also date and time is wrong does not match the date and time of the machine or the pc. | — | Bug | image12.jpg | Open |
| 4 | In the axiom chat page there is no delete chat option for individual chat windows in the side panel | — | Feature | image15.jpg, image6.jpg | Open |
| 5 | remove the ask axiom button from the bottom left completely | — | Bug | image7.png | Open |
| 6 | Axiom -> view progress -> each task should have bigger box in which we can edit anf review at once in the edit plan tab. | — | Design | image10.png (uncertain — see note below) | Open |
| 7 | notification duration of every action or completion of the noptifications appearing on bottom left should be increased more smooth animation | — | Design | image4.png | Open |
| 8 | in step #3.30 in self test guide. After running the completion button is not coming back | §3.30 | Bug | image17.jpg (shared with item 9) | Open |
| 9 | 3.30 → 3.32 steps in self test guide are not working | §3.30–3.32 | Bug | image17.jpg (shared with item 8) | Open |
| 10 | increase all button sizes make them more aesthetic easy to click and only text is written when cursor hovers on top then a greay button boundary appears just like claude or any other website | — | Design | image21.jpg, image18.jpg, image3.jpg | Open |
| 11 | 'help' → should give error and not generate any plan in step 4.1 in self test guide but it is working and still appearing in the task list with plan approval | §4.1 | Bug | none identified | Open |
| 12 | when rejected the assurance box is not appearing back again | — | Unclear | image22.jpg (uncertain — see note below) | Open |
| 13 | Add re run buttons | — | Unclear | none identified | Open |
| 14 | step 4.50 in self test guide Terminal response not correct | §4.50 (as written) | Unclear | image20.png | Open |
| 15 | 4.54 check terminal output again | §4.54 (as written) | Unclear | image9.png | Open |
| 16 | in step 6.1 in self test guide cards not reloading after refresh | §6.1 | Bug | none identified | Open |
| 17 | 6.3 → 6.4 check from different accounts | §6.3–6.4 | Untested | image11.png | Open |
| 18 | 6.6 → dosent go to the conversation when clicked | §6.6 | Bug | image1.png | Open |
| 19 | 8.3 → SQL execute and dry run not running for csv but it should as per the sel;f test guide from claude | §8.3 | Bug | image13.png | Open |
| 20 | got logged out randomly maybe after 1 hour | — | Bug | none identified | Open |
| 21 | incidents banner does not go from dashboard notifications evenm after resolving and checking the incident. No clode button to clode the popup on investigate prompt tab | — | Bug | image2.png | Open |
| 22 | Settings page full customize it. The timezone should be a drop down menu instead of manually typing timezone and after setting timezone it should work and should be correct according to machines timezone | — | Unclear | image14.png | Open |
| 23 | Onm first sign up some questionnaire is asked for more better understanding of user so store those answers in the user profile section in the setting tab | — | Feature | none identified | Open |
| 24 | Main change very important; PUT AXIOM in a sub folder in the dashboard with all the other employees. The side panel make it free free up some space. Like first i click on ai employees then i choose axiom and then the side panel changes accordingly and all axiom chat features appear in the side panel. Axiom is not the main employee is just the first on to be built so put it with all the other employees yet to come in a sub section. | — | Feature | none identified | Open |
| 25 | double verification for changing the mail or slack url anbd invalid email task should be there when the email not verified. | — | Feature | image8.png | Open |
| 26 | approvals: check from different accounts for cicd action/ agent action | — | Untested | image19.png | Open |
| 27 | The self test guide has nothing on testing the CICD and automations feature please see into that too. | — | Feature | none identified | Open |
| 28 | ALL OF THIS HAS TO BE AUTOMATED the user upload data in the axiom chat is what we want and then the ai employee carries out all the remaining steps on its opwnm is what the main idea is just like claude code try to make the possible . make it chat friendly all the major working the user does while chatting with axiom if data needed axiom asks for it user uploads the data csv and axiom puts it in datasources and does profiling and all other steps on its own this is what we want fully automated process to reduce human effort. | — | Feature | none identified | Open |
| 29 | Nav items are not role-filtered — every logged-in user sees the identical sidebar regardless of role (a Viewer sees Team, Billing, Settings, and CI/CD listed exactly like an Owner does) and only hits a wall once they actually try to use something inside those screens. Found while investigating the sidebar's real role-gating for the 2026-08 IA restructure proposal — confirmed directly by reading `navItems.tsx`/`Sidebar.tsx`/`layout.tsx`, none of which do any role-based filtering; all real enforcement is one layer down, at the page/control level. Not fixed — logged only, per instruction. | — | Bug | none | Open |
| 30 | Governance's own **Audit Log** tab (a real, live tab inside the Governance screen) has the identical name as the sidebar's separate **Audit Logs** item (a stub page, unrelated screen) — a genuine naming collision between two different things. Already documented once, in passing, in `docs/SELF_TEST_GUIDE.md` §11's own note about this exact collision. Logged here as its own findings-index item per instruction — explicitly not renamed this session. | §11 | Design | none | Open |

---

## Notes on screenshot correlation

The docx pastes the 28-item list once, then a second pass — screenshots
each paired with a short caption — mostly in the same order as the list,
but not numbered against it. Most pairings above are unambiguous (the
caption text clearly restates the matching list item). Two are not, and
are marked "uncertain" rather than asserted:

- **image10.png** (caption: "increase box size like skip to next line to
  see what tyuped in") — placed in the docx right after item 6's theme
  (bigger edit-plan box) and before item 7's notification screenshot.
  Plausible match to item 6, not certain.
- **image22.jpg** — has no caption of its own in the docx; it sits
  immediately before a pasted excerpt of the guide's §4.2 "Reject Plan"
  text, with two other images (image18.jpg, image3.jpg, captioned
  "increase this small vague grey button all taks") right before it that
  clearly belong to item 10 instead. image22.jpg's position suggests it
  might illustrate item 12, but nothing in the docx confirms that.

## Ambiguous items — flagging rather than guessing

Per your instruction, these are described ambiguously enough that
resolving them would mean guessing your intent. Not fixed, not
interpreted above — just flagged here for you to clarify.

- **Item 12** — "the assurance box" isn't a label used anywhere in the
  app or the self-test guide. Unclear which UI element this refers to
  (the task-detail "Approve or reject this step" card? a different
  confirmation element?) and unclear whether "when rejected" means a
  rejected **plan** (§4.2) or a rejected **step** (§3.32/Reject Step).
- **Item 13** — "Add re run buttons" doesn't say where. Candidates that
  already have some form of this (Pipelines' existing "Trigger" button,
  Transforms' "Replay") vs. a genuinely new control somewhere else (Tasks?
  a failed step?) aren't distinguishable from the text alone.
- **Item 14** — cites "step 4.50," which doesn't exist in the guide (it
  only reaches §4.5, and §4.5 has 4 sub-steps, no decimal "4.50"). Can't
  tell if this means §4.5 generally, a typo for a specific sub-step, or
  something else. "Terminal response not correct" is also unclear on its
  own — which terminal, which command's output.
- **Item 15** — cites "4.54," same problem as item 14 (no such section;
  the guide's §4.5 has sub-steps 1–4, not a decimal 4.5.4). Possibly the
  same underlying observation as item 14 restated, possibly a different
  sub-step — can't tell which from the text.
- **Item 22** — "Settings page full customize it" is vague standing
  alone: unclear whether this means a broader/unspecified customization
  request beyond the timezone-dropdown ask that follows it in the same
  sentence, or whether it's just emphasis on that one fix.
