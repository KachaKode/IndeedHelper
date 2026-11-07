"""The per-user files and folders a run needs on disk, and creating them.

The bot derives a per-user folder from the name + id
(main3.py load_startup_info: MY_PATH = "Users\\{First} {Last} {id}\\") and opens
"output <timestamp>.txt" and "skipped.txt" inside it. It also needs a Chrome
user-data directory of its own. A new user has none of that, and it used to be
the user's job to build it by hand before the Run tab would let them start.
`ensure_user_workspace` does it instead -- from the runner before launching, and
from the bot itself so a standalone `python main3.py` is just as self-sufficient.

Nothing in here imports the database layer, so main3.py can use it directly.

One thing is deliberately NOT created: a folder for a user who was renamed after
they had already run. The old folder still holds skipped.txt, which is what stops
the bot re-evaluating (and paying the AI to re-reject) jobs it already skipped.
A fresh empty folder next to it would silently throw that away, so that case is
reported instead and left for the rename action to fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROFILES_DIRNAME = "ChromeProfiles"


class WorkspaceError(Exception):
    """The folders a run needs could not be set up. The message is meant to be
    shown to the person at the Run tab as it stands."""


# --------------------------------------------------------------- user folders --
# Renaming a user silently orphans their folder, so the GUI has to keep the two
# in sync (see find_orphaned_user_folder / rename_user_folder).

def user_folder_name(user: dict[str, Any]) -> str:
    return f"{user.get('FirstName', '')} {user.get('LastName', '')} {user.get('id', '')}".strip()


def user_folder_path(root: Path | str, user: dict[str, Any]) -> Path:
    return Path(root) / "Users" / user_folder_name(user)


def find_orphaned_user_folder(root: Path | str, user: dict[str, Any]) -> str | None:
    """Find this user's folder when it is sitting under a stale name.

    Folder names always end with the user id ("Marion Faith Agbor 5"), so after a
    rename the old folder is still identifiable by that suffix. This is what lets
    the UI offer to rename it instead of the user hunting for it by hand.
    """
    users_root = Path(root) / "Users"
    if not users_root.is_dir():
        return None
    expected = user_folder_name(user)
    suffix = f" {user.get('id')}"
    for entry in users_root.iterdir():
        if entry.is_dir() and entry.name.endswith(suffix) and entry.name != expected:
            return entry.name
    return None


def rename_user_folder(root: Path | str, old_name: str, new_name: str) -> bool:
    """Rename Users/<old_name> to Users/<new_name>. Returns False if there was
    nothing to rename; raises if the destination is already taken."""
    users_root = Path(root) / "Users"
    source = users_root / old_name
    target = users_root / new_name
    if not source.exists() or old_name == new_name:
        return False
    if target.exists():
        raise FileExistsError(f"Cannot rename: {target} already exists.")
    source.rename(target)
    return True


def orphaned_folder(root: Path | str, user: dict[str, Any]) -> str | None:
    """The stale name of this user's folder, but only when the expected folder is
    missing -- i.e. when creating a fresh one would leave the old one behind."""
    if user_folder_path(root, user).exists():
        return None
    return find_orphaned_user_folder(root, user)


def orphaned_folder_message(user: dict[str, Any], orphan: str) -> str:
    return (f'The bot folder is still named "Users/{orphan}", but it now looks for '
            f'"Users/{user_folder_name(user)}". Rename it first (Users page, Data '
            f'checks, Rename) -- otherwise the history of jobs already skipped stays '
            f'behind in the old folder and starts over.')


# -------------------------------------------------------------- chrome profile --
# A dedicated, id-keyed directory: it must not live inside Users/<name>, because
# a rename moves that folder and the absolute path stored in users.ProfilePath
# would silently stop pointing at anything.

def default_profile_path(root: Path | str, user_id: int | str) -> Path:
    return Path(root).resolve() / PROFILES_DIRNAME / f"user_{user_id}"


def resolve_profile_path(root: Path | str, user: dict[str, Any]) -> str:
    """The Chrome user-data directory for this user: what they configured, or the
    default when that is blank."""
    configured = (user.get("ProfilePath") or "").strip()
    return configured or str(default_profile_path(root, user["id"]))


# ------------------------------------------------------------------- creation --

@dataclass
class WorkspaceSetup:
    """What `ensure_user_workspace` had to create. Empty when everything existed."""

    created: list[str] = field(default_factory=list)
    # A brand-new Chrome profile has no Indeed session, so the person has to sign
    # in once in the window that opens.
    new_profile: bool = False


def _make_dir(path: Path, what: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkspaceError(f"Could not create {what} ({path}): {exc.strerror or exc}") from exc


def ensure_user_workspace(root: Path | str, user: dict[str, Any]) -> WorkspaceSetup:
    """Create whatever of this user's folders and files is missing. Idempotent,
    and never touches anything that already exists.

    Raises WorkspaceError when something cannot be created, or when the user's
    folder is sitting under an old name (see the module docstring).
    """
    root = Path(root)
    setup = WorkspaceSetup()

    folder = user_folder_path(root, user)
    if not folder.is_dir():
        orphan = find_orphaned_user_folder(root, user)
        if orphan:
            raise WorkspaceError(orphaned_folder_message(user, orphan))
        _make_dir(folder, "the bot folder")
        setup.created.append(f"folder Users/{folder.name}")

    # The bot reads this one in "r" mode on every job, so it has to exist before
    # the first job is looked at rather than after the first one is skipped.
    skipped = folder / "skipped.txt"
    if not skipped.exists():
        try:
            skipped.touch()
        except OSError as exc:
            raise WorkspaceError(f"Could not create {skipped}: {exc.strerror or exc}") from exc
        setup.created.append("skipped.txt")

    profile = Path(resolve_profile_path(root, user))
    if not profile.is_absolute():
        profile = root / profile      # Chrome is launched from the project root
    if not profile.is_dir():
        _make_dir(profile, "the Chrome profile folder")
        setup.created.append(f"Chrome profile {profile}")
        setup.new_profile = True

    return setup
