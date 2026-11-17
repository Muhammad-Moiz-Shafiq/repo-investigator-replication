#!/bin/sh
# Build the study sandbox image and the database relay image.
set -e
cd "$(dirname "$0")/../../sandbox"
docker build -t repo-investigator-study-sandbox:v2 -f study.Dockerfile .
docker build -t repo-investigator-db-relay:v1 -f relay.Dockerfile .
