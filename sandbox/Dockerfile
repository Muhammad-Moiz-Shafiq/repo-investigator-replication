# Image for Variant B's open code-execution sandbox: a standard data-analysis
# baseline, not an arbitrarily bare one -- pandas is common enough for
# tabular work that withholding it would test "did the model guess our
# specific setup" rather than "can the model investigate effectively," which
# isn't what this study is measuring. No web/GitHub access needed --
# everything the agent needs is already ingested into Postgres, reached only
# via the read-only sandbox_readonly role (see scripts/create_sandbox_role.sql),
# never the app's normal credentials. Whatever is installed here must also be
# named explicitly in prompts/system_prompt_variant_b_*.md -- the model
# should be told its boundary, not left to discover it by trial and error.
FROM python:3.12-slim

RUN pip install --no-cache-dir "psycopg[binary]>=3.1" "pandas>=2.2"

WORKDIR /sandbox
