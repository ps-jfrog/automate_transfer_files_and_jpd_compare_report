# `created_after` vs `downloaded_after`

These optional settings live under `transfer` in `config.yaml`. They are passed to `jf rt transfer-files` as `--created-after` and `--downloaded-after`.

Leave both as `null` to transfer without a time filter (current CLI default).

**Format:** `YYYY-MM-DDTHH:mm:ss.sssZ` (UTC)

Always quote the value in YAML so it stays a string:

```yaml
created_after: "2026-07-01T00:00:00.000Z"
```

Unquoted timestamps are valid YAML dates; older builds crashed with
`datetime has no attribute 'strip'`. Current code converts them to the CLI string.

They look at **different clocks** on the artifact.

| Setting | Question it asks | Simple meaning |
|---------|------------------|----------------|
| `created_after` | When was this file **uploaded / created** in the source repo? | Transfer files created at or after this time. |
| `downloaded_after` | When was this file **last downloaded** from Artifactory? | Transfer files last downloaded at or after this time. |

---

## `created_after`

Transfers files whose **create/upload time** is at or after the timestamp.

Example:

```yaml
transfer:
  created_after: "2024-06-01T00:00:00.000Z"
  downloaded_after: null
```

- JAR uploaded on **June 10** → transferred
- JAR uploaded on **May 20** → skipped
- JAR uploaded on June 10 that **nobody ever downloaded** → still transferred

---

## `downloaded_after`

Transfers files whose **last download time** is at or after the timestamp.

Files that were **never downloaded** are skipped (they have no download time).

Example:

```yaml
transfer:
  created_after: null
  downloaded_after: "2024-06-01T00:00:00.000Z"
```

- File last downloaded on **June 10** → transferred
- File last downloaded on **May 20** → skipped
- File **never downloaded** → skipped

To include **every file that was ever downloaded**, and still skip never-downloaded files, use a far-past timestamp:

```yaml
transfer:
  created_after: null
  downloaded_after: "1970-01-01T00:00:00.000Z"
```

---

## Same repo, three files

Assume the filter date is **June 1, 2024**.

| File | Created | Last downloaded | `created_after` June 1 | `downloaded_after` June 1 |
|------|---------|-----------------|------------------------|---------------------------|
| A | May 1 | June 15 | skip | transfer |
| B | June 10 | never | transfer | skip |
| C | June 10 | June 20 | transfer | transfer |

---

## If both are set

JFrog CLI uses **`created_after` only**. `downloaded_after` is ignored.

For “skip files that were never downloaded,” set **only** `downloaded_after` and leave `created_after: null`.
