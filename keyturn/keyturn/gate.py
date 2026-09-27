"""KeyTurn tool gate v0.2: pure classification and decision logic (no I/O; unit-tested).

IBM Bob runs this before a covered tool operation (PreToolUse); exit code 2 stops the operation.
It covers the operations below as they appear in command and file-tool inputs. It cannot see
every possible way to change a system (e.g. SQL hidden in an unread script), so it is a guard
rail, not a guarantee. Kinds:

  retire_old_role     make the OLD role stop working for good: NOLOGIN, DROP, RENAME, VALID UNTIL,
                      removing/renaming the old user's PgBouncer userlist entry
  change_old_password in-place (same-user) rotation: ALTER ROLE <old> PASSWORD, \\password <old>,
                      changing the old user's hash in userlist.txt
  activate            make running services pick up the files: PgBouncer RELOAD/RECONNECT/SIGHUP/
                      restart, recreating or restarting web/sidekiq/streaming
  protect_config      edits to KeyTurn's own Bob configuration under .bob/
  private             reading KeyTurn's private folder (passwords, answer key, logs)

Whether an action is allowed is decided by readiness checks computed from live observations
(checker.readiness). Readiness is about ORDER; it is never a claim of zero downtime.
"""
import re

WORD = r"(?<![\w$-]){u}(?![\w$-])"
SERVICES = ("pgbouncer", "web", "sidekiq", "streaming")


def _user_re(user):
    """The old user as an SQL identifier: bare, quoted, or with shell-escaped quotes (\\"name\\")."""
    u = re.escape(user)
    return r'(?:\\?["\'])?' + WORD.format(u=u) + r'(?:\\?["\'])?'


def strings_in(obj):
    out = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(strings_in(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(strings_in(v))
    return out


ACCESS_KEYS = ("path", "file", "file_path", "target_file", "filename", "command", "cwd", "directory", "dir",
               "pattern", "glob", "regex", "args", "paths")


def access_strings(tool_input):
    """Strings that say WHERE a tool reads, writes or runs (never free text such as a plan or a summary)."""
    if not isinstance(tool_input, dict):
        return []
    out = []
    for k in ACCESS_KEYS:
        if k in tool_input:
            out.extend(strings_in(tool_input[k]))
    return out


def command_text(tool_input):
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    return None


def tool_path(tool_input):
    if not isinstance(tool_input, dict):
        return ""
    for k in ("path", "file", "file_path", "target_file", "filename"):
        v = tool_input.get(k)
        if isinstance(v, str):
            return v
    return ""


# ---------------------------------------------------------------- SQL
def sql_kind(text, old_user):
    u = _user_re(old_user)
    retire = [
        (r"\balter\s+(?:role|user)\s+" + u + r"(?:\s+with)?[^;]*?\bnologin\b", "disables login for the old user"),
        (r"\balter\s+(?:role|user)\s+" + u + r"\s+rename\s+to\b", "renames the old user"),
        (r"\balter\s+(?:role|user)\s+" + u + r"(?:\s+with)?[^;]*?\bvalid\s+until\b", "expires the old user"),
        (r"\bdrop\s+(?:role|user)\s+(?:if\s+exists\s+)?(?:[\w\"']+\s*,\s*)*" + u, "drops the old user"),
    ]
    change = [
        (r"\balter\s+(?:role|user)\s+" + u + r"(?:\s+with)?[^;]*?\b(?:encrypted\s+)?password\b", "changes the old user's password in place"),
        (r"\\password\s+" + u, "changes the old user's password in place"),
    ]
    for p, why in retire:
        if re.search(p, text, re.IGNORECASE | re.DOTALL):
            return "retire_old_role", why
    for p, why in change:
        if re.search(p, text, re.IGNORECASE | re.DOTALL):
            return "change_old_password", why
    return None


def sql_file_args(cmd):
    return re.findall(r"(?:\s-f\s*|--file[=\s])['\"]?([^\s'\";|&]+)", cmd) + re.findall(r"<\s*['\"]?([^\s'\";|&]+\.sql)", cmd)


# ---------------------------------------------------------------- userlist.txt
def userlist_entry(content, user):
    """The quoted hash/verifier of `user` in userlist text, or None if absent."""
    m = re.search(r'^\s*"' + re.escape(user) + r'"\s+"([^"]*)"', content or "", re.MULTILINE)
    return m.group(1) if m else None


def userlist_effect(before, after, old_user):
    b, a = userlist_entry(before, old_user), userlist_entry(after, old_user)
    if b is not None and a is None:
        return "retire_old_role", "removes the old user's entry from userlist.txt"
    if b is not None and a is not None and a != b:
        return "change_old_password", "changes the old user's password hash in userlist.txt"
    return None


def apply_search_replace(current, search, replace):
    if current is None or search not in current:
        return None
    return current.replace(search, replace, 1)


def file_edit_kind(tool_name, tool_input, old_user, current_userlist=None):
    path = tool_path(tool_input)
    if "userlist" not in path:
        return None
    ti = tool_input
    if tool_name == "insert_content" or ("line" in ti and "content" in ti and "diff" not in ti and tool_name != "write_file"):
        # inserting lines never removes or changes the existing old entry; a second entry for the
        # old user would be ambiguous, so treat an inserted old-user line as a change
        if userlist_entry(ti.get("content", ""), old_user) is not None:
            return "change_old_password", "adds a second entry for the old user in userlist.txt"
        return None
    if isinstance(ti.get("content"), str):  # full rewrite
        return userlist_effect(current_userlist if current_userlist is not None else "", ti["content"], old_user) \
            if current_userlist is not None else (("retire_old_role", "rewrites userlist.txt without the old user's entry")
                                                  if userlist_entry(ti["content"], old_user) is None else None)
    if isinstance(ti.get("diff"), str):
        blocks = re.findall(r"<<<<<<<\s*SEARCH.*?\n(.*?)\n=======\n(.*?)\n>>>>>>>\s*REPLACE", ti["diff"], re.DOTALL)
        for search, replace in blocks:
            after = apply_search_replace(current_userlist, search, replace)
            if after is not None:
                eff = userlist_effect(current_userlist, after, old_user)
            else:
                eff = userlist_effect(search, replace, old_user)
            if eff:
                return eff
        removed = "\n".join(l[1:] for l in ti["diff"].splitlines() if l.startswith("-") and not l.startswith("---"))
        added = "\n".join(l[1:] for l in ti["diff"].splitlines() if l.startswith("+") and not l.startswith("+++"))
        if removed or added:
            return userlist_effect(removed, added, old_user)
        return None
    search = ti.get("search", ti.get("old_string", ti.get("old_str")))
    replace = ti.get("replace", ti.get("new_string", ti.get("new_str")))
    if isinstance(search, str) and isinstance(replace, str):
        after = apply_search_replace(current_userlist, search, replace)
        if after is not None:
            return userlist_effect(current_userlist, after, old_user)
        return userlist_effect(search, replace, old_user)
    return None


def shell_userlist_kind(cmd, old_user):
    if "userlist" not in cmd:
        return None
    u = re.escape(old_user)
    if re.search(r"sed\b[^|;&]*?/[^/]*" + u + r"[^/]*/\s*d\b", cmd, re.IGNORECASE) or \
            re.search(r"grep\s+(?:-\w*v\w*|--invert-match)\b[^|;&]*" + u, cmd, re.IGNORECASE):
        return "retire_old_role", "removes the old user's entry from userlist.txt"
    m = re.search(r"sed\b[^|;&]*?s([/|#,])(.*?)\1(.*?)\1", cmd)
    if m and re.search(r'"?' + u + r'"?', m.group(2)):
        if re.search(r'"' + u + r'"', m.group(3)) or re.search(WORD.format(u=u), m.group(3)):
            return "change_old_password", "changes the old user's password hash in userlist.txt"
        return "retire_old_role", "renames or removes the old user's entry in userlist.txt"
    return None


def userlist_copy_src(cmd):
    """Source path when a shell command replaces userlist.txt with another file (cp/mv/install/cat >), else None."""
    end = r"userlist\.txt['\"]?(?=$|[\s;|&])"
    m = re.search(r"\b(?:cp|mv|install)\b(?:\s+-{1,2}[\w-]+)*\s+['\"]?([^\s'\";|&]+)['\"]?\s+['\"]?[^\s'\";|&]*" + end, cmd)
    if m:
        return m.group(1)
    m = re.search(r"\bcat\s+['\"]?([^\s'\";|&>]+)['\"]?\s*>\s*['\"]?[^\s'\";|&]*" + end, cmd)
    return m.group(1) if m else None


def userlist_copy_kind(cmd, old_user, current_userlist, copy_text):
    if not userlist_copy_src(cmd):
        return None
    if copy_text is None or current_userlist is None:
        return "change_old_password", "replaces userlist.txt with a file KeyTurn could not read"
    return userlist_effect(current_userlist, copy_text, old_user)


# ---------------------------------------------------------------- activation
ACTIVATE_PATTERNS = [
    (r"\b(?:RELOAD|RECONNECT)\b", "reloads or reconnects PgBouncer"),
    (r"\bkill\b[^|;&]*(?:-s\s*|--signal[=\s])\s*(?:SIG)?HUP\b[^|;&]*\bpgbouncer\b", "reloads PgBouncer (SIGHUP)"),
    (r"\bkill\s+-HUP\b[^|;&]*\bpgbouncer\b", "reloads PgBouncer (SIGHUP)"),
    (r"\bpkill\s+-HUP\b[^|;&]*\bpgbouncer\b", "reloads PgBouncer (SIGHUP)"),
    (r"\bdocker(?:-compose|\s+compose)?\b[^|;&]*\b(?:restart|up|start|kill)\b[^|;&]*\b(?:pgbouncer|web|sidekiq|streaming)\b",
     "restarts or recreates services"),
    (r"\bdocker(?:-compose|\s+compose)\b[^|;&]*\bup\b(?![^|;&]*\b(?:db|redis)\b)[^|;&]*$", "recreates services"),
    (r"\bdocker(?:-compose|\s+compose)\s+(?:-\S+\s+\S+\s+)*restart\s*(?:$|[|;&])", "restarts every service"),
    (r"\bdocker\s+(?:exec|kill)\b[^|;&]*\bpgbouncer\b[^|;&]*\bkill\s+-(?:HUP|SIGHUP|1)\b", "reloads PgBouncer (SIGHUP)"),
    # v0.2.1: stopping or removing a service; its next start reads the credentials in the files
    (r"\bdocker(?:-compose|\s+compose)?\b[^|;&]*\b(?:stop|down|rm)\b[^|;&]*\b(?:pgbouncer|web|sidekiq|streaming)\b",
     "stops or removes services (their next start uses the credentials in the files)"),
    (r"\bdocker(?:-compose|\s+compose)\s+(?:-\S+\s+\S+\s+)*(?:stop|down)\s*(?:$|[|;&]|-)",
     "stops or removes every service (their next start uses the credentials in the files)"),
]


def activation(cmd):
    for p, why in ACTIVATE_PATTERNS:
        if re.search(p, cmd, re.IGNORECASE | re.MULTILINE):
            # plain reads of RELOAD in e.g. `grep RELOAD` are not activation
            if why.startswith("reloads or reconnects") and not re.search(r"\bpsql\b|pgbouncer", cmd, re.IGNORECASE):
                continue
            return "activate", why
    return None


# ---------------------------------------------------------------- config protection / private
def config_edit(tool_name, tool_input):
    path = tool_path(tool_input)
    if path and re.search(r"(^|/)\.bob/", path) and tool_name not in ("read_file", "list_files", "glob", "grep"):
        return "protect_config", "edits KeyTurn's Bob configuration under .bob/"
    cmd = command_text(tool_input)
    if cmd and re.search(r"(?:>|>>|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|\bchmod\b)[^|;&]*\.bob/", cmd):
        return "protect_config", "edits KeyTurn's Bob configuration under .bob/"
    return None


def private_access(tool_input, private_markers):
    for s in access_strings(tool_input):
        for m in private_markers:
            if m and m in s:
                return True
    return False


# ---------------------------------------------------------------- classify
def classify(tool, tool_input, old_user, private_markers=(), sql_files=None, current_userlist=None, copy_text=None):
    """Returns None (not covered) or {"kind": ..., "why": ...}. First match wins, most specific first."""
    if private_markers and private_access(tool_input, private_markers):
        return {"kind": "private", "why": "reads KeyTurn's private checker data"}
    c = config_edit(tool, tool_input)
    if c:
        return {"kind": c[0], "why": c[1]}
    cmd = command_text(tool_input)
    if cmd:
        for t in [cmd] + list(sql_files or []):
            k = sql_kind(t, old_user)
            if k:
                return {"kind": k[0], "why": k[1]}
        k = shell_userlist_kind(cmd, old_user) or userlist_copy_kind(cmd, old_user, current_userlist, copy_text)
        if k:
            return {"kind": k[0], "why": k[1]}
        k = activation(cmd)
        if k:
            return {"kind": k[0], "why": k[1]}
        return None
    if isinstance(tool_input, dict):
        k = file_edit_kind(tool, tool_input, old_user, current_userlist)
        if k:
            return {"kind": k[0], "why": k[1]}
    return None


# ---------------------------------------------------------------- decide
HOW = ("Two correct ways to rotate: (a) SAME USER: first point every copy of the password in the deployment files at the new "
       "password, then change the role's password, then reload PgBouncer and recreate the apps at once; or (b) NEW USER: "
       "create a new login role with the new password (e.g. GRANT <old> TO <new>), move every consumer to it, then retire "
       "the old role. Either way, call the KeyTurn watch tool first so the change window is observed.")


def decide(cls, readiness):
    """(allow, message). readiness comes from checker.readiness(); each part: {"ok": bool, "blockers": [...]}."""
    if cls is None:
        return True, ""
    kind = cls["kind"]
    if kind == "private":
        return False, ("Blocked by KeyTurn: that path holds KeyTurn's private checker data (passwords, answer key). "
                       "Use the KeyTurn MCP tools instead.")
    if kind == "protect_config":
        return False, ("Blocked by KeyTurn: .bob/ holds KeyTurn's own hooks, modes and tool settings. "
                       "Agents may not change them during a handover; ask the operator if a setting looks wrong.")
    part = (readiness or {}).get(kind) or {"ok": False, "blockers": ["readiness could not be evaluated"]}
    if part.get("ok"):
        note = {"change_old_password": " A short window remains until PgBouncer reloads and the apps restart; do those next.",
                "activate": "", "retire_old_role": ""}.get(kind, "")
        return True, "KeyTurn gate allows: %s.%s" % (cls["why"], note)
    lines = ["Blocked by the KeyTurn gate: this step %s, and it is not safe yet:" % cls["why"]]
    for b in part.get("blockers", []):
        lines.append("  - " + b)
    if kind in ("change_old_password", "retire_old_role"):
        lines.append(HOW)
    else:
        lines.append("Reloading or restarting now would leave services on credentials that do not work yet (Postgres does not "
                     "accept them, or PgBouncer would refuse the apps' sign-in). Fix what is listed, check with login_test, then "
                     "reload/restart.")
    return False, "\n".join(lines)
