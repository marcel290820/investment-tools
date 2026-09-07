# investment-tools

Personal tooling for managing investments. One tool per concern; they share a
repository, not a framework.

## Allocation drift bot

Reads a comdirect depot, compares it against a target allocation, and reports
which positions have wandered far enough to be worth acting on.

You trigger it yourself, from a terminal or with `/check` in Telegram. It is
not on a timer, because comdirect has no unattended login: every API session
starts with a two-factor approval, and the session dies with its tokens roughly
ten minutes later.

With photoTAN-Push you never type a TAN. The bank pushes a prompt to the
photoTAN app and you approve it there, so no second factor passes through
Telegram or through your shell history. The bank offers no way to ask whether
you have approved yet, so you say so: press Enter in the terminal, or send
`/done` in Telegram. Only then does the tool claim the session.

The depot is only ever read. Nothing here places an order.

comdirect issues a token with brokerage write access whether you want it or not,
so the session is revoked the moment the reads finish instead of being left to
expire. If the bank does not confirm the revocation, the bot says so in the same
message rather than letting it lapse quietly.

### Two front ends

```sh
investment-tools check   # read the depot once and print the report
investment-tools bot     # answer /check in Telegram until stopped
```

Both run the same check. In the terminal the report goes to stdout and the
"approve the prompt in your photoTAN app" line goes to stderr, so redirecting
the report to a file still leaves you something to react to.

The bot is worth running only when you want the answer on your phone. It reads
a Telegram token; the terminal front end never asks for one.

### Tolerance bands

A position is flagged once it moves either 5 percentage points or a quarter of
its own target away from where it belongs, whichever comes first. Wide bands are
the point: a rebalance in a German depot realises a capital gain and costs tax,
so the bot is built to stay quiet through normal market noise and speak up only
when the allocation has genuinely shifted.

When something is out of band, the suggestion is to buy, not to sell. The report
says how much new money each underweight position needs to reach its target, and
which positions to pause contributions to. Selling is left to you. The bot never
moves money and has no command that could.

### History

Every check is written to a SQLite file, so the report can say how long a
position has been out of band rather than only that it is out today. Drift that
has held for months reads differently from drift that appeared this morning, and
one snapshot cannot tell you which you are looking at.

### Target allocation

The bands are derived, not configured. The only thing you set is the targets, in
a TOML file at `~/.config/investment-tools/allocation.toml`. It never enters this
repository, because it describes real holdings. `deploy/allocation.example.toml`
shows the shape.

## Development

```sh
uv venv .venv && . .venv/bin/activate
uv pip install -e ".[dev]"
./.claude/check.sh          # lint, typecheck, tests
pytest tests/test_drift.py  # one file
```

The drift calculation and the report formatting are pure functions and are
tested directly. The comdirect and Telegram layers hold no logic worth testing
without a live account.

## Installing it

It runs on your own machine. There is no server, so there is no server to break
into, and the credentials stay where you typed them.

```sh
uv venv .venv && . .venv/bin/activate
uv pip install -e .

mkdir -p ~/.config/investment-tools
cp .env.example ~/.config/investment-tools/env
chmod 600 ~/.config/investment-tools/env
$EDITOR ~/.config/investment-tools/env

cp deploy/allocation.example.toml ~/.config/investment-tools/allocation.toml
$EDITOR ~/.config/investment-tools/allocation.toml
```

The tool reads its credentials from the environment, so something has to put
them there. A shell function keeps them loaded for one command and no longer,
which beats exporting your banking PIN into every shell you open:

```sh
investment-tools() (
    set -a
    . ~/.config/investment-tools/env
    set +a
    exec /path/to/this/repo/.venv/bin/investment-tools "$@"
)
```

For Telegram, `deploy/com.investment-tools.bot.plist` runs the bot as a launchd
agent. Its header says which two paths to replace. A laptop sleeps, so the bot
answers only while the machine is awake and you are logged in.

## Secrets

This repository is public. Credentials, account identifiers, chat ids, and the
target allocation are read from the environment or from files under
`~/.config/investment-tools`, mode 600. `.env.example` lists the variable names
and nothing else.

A leaked PIN alone does not move money: opening a session still needs a
photoTAN approval on your phone. The token comdirect then issues is the
dangerous part, which is why it is revoked as soon as the reads finish.
