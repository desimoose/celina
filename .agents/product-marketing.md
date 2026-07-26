# Product Marketing Context

*Last updated: 2026-07-22*

> **Status: hypothesis, not fact.** This is drafted from the product decisions made so far, not from customer interviews. Every quote in Customer Language is written *as we expect people to talk*, not verbatim from a real user. Replace them with real quotes as soon as we have five conversations. Sections marked **[unproven]** are the ones most likely to be wrong.

## Product Overview

**One-liner:** Celina researches the web for you without leaving a trail — or a bias.

**What it does:** Celina searches the web and social platforms without logging in as you, so nothing you look at is shaped by your history or tied back to your account. She keeps watching the topics you care about and tells you what changed. Everything she finds stays on your machine.

**Product category:** Private research tool. People will look for us under "anonymous search," "OSINT tool," "social listening," or "competitor research" — four different shelves, which is a positioning problem to solve, not a fact to celebrate.

**Product type:** Local-first desktop app (BYOK for model access). Not SaaS — nothing runs on our servers.

**Business model:** Free tier that is genuinely useful (bring your own key or run local models). Paid tier for continuous trend watching and the desktop build. Pricing not set. **[unproven]**

## Target Audience

**Primary: journalists and investigators.** They carry the highest stakes and the strongest motivation — tipping off a subject can kill a story or endanger a source. They also confer credibility on everyone downstream. Small market, but they decide whether this tool is trusted.

**Feeder: independent researchers and analysts.** Competitive intelligence, market analysts, consultants, strategists. Far larger, researches daily, and shares the same core problem in lower-stakes form. This is where volume and revenue come from; journalists are where trust comes from.

**Decision-makers:** Mostly the individual. Freelancers and staff reporters buy their own tools. At agencies and newsrooms, a research lead or editor may approve it, but adoption starts bottom-up.

**Primary use case:** Look into a person, company, or topic without the act of looking becoming visible or self-distorting.

**Jobs to be done:**
- "Let me look into this without them knowing I looked."
- "Show me what's actually being said, not what my feed thinks I want."
- "Tell me when something changes on a story I'm tracking, so I don't have to keep checking."

**Use cases:**
- Background a company or individual before publishing or pitching
- Watch a story develop across X, Reddit, and YouTube over weeks
- Track a competitor's launch reaction without appearing in their analytics
- Check whether a narrative is genuinely spreading or just loud in your own bubble

## Personas

| Persona | Cares about | Challenge | Value we promise |
|---|---|---|---|
| Investigative journalist | Source safety, not tipping the subject | Researching a target from a logged-in browser is visible and traceable | Look freely without leaving a trail back to you |
| Staff reporter / editor | Speed and defensibility | Needs a fast, honest read on whether a story is real and spreading | A clean, unpersonalized picture in one place |
| Competitive analyst | Signal quality | Can't tell real movement from feed noise; visits show up in competitor analytics | Results that reflect reality, not your history |
| Independent consultant | Time and cost | Enterprise listening tools are overpriced and overbuilt for one person | Serious research without an enterprise contract |

## Problems & Pain Points

**Core problem:** The moment you research from your own logged-in browser, two things go wrong at once. The platforms shape what you see based on who they think you are, so you can no longer tell what's genuinely happening from what you're being shown. And the act of looking becomes visible — to the platform, to the site, sometimes to the person you're researching.

**Why alternatives fall short:**
- Incognito only forgets things locally. Sites still fingerprint you, search engines still personalize, and platforms still log the visit.
- Private search engines fix search but do nothing for social platforms, and forget everything the moment you close the tab.
- Social listening tools are built for brand managers with budgets, not researchers with deadlines, and they have no interest in your anonymity.
- Doing it by hand — burner accounts, a VPN, a spreadsheet — works until the day discipline slips, and it always eventually slips.

**What it costs them:** A tipped-off subject can end a story outright. For analysts, a contaminated read produces a confident recommendation built on their own echo. Both lose hours a week to tab-hopping and re-checking, with no record of what changed.

**Emotional tension:** For journalists, a specific dread — that the search itself is the leak, and that their own history is discoverable later. For analysts, a quieter doubt: *is this actually a trend, or am I just seeing it a lot?* Neither wants to feel paranoid. They want to feel careful.

## Competitive Landscape

**Direct:** Incognito windows, Brave, DuckDuckGo, Startpage — solve local history and search personalization, but stop at the browser. No social research, no memory of what you were tracking, no sense of change over time.

**Secondary:** Brandwatch, Meltwater, Sprout Social — real social listening, but priced and built for brand teams, sold through demos and annual contracts, and indifferent to whether your research is private.

**Secondary:** ChatGPT, Perplexity, and general AI search — convenient, but your queries are logged on someone else's server, native access to X and Reddit is limited, and they have no memory of what you were watching last month.

**Indirect:** A burner laptop, a VPN, and a spreadsheet. Free and genuinely effective in disciplined hands. Loses to us on effort and consistency, not on capability. This is the real competitor for our best users.

## Differentiation

**Key differentiators:**
- Unprofiled by default — no login, no cookies, no account attached to the looking
- Web and social in one place, rather than six tabs and a note file
- Remembers what you're tracking and reports what changed
- Local-first: your research sits on your disk, not our servers
- Warm and plain to use, in a category that otherwise looks like a threat briefing

**How we do it differently:** Competitors treat anonymity as a privacy feature. We treat it as an accuracy feature. Being unprofiled isn't only about hiding — it's the only way to see what's actually there instead of what an algorithm has decided you want.

**Why that's better:** You get research you can trust twice over. Trustworthy because nobody watched you gather it, and trustworthy because nothing personalized it on the way in.

**Why customers choose us:** They can look into something properly without either tipping off the subject or fooling themselves.

## Objections

| Objection | Response |
|---|---|
| "Is this really anonymous, or is that just marketing?" | Say exactly what it is: unprofiled, not network-masked. Sites see a visitor with no history and no account. Your IP is not hidden unless you add that yourself. Precision here is the trust asset — overclaiming would cost us the journalist audience permanently. |
| "How is this different from an incognito window?" | Incognito forgets your history locally. It doesn't stop search personalization, doesn't cover social platforms, and forgets everything you found the moment you close it. |
| "Do I have to trust you with my research?" | No. It runs on your machine, with your own model key, and saves to your own disk. There's no account and no server for us to hand over. |
| "Can it really replace my listening tool?" | Not if you need dashboards, seats, and approval workflows. It replaces the tab-hopping, not the enterprise contract. |

**Anti-persona:** Anyone trying to de-anonymize, surveil, or harass a private individual. Also a poor fit for enterprise brand teams who need SSO, seats, and dashboards — we'd be a bad purchase and a worse support burden.

## Switching Dynamics

**Push:** A near-miss. Realizing a target could see the visit, or finding out a "trend" was only ever loud inside their own feed.

**Pull:** Being able to look at anything, from a clean slate, and have it quietly kept track of.

**Habit:** Their browser is already open and already logged in. Doing it the careful way costs an extra step, every single time. This is our hardest force to beat — the product has to be *faster* than the sloppy path, not merely safer.

**Anxiety:** "Will this actually work, or will it break on the sites I need?" And, for the security-minded: "Is a new tool a new risk?"

## Customer Language

> **[unproven] — all quotes below are anticipated, not collected.**

**How they describe the problem:**
- "I don't want them to know I've been looking."
- "I can't tell if this is actually blowing up or if it's just my feed."
- "I had six tabs open and lost half of it."

**How they describe us:**
- "It's the cat that goes and looks for you."
- "It doesn't log in as me."

**Words to use:** look into, quietly, clean, unprofiled, keeps watch, what changed, on your machine, no account

**Words to avoid:** stealth, untraceable, covert, spy, surveillance, dark web, military-grade, bulletproof — every one of these overclaims, attracts the wrong user, and scares off the professional one. Also avoid the AI-marketing register entirely: seamless, empower, unlock, revolutionize, leverage, game-changing.

**Glossary:**
| Term | Meaning |
|---|---|
| Unprofiled | Browsing with no account, cookies, or history attached, so results aren't personalized and the visit isn't tied to you |
| Trail | A topic Celina keeps watching for you over time — deliberately doubles as the investigative sense of the word |
| Sources | What social platforms are saying about a topic |
| Clean result | A result shaped by relevance rather than by your history |

## Product Principles — the house cat

This governs product behaviour, not just artwork. It is the most important section in this document.

A really nice house cat is around without demanding anything. It goes off and does its own thing, comes to you when it has a reason, and never needs managing. You trust it in the house unsupervised. It is the same every day, and that dependability is the whole point of it.

| A good house cat | Celina |
|---|---|
| Doesn't demand attention | No notifications designed to pull you back |
| Goes off and does its own thing | Trails run without a dashboard to watch |
| Comes to you when there's a reason | She surfaces when something changed — and once to say nothing did |
| Never needs managing | No tuning, no maintenance, no configuration anxiety |
| Doesn't perform for you | No streaks, no badges, no "you haven't searched in 3 days" |
| Is the same every day | Boring reliability is the feature |
| Comfortable with silence | An empty result is a finished answer, not a failure |

**This is deliberately the opposite of standard engagement design.** Our audience already has too many things competing for their attention; a research tool that nags is a research tool that gets uninstalled. Retention comes from being dependable enough to become habit, not from manufactured re-engagement.

The test for any new feature: *would a good house cat do this?* If it demands attention, needs maintenance, or performs for approval, it doesn't ship.

**Celina stays in — as a house cat, not a widget.** She appears on the icon, the site, the first-run line, and in the app itself: she has her own quiet corner and rests there. The restraint isn't hiding her; it's in her behaviour. She does not react to your actions, animate while you read, or perform for approval — a cat shares the room without running it. That distinction is what lets the same product serve someone who wants a companion on screen and someone who wants the software to disappear: she's visible and warm, and she's ignorable. The character carries the warmth; her stillness keeps the interface out of the way.

## Brand Voice

**Tone:** Warm, plain, and quietly competent. Calm rather than urgent. Never breathless, never ominous.

**Style:** Short, concrete sentences. Say the actual thing. Occasional dry humor, mostly through Celina herself. No hype vocabulary, no exclamation marks, no fear-based selling — the category is already saturated with alarm, and our users are tired of it.

**Personality:** Curious, discreet, unhurried, dependable, warm.

**Character:** Celina is a black Persian cat. She's the reason the product feels approachable instead of clinical. She observes without being noticed, goes and looks on your behalf, and comes back with what she found. Use her for warmth and for explaining what's happening — never for cuteness that undercuts reliability. She is competent first and charming second.

**Visual direction:** Studio Ghibli meets Hanna-Barbera. From Ghibli: soft painted backgrounds, natural warm light, a sense of place, and visible hand-made imperfection. From Hanna-Barbera: flat bold shapes, confident economical linework, a limited palette, mid-century graphic simplicity. Explicitly *not* Toei, and explicitly not the dark, neon, hooded-figure look every privacy tool defaults to.

Warm light is the default theme, not dark — that's the contrarian, memorable choice in this category. Dark mode is supported, and Celina reads well in both.

Working palette:
| Role | Colour |
|---|---|
| Paper (background) | `#F5F1E8` warm cream |
| Ink (Celina, text) | `#1E1B1A` warm near-black, never pure black |
| Sage | `#7E9B8A` |
| Dusty sky | `#8FB0C4` |
| Amber (accent) | `#E0A44C` — her eyes; the one bright thing in the mark |

## Proof Points

**Metrics:** None yet. Pre-launch.

**Customers:** None yet.

**Testimonials:** None yet. Do not fabricate any, and do not ship a testimonial section with placeholders — in a trust-led category, a fake quote is fatal.

**Value themes:**
| Theme | Proof |
|---|---|
| Looking doesn't leave a trail | No account, no cookies, no login. Demonstrable in the product. |
| Results aren't shaped by you | Side-by-side: same query logged-in vs. unprofiled. This comparison is our single best demo. |
| Your research stays yours | Runs locally, BYOK, files on your own disk. Verifiable — the code is open. |
| It keeps watching so you don't | Trails report what changed since you last looked. |

## Goals

**Business goal:** Earn trust with a small, credible group of journalists and investigators, then convert the much larger analyst audience that follows them.

**Conversion action:** Download and run a first search. There's no signup, so activation is the first Trail created — that's the moment the product becomes habit rather than novelty.

**Current metrics:** None. Pre-launch, pre-rename.

## Naming and IA

**Product:** Celina. **Mascot:** a black Persian cat, same name.

Three surfaces, deliberately named in plain language so the character carries the warmth and the interface carries the credibility:

| Surface | What it does |
|---|---|
| **Search** | One query, clean results, no profile attached |
| **Sources** | What social platforms are saying right now |
| **Trails** | Topics Celina keeps watching, and what changed |

Feature names stay plain on purpose. Cute function names ("Prowl," "Pounce") would undercut the reliability we're selling and age badly.
