# TruthLens AI — Phase 0 to Phase 5 implementation

This batch extends the existing Streamlit application. It does not migrate the UI
framework or replace the existing authentication, profile, photo, or image-forensics
modules. The aqua-blue workspace theme is retained.

## Phase map

1. **Phase 0 — Audit and safety foundation:** inspect the existing modules, retain the
   current login/profile flow, add backward-compatible SQLite claims storage, and add
   an optional cloud persistence adapter.
2. **Phase 1 — Persistent investigations:** save extracted text, candidate claims and
   evidence; reopen and delete saved investigations from History.
3. **Phase 2 — Claim verification:** add an evidence-based assessment page, transparent
   support/contradiction counts, lexical overlap indicators and an optional Hugging Face
   model-assisted explanation. No unsupported true/false verdict is generated.
4. **Phase 3 — Source credibility:** add a dedicated URL checker with domain category,
   HTTPS and explainable URL-level warnings. It is not a publisher reputation database.
5. **Phase 4 — Reports and assistant:** add a complete multi-claim PDF report and an
   assistant page. The local assistant works without a paid API; open-ended model replies
   are optional and require a Hugging Face token.
6. **Phase 5 — Analytics and regression readiness:** add account-level investigation
   analytics and a consolidated automated test suite.

## Supabase setup for durable cloud history

The current local SQLite fallback preserves compatibility with the existing app, but
Streamlit Community Cloud does not promise that local files survive restarts/redeploys.
For persistent hosted history:

1. Create a free Supabase project.
2. Open its SQL Editor and run the file supabase/schema.sql.
3. In Streamlit Community Cloud, open the app's Settings > Secrets.
4. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY using the values from your
   Supabase project. Keep the service-role key only in server-side Secrets.
5. Restart the Streamlit app.

The service-role key bypasses row-level security. It must never be committed to GitHub
or exposed in browser code. The application filters all investigation and evidence
queries by the signed-in username. For a larger production deployment, migrate login
to Supabase Auth and use per-user JWT/RLS policies before exposing multi-tenant access.

## Optional free-tier AI model

Add HF_TOKEN to Streamlit Secrets to enable optional model-assisted claim explanations
and open-ended assistant replies through Hugging Face's compatible inference endpoint.
Free inference availability, model access, rate limits and latency are controlled by
Hugging Face and can change. Without a token, deterministic local evidence summaries
and the guided assistant remain available. No paid API key is required by this code.

## Existing data and limitations

- Existing SQLite user accounts and profile data are not migrated to Supabase by this
  batch. Existing authentication continues to work as before.
- Old session-only history entries cannot be recovered after their Streamlit session
  ends. New investigations are persisted from this version onward.
- Existing image-forensics model and dependencies are preserved.
- Source indicators and AI-generated summaries are research aids, not proof of truth.
- Run the consolidated regression suite with:
  python -m unittest discover -s tests -v
