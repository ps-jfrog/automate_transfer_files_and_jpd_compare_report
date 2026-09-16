# Easy Setup (Linux)

Minimum command sequence to get going on Linux.

**Assumption:** JFrog CLI (`jf`) is already installed and configured with your source and target server IDs (`jf c show` lists them).

------

## 1. Install

```bash
cd jfrog-transfer-automation
./scripts/install.sh
```
Note: It installs into whatever Python environment is active. If you don't want it installed globally, activate a virtualenv (python3 -m venv .venv && source .venv/bin/activate) before running ./scripts/install.sh.


## 2. Build your repo list (one repo key per line)

```bash
jf rt curl -X GET "/api/repositories?type=local" --server-id=<source-server-id> | jq -r '.[] | .key' > repos.txt
```

> No `jq`? See `QUICKSTART.md` → "Building the Repository List" for `grep`/`sed`/`awk` alternatives.

## 3. Create config

```bash
cp config.sample.yaml config.yaml
```

Edit `config.yaml` — minimum changes:

```yaml
jfrog:
  source_server_id: "<source-server-id>"
  target_server_id: "<target-server-id>"

transfer:
  include_repos_file: "repos.txt"
  mode: "per_repo"
  jfrog_cli_home_strategy: "per_repo_isolated"

report:
  repos_file_for_comparison: "repos.txt"
```

> `repos.txt` must sit next to `config.yaml` (relative paths resolve from the config file's directory).

## 4. Validate + dry run

```bash
jfrog-transfer-automation validate  --config config.yaml
jfrog-transfer-automation run-once  --config config.yaml --dry-run
```

## 5. Run the transfer

Foreground:

```bash
jfrog-transfer-automation run-once --config config.yaml
```

Or background:

```bash
jfrog-transfer-automation run-once --config config.yaml --background
```

## 6. Useful commands while it runs (separate terminal)

```bash
jfrog-transfer-automation status         --config config.yaml
jfrog-transfer-automation monitor        --config config.yaml --interval 10
jfrog-transfer-automation update-threads --config config.yaml --threads 16
jfrog-transfer-automation stop           --config config.yaml
jfrog-transfer-automation resume         --config config.yaml
jfrog-transfer-automation report         --config config.yaml
```

---

For full details (scheduler, continuous mode, end-time cutoff, adaptive threads, troubleshooting), see `QUICKSTART.md`, `INSTALL.md`, and `TROUBLESHOOTING.md`.
