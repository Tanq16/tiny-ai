---
name: vocabulary-hunter
description: "Builds glossary.json in the current directory for a named show, film, or similar: vocabulary spellings plus likely speech-recognition corrections, harvested from public sources. Invoked explicitly as /vocabulary-hunter with a title. Not for transcribing audio or editing an existing glossary by hand."
user-invocable: true
---

# Vocabulary hunter

**How glossary.json is assembled from public pages about a show, film, or similar.**

The file is a JSON object with `vocabulary` (canonical spellings) and `corrections` (`from` heard -> `to` meant). This skill writes that file in the current working directory and nothing else. It has no consumer, no repository, and no neighbouring script.

## When to Use

The user invokes `/vocabulary-hunter` and names a series, film, season, or similar. A request to hunt vocabulary and corrections for a title is the same job.

## Output

The only durable output is `glossary.json` in the current working directory.

```json
{
  "vocabulary": ["Jon Snow", "Winterfell"],
  "corrections": [{"from": "John Snow", "to": "Jon Snow"}]
}
```

`vocabulary` is an array of non-empty strings. `corrections` is an array of objects whose `from` and `to` are non-empty strings. No other keys are written. Research notes, page dumps, candidate lists, and subagent transcripts are not saved.

## Workflow

1. Identify the work. A title that still matches more than one property is confirmed with the user before any deep read, because two properties with the same name produce two incompatible glossaries.
2. Read public pages about that one property (Wikipedia and its list-of-characters / list-of-episodes pages, the fandom or other fan wiki, IMDb or TMDB credits). Synopses and episode lists are mining text, not output. Terms stay in memory or a scratch pad that is deleted before the turn ends.
3. Harvest every distinctive proper noun and in-world term into a vocabulary list. Ordinary English stays out.
4. Launch two subagents in parallel against that finished vocabulary. Each returns correction objects only. They do not write files.
5. Merge the two correction lists onto the vocabulary, write `glossary.json` in the current directory, and confirm it with `jq`. Then delete scratch.

## Rules

An ambiguous title is confirmed before deep research. A first search that returns more than one reasonable hit (same name, different year, medium, country, or franchise entry) is listed back as year plus medium plus one-line identifier, and work waits. A title the user already pinned down with a year, network, or "the film" is not re-asked.

Every vocabulary string is copied from a page retrieved in this run. A remembered spelling is how a glossary disagrees with the source.

Synopses, episode plots, and wiki prose are scanned for names and then discarded. Plot text in `vocabulary` is not a spelling.

The harvest treats the property like a game of name, place, animal, thing, and also pulls the categories those pages actually use:

| Bucket | What lands in vocabulary |
|---|---|
| People | Character full names, spoken short names, aliases, titles used as names, houses, families, credited unique spellings |
| Places | Planets, regions, cities, buildings, ships-as-places, named rooms |
| Animals | Species, creatures, mounts, named beasts |
| Things | Artifacts, weapons, vehicles, organizations, orders, religions |
| Powers | Named spells, techniques, stand names, bending forms, magic systems |
| Concepts | In-world terms, currencies, calendar names, invented materials |

A term is kept when it is a distinctive proper noun or in-world name. "Red Keep" is kept. The word "castle" is not.

Both the long form and the spoken short form are kept when dialogue uses both. `Daenerys Targaryen` and `Dany` are two vocabulary entries.

Episode titles are mined for proper nouns. The title string itself is added only when it is an in-world name rather than an English phrase.

Canonical capitalization follows the source page. Internal spaces are preserved. A list is de-duplicated by exact string, then sorted in Unicode order so a second run diffs cleanly.

Corrections exist to catch what speech recognition tends to emit instead of a vocabulary spelling. Each `to` is an exact vocabulary string. A correction that points at a spelling not in `vocabulary` is dropped.

`from` is a plausible mishearing, not a second canonical name. Aliases the work itself uses belong in `vocabulary`, not in `corrections`. `Dany` is vocabulary. `Danny` is a correction onto `Dany`.

Useful `from` values are phonetic neighbours of a vocabulary term: common English names that collide (`Jon` vs `John`), invented words split into English words, dropped apostrophes and hyphens, stripped diacritics, spoken letter-names for acronyms, and extra syllables a decoder likes to insert. `from` and `to` that match ignoring case are dropped.

Two subagents propose corrections independently so one pass's blind spot is not the whole list. They run in parallel and each receives the confirmed title, year/medium, and the finished vocabulary. They return a JSON array of `{from, to}` objects and write nothing. One is briefed on English given-name and title collisions. The other is briefed on invented words, foreign phonology, and punctuation or diacritic loss.

Merge is a union keyed on `from` lowercased. A duplicate `from` keeps the `to` that matches vocabulary exactly; if both do, the shorter `to` wins, because the spoken form is the one usually heard. Corrections are sorted by `to` then `from`.

The written file is checked with `jq` before the job is called done. A non-zero exit is a broken glossary and is fixed in place:

```bash
jq -e '
  type == "object"
  and (.vocabulary | type == "array")
  and (.corrections | type == "array")
  and all(.vocabulary[]; type == "string" and length > 0)
  and all(.corrections[];
    type == "object"
    and (.from | type == "string" and length > 0)
    and (.to | type == "string" and length > 0)
  )
' glossary.json
```

Scratch files from research or subagent output are deleted after the glossary validates. `glossary.json` in the current directory is the only path reported to the user.

## Examples

Disambiguation reply when a search is not unique:

```
"The Office" hits more than one series. Which one?
- The Office (US, 2005)
- The Office (UK, 2001)
```

Vocabulary harvest from public character and place lists, not from memory:

```json
["Dany", "Daenerys Targaryen", "Drogon", "Iron Throne", "Winterfell"]
```

Corrections that map a likely mishearing onto a vocabulary string:

```json
[
  {"from": "John Snow", "to": "Jon Snow"},
  {"from": "Danny", "to": "Dany"},
  {"from": "Winter fell", "to": "Winterfell"}
]
```
