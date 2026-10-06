---
type: Schema
root: projects/founder-memo
required: [type, title, description, category, tags, sources, created, updated]
fields:
  type: {enum: [Project, Synthesis, Advisor, Memo, Edition]}
  paper: {type: link}
  date: {type: date}
tables:
  - into: paper
    section: "## Memos"
    match: {type: Memo}
    sort_by: date
    columns: [title, description]
  - into: paper
    section: "## Editions"
    match: {type: Edition}
    sort_by: date
    columns: [title, description]
  - into: paper
    section: "## Your advisors"
    match: {type: Advisor}
    sort_by: title
    columns: [title, description]
title: projects/founder-memo schema
category: meta
tags: [schema]
sources: []
created: {today}
updated: {today}
---
# projects/founder-memo/

The Founder Memo writes here. Every page links back to the memo's page with
`paper:`, so `wiki index` lists memos, editions and advisors there.
