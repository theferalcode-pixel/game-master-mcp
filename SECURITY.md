# Security policy

This project is designed to be small enough to audit in one sitting: a stdlib
web server that binds to 127.0.0.1 by default, one MCP server, no build step,
and a single dependency (`mcp`).

## Reporting a vulnerability

If you find a security problem — anything from a way to read Battleship's
hidden fleets through the API, to a path traversal in the web server, to a
way for one player to move for the other — please report it **privately**:

- Use GitHub's **"Report a vulnerability"** button under the repository's
  **Security** tab (preferred), or
- Email **theferalcode@gmail.com** with the details.

Please include steps to reproduce. You'll get a reply as soon as possible,
and a fix will be published before the report is discussed publicly.

Please do **not** open a public issue for security problems.

## Scope notes

- The Game Room web server is intended for localhost use. Exposing it to a
  network is out of scope by default — but reports about what could go wrong
  if someone does are still welcome.
- "The AI cheated by editing state files on its own machine" is out of scope:
  anyone with shell access to the machine owns the game state. The redaction
  guarantee is about the API surfaces, not local file permissions.
