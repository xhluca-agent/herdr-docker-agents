# herdr Docker Agents

Run coding agents (pi, opencode, …) **fully inside Docker containers** while
herdr still treats them as normal agents: `herdr agent start`, `agent prompt
--wait`, `agent wait`, and idle/working/blocked status all work.

```bash
herdr plugin pane open --plugin xhluca.docker-agents --entrypoint shell   # -> pane id, e.g. w1:p7
herdr agent start coder --kind pi --pane w1:p7 -- --model mistral/mistral-large-4
herdr agent prompt coder "Fix the failing test" --wait
```

## Why

herdr detects agents by looking at the pane's host processes, and it starts
them by typing the agent command into a host shell. An agent inside a container
is invisible to it: under rootless Docker the agent's process isn't even a
descendant of the pane. Mounting herdr's socket into the container would bring
detection back, but that socket can type into every pane, including your host
shells, which defeats the sandbox.

## How it works

```
herdr pane (Docker agent shell)        container (non-root, no caps)
  `pi` shim ─> herdr-docker-run  ─────> docker compose run <service>
                  │ relay socket  <────  herdr's own pi/opencode integration
                  ▼  (filtered)          (mounted read-only from your host)
              herdr socket
```

1. The plugin pane is a bash shell with `shims/` first on its `PATH`. When
   `herdr agent start --kind pi` types `pi …`, it runs `bin/herdr-docker-run pi …`.
2. The launcher creates a private relay socket for this run, readable only by
   the container's user, and starts the agent with `docker compose run`. The
   socket is mounted at `/run/herdr/herdr.sock`, and `HERDR_ENV`,
   `HERDR_PANE_ID` and `HERDR_SOCKET_PATH` are set.
3. herdr's official integration for that agent (the file `herdr integration
   install <kind>` put in your home) is mounted read-only into the container,
   so the agent reports idle/working/blocked exactly as it would on the host.
4. The relay forwards those reports to herdr after rebuilding them from scratch.
5. The launcher keeps its process name equal to the agent kind, which is what
   herdr checks while the agent runs, and releases the pane when the container exits.

## Security model

The relay is the only path from the container to herdr, and it forwards **only**:

- `pane.report_agent` with `state` ∈ {idle, working, blocked}, plus an optional
  `message` (max 200 chars, control characters removed) and a numeric `seq`
- `pane.release_agent`

For both, `pane_id`, `source` and `agent` are **forced** to the launching pane
and agent kind. Everything else is refused: other socket methods (`send_keys`,
`send_text`, `read`, `run`, `agent.*`, `plugin.*`, …), session reports,
session references, and **`resume_argv`**, which herdr would otherwise store
and later run on the host. Requests are rate-limited to 20/s, and lines are capped at 16 KiB.

So a compromised agent can, at worst, lie about its **own** pane's status
(e.g. say `idle` while still working). It can't run anything on the host or
touch other panes. The tests in `tests/test_relay.py` check the filter.

The container is only as strong as your compose service. Use a non-root user,
`cap_drop: [ALL]`, `no-new-privileges`, a read-only root filesystem, and mount
only the project directory. Not covered: network egress, anything the agent can
read in the mounted workspace, and `.git/hooks` it writes there, which run on
your host the next time *you* use git in that folder.

## Requirements

- Linux, herdr ≥ 0.9.5, Docker with Compose v2, python3, `setfacl` (recommended)
- A compose file with one service per agent kind (service name = kind, or
  map it with `HERDR_DOCKER_SERVICE_<KIND>`). The image's entrypoint must be
  the agent, so that `docker compose run <service> <args>` passes `<args>` to the agent.
- herdr integrations installed on the host: `herdr integration install pi`,
  `herdr integration install opencode`
- Agent versions recent enough for those integrations. herdr 0.9.5's pi
  integration needs pi ≥ 1.x (`@earendil-works/pi-coding-agent`); with pi 0.73
  it silently reports nothing.

| kind       | state reporting | tested |
|------------|-----------------|--------|
| `pi`       | yes             | pi 1.4.0 |
| `opencode` | yes (TUI and `opencode run`) | opencode 1.19.5 |
| `claude`, `codex`, `vibe` | not yet: the shim runs them in Docker, but herdr won't detect them, so use pane commands | — |

## Install

```bash
herdr plugin install xhluca-agent/herdr-docker-agents
cat > "$(herdr plugin config-dir xhluca.docker-agents)/config.env" <<'EOF'
HERDR_DOCKER_COMPOSE_FILE=~/path/to/compose.yaml
EOF
```

### Configuration (`config.env` or environment)

| variable | default | |
|---|---|---|
| `HERDR_DOCKER_COMPOSE_FILE` | — (required) | compose file with the agent services |
| `HERDR_DOCKER_SERVICE_<KIND>` | `<kind>` | service to run for an agent kind |
| `HERDR_DOCKER_WORKSPACE` | — | exported as `WORKSPACE` for the compose file; `cwd` = launch directory |
| `HERDR_DOCKER_HOME` | `/home/agent` | agent's home in the container (where integrations are mounted) |
| `HERDR_DOCKER_AGENT_UID` | `1000` | container user's uid |
| `HERDR_DOCKER_AGENT_HOST_UID` | computed | host uid it maps to (rootless Docker: from `/etc/subuid`) |
| `HERDR_DOCKER_DEBUG` | — | log every relayed or refused request to this file |

## Usage

- **From herdr:** run the `Open Docker agent shell` action, or
  `herdr plugin pane open --plugin xhluca.docker-agents --entrypoint shell`
  (it opens as a split and takes focus), then `herdr agent start … --pane <id>`.
- **By hand:** type `pi` or `opencode` in that shell, or run
  `bin/herdr-docker-run <kind> [args]` from any herdr pane.
- Session resume works inside the shell (`pi --session <id>` goes through the
  shim). herdr's own automatic resume after a server restart is disabled on purpose.

## Known limits

- `herdr agent start` must target the plugin's shell pane (or any shell with
  `shims/` first on `PATH`).
- After the agent exits, herdr can take a few seconds to clear the pane's agent label.
- Rootless Docker: the agent's files in the workspace are owned by your mapped
  subuid. Grant it access with ACLs (`setfacl -R -m u:<uid>:rwX,d:u:<uid>:rwX <dir>`).

## License

MIT
