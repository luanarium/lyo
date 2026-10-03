# CLAUDE.md

## Project

lyo Engine — a game engine for chatbot games.

## Core Conventions

1. uses a simple interactive fiction like game engine language for defining locations, items, rooms, players, inventory systems, item specific systems like potions or spells and other logic.

2. manages a shared simulation for multiple chat room players to fascilate things like PVP or cooperative play

3. players can also play via DM's with the bot

4. has a simple boundry or api so that specific bot API's can be used with it via a plugin system

5. first API to map to this game engine is discord.py

6. runnable on either linux or windows

7. first example game to smoke test is defined in BEHAVIOR.md (clarity, the game analyzed in BEHAVIOR.md has observations of bugs and quirks, you can ignore those notation as no code itself is presented in that brief. however when smoke testing a game built within convention 1. match the conventions, features and gameplay defined in that brief.)

8. games defined in convention 1's language are distributed as a single file, in
   two modes: a markdown file whose fenced `game` code blocks are the source, so
   the one file is both the game and its own documentation (collapsible sections
   may hide spans of code); and a cartridge — that same markdown embedded in a
   PNG, whose visible image is the label. markdown is the canonical form; a bare
   `.game` file is just the extracted source. the document is the compilation
   unit: no filesystem includes, and declarations are order-independent. errors
   resolve back through PNG → markdown → code block to a real line and column.

## Build Process

- Project management: git + uv.
- Use git for version control. Keep it local — do not add remotes or push.
- Project management has a basic CLI following the UCI convention (`package.section.option`; get/set/show/commit style), including querying session state.
- The CLI includes a bundle command: zips the project and generates any documentation not yet written or updated.

## Project Management CLI

- A basic CLI manages the project, following the UCI convention (`package.section.option`; get/set/show/commit style).
- Query session state from the CLI. It lives in the project's sqlite3 file, alongside saved characters and configuration.
- Bundle command: zips the project and generates any documentation not yet written or updated.
- The CLI packs and unpacks game cartridges and tangles markdown game sources.
  Lint accepts all three forms (`.md`, `.png`, `.game`).

## Deployment

- Simple, intuitive commands for running the app.
- If the app listens on a socket, it binds to localhost only by default. Binding to all interfaces or a single named interface is an explicit, simple flag/convention.
- README opens with the most common usage examples, then expands to everything else.
- Built-in mechanism to run and manage the app as a service.
- Configuration is exposed to stdin/tty in the shape of OpenWrt's UCI (`package.section.option=value`; get/set/show/commit style).

## Reasoning Process & Preferences

### Selection (what to pick)

- Collapse app responsibilities onto 1–2 existing OSS projects.
- Prefer simple, low-dependency, idiomatically extensible libraries/applications over heavy ones.
- If no suitable OSS exists for the 1–2 composition, hand-roll a convention or scaffold that serves these principles idiomatically, drawing on host system primitives where useful. Host here is Python (stdlib, modules/packages, dunder protocols, entry points). The scaffold exists to host 3+ smaller, primitive existing OSS pieces, each chosen as the best fit for these principles.
- Select component roles (e.g., the user-interacted layer) by the same reasoning process, preferring libraries with a mature first-class extension convention. Example: a theming system for the selected chat UI. Rank candidate extension systems by the same principles (existing OSS, low dependency, idiomatic).

### Interaction (when to speak up)

- If a strong single OSS covers most of the core principles but would require reducing app responsibilities or core conventions, surface those reductions. Propose paths that meaningfully change the app's role, shape, or purpose based on that tool's strength profile, and prompt the user to choose or discard each.
- When an alternative, compelling library could collapse existing responsibilities or stack, present its strength profile and prompt the user to choose or discard it, even if adopting it changes the app's shape, responsibilities, or purpose. Prioritize proposals that raise the final app's value in line with these principles, and only when a compelling library surfaces. Treat the core conventions as scope: don't propose every alternative that surfaces, especially ones that conflict with them.
- "Surface" is reactive, not proactive. Look for compelling alternatives only when I pause development with a question about a specific thing, or when I'm working the strength profile of a choice or convention. That signals I'm inside a boundary where insights may improve the project design, so offer alternatives then to help refine the spec where relevant. I will indicate when ready to move on.

## Session State

- When I say "save project state", write one brief high-level paragraph summarising what changed in the session. Stored in the project's sqlite3 file so the CLI can query it. Read the latest entry at session start.
- Git is the record of what changed and why; session state is only the human-readable digest on top of it. Do not keep parallel project logs.

## Documentation

- Deferred: do not build or update READMEs or briefs as development proceeds. Documentation is its own compilation step, run only when I invoke it.
- Games are self-documenting: a game's markdown file is both its source and its
  documentation, so the deferred rule above does not apply to game files.
  Project documentation stays deferred.
- When I discuss deployment or preparing a deliverable, generate the end-user documentation.
- Briefs: concise, bloat-free language, with a mini table defining terms used (acronyms, software names, method names). Git is the versioning; no numbered filenames (that convention is for web chat only).
- Session state is stored in the project's sqlite3 file. Commit messages are the record of what was discarded and why.

| Term            | Definition                                                                                     |
| --------------- | ---------------------------------------------------------------------------------------------- |
| cartridge       | a game's markdown source embedded in a PNG chunk; the visible image is the label                |
| tangle          | extract a markdown game's fenced `game` blocks, in document order, as source                    |
| literate source | a markdown file that is at once a game's code and its documentation                             |
| UCI             | OpenWrt's Unified Configuration Interface: `package.section.option=value`, get/set/show/commit  |
| DSL             | domain-specific language; here, convention 1's game language                                    |
