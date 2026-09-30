

## `mode: "single_command"`

One JFrog CLI process is launched, and it transfers **all repos together**.

**Uses:**
- `threads` — the only knob that matters. It's passed to that single process.

**Ignores:**
- `batch_size` (there's no batching — everything runs as one process)
- `max_total_threads` (there's only one process, so its threads = total load)
- `adaptive_threads` (nothing to redistribute)
- `jfrog_cli_home_strategy: per_repo_isolated` (no per-repo homes)

**Uses (monitoring):**
- `stuck_timeout_seconds` — restarts the combined transfer if it makes no
  progress for N seconds. Progress is measured by the modification time of
  the raw CLI output log at `<output_dir>/<timestamp>/logs/transfer.log`.
- `poll_interval_seconds` — how often the monitor checks for completion,
  staleness, `schedule.end_time`, and a user-invoked `stop`.

The transfer is launched as a background process and monitored rather than
run as a blocking call, so `end_time` and `stuck_timeout_seconds` are both
enforced even mid-transfer — the same monitoring loop `per_repo` mode uses,
applied to the single combined command.

**Logging:** all repos share **one** JFrog CLI process, so raw output arrives
as a single stream. It's always written in full to `logs/transfer.log`, and
a demultiplexer thread additionally tees it into `logs/<repo>.log` per repo
by watching the CLI's own per-repo phase markers (e.g. `for repo 'X'`,
`repository 'X'...`) — the same markers the CLI prints because repos in
`--include-repos` are transferred **sequentially** (one at a time, in list
order). This gives you the same `logs/<repo>.log` files as `per_repo` mode.
Two caveats: (1) the split relies on undocumented log wording, so treat
`logs/transfer.log` as the authoritative fallback if a per-repo file looks
incomplete; (2) a restart re-invokes the **entire** `--include-repos` list
from the top rather than just the one stuck repo — use `per_repo` mode if
you need a restart scoped to a single repo.

**Stuck detection** is based on `logs/transfer.log`'s modification time (not
the per-repo files), and is unaffected by the caveats above — since repos
are processed sequentially, a hang in the currently-active repo always goes
stale correctly.

**How to tune:** just pick `threads`. Start conservative (e.g. 32–128), watch source Artifactory CPU/network, raise if fine.

```yaml
transfer:
  mode: "single_command"
  threads: 128         # only setting that matters
```

**Best for:** small-to-medium repo sets (say, under ~20 repos) where you're happy with one process handling everything.

---

## `mode: "per_repo"`

One JFrog CLI process **per repo**, run in parallel batches. This is where all the fancy knobs come alive.

**Uses:**
- `batch_size` — how many repos to transfer in parallel at once.
- `threads` — the **ceiling** for each single repo's process.
- `max_total_threads` — the **global cap** across all parallel processes.
- `adaptive_threads` — if true, hands freed threads to still-running repos. Freed threads are the leftover thread slots from repos that finished early — adaptive_threads decides whether those slots are given to the still-running repos (boost throughput) or simply left idle (predictable load).
- `stuck_timeout_seconds` — restart a repo if it makes no progress for N seconds.
- `jfrog_cli_home_strategy` — use `per_repo_isolated` for one CLI home per repo (recommended).

**The formula each batch uses:**
```
per_repo_threads = min(threads, max_total_threads ÷ active_repos_in_batch)
```

### Two common patterns

**Pattern 1 — Simple, predictable load (no adaptive):**

Each repo gets a fixed thread count. Idle capacity is wasted when repos finish early, but load is very predictable.

```yaml
transfer:
  mode: "per_repo"
  threads: 256              # each repo gets 256 threads
  batch_size: 4             # 4 repos in parallel
  max_total_threads: 1024   # safety cap = 4 × 256 = 1024
  adaptive_threads: false
  stuck_timeout_seconds: 600
  jfrog_cli_home_strategy: "per_repo_isolated"
```

Result: constant 1024 total threads while all 4 run; when repos finish, total drops.

**Pattern 2 — Maximum throughput (adaptive):**

Set `threads` equal to `max_total_threads` so idle capacity can be redistributed to the remaining repos.

```yaml
transfer:
  mode: "per_repo"
  threads: 1024             # per-repo ceiling = same as global cap
  batch_size: 4
  max_total_threads: 1024   # global cap
  adaptive_threads: true    # redistribute freed threads
  stuck_timeout_seconds: 600
  jfrog_cli_home_strategy: "per_repo_isolated"
```

Result: starts at 256 per repo (4 × 256 = 1024). As repos finish, remaining repos are boosted (2 left → 512 each; 1 left → 1024). Total load stays close to 1024.

**Best for:** larger repo sets, or when you want isolation, restart-on-stuck, and adaptive load balancing.

---

## Quick decision guide

| Situation | Mode | Key settings |
|---|---|---|
| Few repos (< 20), you just want it to work | `single_command` | `threads` |
| Many repos, want parallelism | `per_repo` + `per_repo_isolated` | `threads`, `batch_size`, `max_total_threads` |
| Same as above + want to squeeze max throughput | Add `adaptive_threads: true` | Set `threads = max_total_threads` |
| Recover automatically from stuck transfers | Both modes support this | `stuck_timeout_seconds` |
| Restart isolation per repo when stuck | Only `per_repo` supports this (single_command restarts the whole combined transfer, even though it also has per-repo log files) | `stuck_timeout_seconds` + `per_repo` |
| Per-repo log files (`logs/<repo>.log`) | Both modes — `per_repo` writes them directly; `single_command` demultiplexes them from the combined stream (best-effort) | n/a |

## Rule of thumb

- **First** pick your mode.
- Set `max_total_threads` = the **total** load your source Artifactory can handle (e.g. 1024).
- If not adaptive: `threads = max_total_threads ÷ batch_size` (e.g. 256).
- If adaptive: `threads = max_total_threads` (e.g. 1024).
- Ramp up gradually while watching source CPU/network.