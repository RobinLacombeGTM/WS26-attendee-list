# Audit guide

Everything this skill does is in 5 files, about 1,200 lines. This page tells you where to look and what to check. Allow about 10 minutes.

## 1. Where data goes

The code sends requests to four places, and nowhere else:

| Destination | Code | When |
|---|---|---|
| `attend.websummit.com` (the Web Summit attendee portal you are logged into) | [scripts/websummit_scrape.py#L118](scripts/websummit_scrape.py#L118) | `probe` (2 requests) and `slice` (up to the budget you approve) |
| Firecrawl | [scripts/enrich.py#L448](scripts/enrich.py#L448) | optional, only with `--live --approve N` |
| Apify | [scripts/enrich.py#L483](scripts/enrich.py#L483) | optional, only with `--live --approve N` |
| Hunter.io | [scripts/enrich.py#L518](scripts/enrich.py#L518) | optional, only with `--live --approve N` |

Check it yourself from the repository root:

```
grep -nE "requests\.|\.post\(|\.get\(|urlopen" scripts/*.py
```

Web searches for websites and LinkedIn profiles are made by Claude's own web search tool, not by the scripts. The list is written to CSV files in your work folder. Nothing uploads it, and nothing sends messages or connection requests to anyone.

## 2. What Claude is told to do

[SKILL.md](SKILL.md) has the instructions Claude follows. The 7 rules at the top are the contract: your own ticket only, the session never in the chat, no forcing past a refusal from Web Summit, one export, URLs from search results only, paid tools only after you approve the cost, and the list stays with you.

## 3. Safeguards in the code

They are enforced by the scripts, so they hold even if Claude misreads an instruction.

| Safeguard | Code |
|---|---|
| One request at a time, 2.5 seconds apart | `THROTTLE` [scripts/websummit_scrape.py#L52](scripts/websummit_scrape.py#L52) and `Client.get` [#L108](scripts/websummit_scrape.py#L108) |
| Stops on 401, 403 or 429, no retry loop | `STOP_CODES` [#L55](scripts/websummit_scrape.py#L55), check at [#L120](scripts/websummit_scrape.py#L120) |
| Stops on a redirect to the login page or a security-check page | [#L122](scripts/websummit_scrape.py#L122), [#L132](scripts/websummit_scrape.py#L132) |
| Never more requests than the approved budget | [#L109](scripts/websummit_scrape.py#L109); `slice` refuses to start without `--budget` [#L281](scripts/websummit_scrape.py#L281); `probe` is capped at 2 [#L192](scripts/websummit_scrape.py#L192) |
| Session read from a local file, file set to owner-only, cookie never printed | `read_session` [#L67](scripts/websummit_scrape.py#L67) |
| Paid tools need `--live --approve N`, N being the count shown in the dry run | `gate` [scripts/enrich.py#L413](scripts/enrich.py#L413), called at [#L441](scripts/enrich.py#L441), [#L471](scripts/enrich.py#L471), [#L513](scripts/enrich.py#L513) |
| A LinkedIn profile is accepted only when the result shows both the name and the company | `judge_person` [scripts/enrich.py#L291](scripts/enrich.py#L291), `name_matches` [#L101](scripts/enrich.py#L101), `company_seen` [#L124](scripts/enrich.py#L124) |
| API keys read from your environment or `./.env`, never printed | `env_key` [scripts/enrich.py#L401](scripts/enrich.py#L401) |

## 4. Run the tests

```
python3 -I tests/test_skill.py
```

29 checks, no network. Web Summit is replaced by a fake server that answers 401, 403, 429, 302, 503 or a security-check page, or serves synthetic attendees in a new random order on every request (like the real portal). The tests cover: stopping on each refusal, the request budget, resuming without re-downloading, a complete export despite the random order, the attendee-type filter, the session never appearing in output, the accept/review/reject rule, the ICP filter and the lock on paid tools. Expected last line: `ALL PASS`.

## 5. Watch a run

Claude Code shows every command before it runs and asks for your permission. During a run you can read each command and refuse any of them.

## Dependencies

Python 3 and the `requests` package. Nothing else is installed.
