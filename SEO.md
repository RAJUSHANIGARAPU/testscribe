# TestScribe — SEO Master Document

---

## 1. META TAGS

### index.html (Landing Page)

```html
<title>TestScribe — AI Test Case Generator for QA Engineers</title>
<meta name="description" content="Generate Gherkin BDD, pytest, and tabular test cases from user stories or OpenAPI specs in seconds. Free plan available. Built for QA engineers." />

<!-- Open Graph -->
<meta property="og:title" content="TestScribe — AI Test Case Generator for QA Engineers" />
<meta property="og:description" content="Generate Gherkin BDD, pytest, and tabular test cases from user stories or OpenAPI specs in seconds. Free plan available." />
<meta property="og:type" content="website" />
<meta property="og:url" content="https://testscribe.io/" />
<meta property="og:image" content="https://testscribe.io/assets/og-cover.png" />

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="TestScribe — AI Test Case Generator for QA Engineers" />
<meta name="twitter:description" content="Paste a user story, get Gherkin BDD test cases instantly. Free plan available. No prompt engineering needed." />
<meta name="twitter:image" content="https://testscribe.io/assets/og-cover.png" />

<!-- Canonical -->
<link rel="canonical" href="https://testscribe.io/" />
```

---

### demo.html

```html
<title>Live Demo — TestScribe AI Test Case Generator</title>
<meta name="description" content="Try TestScribe free. Paste a user story or requirements doc and watch it generate Gherkin BDD and pytest test cases in real time." />
<link rel="canonical" href="https://testscribe.io/demo" />
```

---

### pricing.html

```html
<title>Pricing — TestScribe Free, Pro & Team Plans</title>
<meta name="description" content="TestScribe offers a free tier plus Pro at $19/mo and Team at $49/mo. Unlock unlimited test case generation, OpenAPI import, and team collaboration." />
<link rel="canonical" href="https://testscribe.io/pricing" />
```

---

### docs.html

```html
<title>Documentation — TestScribe API & Integration Guide</title>
<meta name="description" content="Learn how to use TestScribe to generate test cases from user stories, Jira tickets, and OpenAPI specs. Guides for Gherkin, pytest, and tabular formats." />
<link rel="canonical" href="https://testscribe.io/docs-page" />
```

---

## 2. TOP 5 LONG-TAIL KEYWORDS

| # | Keyword | Est. Monthly Searches | Competition | Rank Opportunity | Target Page |
|---|---------|----------------------|-------------|-----------------|-------------|
| 1 | generate gherkin test cases from user story | 400–600 | Low | Top 3 achievable within 3 months with 2–3 supporting blog posts | index.html + blog post |
| 2 | AI test case generator for QA engineers | 300–500 | Low–Medium | Top 5; most existing tools target devs, not QA specifically | index.html |
| 3 | convert requirements to test cases automatically | 500–800 | Medium | Top 5; high commercial intent, sparse dedicated landing pages | index.html + docs.html |
| 4 | BDD scenario generator from user story | 200–350 | Low | Top 3; very low competition, niche audience matches perfectly | demo.html + blog post |
| 5 | pytest test case generator from OpenAPI spec | 150–250 | Low | Top 3; almost no direct competitors targeting this exact phrase | docs.html + blog post |

**Notes:**
- Search volumes are estimates based on related keyword clusters (Ahrefs/Semrush equivalents); validate with actual tooling before committing to a budget.
- All five keywords have transactional or high-consideration intent — visitors arriving via these terms are actively looking for a solution, not just researching.
- Recommended on-page strategy: use each keyword as an H1 or H2 on the target page, include it in the first 100 words of body copy, and create one supporting blog post per keyword within 60 days.

---

## 3. SITEMAP.XML

Deploy at: `https://testscribe.io/sitemap.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">

  <url>
    <loc>https://testscribe.io/</loc>
    <lastmod>2025-05-02</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>

  <url>
    <loc>https://testscribe.io/demo</loc>
    <lastmod>2025-05-02</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>

  <url>
    <loc>https://testscribe.io/pricing</loc>
    <lastmod>2025-05-02</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>

  <url>
    <loc>https://testscribe.io/docs-page</loc>
    <lastmod>2025-05-02</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>

  <url>
    <loc>https://testscribe.io/auth/login</loc>
    <lastmod>2025-05-02</lastmod>
    <changefreq>yearly</changefreq>
    <priority>0.3</priority>
  </url>

  <url>
    <loc>https://testscribe.io/auth/register</loc>
    <lastmod>2025-05-02</lastmod>
    <changefreq>yearly</changefreq>
    <priority>0.4</priority>
  </url>

</urlset>
```

---

## 4. ROBOTS.TXT

Deploy at: `https://testscribe.io/robots.txt`

```
User-agent: *
Allow: /
Allow: /demo
Allow: /pricing
Allow: /docs-page
Allow: /auth/login
Allow: /auth/register

Disallow: /api/
Disallow: /admin/
Disallow: /internal/
Disallow: /_next/
Disallow: /static/chunks/

Sitemap: https://testscribe.io/sitemap.xml
```

---

## 5. CONTENT CALENDAR — Weeks 1–4

### Week 1
- **Title:** How to Generate Gherkin Test Cases from a User Story (Without Writing a Single Line of Gherkin Yourself)
- **Target Keyword:** generate gherkin test cases from user story
- **Format:** Blog post (1,800–2,200 words) + LinkedIn summary post
- **Platform:** TestScribe blog + LinkedIn + cross-post to dev.to
- **Key Talking Points:**
  - Why hand-writing Gherkin is a bottleneck: the average QA engineer spends 40–60 minutes per feature writing scenarios from scratch
  - Step-by-step walkthrough: paste a real user story → show the Gherkin output → explain Given/When/Then decomposition the AI applies
  - Common mistakes in manual Gherkin authoring (missing edge cases, duplicated scenarios) and how structured AI generation avoids them

---

### Week 2
- **Title:** I Stopped Writing Test Cases Manually — Here's What Changed
- **Target Keyword:** AI test case generator for QA engineers
- **Format:** Reddit post (r/QualityAssurance) + LinkedIn personal story post
- **Platform:** r/QualityAssurance, LinkedIn
- **Key Talking Points:**
  - Personal/relatable hook: sprint planning ends and QA owns 30+ user stories with zero test case coverage — familiar pain
  - Concrete before/after: 3 hours of test case writing reduced to 20 minutes using AI generation + human review
  - Practical framing: AI as a first-draft generator, QA engineer as reviewer/editor — addresses the "will AI replace me?" fear directly

---

### Week 3
- **Title:** Convert Requirements to Test Cases Automatically — A QA Engineer's Field Guide
- **Target Keyword:** convert requirements to test cases automatically
- **Format:** Blog post (2,000+ words, SEO-optimised) with embedded demo GIF
- **Platform:** TestScribe blog + r/softwaretesting + Hacker News Show HN (if product is live)
- **Key Talking Points:**
  - Three input types that work best: well-structured user stories, OpenAPI/Swagger specs, plain-English acceptance criteria
  - What the AI cannot do: requirements with ambiguous scope, missing personas, or no defined acceptance criteria — and how to fix your inputs before generating
  - Integration workflow: how to copy outputs directly into Jira, TestRail, or a pytest conftest without reformatting

---

### Week 4
- **Title:** From OpenAPI Spec to pytest in 90 Seconds — A Walkthrough
- **Target Keyword:** pytest test case generator from OpenAPI spec
- **Format:** Tutorial blog post + short demo video (Loom/YouTube) + LinkedIn post
- **Platform:** TestScribe blog + r/Python + LinkedIn
- **Key Talking Points:**
  - Why OpenAPI is the ideal structured input: endpoints, request/response schemas, and status codes give the AI everything it needs to infer test boundaries
  - Walkthrough of a real petstore-style OpenAPI spec → generated pytest file with parametrised cases, fixture stubs, and status-code assertions
  - How to review and extend the generated pytest file: what to trust, what to verify, and what to add manually (auth headers, test data cleanup)
