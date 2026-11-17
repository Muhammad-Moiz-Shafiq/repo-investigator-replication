# The only way out of the study sandbox's network. The sandbox runs on an
# internal Docker network with no internet. This relay sits on that network
# and on the normal one, and forwards one port to the database host and
# nowhere else.
FROM alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f

RUN apk add --no-cache socat
