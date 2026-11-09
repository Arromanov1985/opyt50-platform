# Release 0.8 — role-first product UX

## Goal

Move STAZHNO from an MVP-looking landing page to a clearer two-sided marketplace experience for candidates and employers without changing database schema, matching rules or payment logic.

## Candidate experience

- Clear “Ищу работу” path on the landing page.
- Vacancy browsing remains available before registration.
- Candidate registration copy is specific to the candidate flow.
- Profile readiness indicator shows the next useful completion step.
- Real contact fields are described as private rather than “fictional/test-only”.
- Privacy messaging explains that contacts are not public and require the introduction flow.

## Employer experience

- Clear “Ищу сотрудников” path on the landing page.
- Employer-specific registration CTA and guidance.
- Separate employer journey explaining vacancy -> applications/matching -> consent/contact.
- Employer dashboard highlights one priority next action based on current funnel state.
- Vacancy copy no longer asks for fictional company data; it warns against publishing personal contacts in vacancy text.

## Public landing

- Removed the public “0.3.0-dev test release” ribbon.
- New product strip with trust/privacy points.
- Role-first hero with candidate and employer CTAs.
- Separate role cards with benefits and next actions.
- Two explicit journey panels.
- Dedicated privacy-by-default explanation.
- Updated closing CTA.
- Release 0.8 styles isolated in `app/static/release08.css`.

## Safety / non-goals

- No database migrations.
- No user or application data changes.
- No matching algorithm changes.
- No payment behavior changes; demo payment status remains visible.
- Existing technical domain and stazhno.ru DNS settings are outside this release.
- Existing authentication, consent and contact privacy rules remain unchanged.

## Acceptance

- Python tests green.
- JavaScript syntax green.
- Browser smoke covers:
  - STAZHNO role-first landing;
  - candidate/employer registration guidance;
  - candidate profile readiness;
  - employer priority action;
  - existing application/invitation/contact journey.
- PostgreSQL migration/runtime integration green.


## Vacancy discovery and matching

- Public search now exposes profession/skill, city, salary, schedule, employment and sorting controls.
- Search text also matches vacancy description, not only title/skills.
- Sorting supports newest, higher salary first and lower salary first.
- Active filters are shown as compact chips and can be reset in one click.
- Vacancy cards show skill tags instead of a plain comma-separated line.
- Candidate favorites are reflected directly on public/recommended cards.
- Recommended vacancies show a concise fit score plus the first reasons before expansion.
- Employer match cards show professional parameters, fit reasons and the invitation state.
- Already invited candidates are no longer presented as if they can be invited again.
- Invitation state is returned without exposing candidate name, email, phone or freeform profile text.
