"""Stage 8: open existing Office documents and switch between open ones.

``office_open_document`` opens one existing macro-free ``.docx``/``.xlsx``/``.pptx`` from the
user's Desktop, Documents, Downloads or OneDrive folders. It always requires a separate native
approval dialog (the caller binds the approved file's size and modification time, so a file swapped
after approval is rejected). While opening, Office automation security is forced to *disable macros*,
alerts are suppressed, links are not updated, and files downloaded from the internet (Mark-of-the-Web)
are opened read-only. Ozzy never saves over the opened file; edits stay in memory until the user
saves, or until ``office_save_new`` writes a separate new file.

Open-document listing and switching only deal with document *names*; no file paths are returned.
"""
from __future__ import annotations

import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import office_automation as base

OfficeAutomationError = base.OfficeAutomationError

ACTIONS = {"office_open_document", "office_list_open_documents", "office_activate_document"}
OPEN_EXTENSIONS = {".docx": "word", ".xlsx": "excel", ".pptx": "powerpoint"}
APP_LABELS = {"word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint"}
KNOWN_FOLDERS = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads"}
MAX_OPEN_BYTES = 50 * 1024 * 1024
MAX_LISTED_DOCUMENTS = 25
ZIP_MAGIC = b"PK\x03\x04"
FORBIDDEN_PARTS = {"appdata", "program files", "program files (x86)", "programdata", "windows", ".ssh", ".aws", ".gnupg"}
_MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3


def _is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = path.stat(follow_symlinks=False)
        if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction()) if callable(is_junction) else False
    except OSError:
        return True  # fail closed


def is_internet_file(path: Path) -> bool:
    """True when Windows marks the file as downloaded (Mark-of-the-Web, zone 3 or 4)."""
    try:
        with open(f"{path}:Zone.Identifier", "r", encoding="utf-8", errors="ignore") as stream:
            for line in stream.read(2000).splitlines():
                if line.strip().lower().startswith("zoneid="):
                    return line.split("=", 1)[1].strip() in {"3", "4"}
    except OSError:
        return False
    return False


def _candidate_path(raw: str, home: Path) -> Path:
    parts = [part for part in re.split(r"[\\/]+", raw) if part]
    first = parts[0].casefold() if parts else ""
    looks_absolute = bool(re.match(r"^[A-Za-z]:[\\/]", raw)) or raw.startswith(("\\\\", "/")) or Path(raw).expanduser().is_absolute()
    if not looks_absolute and len(parts) >= 2:
        if first in KNOWN_FOLDERS:
            return home.joinpath(KNOWN_FOLDERS[first], *parts[1:])
        if first.startswith("onedrive"):
            return home.joinpath(*parts)
    candidate = Path(os.path.expandvars(raw)).expanduser()
    if not candidate.is_absolute():
        raise ValueError(
            "file_path must be absolute, or start with Desktop, Documents, Downloads or OneDrive, "
            "for example Documents\\Report.docx."
        )
    return candidate


def resolve_existing_file(raw_path: Any) -> tuple[str, Path]:
    """Validate a user-requested document path. Returns (application key, resolved path)."""
    if not isinstance(raw_path, str) or not raw_path.strip() or len(raw_path) > 500:
        raise ValueError("file_path must be the path of an existing .docx, .xlsx or .pptx file.")
    raw = raw_path.strip()
    home = Path.home().resolve(strict=True)
    candidate = _candidate_path(raw, home)
    if ".." in candidate.parts:
        raise ValueError("Parent-directory traversal is not allowed.")
    extension = candidate.suffix.lower()
    app_key = OPEN_EXTENSIONS.get(extension)
    if app_key is None:
        raise ValueError("Ozzy can open only macro-free .docx, .xlsx and .pptx files. Legacy and macro-enabled formats are not supported.")
    name = candidate.name
    if name.startswith((".", "~$")):
        raise PermissionError("Hidden files and Office temporary lock files cannot be opened.")
    if base.SENSITIVE_FILENAME.search(name):
        raise PermissionError("That filename looks sensitive and cannot be opened by Ozzy.")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"That file does not exist: {candidate.name}") from None
    except OSError as exc:
        raise ValueError(f"Could not resolve that file path: {exc}") from exc
    # Refuse paths that reach the file through a symbolic link or junction.
    absolute = Path(os.path.abspath(str(candidate)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if _is_link_or_junction(current):
            raise PermissionError("Files reached through symbolic links or junctions are not supported.")
    try:
        relative = resolved.relative_to(home)
    except ValueError as exc:
        raise PermissionError("Office files can only be opened from folders inside your Windows user profile.") from exc
    first_folder = relative.parts[0].casefold() if relative.parts else ""
    if len(relative.parts) < 2 or not (first_folder in KNOWN_FOLDERS or first_folder.startswith("onedrive")):
        raise PermissionError("Office files can only be opened from Desktop, Documents, Downloads or OneDrive folders in your user profile.")
    if any(part.startswith(".") for part in relative.parts) or any(part.casefold() in FORBIDDEN_PARTS for part in relative.parts):
        raise PermissionError("Hidden and system folders are not supported.")
    if not resolved.is_file():
        raise ValueError("That path is not a regular file.")
    size = resolved.stat().st_size
    if size <= 0:
        raise ValueError("That file is empty.")
    if size > MAX_OPEN_BYTES:
        raise ValueError(f"That file is larger than the {MAX_OPEN_BYTES // (1024 * 1024)} MB limit for Ozzy.")
    try:
        with open(resolved, "rb") as stream:
            magic = stream.read(4)
    except OSError as exc:
        raise OfficeAutomationError(f"Could not read that file: {exc}") from exc
    if magic != ZIP_MAGIC:
        raise ValueError(
            "That file is not a standard macro-free Office Open XML file (it may be password-protected, an older format, or damaged), so Ozzy will not open it."
        )
    return app_key, resolved


def prepare_open_request(args: dict[str, Any]) -> dict[str, Any]:
    """Validate an open request and describe it for the approval dialog. Has no side effects."""
    if not isinstance(args, dict):
        raise ValueError("Open request arguments must be an object.")
    app_key, path = resolve_existing_file(args.get("file_path"))
    requested = args.get("application")
    if requested not in (None, ""):
        if str(requested).strip().lower() != app_key:
            raise ValueError(f"A {path.suffix.lower()} file opens in {app_key}, not {requested}.")
    read_only_flag = args.get("read_only")
    if read_only_flag is not None and not isinstance(read_only_flag, bool):
        raise ValueError("read_only must be true or false.")
    internet = is_internet_file(path)
    info = path.stat()
    return {
        "application": app_key,
        "application_label": APP_LABELS[app_key],
        "file_path": str(path),
        "file_name": path.name,
        "size_bytes": int(info.st_size),
        "modified_ns": str(int(info.st_mtime_ns)),
        "read_only": bool(read_only_flag) or internet,
        "internet_download": internet,
    }


def is_app_running(app_key: str) -> bool:
    """Report whether the Office application is already running (never launches it)."""
    base._require_windows()
    import pythoncom
    pythoncom.CoInitialize()
    try:
        try:
            base._connect(base.APP_PROGIDS[app_key])
            return True
        except OfficeAutomationError:
            return False
    finally:
        pythoncom.CoUninitialize()


@contextmanager
def _automation_security_disabled(app):
    """Force-disable macros for the duration of an automated open, then restore the user's setting."""
    try:
        original = int(app.AutomationSecurity)
    except Exception:
        original = None
    try:
        app.AutomationSecurity = _MSO_AUTOMATION_SECURITY_FORCE_DISABLE
    except Exception as exc:
        raise OfficeAutomationError("Could not disable macros before opening the file, so it was not opened.") from exc
    try:
        yield
    finally:
        if original is not None:
            try:
                app.AutomationSecurity = original
            except Exception:
                pass


@contextmanager
def _alerts_suppressed(app_key: str, app):
    """Suppress Office prompts while opening so an unexpected dialog cannot stall COM."""
    quiet = {"word": 0, "excel": False, "powerpoint": 1}[app_key]
    try:
        original = app.DisplayAlerts
    except Exception:
        original = None
    try:
        app.DisplayAlerts = quiet
    except Exception:
        original = None
    try:
        yield
    finally:
        if original is not None:
            try:
                app.DisplayAlerts = original
            except Exception:
                pass


def _collection(app_key: str, app):
    return {"word": lambda: app.Documents, "excel": lambda: app.Workbooks, "powerpoint": lambda: app.Presentations}[app_key]()


def _open_items(app_key: str, app) -> list[Any]:
    collection = _collection(app_key, app)
    return [collection.Item(index) for index in range(1, min(int(collection.Count), 100) + 1)]


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _activate(app_key: str, item) -> None:
    if app_key == "powerpoint":
        item.Windows.Item(1).Activate()
    else:
        item.Activate()


def _open_with_app(app_key: str, app, path: Path, read_only: bool) -> tuple[Any, bool]:
    for item in _open_items(app_key, app):
        try:
            if _same_path(str(item.FullName), str(path)):
                _activate(app_key, item)
                return item, True
        except Exception:
            continue
    with _automation_security_disabled(app), _alerts_suppressed(app_key, app):
        if app_key == "word":
            # Documents.Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles)
            item = app.Documents.Open(str(path), False, read_only, False)
        elif app_key == "excel":
            # Workbooks.Open(Filename, UpdateLinks=0 (never), ReadOnly)
            item = app.Workbooks.Open(str(path), 0, read_only)
        else:
            # Presentations.Open(FileName, ReadOnly, Untitled=msoFalse, WithWindow=msoTrue)
            item = app.Presentations.Open(str(path), -1 if read_only else 0, 0, -1)
    return item, False


def _open_document(args: dict[str, Any]) -> dict[str, Any]:
    preview = prepare_open_request(args)
    expected_size = args.get("_expected_size")
    expected_modified = args.get("_expected_modified_ns")
    if expected_size is not None and int(expected_size) != preview["size_bytes"]:
        raise PermissionError("The file changed after you approved it. Nothing was opened; ask again to review it.")
    if expected_modified is not None and str(expected_modified) != preview["modified_ns"]:
        raise PermissionError("The file changed after you approved it. Nothing was opened; ask again to review it.")
    app_key = preview["application"]
    path = Path(preview["file_path"])

    def run(app):
        try:
            app.Visible = True
        except Exception:
            pass
        try:
            item, already_open = _open_with_app(app_key, app, path, bool(preview["read_only"]))
        except OfficeAutomationError:
            raise
        except Exception as exc:
            raise OfficeAutomationError(f"{preview['application_label']} could not open that file: {str(exc)[:160]}") from exc
        actual_read_only = bool(base._com_flag(item, "ReadOnly"))
        note = " It opened read-only because it was downloaded from the internet; unblock it in the file's Properties to edit." if preview["internet_download"] else ""
        if already_open:
            message = f"{path.name} was already open, so Ozzy switched to it."
        else:
            message = f"Opened {path.name} in {preview['application_label']} with macros disabled.{note}"
        return {
            "ok": True, "application": app_key, "document_name": str(item.Name)[:180],
            "already_open": already_open, "read_only": actual_read_only,
            "message": message + " Edits stay in memory and are not saved to this file by Ozzy.",
        }

    return base._with_app(app_key, run, allow_launch=True)


def _list_open_documents(args: dict[str, Any]) -> dict[str, Any]:
    requested = args.get("application")
    keys = list(base.APP_PROGIDS)
    if requested not in (None, ""):
        key = str(requested).strip().lower()
        if key not in base.APP_PROGIDS:
            raise ValueError("application must be 'word', 'excel', or 'powerpoint'.")
        keys = [key]
    base._require_windows()
    import pythoncom
    pythoncom.CoInitialize()
    try:
        documents: list[dict[str, Any]] = []
        for app_key in keys:
            try:
                app = base._connect(base.APP_PROGIDS[app_key])
            except OfficeAutomationError:
                continue
            try:
                active_name = ""
                try:
                    # Look up only this application's own property; the others do not exist on it.
                    active_property = {"word": "ActiveDocument", "excel": "ActiveWorkbook", "powerpoint": "ActivePresentation"}[app_key]
                    active_name = str(getattr(app, active_property).FullName)
                except Exception:
                    pass
                for position, item in enumerate(_open_items(app_key, app)[:MAX_LISTED_DOCUMENTS], start=1):
                    try:
                        is_active = bool(active_name) and _same_path(str(item.FullName), active_name)
                    except Exception:
                        is_active = False
                    documents.append({
                        "application": app_key, "index": position, "name": str(item.Name)[:180],
                        "active": is_active, "read_only": bool(base._com_flag(item, "ReadOnly")),
                    })
            finally:
                app = None
        return {"ok": True, "count": len(documents), "documents": documents,
                "message": "Open Office documents listed by name. Ozzy did not launch or open anything."}
    finally:
        pythoncom.CoUninitialize()


def _activate_document(args: dict[str, Any]) -> dict[str, Any]:
    app_key = str(args.get("application") or "").strip().lower()
    if app_key not in base.APP_PROGIDS:
        raise ValueError("application must be 'word', 'excel', or 'powerpoint'.")
    name = args.get("name")
    index = args.get("index")
    if (name in (None, "")) == (index is None):
        raise ValueError("Provide exactly one of name or index (use office_list_open_documents to see both).")

    def run(app):
        items = _open_items(app_key, app)[:MAX_LISTED_DOCUMENTS]
        if index is not None:
            if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= len(items):
                raise ValueError(f"index must be a whole number from 1 to {len(items)}.")
            chosen = items[index - 1]
        else:
            wanted = str(name).strip().casefold()
            matches = [item for item in items if str(item.Name).casefold() == wanted]
            if not matches:
                raise OfficeAutomationError(f"No open {app_key} document is named '{str(name)[:80]}'.")
            if len(matches) > 1:
                raise OfficeAutomationError("More than one open document has that name. Use the index from office_list_open_documents.")
            chosen = matches[0]
        try:
            _activate(app_key, chosen)
        except Exception as exc:
            raise OfficeAutomationError(f"Could not switch to that document: {str(exc)[:160]}") from exc
        return {"ok": True, "application": app_key, "document_name": str(chosen.Name)[:180],
                "message": f"Switched to {str(chosen.Name)[:80]}. Later Office actions will target it."}

    return base._with_app(app_key, run)


def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "office_open_document":
        return _open_document(args)
    if name == "office_list_open_documents":
        return _list_open_documents(args)
    if name == "office_activate_document":
        return _activate_document(args)
    raise ValueError(f"Unsupported Office document action: {name}")
