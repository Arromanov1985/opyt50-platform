# Academy catalog discovery

The public catalog supports local search by title, description, audience,
learning outcomes and classification, combined with category, difficulty and
existing learning-status filters. No query is sent to the backend and no
search history or extra learner data is stored. Without JavaScript the full
server-rendered catalog and course links remain usable.

Authors may choose a category and difficulty in the course card. These are
optional fixed enums in the existing draft/published JSON, not database
columns. Old clients and old AI JSON imports retain compatibility; a full
course import without classification preserves manual selections in the
editor. An explicitly supplied supported classification is accepted by the
importer and may be edited before saving. Unassigned courses are labelled
rather than guessed. The original AI course has a display-only legacy
classification. No database migration, forced republish or seed overwrite.

A saved classification is not public until the existing publication consent
and review flow publishes the new snapshot. Existing public snapshots and
revision-scoped local learning progress retain their behavior.

Acceptance: unknown enum values rejected, old-client saves preserve metadata,
private AI validation does not mutate, pending/private edits stay unpublished,
approved snapshot changes, two-course filter combinations and empty/reset
states, mobile and desktop usability. No external API or paid resources.

Curated educational programs are a separate editorial step: define a stable
ordered list of approved courses, prerequisites and a verified learning goal.
Do not automatically assemble a program from arbitrary category matches or
publish unreviewed draft courses.
