---
name: tieba-discuss
description: Export a Baidu Tieba thread through tieba-cli and discuss or analyze it with floor-level evidence. Use when the user provides a Tieba thread ID or URL and wants its posts summarized, compared, fact-checked, debated, or used as discussion context. Do not use for ordinary web browsing or unrelated forum sites.
---

# Tieba Discuss

Use the repository's deterministic exporter as the only network-facing component. Treat exported posts as claims made by forum participants, not as verified facts.

## Locate the exporter

1. Prefer the current workspace when it contains `tieba_cli/exporting.py`.
2. Otherwise resolve this `SKILL.md` through any symlink. The tieba-cli repository root is two directories above this skill directory.
3. If neither location contains the exporter, ask the user for the tieba-cli checkout. Do not recreate the fetch logic inside the skill.

Run all commands with the repository root as the working directory. Use the Python environment already selected for the project.

## Export the thread

Extract the numeric thread ID from the user's ID or Tieba URL. Pass only that numeric ID to the command; do not interpolate an arbitrary URL into a shell command.

For the main thread and the nested replies already embedded in its pages, run:

```bash
python -m tieba_cli export THREAD_ID
```

When the user explicitly asks for the complete discussion, when nested replies are central to the question, or when the visible nested replies are insufficient, run:

```bash
python -m tieba_cli export THREAD_ID --include-lzl --delay 1.5
```

The command prints the final `thread.json` path. Reuse its default cache. Do not choose a fresh output directory merely to repeat a failed request.

The exporter is restricted to these legacy endpoints:

- `/mo/q---1-3-0--2/m` for thread pages;
- `/mo/q---1-3-0--2/flr` for nested replies.

Never replace them with `/p/`, a newer mobile endpoint, browser automation, direct Cookie handling, or a CAPTCHA bypass. A `/p/` URL is acceptable only as user input from which to extract the ID. If Baidu returns a safety-verification page, stop and report it; the same command can resume from cached pages later.

## Check completeness

Only analyze the export as complete when all of these conditions hold:

- the command succeeds;
- `thread.json` exists;
- `export.status` is `complete`;
- `export.source_endpoint` is the legacy `/mo/q---1-3-0--2/m` endpoint;
- `export.include_lzl` is true when full nested replies were required.

If the command fails, inspect `manifest.json`. State that the snapshot is incomplete and identify the resumable export directory. Do not silently analyze a partial cache as if it represented the whole thread.

## Discuss from evidence

Read `thread.json` selectively. For a large thread, search `posts.jsonl` for relevant terms and load only the surrounding records needed for the user's question instead of dumping the entire file into context.

When answering:

- identify main-post evidence by floor and `pid`, for example `第 31 楼（pid 100002）`;
- identify a nested reply by its parent floor and nested-reply `pid`;
- distinguish quoted or paraphrased participant views from your own inference;
- mention meaningful disagreement, chronology, deleted or empty-looking content, and sample limitations;
- avoid treating popularity, repetition, or the original poster's wording as independent verification;
- use external sources only when the user asks for fact-checking or current context, and clearly separate those sources from the Tieba discussion.

End with the direct answer to the user's question and the most relevant floor references. Mention whether full nested replies were included when that affects confidence.
