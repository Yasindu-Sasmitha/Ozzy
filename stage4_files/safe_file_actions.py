"""Restricted, consent-gated file listing and creation for Ozzy Stage 4.

Only directories within the current user's profile are in scope. This module
can list metadata, create a new folder, and create a new plain-text document.
It never reads file contents, overwrites existing items, deletes, moves, or
renames files, or executes anything.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

import windows_automation as ui

MAX_ITEMS = 100
MAX_SCAN_ENTRIES = 1000
MAX_TEXT_LENGTH = 3000
MAX_DIRECTORY_PATH_LENGTH = 500
ALLOWED_TEXT_EXTENSIONS = {".txt", ".md"}
KNOWN_FOLDERS = {
    "desktop": "Desktop",
    "documents": "Documents",
    "downloads": "Downloads",
}
FORBIDDEN_DIRECTORY_PARTS = {
    "appdata", ".ssh", ".aws", ".azure", ".gnupg", ".config",
    "windows", "program files", "program files (x86)", "programdata",
    "credentials", "secrets", "passwords", "private keys", "ssh keys", "vault",
}
INVALID_WINDOWS_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SECRET_CONTENT = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{15,}\b|"
    r"\b(?:client[_ -]?secret|bearer)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _validate_leaf_name(value: Any, *, allowed_extensions: set[str] | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError("The new name must be text.")
    name = value.strip()
    if not name or len(name) > 120 or name in {".", ".."}:
        raise ValueError("Provide a name from 1 to 120 characters.")
    if name.startswith("."):
        raise ValueError("Hidden dot-prefixed names are not supported.")
    if name.casefold() in FORBIDDEN_DIRECTORY_PARTS:
        raise PermissionError("That private or system folder name is outside Stage 4's allowed scope.")
    if name.endswith((".", " ")) or INVALID_WINDOWS_NAME.search(name):
        raise ValueError("The name contains characters that Windows does not allow.")
    base = name.split(".", 1)[0].upper()
    if base in RESERVED_WINDOWS_NAMES:
        raise ValueError("That name is reserved by Windows.")
    if ui.is_sensitive_control({"name": name}):
        raise PermissionError("Names that appear to identify credentials or sensitive data are not allowed.")
    if ui.is_high_impact_control({"name": name}):
        raise PermissionError("That name appears to describe a high-impact or destructive action and is blocked.")
    if allowed_extensions is not None and Path(name).suffix.lower() not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ValueError(f"Only these new file types are supported: {allowed}.")
    return name


def _is_link_or_junction(path: Path) -> bool:
    """Detect symlinks and Windows reparse-point junctions across Python versions."""
    try:
        if path.is_symlink():
            return True
        info = path.stat(follow_symlinks=False)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if getattr(info, "st_file_attributes", 0) & reparse_flag:
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction()) if callable(is_junction) else False
    except OSError:
        # Fail closed when an element in the path cannot be inspected.
        return True


def _resolve_directory(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Provide Desktop, Documents, Downloads, or an absolute folder path within your user profile.")
    raw = value.strip()
    if len(raw) > MAX_DIRECTORY_PATH_LENGTH:
        raise ValueError(f"Folder paths are limited to {MAX_DIRECTORY_PATH_LENGTH} characters.")
    home = Path.home().resolve(strict=True)
    known = KNOWN_FOLDERS.get(raw.casefold())
    if known:
        candidate = home / known
    else:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("Folder paths must be absolute, or use Desktop, Documents, or Downloads.")
    if ".." in candidate.parts:
        raise ValueError("Parent-directory traversal is not allowed.")

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"That folder does not exist: {candidate}") from None
    except OSError as exc:
        raise ValueError(f"Could not resolve that folder: {exc}") from exc

    try:
        within_home = os.path.normcase(os.path.commonpath([str(home), str(resolved)])) == os.path.normcase(str(home))
    except ValueError:
        within_home = False
    if not within_home:
        raise PermissionError("Stage 4 file actions are limited to folders inside your Windows user profile.")

    # Reject symlinks/junctions in the user-supplied path to prevent escaping
    # the profile through a redirected child directory.
    lexical = candidate
    try:
        absolute = Path(os.path.abspath(str(lexical)))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            if _is_link_or_junction(current):
                raise PermissionError("Folders reached through symbolic links or junctions are not supported.")
    except PermissionError:
        raise
    except OSError as exc:
        raise ValueError(f"Could not validate that folder path: {exc}") from exc

    if not resolved.is_dir():
        raise NotADirectoryError("The selected path is not a folder.")
    relative_parts = resolved.relative_to(home).parts
    if any(part.startswith(".") for part in relative_parts):
        raise PermissionError("Hidden folders are outside Stage 4's allowed scope.")
    if any(part.casefold() in FORBIDDEN_DIRECTORY_PARTS for part in resolved.parts):
        raise PermissionError("This system or private configuration folder is outside Stage 4's allowed scope.")
    if any(ui.is_sensitive_control({"name": part}) for part in relative_parts):
        raise PermissionError("Folders with credential, secret, or sensitive-data names are outside Stage 4's allowed scope.")
    return resolved


def _is_hidden_or_system(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        hidden_flag = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2)
        system_flag = getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0x4)
        return bool(attributes & (hidden_flag | system_flag))
    except OSError:
        return True


def _list_directory(args: dict[str, Any]) -> dict[str, Any]:
    directory = _resolve_directory(args.get("directory"))
    rows = []
    truncated = False
    try:
        entries = directory.iterdir()
        for scan_index, item in enumerate(entries):
            ui._check_enabled()
            if scan_index >= MAX_SCAN_ENTRIES:
                truncated = True
                break
            try:
                if _is_link_or_junction(item) or _is_hidden_or_system(item):
                    continue
                if item.name.casefold() in FORBIDDEN_DIRECTORY_PARTS:
                    continue
                if ui.is_sensitive_control({"name": item.name}):
                    continue
                if len(rows) >= MAX_ITEMS:
                    truncated = True
                    break
                info = item.stat(follow_symlinks=False)
                is_dir = item.is_dir()
                rows.append({
                    "name": item.name[:180],
                    "kind": "folder" if is_dir else "file",
                    "extension": "" if is_dir else item.suffix.lower()[:16],
                    "size_bytes": None if is_dir else int(info.st_size),
                    "modified_unix": int(info.st_mtime),
                })
            except OSError:
                continue
    except OSError as exc:
        raise RuntimeError(f"Could not list that folder: {exc}") from exc
    rows.sort(key=lambda item: (item["kind"] != "folder", item["name"].casefold()))
    return {
        "ok": True,
        "directory": str(directory),
        "count": len(rows),
        "truncated": truncated,
        "items": rows,
        "message": "Folder metadata listed. File contents were not opened or read.",
    }


def _create_folder(args: dict[str, Any]) -> dict[str, Any]:
    parent = _resolve_directory(args.get("directory"))
    name = _validate_leaf_name(args.get("folder_name"))
    target = parent / name
    ui._check_enabled()
    try:
        target.mkdir(exist_ok=False)
    except FileExistsError:
        raise FileExistsError("An item with that name already exists. Ozzy will not overwrite or merge it.") from None
    except OSError as exc:
        raise RuntimeError(f"Could not create the new folder: {exc}") from exc
    ui._check_enabled()
    return {"ok": True, "path": str(target), "message": f"Created the new folder '{name}'. No existing items were changed."}


def _create_text_file(args: dict[str, Any]) -> dict[str, Any]:
    parent = _resolve_directory(args.get("directory"))
    name = _validate_leaf_name(args.get("file_name"), allowed_extensions=ALLOWED_TEXT_EXTENSIONS)
    content = ui.validate_text(args.get("content", ""))
    if len(content) > MAX_TEXT_LENGTH:
        raise ValueError(f"New text files are limited to {MAX_TEXT_LENGTH} characters.")
    if SECRET_CONTENT.search(content):
        raise PermissionError("Text that appears to contain a private key, access credential, or secret token cannot be written by Ozzy.")
    target = parent / name
    ui._check_enabled()
    try:
        with target.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except FileExistsError:
        raise FileExistsError("A file with that name already exists. Ozzy will not overwrite it.") from None
    except OSError as exc:
        raise RuntimeError(f"Could not create the new text file: {exc}") from exc
    ui._check_enabled()
    return {
        "ok": True,
        "path": str(target),
        "characters_written": len(content),
        "message": f"Created the new {target.suffix.lower()} file '{name}'. Existing files were not changed.",
    }


def execute_action(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch the deliberately small Stage 4 file allow-list."""
    ui._check_enabled()
    payload = args if isinstance(args, dict) else {}
    actions = {
        "files_list_directory": _list_directory,
        "files_create_folder": _create_folder,
        "files_create_text_file": _create_text_file,
    }
    action = actions.get(name)
    if action is None:
        raise ValueError(f"Unsupported safe file action: {name}")
    result = action(payload)
    ui._check_enabled()
    return result
