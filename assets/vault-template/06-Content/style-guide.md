# ✍️ Content Style Guide

Writing rules for every text a user can see, in every locale. Maintained by the Content & Localization
Reviewer; applied at task intake and before every release (`workflows/content-review.md`). Keep it short:
rules the team actually checks, with one example each.

**Locales:** {LOCALES} · **Last change:** {DATE}

## 1. Voice & tone
- Address the user as {you (informal) | you (formal)} per locale: {locale: form}.
- Tone: {clear, friendly, no jargon}; errors say what happened and what to do next.
- Never blame the user ("You entered an invalid value" → "Enter a value between 1 and 100").

## 2. Capitalization & punctuation
- Buttons and menu items: {sentence case | title case} per locale.
- No trailing period on labels and buttons; full sentences in messages end with a period.
- Quotation marks and dashes per locale: {ru: «…», —; uz: "…", –}.

## 3. Numbers, dates, units
- Dates: {per locale format}; times: {24-hour}; thousands separator: {space}; currency: {symbol position}.
- Units are localized ({МБ / MB}); keep the number and unit together with a non-breaking space.

## 4. Placeholders & plurals
- Placeholders keep their names across locales (`{count}`, `{0}`); never reorder positional placeholders without a format that supports it.
- Plural forms per locale: {ru: one / few / many; uz: one form}; provide every form the locale needs.

## 5. Length & layout
- Buttons ≤ {24} characters, titles ≤ {40}, list rows ≤ {60}; translations that exceed the limit need a design note.
- No text in images; accessibility descriptions describe the action, not the control.

## 6. Per-locale notes
- **{locale}:** {script (Latin / Cyrillic), apostrophe form (ʻ vs '), transliteration rules, forbidden mixed-script fragments}.
- **{locale}:** {…}

## 7. Generated & imported content
- Generated texts follow the same rules; the generating prompt links this guide and the glossary.
- Every generated item carries its locale; items whose text is in another language or script are rejected at import (see the content inventory data checks).
