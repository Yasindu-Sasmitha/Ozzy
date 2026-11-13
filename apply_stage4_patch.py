from __future__ import annotations

import shutil
import sys
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = Path.cwd().resolve()
STAGE4 = ROOT / "stage4_files"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one integration point for {label}; found {count}. No files were changed.")
    return text.replace(old, new, 1)


def main() -> int:
    required = [
        PROJECT / "server.py",
        PROJECT / "windows_automation.py",
        PROJECT / "scripts" / "build-backend.ps1",
        PROJECT / "README.md",
        PROJECT / "PC_CONTROL.md",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("Run this script from the Ozzy repository root. Missing:")
        print("\n".join(missing))
        return 2

    server_path = PROJECT / "server.py"
    build_path = PROJECT / "scripts" / "build-backend.ps1"
    readme_path = PROJECT / "README.md"
    pc_doc_path = PROJECT / "PC_CONTROL.md"
    test_dir = PROJECT / "tests"
    if not test_dir.is_dir():
        raise RuntimeError("The repository tests folder was not found.")

    current_server = server_path.read_text(encoding="utf-8")
    if "import windows_workflows" in current_server:
        complete_markers = (
            "import safe_file_actions",
            "WINDOWS_WORKFLOW_TOOL_NAMES",
            "SAFE_FILE_TOOL_NAMES",
            '"windows_wait_for_window"',
            '"files_create_text_file"',
            'name="windows_wait_for_window"',
            'name="windows_wait_for_control"',
            'name="windows_get_control_state"',
            'name="files_list_directory"',
            'name="files_create_folder"',
            'name="files_create_text_file"',
            "executor = windows_workflows.execute_action",
            "executor = safe_file_actions.execute_action",
            "Safe file tools require a direct user request",
        )
        required_outputs = (
            PROJECT / "windows_workflows.py",
            PROJECT / "safe_file_actions.py",
            test_dir / "test_windows_workflows.py",
            test_dir / "test_safe_file_actions.py",
        )
        incomplete = [marker for marker in complete_markers if marker not in current_server]
        missing_outputs = [str(path) for path in required_outputs if not path.is_file()]
        build_text = build_path.read_text(encoding="utf-8") if build_path.is_file() else ""
        if "--hidden-import windows_workflows" not in build_text or "--hidden-import safe_file_actions" not in build_text:
            incomplete.append("PyInstaller hidden imports")
        readme_text = readme_path.read_text(encoding="utf-8")
        pc_doc_text = pc_doc_path.read_text(encoding="utf-8")
        if "## 8. Context-aware desktop workflows (Stage 4)" not in readme_text:
            incomplete.append("README Stage 4 documentation")
        if "## Stage 4: context-aware desktop workflows" not in pc_doc_text:
            incomplete.append("PC_CONTROL.md Stage 4 documentation")
        if incomplete or missing_outputs:
            details = []
            if incomplete:
                details.append("missing integration markers: " + ", ".join(incomplete))
            if missing_outputs:
                details.append("missing installed files: " + ", ".join(missing_outputs))
            raise RuntimeError(
                "A partial Stage 4 integration was detected (" + "; ".join(details) + "). "
                "Restore the Stage 4 backups before retrying; no files were changed."
            )
        print("Stage 4 is already fully integrated. No files changed.")
        return 0

    server = current_server
    build = build_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    pc_doc = pc_doc_path.read_text(encoding="utf-8")

    # Validate the packaged module before changing project files.
    module_source = STAGE4 / "windows_workflows.py"
    test_source = STAGE4 / "test_windows_workflows.py"
    file_module_source = STAGE4 / "safe_file_actions.py"
    file_test_source = STAGE4 / "test_safe_file_actions.py"
    if not all(path.is_file() for path in (module_source, test_source, file_module_source, file_test_source)):
        raise RuntimeError("The ZIP is incomplete: Stage 4 source or tests are missing.")

    added_targets = (
        PROJECT / "windows_workflows.py",
        PROJECT / "safe_file_actions.py",
        test_dir / "test_windows_workflows.py",
        test_dir / "test_safe_file_actions.py",
    )
    collisions = [str(path) for path in added_targets if path.exists()]
    if collisions:
        raise RuntimeError(
            "The following Stage 4 target files already exist. Review/rename them before installing to avoid overwriting user files: "
            + ", ".join(collisions)
        )

    server = replace_once(
        server,
        "import windows_automation\n",
        "import windows_automation\nimport windows_workflows\nimport safe_file_actions\n",
        "server module imports",
    )

    old_names = '''WINDOWS_AUTOMATION_TOOL_NAMES = {
    "windows_list_windows", "windows_inspect", "windows_activate", "windows_click",
    "windows_set_text", "windows_select", "windows_toggle",
}'''
    new_names = '''WINDOWS_AUTOMATION_TOOL_NAMES = {
    "windows_list_windows", "windows_inspect", "windows_activate", "windows_click",
    "windows_set_text", "windows_select", "windows_toggle",
    "windows_wait_for_window", "windows_wait_for_control", "windows_get_control_state",
    "files_list_directory", "files_create_folder", "files_create_text_file",
}

WINDOWS_WORKFLOW_TOOL_NAMES = {
    "windows_wait_for_window", "windows_wait_for_control", "windows_get_control_state",
}

SAFE_FILE_TOOL_NAMES = {
    "files_list_directory", "files_create_folder", "files_create_text_file",
}'''
    server = replace_once(server, old_names, new_names, "Windows automation tool names")

    tool_anchor = '''        ]
    )
]

PC_CONTROL_TOOLS = ['''
    tool_declarations = '''            types.FunctionDeclaration(
                name="files_list_directory",
                description="List up to 100 visible, non-sensitive item names and basic metadata in Desktop, Documents, Downloads, or an absolute folder inside the user's profile. It does not open or read file contents; hidden/system items and symlinks are skipped. Requires PC Control opt-in and a direct user request.",
                parameters={
                    "type": "OBJECT",
                    "properties": {"directory": {"type": "STRING", "description": "Desktop, Documents, Downloads, or an absolute path inside the current user's profile."}},
                    "required": ["directory"],
                },
            ),
            types.FunctionDeclaration(
                name="files_create_folder",
                description="Create one new folder inside Desktop, Documents, Downloads, or another existing folder inside the user's profile. It never merges with or overwrites an existing item. Does not create nested parent paths. Requires a direct user request and PC Control opt-in.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "directory": {"type": "STRING", "description": "Desktop, Documents, Downloads, or an absolute existing folder path inside the current user's profile."},
                        "folder_name": {"type": "STRING", "description": "Name of the single new folder to create."},
                    },
                    "required": ["directory", "folder_name"],
                },
            ),
            types.FunctionDeclaration(
                name="files_create_text_file",
                description="Create a new .txt or .md file inside Desktop, Documents, Downloads, or another existing folder inside the user's profile. Existing files are never overwritten. Maximum 3,000 characters. Secret-like content and sensitive filenames are blocked. Requires a direct user request and PC Control opt-in.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "directory": {"type": "STRING", "description": "Desktop, Documents, Downloads, or an absolute existing folder path inside the current user's profile."},
                        "file_name": {"type": "STRING", "description": "New filename ending in .txt or .md."},
                        "content": {"type": "STRING", "description": "Plain text supplied by the user, maximum 3,000 characters; do not include secrets or credentials."},
                    },
                    "required": ["directory", "file_name", "content"],
                },
            ),
            types.FunctionDeclaration(
                name="windows_wait_for_window",
                description="Wait for up to 15 seconds for one visible application window whose title matches the requested title. Use after an action that should open a native dialog. Returns its window handle and title. Ambiguous title matches are rejected. Requires PC Control opt-in.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING", "description": "Window title to match, ideally copied from windows_list_windows."},
                        "match": {"type": "STRING", "enum": ["exact", "contains"], "description": "Exact title match by default; contains can be used for a distinctive title fragment."},
                        "timeout_seconds": {"type": "INTEGER", "description": "Wait time from 1 to 15 seconds; defaults to 5."},
                    },
                    "required": ["title"],
                },
            ),
            types.FunctionDeclaration(
                name="windows_wait_for_control",
                description="Wait up to 15 seconds until one uniquely identified Windows UIA control becomes visible and enabled. Identify it by exact name or Automation ID from windows_inspect, optionally with window_handle and control_type. Ambiguous matches fail immediately. Requires PC Control opt-in.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "window_handle": {"type": "STRING", "description": "Optional target window handle from windows_list_windows or windows_wait_for_window."},
                        "name": {"type": "STRING", "description": "Exact control name from windows_inspect."},
                        "automation_id": {"type": "STRING", "description": "Exact Automation ID from windows_inspect; use with name or on its own."},
                        "control_type": {"type": "STRING", "description": "Optional control type to disambiguate the target."},
                        "timeout_seconds": {"type": "INTEGER", "description": "Wait time from 1 to 15 seconds; defaults to 5."},
                    },
                },
            ),
            types.FunctionDeclaration(
                name="windows_get_control_state",
                description="Check the current state of one uniquely identified, non-sensitive Windows control. Reports visible/enabled status, checkbox toggle state, radio/tab/list selection state and keyboard focus when supported. It never reads Edit field values or document text. Requires PC Control opt-in.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "window_handle": {"type": "STRING", "description": "Optional target window handle from windows_list_windows."},
                        "name": {"type": "STRING", "description": "Exact control name from windows_inspect."},
                        "automation_id": {"type": "STRING", "description": "Exact Automation ID from windows_inspect; use with name or on its own."},
                        "control_type": {"type": "STRING", "description": "Optional control type to disambiguate the target."},
                    },
                },
            ),
        ]
    )
]

PC_CONTROL_TOOLS = ['''
    server = replace_once(server, tool_anchor, tool_declarations, "Windows Stage 4 function declarations")

    system_anchor = '''- Some applications expose incomplete/custom accessibility trees. If a UIA control is not available or an action fails, report that honestly and use visual controls only when the target can be identified safely.'''
    system_addition = system_anchor + '''
- For multi-step desktop tasks, do one small action at a time and verify its result. After an action that opens a dialog, use windows_wait_for_window; after a loading or tab change, use windows_wait_for_control rather than guessing with fixed delays. Use windows_get_control_state to verify supported checkbox/radio/tab/list state. These wait calls are bounded to 15 seconds and stop when PC Control is disabled.
- Never infer permission for a later step from an earlier one. Do not chain irreversible actions; ask the user to take over for delete, overwrite, send, publish, purchase, payment, administrative or security actions.
- Safe file tools require a direct user request. They may only list metadata inside the current user's profile, create a new folder, or create a new .txt/.md file (maximum 3,000 characters). Use the Desktop, Documents or Downloads aliases when requested. They never read file contents, overwrite, delete, move, rename, copy, download or execute files. Do not use them for AppData, credentials, hidden/system folders, or paths outside the user profile.'''
    server = replace_once(server, system_anchor, system_addition, "Windows workflow system instructions")

    dispatch_pattern = r"(?m)^(?P<indent>[ \t]*)action_result = await asyncio\.to_thread\(windows_automation\.execute_action, name, args\)$"
    dispatch_match = list(re.finditer(dispatch_pattern, server))
    if len(dispatch_match) != 1:
        raise RuntimeError(
            f"Expected exactly one Windows UIA dispatch line; found {len(dispatch_match)}. No files were changed."
        )
    indent = dispatch_match[0].group("indent")
    dispatch_replacement = (
        f"{indent}if name in WINDOWS_WORKFLOW_TOOL_NAMES:\n"
        f"{indent}    executor = windows_workflows.execute_action\n"
        f"{indent}elif name in SAFE_FILE_TOOL_NAMES:\n"
        f"{indent}    executor = safe_file_actions.execute_action\n"
        f"{indent}else:\n"
        f"{indent}    executor = windows_automation.execute_action\n"
        f"{indent}action_result = await asyncio.to_thread(executor, name, args)"
    )
    server = re.sub(dispatch_pattern, lambda _match: dispatch_replacement, server, count=1)

    build = replace_once(
        build,
        "  --hidden-import windows_automation `\n",
        "  --hidden-import windows_automation `\n  --hidden-import windows_workflows `\n  --hidden-import safe_file_actions `\n",
        "PyInstaller hidden imports",
    )

    readme_addition = '''

## 8. Context-aware desktop workflows (Stage 4)

Stage 4 adds bounded wait and state-verification helpers on top of Stage 3 UI Automation:

- `windows_wait_for_window`: wait up to 15 seconds for a visible native window/dialog by exact title or distinctive title fragment.
- `windows_wait_for_control`: wait up to 15 seconds for an exact control/Automation ID to become visible and enabled.
- `windows_get_control_state`: verify enabled/visible state, checkbox toggle state, radio/tab/list selection state and keyboard focus when supported.
- `files_list_directory`: list visible, non-sensitive metadata in Desktop, Documents, Downloads, or another folder inside the user profile.
- `files_create_folder`: create one new folder inside an existing user-profile folder, without merging or overwriting.
- `files_create_text_file`: create a new `.txt` or `.md` file (maximum 3,000 characters), never overwriting an existing item.

Use the wait tools between ordinary Stage 3 actions to handle Save/Open dialogs and controls that appear after a tab change or loading step. Ozzy should act one step at a time and verify each result. Wait tools poll every 250 ms, check the existing PC Control stop state during polling, and reject ambiguous matches. File tools require a direct user request, never read file contents and are limited to the current user profile. They skip hidden/system items and symlinks. Deletion, overwrite, move, rename, copy, downloads and execution are not available. No additional Python dependencies are required.
'''
    if "## 8. Context-aware desktop workflows (Stage 4)" in readme:
        raise RuntimeError("README.md already contains the Stage 4 section. No files were changed.")
    readme = readme.rstrip() + readme_addition + "\n"

    pc_addition = '''

## Stage 4: context-aware desktop workflows

Stage 4 adds bounded UIA workflow helpers and restricted file tools while preserving the Stage 3 safety model:

| Tool | Purpose |
|---|---|
| `windows_wait_for_window` | Wait for a visible application window/dialog by title (maximum 15 seconds). |
| `windows_wait_for_control` | Wait for one exact UIA control to become visible and enabled (maximum 15 seconds). |
| `windows_get_control_state` | Verify visibility/enabled state and supported checkbox/radio/tab/list/focus state without reading text values. |
| `files_list_directory` | List visible metadata in Desktop, Documents, Downloads or another user-profile folder; it never reads contents. |
| `files_create_folder` | Create one new folder in an existing user-profile directory, without merging or overwriting. |
| `files_create_text_file` | Create a new `.txt` or `.md` file (up to 3,000 characters), without overwriting. |

Use a sequence of small actions: inspect, activate/click, wait for the expected dialog or control, inspect again, then verify state. Waits are cancelled by Stop Now and reject ambiguous matches. File tools require a direct user request, stay inside the current user's profile, skip hidden/system items and symlinks, and never read file contents. Deletion, overwrite, move, rename, copy, downloads and execution are unavailable. No new dependencies are required.
'''
    if "## Stage 4: context-aware desktop workflows" in pc_doc:
        raise RuntimeError("PC_CONTROL.md already contains the Stage 4 section. No files were changed.")
    pc_doc = pc_doc.rstrip() + pc_addition + "\n"

    # Prepare the complete output set first; backups are made before the first write.
    output_files = {
        server_path: server,
        build_path: build,
        readme_path: readme,
        pc_doc_path: pc_doc,
    }
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = PROJECT / "backups" / "stage4-desktop-workflows" / timestamp
    for path in output_files:
        backup = backup_dir / path.relative_to(PROJECT)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)

    for path, content in output_files.items():
        path.write_text(content, encoding="utf-8", newline="\n")

    installed_module = PROJECT / "windows_workflows.py"
    installed_test = test_dir / "test_windows_workflows.py"
    installed_file_module = PROJECT / "safe_file_actions.py"
    installed_file_test = test_dir / "test_safe_file_actions.py"
    shutil.copy2(module_source, installed_module)
    shutil.copy2(test_source, installed_test)
    shutil.copy2(file_module_source, installed_file_module)
    shutil.copy2(file_test_source, installed_file_test)

    print("Stage 4 integration applied.")
    print(f"Backups: {backup_dir}")
    print("Added: windows_workflows.py, safe_file_actions.py and their unit tests")
    print("Updated: server.py, scripts\\build-backend.ps1, README.md, PC_CONTROL.md")
    print("No new dependencies were added.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Stage 4 patch was not applied: {error}", file=sys.stderr)
        raise SystemExit(1)
