# TestScribe Onboarding Flow

---

## 1. POST-SIGNUP WELCOME EMAIL

### Subject
```
Your TestScribe account is ready — generate your first test case in 30 seconds
```

---

### HTML Version

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Your TestScribe account is ready</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; margin: 0; padding: 0; }
    .wrapper { max-width: 560px; margin: 40px auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; }
    .header { background: #4f46e5; padding: 32px 40px; }
    .header h1 { color: #ffffff; font-size: 22px; margin: 0; font-weight: 700; }
    .header p { color: #c7d2fe; font-size: 14px; margin: 6px 0 0; }
    .body { padding: 32px 40px; color: #334155; font-size: 15px; line-height: 1.7; }
    .cta-block { text-align: center; margin: 28px 0; }
    .cta-btn { display: inline-block; background: #4f46e5; color: #ffffff; text-decoration: none; font-weight: 700; font-size: 16px; padding: 14px 32px; border-radius: 8px; }
    .example-box { background: #f1f5f9; border-left: 4px solid #4f46e5; border-radius: 6px; padding: 16px 20px; font-family: 'Courier New', Courier, monospace; font-size: 13px; color: #1e293b; line-height: 1.6; margin: 20px 0; }
    .steps { margin: 20px 0; padding: 0; list-style: none; }
    .steps li { padding: 8px 0; display: flex; gap: 12px; align-items: flex-start; }
    .steps li .num { background: #4f46e5; color: #fff; font-weight: 700; font-size: 12px; min-width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-top: 2px; }
    .what-to-expect { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px 20px; margin: 20px 0; color: #166534; font-size: 14px; }
    .footer { padding: 20px 40px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 13px; color: #94a3b8; }
    .ps { margin-top: 24px; font-size: 14px; color: #475569; font-style: italic; }
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>TestScribe</h1>
      <p>AI-generated test cases from user stories</p>
    </div>
    <div class="body">
      <p>Welcome — your TestScribe account is ready and you have 25 free generations waiting for you.</p>

      <div class="cta-block">
        <a href="https://testscribe.io/demo" class="cta-btn">Generate your first test case &rarr;</a>
      </div>

      <p><strong>Copy this into TestScribe to see it in action:</strong></p>

      <div class="example-box">As a user, I want to reset my password by clicking a link in an email,
so I can regain access to my account.

AC:
- Link expires in 30 minutes
- Link is single-use
- User can set a new password that meets requirements</div>

      <div class="what-to-expect">
        <strong>What you'll get:</strong> 8+ test cases in Gherkin BDD format covering the happy path, edge cases, and security scenarios — ready to drop into Cucumber, Behave, or any BDD framework.
      </div>

      <p><strong>Quick setup (3 steps):</strong></p>
      <ul class="steps">
        <li>
          <span class="num">1</span>
          <span>Go to <a href="https://testscribe.io/demo">testscribe.io/demo</a> — no API key needed for your first generation.</span>
        </li>
        <li>
          <span class="num">2</span>
          <span>Paste the example above (or your own user story) and click <strong>Generate Test Cases</strong>.</span>
        </li>
        <li>
          <span class="num">3</span>
          <span>Copy the output straight into your test suite. Done.</span>
        </li>
      </ul>

      <p class="ps">P.S. Hit reply if you have any questions — I read every email.</p>
    </div>
    <div class="footer">
      TestScribe &middot; <a href="https://testscribe.io/pricing" style="color:#94a3b8;">Pricing</a> &middot;
      <a href="https://testscribe.io/docs" style="color:#94a3b8;">Docs</a> &middot;
      <a href="{{unsubscribe_url}}" style="color:#94a3b8;">Unsubscribe</a>
    </div>
  </div>
</body>
</html>
```

---

### Plain-Text Version

```
Subject: Your TestScribe account is ready — generate your first test case in 30 seconds

Welcome — your TestScribe account is ready and you have 25 free generations waiting.

GENERATE YOUR FIRST TEST CASE →
https://testscribe.io/demo

---

Copy this into TestScribe to see it in action:

"As a user, I want to reset my password by clicking a link in an email,
so I can regain access to my account.

AC:
- Link expires in 30 minutes
- Link is single-use
- User can set a new password that meets requirements"

What you'll get: 8+ test cases in Gherkin BDD format covering the happy path,
edge cases, and security scenarios — ready to drop into Cucumber, Behave, or
any BDD framework.

---

QUICK SETUP (3 steps):

1. Go to https://testscribe.io/demo — no API key needed for your first generation.
2. Paste the example above (or your own user story) and click Generate Test Cases.
3. Copy the output straight into your test suite. Done.

---

P.S. Hit reply if you have any questions — I read every email.

—
TestScribe
https://testscribe.io
Unsubscribe: {{unsubscribe_url}}
```

---

## 2. IN-APP TOOLTIP COPY

### Textarea Placeholder

```
As a user, I want to reset my password by clicking a link in an email,
so I can regain access to my account.

AC:
- Link expires in 30 minutes
- Link is single-use
- User can set a new password that meets requirements
```

*Do not use "Enter text here" or generic placeholder copy. The example above teaches users the expected format on first sight.*

---

### Format Selector Tooltips

| Format | Tooltip (shown on hover) |
|--------|--------------------------|
| **Gherkin BDD** | Given/When/Then scenarios — paste into Cucumber, Behave, or SpecFlow |
| **Tabular** | Rows of ID / description / steps / expected result — paste into Jira or a test plan doc |
| **Pytest** | Python test functions with assertions — paste directly into a pytest file |

---

### "Generate" Button Tooltip

```
Click to generate test cases — your first 25 are free
```

---

### Empty State Messages

**Right column before any generation (first visit):**
```
Paste a user story on the left and click Generate.
You'll see 8+ test cases here — covering happy path, edge cases, and security.
```

**Right column, returning user with no output yet this session:**
```
Your test cases will appear here.
Fill in a user story and click Generate Test Cases.
```

---

### Error State Messages

| Error | User-facing message |
|-------|---------------------|
| **401 Unauthorized** | Your session has expired. [Sign in again →] |
| **402 Payment Required** | You've used all 25 free generations this month. [Upgrade to Solo →] to continue, or wait until your limit resets on {reset_date}. |
| **429 Too Many Requests** | Slow down — you're generating too fast. Wait a few seconds and try again. |
| **500 Server Error** | Something went wrong on our end. This isn't your fault — please try again in a moment. If it keeps happening, reply to your welcome email and we'll fix it. |
| **Network / timeout** | Couldn't reach TestScribe. Check your connection and try again. |
| **Empty input** | Please enter a user story or spec before generating. |

---

## 3. FIRST-RUN DEMO (shows value in < 60 seconds)

### Pre-filled Textarea Content

```
As a user, I want to log into the app with my email and password.

AC:
- Correct credentials → redirect to dashboard
- Wrong password → show "Invalid credentials" error
- After 5 failed attempts → lock account for 15 minutes
```

### Pre-selected Format

Gherkin BDD (default, no action required from user)

### Pre-generated Example Output (hardcoded, shown before first click)

Displayed below the form by default so users see the value before interacting.

```gherkin
Feature: User Login

  Scenario: Successful login with valid credentials
    Given the user is on the login page
    When they enter a valid email "user@example.com" and correct password
    Then they should be redirected to the dashboard
    And the session should be authenticated

  Scenario: Login fails with wrong password
    Given the user is on the login page
    When they enter a valid email "user@example.com" and an incorrect password
    Then they should see the error "Invalid credentials"
    And they should remain on the login page

  Scenario: Login fails with unknown email address
    Given the user is on the login page
    When they enter an email that is not registered and any password
    Then they should see the error "Invalid credentials"
    And no information about whether the email exists should be revealed

  Scenario: Account is locked after 5 consecutive failed login attempts
    Given the user has failed to log in 4 times
    When they enter incorrect credentials a fifth time
    Then their account should be locked for 15 minutes
    And they should see a message "Account locked. Try again in 15 minutes."

  Scenario: Locked account cannot log in before the lockout period expires
    Given the user's account is locked
    When they attempt to log in with correct credentials
    Then they should see the lockout message
    And they should NOT be redirected to the dashboard

  Scenario: Account unlocks automatically after the lockout period
    Given the user's account was locked 15 minutes ago
    When they attempt to log in with correct credentials
    Then they should be redirected to the dashboard
    And the failed-attempt counter should be reset to zero
```

### CTA Below Example Output

```
This took AI 3 seconds. Generate for your own user story →
```
*(Links to the main Generate form with the textarea focused)*

---

## 4. EMPTY STATE MESSAGES

### /dashboard — No Generations Yet

```
No generations yet.
[Generate your first test case →]
```

*Link to /demo. Shown in the generations table area when history is empty.*

### /dashboard — No API Keys (Solo+ plans only)

```
No API keys yet.
[Create your first key →]
```

*Link to the API key creation flow. Shown in the API keys section.*

### Generation History — Personalized Empty State

```
Hey {name}, your test cases will appear here after your first generation.
```

*{name} resolved from the authenticated user's display name. Falls back to "there" if name is not set: "Hey there, your test cases will appear here after your first generation."*

---

## 5. UPGRADE FLOW COPY

### Banner — Free User at 80% Usage (20/25)

Shown at the top of /dashboard and /demo when `usage_count >= 20` and plan is free:

```
You've used 20 of 25 free generations this month.
Upgrade to Solo for 200/month — 8× more test cases.  [Upgrade →]
```

*"20" and "25" are dynamic. The ratio and multiplier update if limits change.*

### Modal — At Limit (25/25)

Triggered when a generation attempt returns 402.

**Headline:**
```
You've hit your free limit for this month
```

**Body:**
```
Upgrade to Solo ($19/month) to continue generating.
Or wait until {next_reset_date} when your free limit resets.
```

**Primary CTA:**
```
Upgrade to Solo →
```

**Secondary CTA (dismisses modal):**
```
No thanks, I'll wait
```

*{next_reset_date} formatted as "June 1" — no year unless it differs from current year.*

### Post-Upgrade Confirmation

Shown on /dashboard immediately after a successful plan upgrade:

```
You're now on Solo. You have 200 generations this month.
Go generate something →
```

*"Go generate something →" links to /demo.*
