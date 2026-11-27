# Academy course studio: private learner preview

The author/editor may switch between the answer-key view and learner view.
Learner mode uses the current in-memory draft and shows explanations only after checking a complete set of answers. It does not submit answers to the server, create a learning record, mark the draft dirty or change publication consent. Leaving or changing a lesson resets the trial answers. An incomplete quiz cannot be attempted. Only the existing saved server checklist controls publication readiness.

Before publication, check incorrect and correct answers, reset, previous/next lesson navigation, mobile keyboard and touch interactions, and review the final saved text and answer keys.

Leaving the preview through either a numbered editor step or its forward action clears all trial answers and grading feedback. Returning to preview starts a new trial. The integrated release retains the template picker, manual AI drafting helper and own-course filters alongside this behavior. All are subject to the existing saved-draft and publication checks.

## Integrated release acceptance

- Template creation: blank and all three predefined outlines remain private; a lost response must retry with the same key and template.
- Assistant: manually entered topic and audience generate a local prompt. No external AI service is called. The pasted result is checked for exact supported fields, bounded structure, strict types and duplicate JSON keys. Invalid input must not echo contacts or change the saved draft. Review content and explicitly apply before saving.
- Instructor overview: counts and search are scoped to the authorized own-course collection, not the public catalog or other authors' drafts. The total count used for the course limit is independent of filtering.
- Verify an incomplete draft cannot be submitted, published versions remain unchanged until explicit approval, and legal/media activation gates remain disabled. Live deployment requires a successful version verification against the merged commit.
