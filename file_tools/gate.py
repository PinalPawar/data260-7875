"""
HW7 Part 6: the bash safety gate. Pure Python, no model, no shell is ever started here.

    is_destructive(command)                   -> bool  (independent deny-list)
    destructive_reason(command)               -> str | None  (which deny rule matched)
    confirm_bash(command, auto_approve=False) -> {"allow": bool, "reason": str}

Order of checks in confirm_bash:
  1. empty command                      -> block
  2. is_destructive(command)            -> block, unless auto_approve=True (explicit
                                           confirmation). SAFE_PREFIXES is NOT consulted, so
                                           "ls; rm -rf ~" or "echo x > /etc/hosts" stay blocked.
  3. every segment of the command (split on ; && || | and newlines) starts with an entry of
     SAFE_PREFIXES and contains no command substitution  -> allow
  4. anything else                      -> block, unless auto_approve=True
"""

import re
import shlex
from typing import Optional

# Read-only or sandbox-local commands that may run without asking.
SAFE_PREFIXES = (
    "ls",
    "pwd",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "echo",
    "sort",
    "uniq",
    "diff",
    "date",
    "git status",
    "git diff",
    "git log",
)

SEGMENT_SPLIT = re.compile(r"\|\||&&|;|\||\n|(?<![>&])&(?![>&])")
SUBSTITUTION = re.compile(r"`|\$\(|<\(|>\(")
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "nice", "env", "xargs"}
SAFE_DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}

# (rule name, test on one segment's argv) - each returns True when the segment is destructive
PRIV_CMDS = {"sudo", "su", "doas", "pkexec", "runas"}
PERM_CMDS = {"chmod", "chown", "chgrp", "chattr", "setfacl"}
MKFS_CMDS = {"mkfs", "mke2fs", "mkswap", "newfs", "mkdosfs", "wipefs", "fdisk", "parted"}


def _segments(command: str) -> list:
    return [s.strip() for s in SEGMENT_SPLIT.split(command) if s.strip()]


def _argv(segment: str) -> list:
    try:
        return shlex.split(segment)
    except ValueError:  # unbalanced quotes: fall back to whitespace split
        return segment.split()


def _program(argv: list) -> tuple:
    """(program basename, remaining args), skipping wrappers like env/command/nohup and
    leading VAR=value assignments, so '\\rm', '/bin/rm' and 'env sudo' are all seen."""
    i = 0
    while i < len(argv) and (
        re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[i])
        or argv[i].lstrip("\\").split("/")[-1] in WRAPPERS
    ):
        i += 1
    if i >= len(argv):
        return "", []
    return argv[i].lstrip("\\").split("/")[-1], argv[i + 1 :]


def _recursive_delete(prog: str, args: list) -> bool:
    if prog == "rm":
        for a in args:
            if a == "--recursive" or (
                a.startswith("-") and not a.startswith("--") and re.search(r"[rR]", a)
            ):
                return True
    if prog == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok") for a in args):
        return "-delete" in args or any(x in ("rm", "/bin/rm") for x in args)
    if prog == "git" and args[:1] == ["clean"] and any("f" in a for a in args if a.startswith("-")):
        return True
    return prog in {"shred", "srm"}


def _raw_device_write(prog: str, args: list, segment: str) -> bool:
    if prog == "dd" and any(a.startswith("of=/dev/") for a in args):
        return True
    for target in re.findall(r">>?\s*(/dev/[^\s;|&]+)", segment):
        if target not in SAFE_DEVICES:
            return True
    return prog in {"tee", "cp"} and any(
        a.startswith("/dev/") and a not in SAFE_DEVICES for a in args
    )


def _root_redirect(prog: str, args: list, segment: str) -> bool:
    """Writing to an absolute path: '> /etc/x', '>> /x', 'tee /etc/x', '2> /var/log/x'."""
    for target in re.findall(r"\d?>>?\|?\s*(/[^\s;|&]*)", segment):
        if target not in SAFE_DEVICES and not target.startswith("/dev/"):
            return True
    if prog == "tee":
        return any(a.startswith("/") and a not in SAFE_DEVICES for a in args if a != "-a")
    return False


def destructive_reason(command: str) -> Optional[str]:
    """Name of the first deny rule the command triggers, or None. Commands inside $(...),
    backticks and <(...) are checked too, so 'ls $(rm -rf x)' is caught."""
    for inner in re.findall(r"\$\(([^()]*)\)|`([^`]*)`|[<>]\(([^()]*)\)", command or ""):
        rule = destructive_reason(next(x for x in inner if x))
        if rule:
            return rule
    for segment in _segments(command or ""):
        prog, args = _program(_argv(segment))
        if _recursive_delete(prog, args):
            return "recursive deletion"
        if prog in PRIV_CMDS:
            return "privilege escalation"
        if prog in PERM_CMDS:
            return "permission/ownership change"
        if _raw_device_write(prog, args, segment):
            return "raw-device write"
        if (
            prog in MKFS_CMDS
            or prog.startswith("mkfs.")
            or (prog == "diskutil" and any(a.lower().startswith("erase") for a in args))
        ):
            return "filesystem creation"
        if _root_redirect(prog, args, segment):
            return "redirection to a root path"
    return None


def is_destructive(command: str) -> bool:
    """Independent deny-list check (does not look at SAFE_PREFIXES)."""
    return destructive_reason(command) is not None


def _matches_safe_prefix(segment: str) -> bool:
    words = " ".join(_argv(segment))
    prog, args = _program(_argv(segment))
    normalised = " ".join([prog] + args) if prog else words
    return any(normalised == p or normalised.startswith(p + " ") for p in SAFE_PREFIXES)


def confirm_bash(command: str, auto_approve: bool = False) -> dict:
    """Allow/block decision with a short reason. auto_approve=True is explicit confirmation."""
    command = (command or "").strip()
    if not command:
        return {"allow": False, "reason": "empty command"}
    rule = destructive_reason(command)
    if rule:
        if auto_approve:
            return {"allow": True, "reason": f"destructive ({rule}) - explicitly confirmed"}
        return {"allow": False, "reason": f"destructive: {rule}; needs explicit confirmation"}
    if SUBSTITUTION.search(command):
        verdict = "command substitution is never auto-allowed"
    elif all(_matches_safe_prefix(s) for s in _segments(command)):
        return {"allow": True, "reason": "every part matches SAFE_PREFIXES"}
    else:
        verdict = "not on the SAFE_PREFIXES allow-list"
    if auto_approve:
        return {"allow": True, "reason": f"{verdict} - explicitly confirmed"}
    return {"allow": False, "reason": f"{verdict}; needs confirmation"}


def prefix_only_gate(command: str) -> dict:
    """The first, naive version kept for comparison: allow when the command STARTS with a safe
    prefix. It has no deny-list and does not split chained commands."""
    first = (command or "").strip()
    ok = any(first == p or first.startswith(p + " ") for p in SAFE_PREFIXES)
    return {"allow": ok, "reason": "starts with a safe prefix" if ok else "not allow-listed"}
