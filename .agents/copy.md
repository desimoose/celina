# Celina — Core Copy & Voice (MVP)

*Last updated: 2026-07-22. Companion to `.agents/product-marketing.md`.*

Every string here is meant to ship as written. Where a screen isn't listed, it isn't in the MVP.

---

## The tension, and how it resolves

We're writing for two people at once: someone who wants a new thing to have character, and someone who wants the interface to disappear so they can work.

**Charm lives in the words. Restraint lives in the chrome.**

Celina is warm and dry in what she *says*. She is invisible in how she *behaves*. That means:

- No onboarding tour, no coach marks, no tooltips that follow you
- No animation over content you're reading
- Nothing that needs dismissing
- No celebration, no streaks, no "how did I do?"
- She never speaks unless she's reporting something you asked for
- She's on screen in her own corner, but she rests there — she doesn't react to your clicks or narrate what you're doing

**Celina is present, the way a house cat is present.** She's on the icon, the site, the first-run line — and yes, she's in the app: she has her own quiet corner and she rests there. What she does *not* do is react to your every action, animate over what you're reading, or perform for approval. A cat shares the room without running the room. That's the line: she's visible and warm, and she's ignorable. Gen Alpha gets a companion on screen; Gen X gets a sleeping cat they can look right past.

Read as a character, the copy is funny. Read as status output, it's terse and informative. Same words, both audiences, no toggle.

---

## Voice

**Celina reports. She doesn't perform.**

| Do | Don't |
|---|---|
| "Found 14. Three are new." | "I found some great results for you!" |
| "Quiet everywhere I looked." | "Hmm, looks like there's nothing here! 😿" |
| "That site blocked me." | "Oops! Something went wrong." |
| "I checked Tuesday and again today." | "I'm always working hard for you!" |

**Rules:**

1. Short, complete sentences. Full stops, not exclamation marks.
2. First person, sparingly. Mostly she just states what's there.
3. Never apologetic theatre. Say what happened and what to do next.
4. No emoji. No meowing. No cat puns — at most one cat reference in the whole app, and we haven't spent it yet.
5. The cat-ness lives in word choice: *looked, watched, waited, quiet, left it alone, came back*. Never in costume.
6. She never nags. If nothing happened, she says so once and stops.
7. Never sell inside the product. The app is not a landing page.

**She is competent first, charming second.** If a line is cute at the cost of being clear, the line loses.

---

## Positioning copy

**Name:** Celina

**Tagline:** Goes and looks. Leaves nothing behind.

**One-liner:** Celina searches the web and social platforms without logging in as you — so results aren't shaped by your history, and nobody can tell you were looking.

**Description (app stores, README, ~50 words):**
> Celina is a quiet research tool. She looks things up without an account, so what comes back is shaped by the topic instead of your history. She reads social platforms too, and keeps watching the topics you care about. Everything stays on your machine.

**Alternate taglines** (hold in reserve, don't A/B in MVP):
- A quieter way to look things up.
- She looks. You read. Nobody's counting.

---

## The core claim — write it precisely, every time

This is the sentence the whole product rests on. Never soften it, never inflate it.

**Short form:** No account. No cookies. No history shaping what comes back.

**Full form, used once in Settings and once on the site:**
> Celina doesn't log in as you. Sites see a visitor with no history, so results aren't personalized and the visit isn't tied to your accounts.
>
> Your IP address is not hidden. If you need that, run a VPN alongside her.

That second paragraph is not optional. Overclaiming costs us the journalists permanently, and honesty about the boundary is the most persuasive thing on the page.

---

## Screens

### First run

There is no welcome screen. The app opens on the search field with one line above it.

```
Hello. I'm Celina.
Ask me to look something up. I won't log in as you.

[ What should I look into?              ]  [ Look ]
```

If no model key is set, a single quiet line sits below the field — not a modal:

```
I need a model to think with. Add a key or run one locally. → Settings
```

### Search

| Element | Copy |
|---|---|
| Field placeholder | `What should I look into?` |
| Button | `Look` |
| Results header | `14 results` |
| Privacy badge (next to header) | `no account · no cookies` |
| Save action | `Keep this` |
| Zero results | `Nothing. Either it isn't out there, or it's behind a login I won't use.` |
| Site blocked | `That site blocked me. I don't log in to get around it — that's rather the point.` |
| Site slow / no answer | `That one didn't answer. I'll leave it and carry on.` |

### Sources

| Element | Copy |
|---|---|
| Empty state | `Give me a topic and I'll see what people are actually saying — not what your feed would show you.` |
| Field placeholder | `What's the topic?` |
| Section headers | `Reddit` · `X` · `YouTube` · `Hacker News` |
| Result meta | `1,204 upvotes · 3 days ago` |
| Zero results | `Quiet everywhere I looked.` |
| Scope caveat (always visible, small) | `I only read what's public. Anything behind a login stays there.` |

### Trails

The retention surface. A trail is a topic Celina keeps watching.

| Element | Copy |
|---|---|
| Empty state | `A trail is a topic I keep watching. I'll check on it and tell you what changed, so you don't have to keep looking.` |
| Empty CTA | `Start a trail` |
| Create — name | `What are you following?` |
| Create — frequency | `Check on it: Daily / Weekly` |
| Create — confirm | `Watching. I'll tell you when something moves.` |
| Digest, changes found | `Three things changed on Acme layoffs since Tuesday.` |
| Digest, nothing found | `Nothing new on Acme layoffs. I checked Tuesday and again today.` |
| Paused | `I've stopped watching this. Say the word and I'll pick it back up.` |
| Delete confirm | `Stop watching this and forget what I've collected?` |

> **The "nothing changed" line is load-bearing.** Most tools go silent when nothing happens, which reads as broken. Celina reporting that she checked and found nothing is what makes her feel reliable — and it's the line that turns the app into a habit. Never suppress it.

### Settings

Two lines, then fields. Nobody enjoys this screen; get them out of it.

```
Celina needs a model to think with.
Bring your own key, or run one locally. Either way it never passes through us.

Anthropic     [ sk-ant-…            ]
OpenAI        [ sk-…                ]
OpenRouter    [ sk-or-…             ]
xAI           [ xai-…               ]
Local         Run with Ollama — no key needed

Your keys stay in a file on this machine. There's no account, so there's
nothing for us to hand over.
```

---

## Celina's line bank

Short status lines shown while she works. Rotate; never repeat within a session. Each must be under six words.

**Looking (web):**
- Looking.
- Reading the first few.
- Checking who else says this.
- Following a link.

**Looking (social):**
- Reading Reddit.
- Seeing what X makes of it.
- Counting how often this comes up.
- Sorting the loud from the many.

**Coming back:**
- Found 14. Three are new.
- Two of these say the same thing.
- Most of this is one week old.
- Found plenty. Little of it useful.

**Nothing there:**
- Quiet everywhere I looked.
- Nothing worth bringing back.
- Everyone's saying the same three things.

---

## Errors

**Rule: what happened, then what to do. Never blame the user, never hide the cause, never say "oops".**

| Situation | Copy |
|---|---|
| No model key | `No model key yet. Add one in Settings, or switch to a local model.` |
| Provider rejected the key | `Anthropic didn't accept that key. Check it in Settings.` |
| Provider unreachable | `Anthropic didn't answer. Try again, or switch model at the top right.` |
| Local model not running | `Ollama isn't running. Start it, or switch to a hosted model.` |
| Rate limited | `That's as fast as they'll let me go. Try again shortly.` |
| Site blocked her | `That site blocked me. I don't log in to get around it — that's rather the point.` |
| Nothing saved yet | `Nothing kept yet. Anything you keep lands here.` |
| Disk write failed | `Couldn't save that — the workspace folder isn't writable.` |

---

## Words

**Use:** look into · quietly · clean · unprofiled · keeps watch · what changed · on your machine · no account · public

**Never use:**

*Overclaims that would cost us journalists* — untraceable · stealth · covert · anonymous browsing · spy · surveillance · military-grade · bulletproof · dark web

*AI-marketing register* — seamless · empower · unlock · revolutionize · leverage · game-changing · supercharge · effortless · cutting-edge

*Interface filler* — Oops · Uh oh · Whoops · Something went wrong · Please wait · Loading… · Are you sure?

**On "anonymous":** we say Celina researches *without logging in as you*, or that a search is *unprofiled*. We do not say she makes **you** anonymous — she doesn't hide your IP, and the distinction is the honest one.
