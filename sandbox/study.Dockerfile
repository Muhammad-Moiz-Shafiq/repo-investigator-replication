# Image for the scaled study's sandbox setup. A standard data analysis
# environment, so a model isn't held back by guessing what we installed:
# pandas and numpy, scipy for the statistics (the query levels get a Fisher
# test tool, so the sandbox needs a way to run one too), and the two usual
# Postgres drivers plus SQLAlchemy, which pandas.read_sql needs for a
# connection string. pandas is the last 2.x release: models mostly write
# pandas 2 code, and pandas 3 rejects common spellings like "12H". The base
# image and every version are pinned so every run has the same setup.
# The pilot's image (sandbox/Dockerfile) is unchanged.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

RUN pip install --no-cache-dir \
    "numpy==2.3.5" \
    "pandas==2.3.3" \
    "scipy==1.18.1" \
    "SQLAlchemy==2.1.8" \
    "psycopg[binary]==3.3.9" \
    "psycopg2-binary==2.9.13"

WORKDIR /sandbox
