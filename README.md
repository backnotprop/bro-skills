<p align="center">
  <img src="./assets/hero.svg" alt="A wall of dense agent output fades, /bro cuts in, and a flowing human summary reveals below." width="100%"/>
</p>

<h1 align="center">bro-skills</h1>

<p align="center">a growing set of skills for doing better work more simply.</p>

<br/>

## install

All skills, globally:

```sh
npx skills add backnotprop/bro-skills -g
```

Just one:

```sh
npx skills add backnotprop/bro-skills --skill bro -g
```

Works with Claude Code, Codex, Cursor, OpenCode, and any other skills-compatible agent. See [the skills CLI](https://github.com/vercel-labs/skills) for more install options.

<br/>

## skills

### `/bro`

Cuts the jargon. Restate the last message plainly, like a human talking to another human. Human-invoked only.

### `/bro-self-review`

Self-review the code you just wrote. Actively look for bugs, duplications, oversights, edge cases, and reusability issues before moving on. Human-invoked only.

### `/bro-fbombs`

Tally your frustrations over time. Human-invoked only. Takes ~10-15s. OpenCode not yet supported (sessions don't exist in files on disk).

<br/>

## license

MIT
