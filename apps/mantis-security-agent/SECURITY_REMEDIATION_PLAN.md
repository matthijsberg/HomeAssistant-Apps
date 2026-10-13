# Mantis Security Agent — Security & Architecture Remediation Plan

**Target Component:** `apps/mantis-security-agent`  
**Audit Baseline:** `v1.1.0` (`abf1a80`)  
**Scope:** Internal MCP tools, harness orchestration, static scanner runners, OKF v0.2 knowledge engine, and approval UI.

This document provides step-by-step implementation instructions to remediate all verified security vulnerabilities (`SEC-01` through `SEC-08`), complete the disconnected LLM/Mantis skill pipeline stages (`LOGIC-01` through `LOGIC-05`), and harden the static scanner runners (`SCAN-01` through `SCAN-04`).

---

## Part 1: Security Remediations (Priority P0)

### SEC-01: Prevent `.git/config` (`core.fsmonitor`) RCE on Uploaded Archives (`CWE-78`)

**Problem:**
1. In `server.py` (`handle_tool_call` for `mantis_start_audit`, lines 411–418), `unpack_upload()` extracts an untrusted `tar.gz` archive into `/data/workspaces/upload_<id>/extracted` and immediately passes that directory to `compute_snapshot_id()` **before** operator approval.
2. `safely_extract_tar()` in `harness/uploads.py` (lines 13–56) permits `.git/config` files inside tar archives.
3. Because the container process owns the extracted files, Git's `safe.directory` check passes and `git -C <target_path> status --porcelain` in `harness/snapshot.py` (line 144) executes `core.fsmonitor` from the archive's `.git/config`.

**How to Fix:**
1. In `harness/uploads.py` (`safely_extract_tar`), reject any archive member that includes a `.git` path segment (if Git history is needed for an upload, require `upload_type == "bundle"`):
   ```python
   # Inside safely_extract_tar() member loop in harness/uploads.py:
   member_parts = Path(member.name).parts
   if ".git" in member_parts:
       raise ValueError(f"Git metadata directory (.git) is prohibited in tar archives: {member.name}")
   ```
2. In `harness/snapshot.py` (`compute_snapshot_id`, lines 134–148), disable `fsmonitor`, hooks, and optional locks on all `git` invocations:
   ```python
   GIT_SAFE_ARGS = [
       "git",
       "-c", "core.fsmonitor=false",
       "-c", "core.hooksPath=/dev/null",
       "--no-optional-locks",
       "-C", str(target_path),
   ]
   rev_res = subprocess.run(
       GIT_SAFE_ARGS + ["rev-parse", "HEAD"],
       capture_output=True, text=True, timeout=5,
   )
   ...
   status_res = subprocess.run(
       GIT_SAFE_ARGS + ["status", "--porcelain"],
       capture_output=True, text=True, timeout=5,
   )
   ```

---

### SEC-02: Prevent Agent Self-Approval on `/api/approve/{job_id}` & Lock Down CORS (`CWE-306` / `CWE-284`)

**Problem:**
- `/mcp` enforces `Depends(verify_bearer_token)`, but `/api/jobs`, `/api/jobs/{job_id}`, `/api/approve/{job_id}`, and `/api/reject/{job_id}` (`server.py`, lines 107–138) have no authentication or origin verification on the same port (`8000`).
- Any MCP client/agent that calls `mantis_start_audit` receives `job_id` and can immediately call `POST /api/approve/{job_id}` itself, bypassing human-in-the-loop approval.
- `CORSMiddleware` (`server.py`, lines 76–82) sets `allow_origins=["*"]` with `allow_credentials=True`.

**How to Fix:**
1. Remove `CORSMiddleware` with `allow_origins=["*"]` from `server.py` (or restrict `allow_origins` to explicit configured origins).
2. Protect `/api/approve/{job_id}`, `/api/reject/{job_id}`, and `/api/jobs*` so they cannot be called by the MCP agent client:
   - Verify the request comes from the Ingress proxy IP (`172.30.32.2`) or require a dedicated operator session/header check on `/api/*`.
   - Require `manifest_hash` verification in `POST /api/approve/{job_id}` AND enforce `expires_at` so stale jobs cannot be approved:
     ```python
     @app.post("/api/approve/{job_id}")
     async def api_approve_job(job_id: str, request: Request, background_tasks: BackgroundTasks):
         job = get_job(job_id)
         if not job:
             raise HTTPException(status_code=404, detail="Job not found")
         if job["status"] != "waiting_confirmation":
             return JSONResponse({"status": "error", "message": f"Job is in state '{job['status']}'"}, status_code=400)

         # Verify job approval window has not expired (30 minutes)
         created_dt = datetime.datetime.fromisoformat(job["created_at"])
         if (datetime.datetime.now(datetime.timezone.utc) - created_dt).total_seconds() > 1800:
             update_job_status(job_id, status="cancelled", stage="approval_expired")
             raise HTTPException(status_code=410, detail="Approval window expired")
     ```

---

### SEC-03: Fix Path Traversal in `mantis_export_okf`, `mantis_import_okf`, and `export_okf_bundle` (`CWE-22` / `CWE-732`)

**Problem:**
1. In `server.py` (lines 492–500), `mantis_export_okf` and `mantis_import_okf` resolve arbitrary caller-supplied paths (`output_dir` and `bundle_dir`) without calling `validate_target_path()`.
2. In `harness/okf.py` (`export_okf_bundle`, lines 258–261):
   ```python
   slug = _OKF_SLUG_RE.sub('_', c.get('title', 'concept').lower())[:50].strip('_.')
   cid = c.get('concept_id', 'concept')
   filename = f"{cid}_{slug}.md"
   file_path = subdir / filename
   ```
   `cid` is not sanitized with `_OKF_SLUG_RE`. When `import_okf_bundle` (line 360) imports a file from a subdirectory (e.g., `invariants/inv_no_root.md`), `default_concept_id` is set to `"invariants/inv_no_root.md"` (containing `/`). Subsequent export either fails with `FileNotFoundError` or traverses directories if `cid` contains `..`.

**How to Fix:**
1. In `server.py`:
   - Restrict `mantis_export_okf` so `output_dir` must resolve inside `/data/okf_bundle` (or `/data/exports`):
     ```python
     elif name == "mantis_export_okf":
         base_export_root = (DATA_DIR / "okf_exports").resolve()
         base_export_root.mkdir(parents=True, exist_ok=True)
         raw_out = args.get("output_dir") or str(base_export_root / "default")
         out_dir = validate_target_path(raw_out, allow_list=[str(base_export_root)])
     ```
   - Validate `bundle_dir` in `mantis_import_okf` using `validate_target_path(args.get("bundle_dir", ""), APP_OPTIONS.get("allow_list") + [str(DATA_DIR / "okf_exports")])` (note: update `validate_target_path` so `/data/okf_exports` is permitted when explicitly in `allow_list`).
2. In `harness/okf.py`:
   - Sanitize `cid` in `export_okf_bundle` (line 259):
     ```python
     raw_cid = str(c.get("concept_id") or "concept")
     safe_cid = _OKF_SLUG_RE.sub("_", Path(raw_cid).stem)[:50].strip("_.") or "concept"
     filename = f"{safe_cid}_{slug}.md" if not safe_cid.endswith(slug) else f"{safe_cid}.md"
     ```
   - In `import_okf_bundle` (line 360), pass `default_concept_id=f_path.stem` (or store `concept_id` explicitly in frontmatter during export) so re-importing and re-exporting is idempotent.

---

### SEC-04: Fix Stored DOM XSS in `ui/index.html` (`CWE-79`)

**Problem:**
- `ui/index.html` (lines 120–231) interpolates untrusted strings from audited repositories (`targets`, `job.markdown_report`, `f.title`, `f.rationale`, `f.file`, `f.suggested_patch`, `m.models`) directly into `.innerHTML`.
- A malicious filename, comment, or code snippet in an audited target can execute JavaScript in the operator's browser when viewing the dashboard and automatically invoke `approveJob()`.

**How to Fix:**
Add an `escapeHtml()` helper in `ui/index.html` and wrap every dynamic value interpolated into HTML templates:
```javascript
function escapeHtml(unsafe) {
  if (unsafe === null || unsafe === undefined) return "";
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
```
Apply `escapeHtml(...)` to `job.job_id`, `targets`, `m.models?.triage?.model`, `m.models?.deep?.model`, `j.job_type`, `j.status`, `job.markdown_report`, `f.cwe`, `f.title`, `f.severity`, `f.rationale`, `f.message`, `f.file`, and `f.suggested_patch`.

---

### SEC-05: Replace `os.system` & Read-Only Mount Write in `synthesize_patch_check` (`CWE-78`)

**Problem:**
- `harness/stages.py` (lines 157–177) writes `.mantis_temp.patch` directly into `repo_dir` (which fails on read-only mounts like `/addons` or `/share/projects`) and calls `os.system(f"git -C '{repo_dir}' apply --check '{patch_file}' >/dev/null 2>&1")`, which is vulnerable to shell command injection if `repo_dir` contains `'`.

**How to Fix:**
Replace `synthesize_patch_check` in `harness/stages.py` with `subprocess.run` feeding the diff via `stdin`:
```python
def synthesize_patch_check(repo_dir: Path, target_file: str, patch_diff: str) -> str:
    """
    Verify if a proposed unified diff applies cleanly using git apply --check.
    Returns: 'proposed_applies_cleanly' | 'proposed_conflicts' | 'none'
    """
    if not patch_diff or not patch_diff.strip():
        return "none"

    try:
        res = subprocess.run(
            [
                "git",
                "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=/dev/null",
                "-C", str(repo_dir),
                "apply", "--check", "-",
            ],
            input=patch_diff,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "proposed_applies_cleanly" if res.returncode == 0 else "proposed_conflicts"
    except Exception:
        return "proposed_conflicts"
```

---

### SEC-06: Harden Symlink Handling in Uploads, Git Bundles, and Directory Walkers (`CWE-59` / `CWE-22`)

**Problem:**
1. In `harness/uploads.py` (`safely_extract_tar`, lines 41–44), `link_target = (dest_dir / member.linkname).resolve()` resolves relative symlinks against `dest_dir` instead of `(dest_dir / member.name).parent`.
2. In `harness/uploads.py` (`unpack_upload`, line 86), `git clone` on a bundle checks out symlinks into `clone_dir`.
3. `os.walk` loops in `harness/snapshot.py` (line 91), `surface/extractor.py` (line 91), `scanners/hadolint_runner.py` (line 18), and `scanners/shellcheck_runner.py` (line 18) follow symlinks when opening files.

**How to Fix:**
1. In `safely_extract_tar` (`harness/uploads.py`, lines 40–45), reject all symlinks and hardlinks in uploaded archives (or resolve symlinks relative to `(dest_dir / member.name).parent`):
   ```python
   if member.issym() or member.islnk():
       raise ValueError(f"Symlinks and hardlinks are prohibited in uploaded archives: {member.name}")
   ```
2. In `unpack_upload` (`harness/uploads.py`, line 86), disable symlinks and fsmonitor when cloning bundles:
   ```python
   ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false", "-c", "core.fsmonitor=false", "clone", str(bundle_file), str(clone_dir)]
   ```
3. In all `os.walk` loops (`snapshot.py`, `extractor.py`, `hadolint_runner.py`, `shellcheck_runner.py`, `okf.py`), skip symlinks and ensure resolved paths stay within the root directory:
   ```python
   if abs_p.is_symlink():
       continue
   ```

---

### SEC-07: Prevent Gemini API Key Leak in `call_llm` Exceptions (`CWE-532` / `CWE-200`)

**Problem:**
- In `harness/stages.py` (line 52), `call_llm` embeds `api_key` in the URL query string:
  `url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"`
- When `resp.raise_for_status()` fails, `httpx.HTTPStatusError` includes the full URL (with the secret key) in `str(e)`, which `server.py` (lines 243 and 553) writes into `jobs.db` (`error_message`) and returns over MCP.

**How to Fix:**
Pass the Gemini API key in the `x-goog-api-key` header instead of the URL:
```python
if provider == "gemini":
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    ...
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
```

---

### SEC-08: Wire `_NoAnchorLoader` & Fix Empty-Resource SQLite `LIKE` Wildcard in `harness/okf.py` (`CWE-776` / `CWE-89`)

**Problem:**
1. `harness/okf.py` (lines 14–23) defines `_NoAnchorLoader`, but does not override `compose_node` to reject aliases, and line 48 still uses `Loader=yaml.SafeLoader`.
2. In `query_okf_concepts` (`harness/okf.py`, lines 198–202):
   `conditions.append("(resource = ? OR resource LIKE ? OR ? LIKE '%' || resource)")`
   When a stored concept has `resource == ""` (e.g., cross-artifact risks from `server.py:162–170`), `'%' || resource` becomes `'%'`, matching **every** `target_file` query.

**How to Fix:**
1. Properly implement `_NoAnchorLoader` in `harness/okf.py` and use it on line 48:
   ```python
   class _NoAnchorLoader(yaml.SafeLoader):
       """Prohibit YAML aliases/anchors to prevent billion-laughs attacks in frontmatter."""
       def compose_node(self, parent, index):
           if self.check_event(yaml.events.AliasEvent):
               raise yaml.YAMLError("YAML aliases/anchors are prohibited in OKF frontmatter.")
           return super().compose_node(parent, index)
   ```
   And on line 48:
   ```python
   loaded = yaml.load(fm_raw, Loader=_NoAnchorLoader)
   ```
2. In `query_okf_concepts` (`harness/okf.py`, lines 198–202), ignore empty `resource` values in the suffix match and escape `LIKE` wildcards (`%`, `_`):
   ```python
   if resource:
       clean_res = resource.replace("\\", "/").lstrip("/")
       escaped_res = clean_res.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
       conditions.append(
           "(resource != '' AND (resource = ? OR resource LIKE ? ESCAPE '\\' OR ? LIKE '%' || resource))"
       )
       params.extend([clean_res, f"%{escaped_res}%", clean_res])
   ```

---

## Part 2: Completing Disconnected Tool & Pipeline Logic (Priority P1)

### LOGIC-01: Wire `call_llm`, `check_and_update_budget`, `synthesize_patch_check`, and `vendor/mantis/` Skills into `execute_campaign_job`

**Problem:**
- `server.py` (line 19) imports `call_llm` and `synthesize_patch_check`, and `harness/budget.py` defines `check_and_update_budget`, **but none of them are called**.
- `execute_campaign_job` (`server.py`, lines 142–243) only runs `run_deterministic_prepass()`, labels raw scanner output as `statically_confirmed`, hardcodes `estimated_cost_eur: 0.05`, and never invokes the LLM or any of the 19 skills under `vendor/mantis/`.

**How to Fix:**
1. Move `run_deterministic_prepass()` and secret-redacted file collection **into `mantis_start_audit` (or an indexing pre-stage before `waiting_confirmation`)**, as specified in `ARCHITECTURE.md`.
2. After operator approval, in `execute_campaign_job`:
   - Load the relevant stage prompts from `vendor/mantis/` (`mantis-threat-model/SKILL.md`, `mantis-researcher/SKILL.md`, `mantis-critic/SKILL.md`, `mantis-calibrate/SKILL.md`, `mantis-patch/SKILL.md`).
   - Redact all candidate source snippets with `redact_secrets()` before constructing LLM prompts.
   - Before/after each `call_llm()` call, invoke `check_and_update_budget(DATA_DIR / "jobs.db", job_id, total_tokens_in, total_tokens_out, actual_cost_eur, APP_OPTIONS.get("budgets", {}))`.
   - For any finding where the LLM proposes a unified diff (`suggested_patch`), validate it via `synthesize_patch_check(p, finding["file"], finding["suggested_patch"])` and attach the verification status (`patch_status`).
   - Run blocking subprocess/HTTP operations in a worker thread (`await asyncio.to_thread(...)`) so the main FastAPI event loop remains responsive.

---

### LOGIC-02: Compute Real File, Byte, and Redaction Counts in `mantis_start_audit`

**Problem:**
- `server.py` (lines 423–429) hardcodes `files_count=10, bytes_count=50000, redactions=0` in `create_egress_manifest()`.

**How to Fix:**
Walk all `validated_targets` (filtering out `is_path_denied()` and symlinks), count the actual eligible source files, sum their byte lengths, run `redact_secrets()` across the candidate content to obtain the true `redactions` count, and pass those real metrics to `create_egress_manifest()`.

---

### LOGIC-03: Persist `validated_targets` (Not `raw_targets`) and Clean Up Ephemeral Workspaces

**Problem:**
- In `server.py` (line 438), `create_job()` saves `targets=raw_targets` instead of `validated_targets`.
- For `type: "upload"`, `raw_targets` contains the base64 archive string in `"target"`, causing `execute_campaign_job` (line 159: `Path(target_path).resolve()`) to fail instead of scanning `/data/workspaces/upload_<id>/extracted`.
- Also pass `upload_type=t.get("upload_type", "tar")` to `unpack_upload()` on line 415, handle or remove `"git_url"` from the `mantis_start_audit` schema, and delete `/data/workspaces/upload_<id>` inside the `finally:` block of `execute_campaign_job` (and on job rejection/cancellation).

---

### LOGIC-04: Upgrade `mantis_review_diff` Beyond 2 Substring Checks

**Problem:**
- `mantis_review_diff` (`server.py`, lines 355–395) only checks `if "subprocess" in clean_diff and "shell=True" in clean_diff` and `if "eval(" in clean_diff or "exec(" in clean_diff` across the entire diff string (including removed `-` lines and context lines), ignores `repo_path`, `context_paths`, `context`, and `llm`, does not enforce the 200 KB max diff size, and does not save a job in `jobs.db`.

**How to Fix:**
1. Enforce `if len(diff_text.encode("utf-8")) > 200 * 1024: raise ValueError("Diff exceeds 200 KB limit")`.
2. Parse unified diff hunks to inspect added (`+`) lines and run Semgrep (`rules/ha/homeassistant_rules.yaml`) and `secret_scanner` patterns on the added content.
3. If `repo_path` is provided, validate it with `validate_target_path()`.
4. Persist the review result in `jobs.db` via `create_job(..., job_type="diff_review", status="completed")` so `mantis_get_report` and the UI table display diff reviews as documented.

---

### LOGIC-05: Respect Job Cancellation Between Pipeline Stages

**Problem:**
- `mantis_cancel_audit` sets `status="cancelled"`, but `execute_campaign_job` (`server.py`, lines 195 and 231) unconditionally overwrites the status back to `"running"` and `"completed"`.

**How to Fix:**
Create a helper `is_job_cancelled(job_id) -> bool` that checks `get_job(job_id)["status"] == "cancelled"`, and check it before each stage transition and before writing the final `"completed"` status in `execute_campaign_job`.

---

## Part 3: Static Scanner & Container Hygiene (Priority P2)

1. **`scanners/semgrep_runner.py` & `harness/stages.py` (`SCAN-01`)**:
   - In `harness/stages.py` (line 133), pass `custom_rules_dir= Path(__file__).parent.parent / "rules"` to `run_semgrep()`.
   - In `scanners/semgrep_runner.py` (line 29), add `"--metrics=off"` so Semgrep never phones home during local static pre-passes.
2. **Do Not Convert Scanner Exceptions into Vulnerability Findings (`SCAN-02`)**:
   - In `scanners/semgrep_runner.py`, `gitleaks_runner.py`, `shellcheck_runner.py`, and `hadolint_runner.py`, when an exception occurs, return `{"source": "...", "error": str(e)}` in a separate `scanner_errors` list (or filter `if "error" in lead: continue` in `server.py:171`) so scanner timeouts are not recorded as `statically_confirmed` vulnerabilities in `jobs.db` and `knowledge.db`.
3. **Enforce `is_path_denied()` Across All Scanners & Walkers (`SCAN-03`)**:
   - Filter out files matching `DENIED_GLOBS` (`harness/snapshot.py`) and skip `.git`, `node_modules`, `.venv`, and `vendor` directories in `surface/extractor.py`, `hadolint_runner.py`, and `shellcheck_runner.py`.
   - Batch `scripts` in `shellcheck_runner.py` (e.g., chunks of 50 files) to avoid hitting OS `ARG_MAX` limits on large repositories.
4. **Container & Supply-Chain Hardening (`SCAN-04`)**:
   - Verify SHA-256 checksums when downloading `gitleaks` and `hadolint` in `Dockerfile` (lines 22–29).
   - Pin exact package versions in `requirements.txt`.
   - Avoid printing the raw `MANTIS_BEARER_TOKEN` to stdout in `run.sh` (line 30); instead log the path `/data/bearer_token.txt` or a masked prefix.
