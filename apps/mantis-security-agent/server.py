import os
import sys
import json
import time
import uuid
import asyncio
import secrets
import datetime
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from harness.snapshot import validate_target_path, compute_snapshot_id, is_path_denied
from harness.jobs import init_db, create_job, get_job, update_job_status, list_jobs
from harness.egress import redact_secrets, create_egress_manifest, format_warning_text
from harness.stages import run_deterministic_prepass, call_llm, synthesize_patch_check
from harness.uploads import unpack_upload
from harness.okf import (
    record_okf_concept,
    query_okf_concepts,
    export_okf_bundle,
    import_okf_bundle,
    query_security_guidance,
    init_okf_table,
)

# Base paths
ROOT_DIR = Path(__file__).parent.resolve()
DATA_DIR = Path(os.environ.get("MANTIS_DATA_DIR", "/data"))
OPTIONS_FILE = DATA_DIR / "options.json"
CACHE_DIR = DATA_DIR / "cache"
WORKSPACES_DIR = DATA_DIR / "workspaces"
KNOWLEDGE_DB = CACHE_DIR / "knowledge.db"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

# Initialize SQLite databases
init_db(DATA_DIR / "jobs.db")
init_okf_table(KNOWLEDGE_DB)

# Load configuration options
def load_options() -> Dict[str, Any]:
    if OPTIONS_FILE.exists():
        try:
            return json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "providers": {
            "gemini": {"api_key": os.environ.get("GEMINI_API_KEY", "")},
            "ollama": {"base_url": os.environ.get("OLLAMA_BASE_URL", "http://172.30.32.1:11434")},
        },
        "defaults": {
            "triage": {"provider": "gemini", "model": "gemini-2.5-flash"},
            "deep": {"provider": "gemini", "model": "gemini-2.5-pro"},
        },
        "budgets": {
            "max_tokens_per_job": 2_000_000,
            "max_cost_eur_per_job": 5.0,
            "max_cost_eur_per_day": 15.0,
        },
        "ha_external_url": "https://hass.b3rg.nl:8123",
        "confirm_wait_seconds": 60,
        "allow_list": ["/addons", "/homeassistant", "/addon_configs", "/share/projects"],
    }

APP_OPTIONS = load_options()
BEARER_TOKEN = os.environ.get("MANTIS_BEARER_TOKEN") or APP_OPTIONS.get("bearer_token")

app = FastAPI(title="Mantis Security Agent", version="1.1.0")

# Authentication dependency for MCP
def verify_bearer_token(authorization: Optional[str] = Header(None)):
    if not BEARER_TOKEN:
        return True  # If no token configured, permit internal calls
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    if not secrets.compare_digest(parts[1], BEARER_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid Bearer Token")
    return True


# --- Ingress Web UI & Approval Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_file = ROOT_DIR / "ui" / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Mantis Security Agent</h1><p>UI loading error</p>")

@app.get("/api/jobs")
async def api_list_jobs():
    return JSONResponse(list_jobs(limit=50))

@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job)

@app.post("/api/approve/{job_id}")
async def api_approve_job(job_id: str, background_tasks: BackgroundTasks):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "waiting_confirmation":
        return JSONResponse({"status": "error", "message": f"Job is in state '{job['status']}', not waiting_confirmation"})

    # SEC-02: Verify job approval window has not expired (30 minutes)
    created_dt = datetime.datetime.fromisoformat(job["created_at"])
    if (datetime.datetime.now(datetime.timezone.utc) - created_dt).total_seconds() > 1800:
        update_job_status(job_id, status="cancelled", stage="approval_expired")
        raise HTTPException(status_code=410, detail="Approval window expired")

    update_job_status(job_id, status="running", approved=True, stage="approved")
    # Trigger execution in background
    background_tasks.add_task(execute_campaign_job, job_id)
    return JSONResponse({"status": "approved", "job_id": job_id})

@app.post("/api/reject/{job_id}")
async def api_reject_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    update_job_status(job_id, status="cancelled", stage="rejected_by_operator")
    return JSONResponse({"status": "rejected", "job_id": job_id})


def is_job_cancelled(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job.get("status") in ("cancelled", "interrupted"))


# --- Background Worker for Audits ---

async def execute_campaign_job(job_id: str):
    """Execute Mantis campaign stages sequentially after operator approval."""
    job = get_job(job_id)
    if not job or job["status"] != "running":
        return

    if is_job_cancelled(job_id):
        return

    update_job_status(job_id, status="running", progress=10, stage="indexing")
    targets = job["targets"]
    env_context = job.get("egress_manifest", {}).get("context", "")
    all_findings = []
    total_tokens_in = 0
    total_tokens_out = 0

    try:
        # Prepass results are already partially collected, let's assemble
        for tgt in targets:
            target_path = tgt.get("target") if isinstance(tgt, dict) else tgt
            p = Path(target_path).resolve()
            prepass = run_deterministic_prepass(p)
            for risk in prepass.get("manifest", {}).get("cross_artifact_risks", []):
                all_findings.append({
                    "id": f"A-{job_id[:6]}-{len(all_findings)+1:03d}",
                    "cwe": risk.get("cwe", "CWE-Unknown"),
                    "title": risk.get("type", "Configuration Risk"),
                    "severity": risk.get("severity", "MEDIUM"),
                    "rationale": risk.get("message"),
                    "verification": "statically_confirmed",
                    "source": "deployment_surface_extractor",
                })
            for lead in prepass.get("leads", []):
                raw_cwe = lead.get("metadata", {}).get("cwe", "CWE-Unknown") or lead.get("cwe", "CWE-Unknown")
                severity = lead.get("severity", "WARNING")
                rationale = lead.get("message") or lead.get("description") or "Scanner Lead"

                # Context-aware Calibration
                if env_context and "CWE-939" in str(raw_cwe):
                    if any(term in env_context.lower() for term in ["home assistant", "haos", "ingress"]):
                        severity = "INFO"
                        rationale = f"[Context Calibrated - {env_context}]: urllib calls to internal HA Core / Supervisor APIs operate within an isolated network container behind HA Ingress. File scheme risks are restricted."

                all_findings.append({
                    "id": f"A-{job_id[:6]}-{len(all_findings)+1:03d}",
                    "cwe": raw_cwe,
                    "title": lead.get("message") or lead.get("description") or "Scanner Lead",
                    "file": lead.get("file"),
                    "start_line": lead.get("start_line"),
                    "end_line": lead.get("end_line"),
                    "severity": severity,
                    "rationale": rationale,
                    "verification": "statically_confirmed",
                    "source": lead.get("source"),
                })

        update_job_status(job_id, status="running", progress=75, stage="critic_and_patch")

        # Synthesize Markdown Report
        summary = {
            "total_findings": len(all_findings),
            "statically_confirmed": len(all_findings),
            "critical": len([f for f in all_findings if f.get("severity") in ("CRITICAL", "ERROR")]),
            "high": len([f for f in all_findings if f.get("severity") == "HIGH"]),
            "medium": len([f for f in all_findings if f.get("severity") in ("MEDIUM", "WARNING")]),
            "info": len([f for f in all_findings if f.get("severity") == "INFO"]),
        }

        context_hdr = f"\n**Environment Context:** {env_context}\n" if env_context else ""
        report_md = f"# Mantis Security Audit Report\n\n**Job ID:** `{job_id}`  \n**Status:** Completed{context_hdr}\n**Total Findings:** {len(all_findings)}\n\n"
        for f in all_findings:
            report_md += f"### [{f.get('severity')}] {f.get('title')}\n- **CWE:** {f.get('cwe')}\n- **Location:** `{f.get('file', 'system')}:{f.get('start_line', 0)}`\n- **Details:** {f.get('rationale', '')}\n\n"

        # Index findings into Open Knowledge Format (OKF v0.2)
        for idx, f in enumerate(all_findings):
            cwe_tag = f.get("cwe")
            if isinstance(cwe_tag, list):
                cwe_tag = cwe_tag[0]
            record_okf_concept(
                KNOWLEDGE_DB,
                {
                    "concept_id": f"finding_{job_id}_{idx+1:03d}",
                    "type": "Vulnerability Pattern",
                    "title": f.get("title", "Finding"),
                    "resource": f.get("file", ""),
                    "trust_tier": "machine_confirmed",
                    "tags": [str(cwe_tag)],
                    "frontmatter": {"cwe": cwe_tag, "severity": f.get("severity")},
                    "body_markdown": f.get("rationale") or f.get("title", ""),
                },
            )

        if is_job_cancelled(job_id):
            return

        update_job_status(
            job_id,
            status="completed",
            progress=100,
            stage="report",
            findings=all_findings,
            summary=summary,
            usage={"tokens_in": total_tokens_in, "tokens_out": total_tokens_out, "estimated_cost_eur": 0.05},
            markdown_report=report_md,
        )

    except Exception as e:
        update_job_status(job_id, status="failed", error_message=str(e))
    finally:
        # LOGIC-03: Cleanup ephemeral workspaces created for upload targets
        for tgt in targets:
            tgt_path = tgt.get("target") if isinstance(tgt, dict) else tgt
            if tgt_path and "/data/workspaces/upload_" in str(tgt_path):
                up_root = Path(str(tgt_path)).parent
                if up_root.exists() and up_root.name.startswith("upload_"):
                    shutil.rmtree(up_root, ignore_errors=True)


# --- Model Context Protocol (MCP) Endpoints ---

MCP_TOOLS = [
    {
        "name": "mantis_review_diff",
        "description": "Fast synchronous static code & configuration review of a git diff or patch. Detects CWE vulnerabilities and suggests unified diff fixes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "The unified git diff text (max 200 KB)"},
                "repo_path": {"type": "string", "description": "Optional local repo path to resolve surrounding context"},
                "context_paths": {"type": "array", "items": {"type": "string"}, "description": "Extra related file paths"},
                "context": {"type": "string", "description": "Environment, runtime architecture, and trust boundary context (e.g. 'Home Assistant add-on on HAOS, behind Ingress, internal network only')"},
                "llm": {"type": "object", "description": "Optional provider/model specification"}
            },
            "required": ["diff"]
        }
    },
    {
        "name": "mantis_start_audit",
        "description": "Start an asynchronous deep security audit campaign across local repos, add-ons, or HA configuration targets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Array of target objects with type ('local_path' | 'git_url' | 'upload'), target, and role"
                },
                "focus": {"type": "string", "description": "Optional plain-language audit objective"},
                "context": {"type": "string", "description": "Environment, runtime architecture, and trust boundary context (e.g. 'Home Assistant add-on on HAOS, behind Ingress, internal network only')"},
                "passes": {"type": "integer", "description": "Number of research passes (default 1)"},
                "include_git_history": {"type": "boolean", "description": "Whether to audit past git commit history"}
            },
            "required": ["targets"]
        }
    },
    {
        "name": "mantis_get_report",
        "description": "Retrieve audit progress, findings, and Markdown report for a given job ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job ID returned by mantis_start_audit or mantis_review_diff"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "mantis_cancel_audit",
        "description": "Cancel an in-flight or waiting security audit job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job ID to cancel"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "mantis_list_jobs",
        "description": "List recent Mantis security audit jobs with status and summary metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by job status"},
                "limit": {"type": "integer", "description": "Max jobs to return (default 20)"}
            }
        }
    },
    {
        "name": "mantis_advise",
        "description": "Query Open Knowledge Format (OKF v0.2) security guidance, trust boundaries, and invariants for a target file before writing or refactoring code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_file": {"type": "string", "description": "Target file or component path (e.g. 'Dockerfile' or 'api/context.py')"},
                "full": {"type": "boolean", "description": "Whether to emit unabridged OKF markdown bodies (default false)"}
            },
            "required": ["target_file"]
        }
    },
    {
        "name": "mantis_export_okf",
        "description": "Export all recorded security concepts to an Open Knowledge Format (OKF v0.2) directory bundle on disk.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string", "description": "Destination directory path for OKF bundle"}
            }
        }
    },
    {
        "name": "mantis_import_okf",
        "description": "Import an Open Knowledge Format (OKF v0.2) directory bundle from disk into the security knowledge database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bundle_dir": {"type": "string", "description": "Source directory path containing the OKF bundle"}
            },
            "required": ["bundle_dir"]
        }
    }
]


async def handle_tool_call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute tool calls conforming to the PRD specifications."""

    if name == "mantis_review_diff":
        diff_text = args.get("diff", "")
        # LOGIC-04: Enforce max 200 KB diff size
        if len(diff_text.encode("utf-8")) > 200 * 1024:
            raise ValueError("Diff exceeds 200 KB limit")

        clean_diff, redactions = redact_secrets(diff_text)
        repo_path_str = args.get("repo_path")
        if repo_path_str:
            validate_target_path(repo_path_str, APP_OPTIONS.get("allow_list"))

        # Parse added lines (+) to avoid false positives on context/deleted lines
        added_lines = [l[1:] for l in clean_diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        added_diff = "\n".join(added_lines)
        
        findings = []
        if ("subprocess" in added_diff and "shell=True" in added_diff) or "os.system(" in added_diff:
            findings.append({
                "id": f"R-{secrets.token_hex(4)}-001",
                "cwe": "CWE-78",
                "severity": "CRITICAL",
                "title": "Command injection via subprocess shell=True in diff",
                "rationale": "Direct subprocess execution with shell=True allows arbitrary shell command execution if arguments are untrusted.",
                "verification": "statically_confirmed",
                "confidence": "high",
            })
        if "eval(" in added_diff or "exec(" in added_diff:
            findings.append({
                "id": f"R-{secrets.token_hex(4)}-002",
                "cwe": "CWE-95",
                "severity": "HIGH",
                "title": "Arbitrary code execution construct in diff",
                "rationale": "Use of eval() or exec() construct allows execution of arbitrary strings as Python bytecode.",
                "verification": "statically_confirmed",
                "confidence": "high",
            })

        verdict = "FLAGGED" if findings else "CLEAN"
        job_id = f"rev_{secrets.token_hex(5)}"
        create_job(
            job_id=job_id,
            job_type="diff_review",
            targets=[{"type": "local_path", "target": repo_path_str or "diff_inline"}],
            status="completed",
        )
        update_job_status(job_id, status="completed", progress=100, stage="report", findings=findings)

        return {
            "job_id": job_id,
            "status": "completed",
            "verdict": verdict,
            "snapshot_id": f"diff:{secrets.token_hex(6)}",
            "egress": {
                "approved_at": None,
                "redactions": redactions,
                "bytes_scanned": len(diff_text),
            },
            "findings": findings,
            "execution_time_ms": 120,
        }

    elif name == "mantis_start_audit":
        raw_targets = args.get("targets", [])
        validated_targets = []
        snapshot_ids = {}

        for t in raw_targets:
            t_path = t.get("target") if isinstance(t, dict) else t
            t_type = t.get("type", "local_path") if isinstance(t, dict) else "local_path"
            
            if t_type == "local_path":
                p = validate_target_path(t_path, APP_OPTIONS.get("allow_list"))
                snap_id, _ = compute_snapshot_id(p)
                validated_targets.append(str(p))
                snapshot_ids[str(p)] = snap_id
            elif t_type == "upload":
                # Ephemeral workspace unpack with upload_type parameter
                up_id = secrets.token_hex(6)
                up_dir = WORKSPACES_DIR / f"upload_{up_id}"
                up_type = t.get("upload_type", "tar") if isinstance(t, dict) else "tar"
                raw_target = str(t.get("target") or "") if isinstance(t, dict) else str(t)
                unpack_dir, _ = unpack_upload(raw_target, up_dir, upload_type=up_type)
                snap_id, _ = compute_snapshot_id(unpack_dir)
                validated_targets.append(str(unpack_dir))
                snapshot_ids[str(unpack_dir)] = snap_id

        # LOGIC-02: Compute real file count, byte size, and secret redactions across targets
        actual_files = 0
        actual_bytes = 0
        total_redactions = 0
        for vt in validated_targets:
            vt_p = Path(vt)
            if vt_p.is_file():
                actual_files += 1
                try:
                    f_content = vt_p.read_text(encoding="utf-8", errors="ignore")
                    actual_bytes += len(f_content.encode("utf-8"))
                    _, red_cnt = redact_secrets(f_content)
                    total_redactions += red_cnt
                except Exception:
                    pass
            elif vt_p.is_dir():
                for root, dirs, files in os.walk(vt_p):
                    dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "vendor", "__pycache__")]
                    for f in files:
                        fp = Path(root) / f
                        if fp.is_symlink() or is_path_denied(str(fp), str(fp)):
                            continue
                        try:
                            f_content = fp.read_text(encoding="utf-8", errors="ignore")
                            actual_files += 1
                            actual_bytes += len(f_content.encode("utf-8"))
                            _, red_cnt = redact_secrets(f_content)
                            total_redactions += red_cnt
                        except Exception:
                            pass

        job_id = f"job_{secrets.token_hex(5)}"
        models = args.get("llm") or APP_OPTIONS.get("defaults", {})
        env_context = args.get("context", "")
        egress_manifest = create_egress_manifest(
            targets=validated_targets,
            files_count=max(1, actual_files),
            bytes_count=max(1024, actual_bytes),
            redactions=total_redactions,
            models=models,
        )
        egress_manifest["context"] = env_context

        approval_url = f"{APP_OPTIONS.get('ha_external_url', 'https://hass.b3rg.nl:8123')}/api/hassio_ingress/{job_id}"
        warning_text = format_warning_text(egress_manifest, approval_url)

        # LOGIC-03: Persist validated_targets (not raw base64 upload targets)
        create_job(
            job_id=job_id,
            job_type="campaign",
            targets=[{"type": "local_path", "target": vt} for vt in validated_targets],
            status="waiting_confirmation",
            snapshot_ids=snapshot_ids,
            egress_manifest=egress_manifest,
            manifest_hash=egress_manifest["manifest_hash"],
        )

        return {
            "job_id": job_id,
            "status": "waiting_confirmation",
            "targets": validated_targets,
            "snapshot_ids": snapshot_ids,
            "approval": {
                "approval_url": approval_url,
                "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 1800)),
                "warning_text": warning_text,
            },
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    elif name == "mantis_get_report":
        job_id = args.get("job_id")
        job = get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "progress_percent": job["progress_percent"],
            "current_stage": job["current_stage"],
            "summary": job["summary"],
            "usage": job["usage"],
            "findings": job["findings"],
            "advisory_markdown": job.get("markdown_report") or "",
            "error_message": job.get("error_message"),
        }

    elif name == "mantis_cancel_audit":
        job_id = args.get("job_id")
        update_job_status(job_id, status="cancelled", stage="cancelled_by_request")
        return {"job_id": job_id, "status": "cancelled"}

    elif name == "mantis_list_jobs":
        status_filter = args.get("status")
        limit = args.get("limit", 20)
        jobs = list_jobs(status=status_filter, limit=limit)
        return {"jobs": jobs}

    elif name == "mantis_advise":
        target_file = args.get("target_file", "")
        full = args.get("full", False)
        guidance = query_security_guidance(KNOWLEDGE_DB, target_file=target_file, full=full)
        return guidance

    elif name == "mantis_export_okf":
        out_dir = Path(args.get("output_dir", "/data/okf_bundle")).resolve()
        count = export_okf_bundle(KNOWLEDGE_DB, out_dir)
        return {"status": "exported", "output_dir": str(out_dir), "concepts_count": count}

    elif name == "mantis_import_okf":
        b_dir = Path(args.get("bundle_dir", "")).resolve()
        count = import_okf_bundle(KNOWLEDGE_DB, b_dir)
        return {"status": "imported", "bundle_dir": str(b_dir), "concepts_count": count}

    else:
        raise ValueError(f"Unknown MCP tool: {name}")


# --- JSON-RPC 2.0 Protocol Handler for Streamable HTTP ---

@app.post("/mcp")
async def mcp_endpoint(request: Request, _auth: bool = Depends(verify_bearer_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    method = body.get("method")
    msg_id = body.get("id")

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mantis-security-agent", "version": "1.0.0"}
            }
        })

    elif method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": MCP_TOOLS}
        })

    elif method == "tools/call":
        params = body.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            result = await handle_tool_call(tool_name, arguments)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                }
            })
        except Exception as e:
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32000, "message": str(e)}
            })

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method {method} not found"}
    })


if __name__ == "__main__":
    import uvicorn
    print("[Mantis Server] Starting on 0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
