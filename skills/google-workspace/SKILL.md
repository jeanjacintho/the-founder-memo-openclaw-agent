---
name: google-workspace
description: Use Gmail and Google Calendar through the owner's Mac when it is connected, and through Plow when it is not.
---
# Google Workspace

This image holds no Google OAuth credentials. Do not set up local OAuth or
invent tools. The same Google accounts are reachable two ways, and whether the
owner's Mac (Latch) answers right now decides which:

- **The turn's note says the Mac is not connected** (or a Mac tool answers that
  the device is not connected): use Plow's tools. Do not ask the owner to open
  Latch and do not list the Mac's skills.
- **Otherwise** the Mac answers: use it as below. `plow_google` refuses while
  the Mac answers and says so; that refusal means take the Mac path.

## Through the Mac

This google-workspace skill is already loaded locally; the Mac's skill-reading
tool reads only Mac-published skills, not this image's local skills. List the
Mac's skills, then read its listed Google Workspace skill using the actual
exposed tool names, which may be server-prefixed. Follow that skill's exact
commands and arguments instead of guessing them. Respect any approval or denial
the Mac returns. If the Mac's skill list has no Google Workspace capability,
say Google access is not available.

## Through Plow

`plow_google` runs the same plow-gog commands on the same Google accounts.
Pass argv without the leading `plow-gog` and learn the surface from
`["--help"]`; `["accounts"]` lists what is connected. If Google is not
connected, call `plow_connect` with `google`, send the owner the link it
returns, and carry on when Plow tells you their connections changed.

## Either way

Owner-account mail goes out as the owner. Obtain their authorization before
sending, use the complete recipients/subject/body, and do not promise a chat
approval command: this image does not implement one. Replies on the agent's own
email thread use its own mailbox instead; do not treat them as owner-account
Gmail sends.

Check calendar conflicts. Only override one when the owner explicitly directs
that exact booking; preserve all attendees and event details. In shared rooms,
refer to private overlaps as an existing commitment, not the event's name.
