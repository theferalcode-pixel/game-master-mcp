# Contributing

Thanks for pulling up a chair! Bug reports, ideas, and pull requests are all
welcome. A few house rules keep this project easy to trust and easy to review:

## Ground rules

- **Keep it dependency-free.** The web server is Python stdlib only; the MCP
  server needs only the `mcp` package; the web room is plain HTML/CSS/JS with
  no build step. Pull requests that add dependencies, build tooling, or CI
  will usually be declined — that smallness is a feature.
- **The rules stay honest.** Game engines must enforce the real rules and
  never move on a player's behalf. Battleship views must stay redacted —
  nothing that reveals hidden ships may cross the API, in either direction.
- **Run the tests** before opening a PR, and add tests for engine changes:

  ```bash
  pip install mcp pytest
  python -m pytest tests/
  ```

- **Small, focused PRs** with a plain-English description of what changed and
  why are much easier to review than big ones.

## Reporting bugs and requesting features

Open an issue using the templates — they ask for the few details that make
problems reproducible (which game, what you clicked or what tool call the AI
made, and what the state looked like).

## Security

Please don't report security problems in public issues — see
[SECURITY.md](SECURITY.md).
