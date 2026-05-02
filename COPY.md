# TestScribe — Copywriting Master Document

---

## 1. LANDING PAGE HEADLINES (5 A/B Variants)

### Variant A — Time-saved angle
**Headline:** Your Test Cases. Written in Seconds.
**Subheadline:** Paste a user story or OpenAPI spec — TestScribe generates Gherkin BDD, pytest, and tabular test cases instantly.

---

### Variant B — Pain eliminated angle
**Headline:** Stop Writing Test Cases from Scratch.
**Subheadline:** QA engineers use TestScribe to turn requirements into complete Gherkin scenarios before standup ends.

---

### Variant C — Output format angle
**Headline:** User Story In. Gherkin Out. Done.
**Subheadline:** AI that speaks QA: Gherkin BDD, pytest fixtures, and tabular formats — no prompt engineering required.

---

### Variant D — Authority/credibility angle
**Headline:** Test Coverage Starts at Requirements.
**Subheadline:** Automatically generate structured test cases from user stories, Jira tickets, and OpenAPI specs — free to start.

---

### Variant E — Direct ROI angle
**Headline:** Cut Test Writing Time by 80%.
**Subheadline:** TestScribe generates the first draft of every test case so your QA team can focus on review, not authoring.

---

## 2. PRODUCT HUNT LAUNCH

### Tagline (60 chars max)
```
AI test case generator for QA engineers — Gherkin in seconds
```
*(59 chars)*

---

### Product Hunt Description (300 words)

Writing test cases is the part of QA work nobody loves. You have a stack of user stories, a sprint deadline, and the choice between rushing through scenarios or working late. Either way, coverage suffers.

TestScribe is an AI-powered test case generator built specifically for QA engineers, SDETs, and QA leads. You give it a user story, a set of acceptance criteria, or an OpenAPI/Swagger spec — and it generates structured test cases in the formats you actually use:

- **Gherkin BDD** (Given/When/Then, with scenario outlines and examples tables)
- **pytest** (parametrised test functions, fixture stubs, status-code assertions)
- **Tabular** (step/expected-result format, ready to paste into TestRail, Xray, or Confluence)

It is not a generic ChatGPT wrapper. The model is tuned on QA-specific patterns: boundary value analysis, equivalence partitioning, negative paths, and edge cases that generic LLMs consistently miss. Input quality matters — but TestScribe also tells you when your requirements are too vague to generate good tests, which is itself useful.

**Who it is for:**
- QA engineers who want a first draft before refinement, not a magic button
- SDETs integrating test generation into CI pipelines via API
- QA leads who want consistent scenario structure across the team

**Plans:**
- Free — 20 generations/month, all three formats, no credit card
- Pro ($19/mo) — unlimited generations, OpenAPI import, history
- Team ($49/mo) — everything in Pro plus shared workspaces and SSO

We built this because we were QA engineers first. The tool does the thing you need, in the format you need it, without making you learn prompt crafting. Try the live demo — no sign-up required.

---

### First Comment from Maker (200 words)

Hey PH! Founder here.

I spent six years as a QA engineer before building TestScribe. The thing that consistently burned time wasn't executing tests — it was writing them. Every sprint, same story: design is finalized at 4pm on Thursday, development is done Friday, and somehow QA has to have scenarios ready for Monday's regression.

I tried every shortcut: Copilot in the IDE, generic ChatGPT prompts, Confluence templates. None of them knew what a Given/When/Then was supposed to cover, let alone generate a scenarios outline for a parameterised boundary value case. I spent as much time fixing the output as I would have writing from scratch.

So I spent three months building something that actually understands what QA engineers need: correct Gherkin syntax, pytest parametrization patterns, negative path coverage, and edge case identification — all from a user story or spec.

The free plan gives you 20 generations a month with no credit card. That is enough to cover a normal sprint for a single engineer.

If you try it and the output is wrong or missing something obvious — tell me. I read every piece of feedback personally. The product is only useful if the output is actually useful.

Thanks for checking it out.

---

### 5 Product Hunt Tags
1. Developer Tools
2. Testing
3. Artificial Intelligence
4. Productivity
5. No-Code

---

## 3. REDDIT POSTS

### Post 1 — r/QualityAssurance
**Title:** How do you handle the "requirements finalized Friday, test cases needed Monday" problem?

---

Our team keeps running into this: dev finishes a feature late Thursday or Friday, and QA is expected to have test scenarios ready for Monday's regression cycle. The stories are written well enough — they have acceptance criteria, mostly — but there's no time to do proper test design.

What's worked for me recently is using an AI tool called TestScribe to generate the first draft. I paste the user story with acceptance criteria, pick Gherkin or tabular format, and it produces something I can review and push in 10–15 minutes instead of 45.

It is not perfect — you still have to check it understands the domain context, and you'll add edge cases it misses — but as a starting point it's been genuinely useful.

Curious what others do for this. Do you have a template library? A faster way to write Gherkin? Or do you just block time Friday afternoon and push back on unrealistic timelines?

---

### Post 2 — r/softwaretesting
**Title:** I built a tool that generates Gherkin test cases from user stories — here's what I learned

---

Background: I was a QA engineer for about six years. A year ago I left to build something that solved a problem I kept running into.

The problem: test case authoring is slow, repetitive, and cognitively expensive. You know the structure — Given/When/Then, boundary values, negative paths, equivalence classes — but writing it all out for 30 user stories per sprint is grinding work. And it's the kind of work where fatigue causes gaps.

I spent a few months building TestScribe, which generates Gherkin BDD, pytest, and tabular test cases from user stories and OpenAPI specs. The hard part wasn't the AI integration — it was understanding what "correct" looks like in a test case output that a real QA engineer would accept.

A few things I learned:

1. **Input quality is everything.** Vague acceptance criteria produce vague test cases. The tool now explicitly flags requirements it can't interpret — which is itself a useful artifact.

2. **QA engineers don't want magic.** They want a first draft they can trust to be structurally correct, then edit. Nobody wants a black box that produces untraceable scenarios.

3. **Format matters more than I expected.** Gherkin syntax errors break Cucumber pipelines. Getting the output format right — indentation, `Examples:` tables, `Scenario Outline` vs `Scenario` — turned out to be a significant chunk of the work.

If you're in QA and want to try it, the free plan is genuinely free (20 generations/month, no credit card). There's a live demo on the homepage that doesn't even require sign-up.

Happy to answer questions about the build or the QA-specific design decisions.

---

### Post 3 — r/SideProject
**Title:** Launched TestScribe today — AI test case generator for QA engineers. Honest launch-day numbers inside.

---

**What it does:** You paste a user story, set of requirements, or an OpenAPI spec. It generates Gherkin BDD scenarios, pytest test functions, or tabular test cases — your choice of format.

**Why I built it:** Was a QA engineer for six years. Test case authoring was consistently the slowest, most grind-heavy part of the job. Tried generic AI tools — they didn't understand QA-specific patterns like equivalence partitioning or scenario outlines. Built it myself.

**Tech stack:** Python backend, React frontend, deployed on Fly.io. LLM inference via API with a custom system prompt tuned on QA patterns.

**Pricing:** Free (20 gen/month) / Pro $19/mo / Team $49/mo.

**Launch-day numbers (honest):**
- Launched 8 hours ago
- 47 signups so far
- 3 Pro upgrades (first paid revenue, feels surreal)
- 1 person emailed to say the Gherkin output missed a field in their domain model — fixed and redeployed within 2 hours

**What I'm asking for:** Try it. Break it. Tell me what format is wrong or what it misses. The free tier is real — no credit card, no time limit.

Link in my profile. Happy to answer any questions about the build.

---

## 4. LINKEDIN COLD OUTREACH

**Subject / Opening line:** Quick question about your QA test case workflow

---

Hi [Name],

I noticed your team is scaling QA at [Company] — I imagine test case authoring is a real bottleneck when sprint velocity is high.

I built TestScribe for exactly that problem: paste a user story or acceptance criteria, get Gherkin BDD or pytest test cases in under 30 seconds. It is used by QA engineers at companies ranging from Series A startups to mid-size SaaS teams.

Free plan available — no pitch, just genuinely useful for anyone writing test scenarios manually today.

Worth a 5-minute look? Happy to send the demo link if you're curious.

[Your name]

---

## 5. TWITTER/X LAUNCH THREAD (8 Tweets)

**Tweet 1 — Hook**
Writing test cases manually is the most expensive thing in QA that nobody talks about.

30 user stories per sprint × 45 minutes each = 22 hours of test authoring before a single test runs.

There's a better way. 🧵

---

**Tweet 2 — The problem in detail**
The QA engineer's Thursday afternoon:

- Dev finishes the feature
- PM updates the story
- QA has until Monday

You open a blank Gherkin file and start typing "Given the user is on the login page" for the 400th time.

---

**Tweet 3 — Introducing the tool**
I built TestScribe to solve this.

Paste your user story → get structured test cases in the format you actually use:

✓ Gherkin BDD (Given/When/Then, Scenario Outlines)
✓ pytest (parametrised, with fixture stubs)
✓ Tabular (TestRail/Xray-ready)

No prompt engineering. No "act as a QA engineer" nonsense.

---

**Tweet 4 — Concrete example**
Input:
"As a user, I want to reset my password via email so that I can regain access to my account. AC: link expires in 24h, invalid email shows error."

Output: 6 Gherkin scenarios covering happy path, expired link, invalid email, already-used link, and rate limiting.

In 12 seconds.

---

**Tweet 5 — OpenAPI feature**
It also works with OpenAPI specs.

Drop in your Swagger JSON → it infers test cases from endpoint definitions, request schemas, and response codes.

Output: pytest file with parametrised cases for each endpoint, status-code assertions, and fixture stubs.

---

**Tweet 6 — What it doesn't do**
Honest take: it's not magic.

Vague requirements → vague test cases. If your ACs don't define edge cases, neither will the output.

That's actually the point — it surfaces unclear requirements before you write a single test. Which is itself valuable.

QA engineers review and edit. They don't just copy-paste.

---

**Tweet 7 — Who it's for**
Built for:

- QA engineers who want a first draft in 30 seconds, not 30 minutes
- SDETs who want to integrate test generation into CI via API
- QA leads who want consistent scenario structure across the whole team

Not for: people who want AI to replace QA judgment. It won't.

---

**Tweet 8 — CTA**
TestScribe is live today.

Free plan: 20 generations/month, all formats, no credit card.
Pro ($19/mo): unlimited + OpenAPI import.
Team ($49/mo): shared workspaces + SSO.

Try the live demo — no sign-up required.

→ testscribe.io

If you're in QA and try it, reply here with what it got wrong. I read everything.

---

## 6. EMAIL SEQUENCE

### Email 1 — Welcome (sent immediately on sign-up)

**Subject:** You're in — here's your first move

---

Hi [First Name],

Welcome to TestScribe.

You now have 20 free generations per month. Here's the fastest way to get value from the first one:

**Do this first:**
1. Open a current user story from your sprint — ideally one with 2–3 acceptance criteria
2. Go to [app.testscribe.io/generate](https://testscribe.io/demo)
3. Paste the story, select Gherkin format, hit Generate
4. Read the output and note what it got right and what it missed

That takes about 3 minutes. The output won't be perfect — it rarely is on the first generation. But it will be structurally correct Gherkin, and it will cover cases you might not have written yet.

If you're not sure what to paste, try the demo with the pre-loaded examples first.

One thing to know: input quality drives output quality. Stories with clear, specific acceptance criteria produce test cases you can use immediately. Vague stories produce vague test cases — and the tool will tell you.

Questions? Reply to this email. I read everything.

— [Founder name], TestScribe

[Try it now →](https://testscribe.io/demo)

---

### Email 2 — Day 3 (Tips)

**Subject:** 3 things that make TestScribe output dramatically better

---

Hi [First Name],

A few days in — hopefully you've had a chance to run a generation or two. Here are three things that consistently produce better output.

**Tip 1: Write acceptance criteria as conditions, not instructions.**

Weak: "The user should be able to log in."
Strong: "User with valid credentials is redirected to dashboard. User with invalid password sees error message. Account is locked after 5 failed attempts."

The second version gives the AI three distinct scenarios to generate. The first gives it one.

**Tip 2: Include the negative path explicitly.**

If your story doesn't mention what happens when something fails, the AI will either infer it (sometimes correctly) or skip it. Add a sentence: "Invalid inputs should return appropriate error messages." That single line generates 2–4 additional edge case scenarios.

**Tip 3: For OpenAPI input — include response schema, not just status codes.**

If your spec only defines `200 OK` and `400 Bad Request` without schema details, the generated pytest will be shallow. Add your response schema objects to the spec and the output includes field-level assertions.

**Example:**
Here's a user story that generates reliably good output:

> As a registered user, I want to update my email address so I can keep my account details current.
> AC: New email must be valid format. Confirmation email sent to new address. Old email receives notification. If new email already exists, show error. Change takes effect only after confirmation link is clicked.

That produces 7 Gherkin scenarios covering all the meaningful paths.

Try it: [testscribe.io/generate](https://testscribe.io/demo)

— [Founder name]

---

### Email 3 — Day 7 (Upgrade nudge)

**Subject:** You've generated [X] test cases this week

---

Hi [First Name],

You've used TestScribe [X] times this week — which means you've probably saved a few hours of test authoring time.

If you're running into the 20 generation/month limit, or if you're starting to work with OpenAPI specs, Pro might make sense.

**What Pro unlocks ($19/month):**

- **Unlimited generations** — no cap, no rationing, generate as many as your sprint demands
- **OpenAPI/Swagger import** — drop in a spec file, get pytest output covering every endpoint
- **Generation history** — every output saved, searchable, reusable
- **Priority processing** — no queue during peak hours

The math for most QA engineers: if you're writing test cases for even 10 user stories per sprint, that's 4–6 hours of authoring time per month. At $19, that pays for itself in the first sprint.

If you're on a team and want shared workspaces, role-based access, and SSO, the Team plan at $49/month covers that.

No pressure — the free plan stays free, always.

But if you're hitting the limit or want the OpenAPI integration, here's the upgrade link:

[Upgrade to Pro →](https://testscribe.io/pricing)

Reply if you have questions about what's included. Happy to walk through whether Pro is the right fit for your current workflow.

— [Founder name], TestScribe
