# BrandShield AI

BrandShield AI is a pre-publication brand checkpoint. It checks draft text against your team's shared rulebook, explains every flag, suggests safer wording, tracks revisions, and records a human approval decision.

Warnings are guidance, not proof of false claims or legal non-compliance. The checker is transparent phrase matching, not a trained AI model.

## Try it on your computer
1. **Windows:** double-click `START_BRANDSHIELD_WINDOWS.bat`. **Mac/Linux:** run `./START_BRANDSHIELD_MAC_LINUX.command`.
2. Your browser opens. Tap **Use creator / reviewer / admin** to sign in.

Needs Python 3.10+ and internet on the first run only. Local runs include sample accounts; a live site does not (see below).

## What it does
- **Quick check:** paste text, see highlighted issues instantly, nothing saved.
- **Drafts:** create, check, revise (every version kept), and send for review.
- **Rulebook:** shared rules with category, explanation and suggested fix; reviewers and admins add or disable rules.
- **Review:** reviewers approve, reject or request changes, with comments, only after the latest version is checked.
- **Team:** admins add creators, reviewers and other admins.
- Passwords hashed (PBKDF2), CSRF protection, role checks on the server, security headers, SQLite storage, health endpoint at `/api/health`.

## Put it online
Free: see **FREE_DEPLOY.md** (PythonAnywhere, no card). Paid and always-on: see **DEPLOY.md** (Render, about 10 minutes).

## Settings (environment variables)
| Name | Purpose |
|---|---|
| `SECRET_KEY` | Long random string. Required when live. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | Creates the first admin on first start. |
| `BRANDSHIELD_DB` | Database file path (put it on a persistent disk). |
| `BRANDSHIELD_SECURE_COOKIES` | Set to `1` on HTTPS sites. |
| `BRANDSHIELD_DEMO` | `1` adds sample accounts and a sample draft. Keep off when live. |

## Tests
```
python -m unittest discover -s tests -v
```
19 tests cover sign-in, permissions, CSRF, checks, revisions, highlighting, review decisions, rules, team management and production mode.

## Limits
No rate limiting, password reset or email yet. SQLite suits a small team; move to a hosted database if usage grows.
