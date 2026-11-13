"""Stage 5: bounded, consent-aware orchestration for Ozzy workflows.

This module coordinates existing adapters; it does not implement new OS or
browser primitives. Every action is still executed by its existing safety-gated
module. Every state-changing action in a multi-step workflow requires an explicit
read-only verification; read-only observations may stand alone. The first failed
or unverifiable state change stops the workflow.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable

MAX_STEPS = 8
MAX_WORKFLOW_JSON_CHARS = 16_000
MAX_ACTION_TIMEOUT_SECONDS = 30
MAX_TOTAL_TIMEOUT_SECONDS = 120

# Deliberately exclude raw mouse/keyboard actions from orchestration v1. Their
# target selection is visual and less deterministic than the semantic adapters.
WORKFLOW_ACTIONS = {
    "browser_open", "browser_inspect", "browser_click", "browser_scroll",
    "browser_new_tab", "browser_list_tabs", "browser_switch_tab",
    "browser_navigate", "browser_back", "browser_forward", "browser_refresh",
    "windows_list_windows", "windows_inspect", "windows_activate",
    "windows_click", "windows_toggle",
    "windows_wait_for_window", "windows_wait_for_control",
    "windows_get_control_state", "files_list_directory", "files_create_folder",
    "files_create_text_file",
}

# Verification calls must be read-only. In particular, a verifier can never
# click, fill, create, navigate, type, or otherwise mutate the target app.
VERIFY_ACTIONS = {
    "browser_inspect", "browser_list_tabs", "get_active_window", "windows_list_windows",
    "windows_inspect", "windows_wait_for_window", "windows_wait_for_control",
    "windows_get_control_state", "files_list_directory",
}

_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,5}$")


class WorkflowValidationError(ValueError):
    """The proposed workflow is malformed or uses an unsupported action."""


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise WorkflowValidationError("Workflow arguments must contain JSON-compatible values only.") from exc


def validate_steps(steps: Any) -> list[dict[str, Any]]:
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise WorkflowValidationError(f"A workflow must contain between 1 and {MAX_STEPS} steps.")
    if _json_size(steps) > MAX_WORKFLOW_JSON_CHARS:
        raise WorkflowValidationError(f"The workflow is too large. Keep its JSON payload below {MAX_WORKFLOW_JSON_CHARS} characters.")

    cleaned: list[dict[str, Any]] = []
    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            raise WorkflowValidationError(f"Step {index} must be an object.")
        unknown = set(raw) - {"label", "action", "args", "verify"}
        if unknown:
            raise WorkflowValidationError(f"Step {index} contains unsupported fields: {sorted(unknown)}.")
        action = str(raw.get("action") or "").strip()
        if action not in WORKFLOW_ACTIONS:
            raise WorkflowValidationError(f"Step {index} uses unsupported workflow action '{action}'.")
        args = raw.get("args", {})
        if not isinstance(args, dict):
            raise WorkflowValidationError(f"Step {index} args must be an object.")
        label = str(raw.get("label") or f"Step {index}").strip()
        if not label or len(label) > 100:
            raise WorkflowValidationError(f"Step {index} label must contain 1 to 100 characters.")

        verify = raw.get("verify")
        if verify is not None:
            verify = _validate_verification(verify, index)
        elif len(steps) > 1 and action not in VERIFY_ACTIONS:
            raise WorkflowValidationError(
                f"Step {index} needs a read-only verification because this is a multi-step workflow. "
                "Add verify.action and either verify.contains or verify.field plus verify.equals."
            )
        cleaned.append({"label": label, "action": action, "args": args, "verify": verify})
    return cleaned


def _validate_verification(raw: Any, step_index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowValidationError(f"Step {step_index} verify must be an object.")
    unknown = set(raw) - {"action", "args", "field", "equals", "contains"}
    if unknown:
        raise WorkflowValidationError(f"Step {step_index} verification contains unsupported fields: {sorted(unknown)}.")
    action = str(raw.get("action") or "").strip()
    if action not in VERIFY_ACTIONS:
        raise WorkflowValidationError(
            f"Step {step_index} verifier must be a read-only check such as browser_inspect, windows_get_control_state, or files_list_directory."
        )
    args = raw.get("args", {})
    if not isinstance(args, dict):
        raise WorkflowValidationError(f"Step {step_index} verification args must be an object.")
    has_equals = "equals" in raw
    has_contains = "contains" in raw
    if has_equals == has_contains:
        raise WorkflowValidationError(f"Step {step_index} verification must specify exactly one of equals or contains.")
    field = raw.get("field", "")
    if field and (not isinstance(field, str) or not _FIELD_PATH.fullmatch(field)):
        raise WorkflowValidationError(f"Step {step_index} verification field must be a simple dotted JSON field path.")
    if has_equals and not field:
        raise WorkflowValidationError(f"Step {step_index} verification equals requires a specific field path.")
    expected_key = "equals" if has_equals else "contains"
    expected = raw[expected_key]
    if not isinstance(expected, str) or not expected or len(expected) > 240:
        raise WorkflowValidationError(f"Step {step_index} verification {expected_key} must be 1 to 240 characters.")
    return {"action": action, "args": args, "field": field, expected_key: expected}


def _get_field(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def _all_text(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _all_text(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _all_text(child)


def _matches(result: dict[str, Any], verification: dict[str, Any]) -> tuple[bool, str]:
    field = verification.get("field") or ""
    try:
        observed = _get_field(result, field) if field else result
    except KeyError:
        return False, f"Verification field '{field}' was not present in the result."

    if "equals" in verification:
        expected = verification["equals"]
        actual = str(observed).strip()
        if actual.casefold() == expected.casefold():
            return True, f"Verified {field or 'result'} equals '{expected}'."
        return False, f"Verification mismatch: {field or 'result'} was '{actual[:160]}', expected '{expected}'."

    expected = verification["contains"].casefold()
    if field:
        haystack = " ".join(_all_text(observed)).casefold()
    else:
        haystack = " ".join(_all_text(observed)).casefold()
    if expected in haystack:
        return True, f"Verified the expected text '{verification['contains']}'."
    return False, f"Verification text '{verification['contains']}' was not found in the observed result."


async def execute_workflow(
    steps: Any,
    execute_action: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    is_enabled: Callable[[], bool],
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    workflow_id: str = "",
) -> dict[str, Any]:
    """Run a validated workflow sequentially and stop at the first problem.

    A single action may omit verification; its result will explicitly be marked
    unverified. In a multi-step workflow, every state-changing action must provide
    a read-only verifier and a concrete expected value/text assertion. Read-only
    observation steps may stand alone.
    """
    plan = validate_steps(steps)
    started = time.monotonic()
    deadline = started + MAX_TOTAL_TIMEOUT_SECONDS
    records: list[dict[str, Any]] = []

    async def progress(step_number: int, step: dict[str, Any], status: str, message: str):
        if on_progress is not None:
            try:
                await on_progress({
                    "workflow_id": workflow_id,
                    "step": step_number,
                    "total_steps": len(plan),
                    "label": step["label"],
                    "status": status,
                    "message": message[:240],
                })
            except Exception:
                # Progress UI failures must never change the desktop operation.
                pass

    overall_status = "completed"
    final_message = "Workflow completed."

    for number, step in enumerate(plan, start=1):
        if not is_enabled():
            overall_status = "cancelled"
            final_message = "PC Control was disabled. The workflow stopped before the next step."
            break
        if time.monotonic() >= deadline:
            overall_status = "timed_out"
            final_message = "The workflow reached its 120-second time limit and stopped safely."
            break

        await progress(number, step, "running", f"Running {step['action']}.")
        started_step = time.monotonic()
        try:
            action_result = await asyncio.wait_for(
                execute_action(step["action"], step["args"]),
                timeout=min(MAX_ACTION_TIMEOUT_SECONDS, max(0.1, deadline - time.monotonic())),
            )
            if not isinstance(action_result, dict):
                raise RuntimeError("The action adapter returned an invalid result.")
        except asyncio.TimeoutError:
            overall_status = "timed_out"
            final_message = f"Step {number} timed out and the remaining workflow was stopped."
            records.append({"step": number, "label": step["label"], "action": step["action"], "status": "timed_out"})
            await progress(number, step, "failed", final_message)
            break
        except Exception as exc:
            overall_status = "failed"
            final_message = f"Step {number} failed: {str(exc)[:220]}"
            records.append({"step": number, "label": step["label"], "action": step["action"], "status": "failed", "error": str(exc)[:240]})
            await progress(number, step, "failed", final_message)
            break

        clean_action_result = {key: value for key, value in action_result.items() if key != "image_bytes"}
        if action_result.get("ok") is False:
            overall_status = "failed"
            final_message = f"Step {number} was rejected or failed: {str(action_result.get('message') or 'Action returned ok=false')[:180]}"
            records.append({"step": number, "label": step["label"], "action": step["action"], "status": "failed", "result": clean_action_result})
            await progress(number, step, "failed", final_message)
            break

        record = {
            "step": number,
            "label": step["label"],
            "action": step["action"],
            "status": "action_completed",
            "duration_seconds": round(time.monotonic() - started_step, 2),
            "result": clean_action_result,
        }

        verification = step.get("verify")
        if verification is None and step["action"] in VERIFY_ACTIONS:
            record["verification"] = "read_only_observation"
            record["status"] = "verified"
            records.append(record)
            await progress(number, step, "verified", "Read-only observation completed.")
            if not is_enabled():
                overall_status = "cancelled"
                final_message = "PC Control was disabled after the observation. The workflow stopped before the next step."
                break
            continue

        if verification is None:
            record["verification"] = "not_requested"
            record["status"] = "completed_unverified"
            records.append(record)
            await progress(number, step, "completed_unverified", "The action returned successfully, but no outcome check was requested.")
            if number < len(plan):
                overall_status = "paused_unverified"
                final_message = "The workflow paused because the last action was not independently verified. No later steps were run."
            else:
                overall_status = "completed_unverified"
                final_message = "The single action returned successfully, but its resulting state was not independently verified."
            break

        if not is_enabled():
            overall_status = "cancelled"
            final_message = "PC Control was disabled after the action. The workflow stopped before verification or further steps."
            record["status"] = "cancelled_before_verification"
            records.append(record)
            await progress(number, step, "cancelled", final_message)
            break

        await progress(number, step, "verifying", f"Checking with {verification['action']}.")
        verification_timed_out = False
        try:
            verify_result = await asyncio.wait_for(
                execute_action(verification["action"], verification["args"]),
                timeout=min(MAX_ACTION_TIMEOUT_SECONDS, max(0.1, deadline - time.monotonic())),
            )
            if not isinstance(verify_result, dict) or verify_result.get("ok") is False:
                raise RuntimeError(str((verify_result or {}).get("message", "Verification action failed."))[:180])
            matched, verify_message = _matches(verify_result, verification)
        except asyncio.TimeoutError:
            verification_timed_out = True
            matched, verify_message = False, "Verification action timed out."
            verify_result = {}
        except Exception as exc:
            matched, verify_message = False, f"Verification failed: {str(exc)[:180]}"
            verify_result = {}

        record["verification"] = {
            "action": verification["action"],
            "matched": bool(matched),
            "message": verify_message,
            "result": {key: value for key, value in (verify_result or {}).items() if key != "image_bytes"},
        }
        record["status"] = "verified" if matched else "verification_failed"
        records.append(record)
        if not matched:
            overall_status = "timed_out" if verification_timed_out else "verification_failed"
            final_message = f"Step {number} could not be verified. The workflow stopped; no later steps were run. {verify_message}"
            await progress(number, step, "timed_out" if verification_timed_out else "verification_failed", final_message)
            break

        await progress(number, step, "verified", verify_message)
        if not is_enabled():
            overall_status = "cancelled"
            final_message = "PC Control was disabled after verification. The workflow stopped before the next step."
            break
    else:
        final_message = f"All {len(plan)} workflow steps completed and passed their requested checks."

    return {
        "ok": overall_status == "completed",
        "status": overall_status,
        "workflow_id": workflow_id,
        "completed_steps": sum(1 for row in records if row.get("status") == "verified"),
        "processed_steps": len(records),
        "total_steps": len(plan),
        "duration_seconds": round(time.monotonic() - started, 2),
        "steps": records,
        "message": final_message,
    }
