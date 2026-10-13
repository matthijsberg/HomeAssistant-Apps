# Mantis Security Agent — Security & Architecture Remediation Plan (Pass 2)

**Target Component:** `apps/mantis-security-agent`  
**Audit Baseline:** `v1.1.0` (`abf1a80`)  
**Verification Target:** Commit `1cf7fcc` (`fix(mantis-security-agent): apply SECURITY_REMEDIATION_PLAN`)  
**Scope:** Internal MCP tools, harness orchestration, static scanner runners, OKF v0.2 knowledge engine, and approval UI.

---

## Verification Status Summary (Commit `1cf7fcc`)

| ID | Category | Status | Summary of Verification at `1cf7fcc` |
|---|---|---|---|
| **SEC-01** | Security (P0) | ✅ **RESOLVED** | `.git` rejected in `safely_extract_tar()` (`harness/uploads.py:35-38`); `GIT_SAFE_ARGS` (`-c core.fsmonitor=false -c core.hooksPath=/dev/null --no-optional-locks`) enforced in `harness/snapshot.py:135-153`. |
| **SEC-02** | Security (P0) | ⚠️ **PARTIAL** | Wildcard `CORSMiddleware` removed and 30-minute expiry added (`server.py:120-124`), **but `/api/approve/{job_id}` and `/api/reject/{job_id}` (`server.py:112-137`) still lack Ingress/operator verification**, allowing any MCP client with `job_id` to self-approve. Also, rejected/cancelled/expired upload jobs do not clean up `/data/workspaces/upload_*`. |
| **SEC-03** | Security (P0) | ⚠️ **PARTIAL** | `safe_cid` sanitization and `default_concept_id=f_path.stem` fixed in `harness/okf.py:258-261, 362`, **but `mantis_export_okf` and `mantis_import_okf` in `server.py:564-573` were NOT updated** and still resolve arbitrary unvalidated host paths without `validate_target_path()`. |
| **SEC-04** | Security (P0) | ✅ **RESOLVED** | `escapeHtml()` implemented and applied to all dynamic `.innerHTML` fields in `ui/index.html:95-244`. |
| **SEC-05** | Security (P0) | ✅ **RESOLVED** | `synthesize_patch_check` (`harness/stages.py:163-188`) replaced `os.system` and `.mantis_temp.patch` with `subprocess.run(..., input=patch_diff)` and safe Git flags. |
| **SEC-06** | Security (P0) | ⚠️ **PARTIAL** | Symlinks/hardlinks blocked in `uploads.py:40-42, 90-95` and skipped in `snapshot.py`, `extractor.py:98`, `hadolint_runner.py:23`, and `shellcheck_runner.py:23`. **Remaining:** `import_okf_bundle` (`harness/okf.py:358`) and `build_deployment_manifest` (`surface/extractor.py:144, 148`) still do not check `is_symlink()`. |
| **SEC-07** | Security (P0) | ✅ **RESOLVED** | Gemini API key moved from URL query string to `x-goog-api-key` header in `harness/stages.py:52-57`. |
| **SEC-08** | Security (P0) | ✅ **RESOLVED** | `_NoAnchorLoader.compose_node` rejects `AliasEvent` and is wired into `yaml.load` (`harness/okf.py:14-20, 45`); `query_okf_concepts` guards `resource != ''` and escapes `%`/`_` with `ESCAPE '\'` (`harness/okf.py:195-201`). |
| **LOGIC-01** | Pipeline (P1) | ❌ **OPEN** | `call_llm`, `check_and_update_budget`, `synthesize_patch_check`, and `vendor/mantis/` skills are still never called in `execute_campaign_job` (`server.py:147-252`); `run_deterministic_prepass` still runs synchronously on the FastAPI event loop and hardcodes `estimated_cost_eur: 0.05`. |
| **LOGIC-02** | Pipeline (P1) | ✅ **RESOLVED** | `mantis_start_audit` (`server.py:460-500`) computes real file counts, byte counts, and secret redaction counts across `validated_targets`. |
| **LOGIC-03** | Pipeline (P1) | ⚠️ **PARTIAL** | `upload_type` is passed (`server.py:456`), `validated_targets` is persisted (`server.py:512`), and `execute_campaign_job` cleans up `/data/workspaces/upload_*` (`server.py:256-263`). **Remaining:** `"git_url"` is still advertised in `mantis_start_audit`'s MCP schema (`server.py:298`) despite raising `ValueError` at runtime, and rejected/cancelled/expired upload workspaces are not cleaned up. |
| **LOGIC-04** | Pipeline (P1) | ⚠️ **PARTIAL** | `mantis_review_diff` (`server.py:376-423`) now enforces the 200 KB cap, validates `repo_path`, inspects added (`+`) lines, checks `os.system(`, and records a `diff_review` job in `jobs.db`. **Remaining:** Still only performs 2 substring `if` checks instead of running Semgrep (`rules/ha/homeassistant_rules.yaml`) or checking YAML/Privilege/TLS patterns on the added diff lines. |
| **LOGIC-05** | Pipeline (P1) | ✅ **RESOLVED** | `is_job_cancelled(job_id)` is checked at the start of each target iteration and before marking `"completed"` (`server.py:140-154, 239-240`). |
| **SCAN-01** | Scanners (P2) | ✅ **RESOLVED** | `rules_dir` passed to `run_semgrep()` (`harness/stages.py:135-138`) and `--metrics=off` added (`scanners/semgrep_runner.py:30`). |
| **SCAN-02** | Scanners (P2) | ✅ **RESOLVED** | `gitleaks_runner.py`, `hadolint_runner.py`, and `shellcheck_runner.py` no longer emit exceptions as findings, and `server.py:173` filters `if "error" in lead: continue` (note: update `semgrep_runner.py:63-64` to also return `[]` on exception for consistency). |
| **SCAN-03** | Scanners (P2) | ⚠️ **PARTIAL** | Noisy directories (`.git`, `node_modules`, `.venv`, `vendor`, `__pycache__`) excluded and `shellcheck_runner.py` batches by 50. **Remaining:** `is_path_denied()` is still not enforced in `surface/extractor.py`, `hadolint_runner.py`, `shellcheck_runner.py`, or `execute_campaign_job` (`server.py:175`), and raw scanner messages/snippets are not passed through `redact_secrets()`. |
| **SCAN-04** | Container (P2) | ❌ **OPEN** | `Dockerfile`, `requirements.txt`, and `run.sh` were not modified in `1cf7fcc`. |

---

## Remaining Remediations to Apply (Pass 2 Instructions)

### 1. Fix Path Validation & Symlink Check in `mantis_export_okf` and `mantis_import_okf` (`SEC-03` & `SEC-06`)

**Problem in `server.py` (lines 564–573):**
`mantis_export_okf` and `mantis_import_okf` still resolve arbitrary caller-supplied paths (`output_dir` and `bundle_dir`) without calling `validate_target_path()`:
```python
elif name == "mantis_export_okf":
    out_dir = Path(args.get("output_dir", "/data/okf_bundle")).resolve()
    count = export_okf_bundle(KNOWLEDGE_DB, out_dir)
    return {"status": "exported", "concepts_exported": count, "output_dir": str(out_dir)}

elif name == "mantis_import_okf":
    b_dir = Path(args.get("bundle_dir", "")).resolve()
    count = import_okf_bundle(KNOWLEDGE_DB, b_dir)
    return {"status": "imported", "concepts_imported": count, "bundle_dir": str(b_dir)}
```

**How to Fix:**
1. In `server.py` (`handle_tool_call`, lines 564–573), restrict `mantis_export_okf` to `/data/okf_exports` (or `/data/okf_bundle`) and validate `mantis_import_okf` against `allow_list` (plus `/data/okf_exports` / `/data/okf_bundle`):
   ```python
   elif name == "mantis_export_okf":
       allowed_export_root = (DATA_DIR / "okf_bundle").resolve()
       allowed_export_root.mkdir(parents=True, exist_ok=True)
       raw_out = args.get("output_dir") or str(allowed_export_root)
       out_dir = Path(raw_out).resolve()
       if out_dir != allowed_export_root and not str(out_dir).startswith(str(allowed_export_root) + "/"):
           raise ValueError(f"Export output_dir '{out_dir}' must reside inside '{allowed_export_root}'")
       count = export_okf_bundle(KNOWLEDGE_DB, out_dir)
       return {"status": "exported", "concepts_exported": count, "output_dir": str(out_dir)}

   elif name == "mantis_import_okf":
       raw_bundle = args.get("bundle_dir", "")
       if not raw_bundle:
           raise ValueError("bundle_dir is required")
       allowed_export_root = (DATA_DIR / "okf_bundle").resolve()
       b_path = Path(raw_bundle).resolve()
       if b_path == allowed_export_root or str(b_path).startswith(str(allowed_export_root) + "/"):
           b_dir = b_path
       else:
           b_dir = validate_target_path(raw_bundle, APP_OPTIONS.get("allow_list"))
       count = import_okf_bundle(KNOWLEDGE_DB, b_dir)
       return {"status": "imported", "concepts_imported": count, "bundle_dir": str(b_dir)}
   ```
2. In `harness/okf.py` (`import_okf_bundle`, lines 354–364), skip symlinks and excluded directories when walking `bundle_dir`:
   ```python
   for root, dirs, files in os.walk(bundle_dir):
       dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "vendor", "__pycache__")]
       for f in files:
           if not f.endswith(".md") or f.upper().startswith("README"):
               continue
           f_path = Path(root) / f
           if f_path.is_symlink():
               continue
   ```
3. In `surface/extractor.py` (`build_deployment_manifest`, lines 143–149), ensure `config.yaml` and `Dockerfile` are not symlinks:
   ```python
   config_yaml = target_dir / "config.yaml"
   if config_yaml.exists() and not config_yaml.is_symlink():
       manifest["addon_config"] = extract_addon_config_surface(config_yaml)

   dockerfile = target_dir / "Dockerfile"
   if dockerfile.exists() and not dockerfile.is_symlink():
       manifest["dockerfile"] = extract_dockerfile_surface(dockerfile)
   ```

---

### 2. Prevent Agent Self-Approval on `/api/approve/{job_id}` & Clean Up Unapproved Workspaces (`SEC-02` & `LOGIC-03`)

**Problem in `server.py` (lines 112–137, 298, 547–550):**
1. `/api/approve/{job_id}` and `/api/reject/{job_id}` do not check that the request comes from the Home Assistant Ingress proxy (`172.30.32.2` / `X-Ingress-Path`) or a local operator session, so an MCP client that knows `job_id` can `POST /api/approve/{job_id}` directly.
2. When a job is rejected (`api_reject_job`), cancelled (`mantis_cancel_audit`), or expires (`approval_expired`), any `/data/workspaces/upload_*` directory created during `mantis_start_audit` is left on disk permanently.
3. `"git_url"` is still listed in the `mantis_start_audit` MCP tool schema (`server.py:298`), but raises `ValueError: Unsupported target type: git_url` if called.

**How to Fix:**
1. Add a workspace cleanup helper in `server.py` and call it on job expiry, rejection, cancellation, and completion:
   ```python
   def cleanup_job_workspaces(job: Dict[str, Any]) -> None:
       """Remove ephemeral /data/workspaces/upload_* directories for a job."""
       if not job:
           return
       workspaces_root = str((DATA_DIR / "workspaces").resolve())
       for t in job.get("targets", []):
           t_path = str(t.get("target", "")) if isinstance(t, dict) else str(t)
           if t_path.startswith(workspaces_root + "/upload_"):
               ws_parent = Path(t_path).parent
               shutil.rmtree(ws_parent, ignore_errors=True)
   ```
2. Add an Ingress/operator origin guard `verify_ingress_request(request: Request)` on `/api/approve/{job_id}` and `/api/reject/{job_id}`:
   ```python
   def verify_ingress_request(request: Request):
       """Ensure approval/rejection comes from HA Ingress proxy (172.30.32.2) or localhost test client."""
       client_host = request.client.host if request.client else ""
       allowed_hosts = {"172.30.32.2", "127.0.0.1", "::1", "testclient"}
       if client_host not in allowed_hosts and not request.headers.get("X-Ingress-Path"):
           raise HTTPException(
               status_code=403,
               detail="Approval endpoints may only be invoked via the Home Assistant Ingress UI",
           )
   ```
3. Call `verify_ingress_request(request)` in `api_approve_job` and `api_reject_job`, and call `cleanup_job_workspaces(job)` when expiring (`server.py:122`), rejecting (`server.py:134`), or cancelling (`server.py:548`) a job.
4. Remove `"git_url"` from the `enum` on `server.py:298` (`"enum": ["path", "upload"]`).

---

### 3. Wire LLM Stages, Budget Enforcement, Patch Check, and `vendor/mantis/` Skills (`LOGIC-01`)

**Problem in `server.py` (lines 18, 147–252):**
- `call_llm` and `synthesize_patch_check` are imported on line 18 of `server.py`, and `check_and_update_budget` is defined in `harness/budget.py`, **but none of them are ever called**.
- `execute_campaign_job` runs `run_deterministic_prepass(p)` synchronously on the event loop, never invokes the LLM or `vendor/mantis/` skills, and hardcodes `usage={"tokens_in": 1200, "tokens_out": 450, "estimated_cost_eur": 0.05}`.

**How to Fix in `server.py` (`execute_campaign_job`):**
1. Import `check_and_update_budget, BudgetExceededError` from `harness.budget` in `server.py`.
2. Run `run_deterministic_prepass(p)` via `await asyncio.to_thread(run_deterministic_prepass, p)` so it does not block the FastAPI event loop.
3. Load the `vendor/mantis/` skill instructions (e.g., `mantis-threat-model/SKILL.md`, `mantis-critic/SKILL.md`, `mantis-patch/SKILL.md` under `Path(__file__).parent / "vendor" / "mantis"`).
4. When an LLM API key is configured for the job's triage/deep models (or in `APP_OPTIONS`):
   - Redact candidate code/lead snippets with `redact_secrets()` before sending to `call_llm()`.
   - Run `await asyncio.to_thread(call_llm, ...)` to triage leads and synthesize unified diff patches (`suggested_patch`).
   - Track real `tokens_in`, `tokens_out`, and `cost_eur` via `check_and_update_budget(DATA_DIR / "jobs.db", job_id, tokens_in, tokens_out, cost_eur, APP_OPTIONS.get("budgets", {}))`.
   - When a finding includes a non-empty `suggested_patch`, verify it with `patch_status = await asyncio.to_thread(synthesize_patch_check, p, finding.get("file", ""), finding["suggested_patch"])` and store `finding["patch_status"] = patch_status`.
   - When no LLM API key is configured, record `usage={"tokens_in": 0, "tokens_out": 0, "estimated_cost_eur": 0.0}` rather than a hardcoded fake `0.05` cost.

---

### 4. Upgrade `mantis_review_diff` Pattern Coverage (`LOGIC-04`)

**Problem in `server.py` (lines 389–410):**
`mantis_review_diff` only checks two hardcoded substrings (`subprocess`+`shell=True`/`os.system(` and `eval(`/`exec(`). It misses YAML deserialization (`yaml.load(` without `SafeLoader`), disabled TLS verification (`verify=False`), SQL string interpolation (`.execute(f"`), and Home Assistant privilege escalations (`host_network: true`, `full_access: true`, `apparmor: false`) defined in `rules/ha/homeassistant_rules.yaml`.

**How to Fix in `server.py` (`mantis_review_diff`):**
Expand the deterministic diff checks on `added_content` to cover the rules in `rules/ha/homeassistant_rules.yaml` (or run `run_semgrep` on a temporary file containing `added_content`):
- `yaml.load(` without `SafeLoader` / `_NoAnchorLoader` -> `CWE-502` (`HIGH`)
- `verify=False` -> `CWE-295` (`MEDIUM`)
- `.execute(f"` or `.execute(f'` -> `CWE-89` (`HIGH`)
- `host_network: true`, `full_access: true`, or `apparmor: false` -> `CWE-250` (`HIGH`)

---

### 5. Enforce `is_path_denied()` & Secret Redaction Across All Scanners (`SCAN-02` & `SCAN-03`)

**Problem:**
1. `surface/extractor.py` (line 97), `scanners/hadolint_runner.py` (line 22), `scanners/shellcheck_runner.py` (line 22), and `execute_campaign_job` (`server.py`, line 175) do not check `is_path_denied()` from `harness/snapshot.py`.
2. `scanners/semgrep_runner.py` (lines 63–64) still returns `[{"source": "semgrep", "error": str(e)}]` on exception instead of `[]` like the other three runners.
3. In `server.py` (lines 175–184), raw `message`/`description` strings from Semgrep, ShellCheck, and Hadolint are stored in `findings` and `knowledge.db` without calling `redact_secrets()`.

**How to Fix:**
1. In `surface/extractor.py`, `scanners/hadolint_runner.py`, and `scanners/shellcheck_runner.py`, import `is_path_denied` from `harness.snapshot` and skip any file where `is_path_denied(str(f_path.relative_to(target_dir)), str(f_path))` is `True`.
2. In `scanners/semgrep_runner.py` (lines 63–64), return `[]` on exception (matching `gitleaks_runner.py`, `hadolint_runner.py`, and `shellcheck_runner.py`).
3. In `server.py` (`execute_campaign_job`, lines 173–184), skip any lead whose `file` matches `is_path_denied(rel_file, lead_file)` and pass `lead.get("message") or lead.get("description") or "Security lead detected"` through `redact_secrets()` before storing in `findings` or `record_okf_concept()`.

---

### 6. Container & Supply-Chain Hardening (`SCAN-04`)

**Problem in `Dockerfile`, `requirements.txt`, and `run.sh`:**
1. `Dockerfile` (lines 22–29) downloads `gitleaks` and `hadolint` binaries over `curl` without verifying SHA-256 checksums.
2. `requirements.txt` uses unpinned `>=` ranges instead of pinned versions.
3. `run.sh` (line 30) prints the full `MANTIS_BEARER_TOKEN` in plaintext to container stdout (`echo "[Mantis] Bearer Token: $(cat "$TOKEN_FILE")"`).

**How to Fix:**
1. In `Dockerfile` (lines 22–29), download the release archives/binaries to `/tmp` and verify their SHA-256 checksums with `sha256sum -c` before moving them to `/usr/local/bin`.
2. In `requirements.txt`, pin exact `==` versions for reproducible container builds.
3. In `run.sh` (lines 28–32), do not print the raw secret token to container logs; instead log its storage path (`/data/bearer_token.txt`) and a masked prefix:
   ```bash
   TOKEN_PREVIEW="$(head -c 6 "$TOKEN_FILE")..."
   echo "[Mantis] Generated fresh persistent bearer token at $TOKEN_FILE (prefix: $TOKEN_PREVIEW)"
   ```
