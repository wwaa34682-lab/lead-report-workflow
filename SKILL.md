---
name: lead-report-workflow
description: Daily reconciliation of lead counts from any third-party platform against any CRM; renders red-highlighted PNG gap tables and delivers them per recipient (image-only by default). Use when the user wants daily 客资填写统计 / lead-vs-CRM checks, morning/evening lead reports, verification-vs-visit reconciliation, or response-time tables.
---

# Skill: 全平台客资 × CRM 每日对账

## When there is no config yet → onboarding
1. Do NOT guess platforms, recipients or channels. Interview the user following `docs/agent-onboarding.md`
   (one group of questions at a time; recipients are asked one by one: platform, DM/group, which reports
   (morning/evening/alerts), format (image / image+text / file), evidence screenshots yes/no; then who gets auth-failure alerts).
2. Write the answers to `answers.yaml` (shape: `examples/init-answers.example.yaml`), then:
   `python run.py init --out config.yaml --answers answers.yaml && python run.py validate --config config.yaml`
3. Fix every ✗ line `validate` prints (they name the exact field). Tell the user which env vars in `.env.example`
   they must fill and where to get them. Never ask the user to paste secrets into chat if you can avoid it.
4. Dry run: `python run.py run --config config.yaml --slot morning --dry-run`, show the images to the user, and
   confirm the numbers match what they see in their back-offices before going live.

## Every scheduled slot (morning = yesterday, evening = today)
1. **Live re-pull, every time.** For `csv`/`crm-csv` sources export fresh files; for `browser-manual` sources open
   the platform page, read the numbers, and write `captures/<source_id>/<data_day>.yaml` with `fetched_at` = now
   (template: `examples/manual-capture.template.yaml`). Never reuse a previous slot's export, capture or screenshot.
2. **Browse-only.** Never reply to customers, edit, delete, or change settings on any platform or in the CRM.
3. **Auth failure** (login page / QR code / captcha / 401): do not invent numbers or write 0. Set the capture to
   `status: auth_failed` (API sources are detected automatically), run anyway so alerts go out, ask the user to log in,
   then re-pull and re-run the slot to deliver the held reports.
4. Run: `python run.py run --config config.yaml --slot <slot>` (exit 3 = some source failed and was alerted).
5. Read `runs/<run_id>/manifest.json`:
   - `sources.*.status` should be `ok`; `normalize.*.unmatched_group > 0` → suggest aliases to the user.
   - For each `mismatches[]` with `evidence_missing: true` where a recipient has `evidence: true`: take a screenshot
     of the platform list page for that group (mask phone numbers), save under `evidence/<source_id>/`, register it in
     the capture's `evidence:` map, re-run.
6. Delivery: API channels are sent by the program. For `wechat` / `agent_outbox` recipients, open
   `runs/<run_id>/outbox/<recipient>.json` and send exactly those images in order with your own messaging tool
   (as images, previewable — not as files unless `send_as: file`; send `caption` text only if present), then set `status: sent`.
   Only send to recipients in the config; only what the user set up during onboarding counts as approval.
7. Report back to the user briefly: what was sent to whom, which groups have gaps, which platforms need login.

## Rules of thumb
- Gap = max(platform − CRM, 0); red when > 0; over-filling is a footnote, never negative.
- Date attribution = first-contact date unless configured otherwise; channel match is exact.
- Missing data shows "—" or holds the report; never fabricate.
- Changing who receives what, or adding a recipient, requires asking the user — then update `recipients[]` and re-validate.
