# XHS Evidence Hardening Implementation Plan

1. Add failing adapter validation tests for exact detail identity, complete
   proof, field-level metric provenance, and request-bound comments.
2. Add a failing screenshot test proving the full-page fallback is not called
   after a newly visible risk signal.
3. Add a failing creator-pagination test for a duplicate page with a progressing
   cursor followed by a new note.
4. Implement the smallest adapter, screenshot, and pagination changes needed
   to pass those tests.
5. Run targeted tests, the complete offline suite, `git diff --check`, and
   source-versus-installed synchronization checks without live collection.
