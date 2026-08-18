#!/usr/bin/env python3
"""Safe, approval-gated localization of Codex skill-card descriptions."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def path_set(home):
    personal = home / "skills"
    return (home, personal, personal / ".system", home / "plugins" / "cache", home / ".tmp" / "plugins", home / "localize-skill-cards" / "runs")


CODEX_HOME, PERSONAL, SYSTEM, PLUGIN_CACHE, TMP_PLUGINS, RUN_ROOT = path_set(default_codex_home())
CODEX_HOME_ALIAS = Path(os.path.abspath(CODEX_HOME))
RUN_ROOT_ALIAS = CODEX_HOME_ALIAS / "localize-skill-cards" / "runs"
SAFE = re.compile(r"^[^\r\n<>`$\\]*$")
ZH = re.compile(r"[\u3400-\u9fff]")
REQUIRED_TERMS = ("Codex", "GitHub", "PR", "CI", "API")
IDENTIFIER = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*|[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*)(?![A-Za-z0-9])")
TITLE_WORD = re.compile(r"\b[A-Z][a-z]{2,}\b")
RECORD_SCHEMA_VERSION = 1
RECORD_TYPE = "localize-skill-cards-run"
MAX_OPENAI_YAML_BYTES = 256 * 1024
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_DISCOVER_CANDIDATES = 10_000
MAX_DISCOVER_TOTAL_BYTES = 128 * 1024 * 1024
MAX_RECORD_CHANGES = 4_096
RECORD_NAME = re.compile(r"^(?P<timestamp>\d{8}T\d{12}Z)-[0-9a-f]{8}\.json$")
RECORD_REQUIRED_FIELDS = {"schema_version", "record_type", "status", "timestamp", "record_path", "changes"}
RECORD_OPTIONAL_FIELDS = {"error", "rollback_errors", "restore_status", "restore_error", "restore_rollback_errors"}
CATALOG_FIELDS = {"version", "selection_rule", "translations"}
STABLE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def safe_text(value):
    return isinstance(value, str) and all(ch.isprintable() for ch in value)


def diagnostic(value):
    return json.dumps(str(value), ensure_ascii=True)


def valid_stable_id(value):
    if not isinstance(value, str):
        return False
    parts = value.split("/")
    if parts[0] in {"personal", "system"}:
        names = parts[1:]
        if len(parts) != 2:
            return False
    elif parts[0] == "plugin":
        names = parts[1:]
        if len(parts) != 4:
            return False
    else:
        return False
    return all(STABLE_SEGMENT.fullmatch(name) is not None and name not in {".", ".."} for name in names)


def configure_paths(codex_home=None):
    """Configure Codex roots for a CLI run or an isolated test."""
    global CODEX_HOME, PERSONAL, SYSTEM, PLUGIN_CACHE, TMP_PLUGINS, RUN_ROOT, CODEX_HOME_ALIAS, RUN_ROOT_ALIAS
    selected_alias = Path(codex_home).expanduser() if codex_home else default_codex_home()
    selected_alias = Path(os.path.abspath(selected_alias))
    selected_home = selected_alias.resolve(strict=False)
    CODEX_HOME_ALIAS = selected_alias
    RUN_ROOT_ALIAS = selected_alias / "localize-skill-cards" / "runs"
    CODEX_HOME, PERSONAL, SYSTEM, PLUGIN_CACHE, TMP_PLUGINS, RUN_ROOT = path_set(
        selected_home
    )


def read_bounded_bytes(path, limit, label):
    with Path(path).open("rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{label} exceeds {limit} bytes")
    return data


def decode_utf8(data, label):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8") from exc


def inside(p, root):
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def roots(managed=False):
    return [PERSONAL] + ([SYSTEM, PLUGIN_CACHE] if managed else [])


def lexical_inside(p, root):
    try:
        Path(os.path.abspath(p)).relative_to(Path(os.path.abspath(root)))
        return True
    except ValueError:
        return False


def scope_root(p, managed=False):
    if lexical_inside(p, TMP_PLUGINS):
        return None
    if lexical_inside(p, SYSTEM):
        return SYSTEM if managed else None
    if lexical_inside(p, PLUGIN_CACHE):
        return PLUGIN_CACHE if managed else None
    return PERSONAL if lexical_inside(p, PERSONAL) else None


def path_components_safe(p, root):
    target = Path(os.path.abspath(p))
    root_path = Path(os.path.abspath(root))
    if root_path.is_symlink():
        return False
    try:
        relative = target.relative_to(root_path)
        resolved = Path(p).resolve(strict=False)
        resolved.relative_to(root_path.resolve())
    except ValueError:
        return False
    current = root_path
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            return False
    return True


def validate_target_path(p, expected_stable_id=None, managed=False):
    path = Path(p)
    root = scope_root(path, managed)
    if root is None or not path_components_safe(path, root):
        raise ValueError("target path is outside the selected scope or crosses a symlink")
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe target path")
    actual_stable_id = stable_id(path)
    if expected_stable_id is not None and actual_stable_id != expected_stable_id:
        raise ValueError("stable ID does not match target path")
    return root, actual_stable_id


def stable_id(p):
    p = Path(p).resolve()
    try:
        r = p.relative_to(PERSONAL.resolve())
        return ("system/" + r.parts[1]) if r.parts[0] == ".system" else ("personal/" + r.parts[0])
    except ValueError:
        pass
    r = p.relative_to(PLUGIN_CACHE.resolve())
    q = r.parts
    if len(q) >= 5 and q[3] == "skills":
        return f"plugin/{q[0]}/{q[1]}/{q[4]}"
    raise ValueError("outside supported roots")


def parse_yaml(p):
    raw = read_bounded_bytes(p, MAX_OPENAI_YAML_BYTES, "openai.yaml")
    lines = decode_utf8(raw, "openai.yaml").splitlines(keepends=True)
    heads = [i for i, x in enumerate(lines) if re.match(r"^interface:\s*(?:#.*)?(?:\r?\n)?$", x)]
    if len(heads) != 1:
        raise ValueError("interface must occur exactly once")
    end = len(lines)
    for i in range(heads[0] + 1, len(lines)):
        if re.match(r"^[^ \t#][^:]*:\s*", lines[i]):
            end = i
            break
    hits = [i for i in range(heads[0] + 1, end) if re.match(r"^  short_description:\s*", lines[i])]
    if len(hits) != 1:
        raise ValueError("short_description must occur exactly once")
    i = hits[0]
    m = re.match(r"^  short_description:\s*(.*?)(\r?\n)?$", lines[i])
    val = m.group(1).strip()
    if len(val) < 2 or val[0] != '"' or val[-1] != '"':
        raise ValueError("description must be one quoted scalar")
    val = json.loads(val)
    if not safe_text(val) or not SAFE.match(val):
        raise ValueError("unsafe description")
    return raw, lines, i, val


def version_key(p):
    v = Path(p).parts[-5] if len(Path(p).parts) >= 5 else ""
    nums = tuple(int(x) for x in re.findall(r"\d+", v))
    return (nums, Path(p).stat().st_mtime_ns, v)


def discover(managed=False):
    candidates = {}
    candidate_count = 0
    total_bytes = 0
    for root in roots(managed):
        if not root.exists():
            continue
        for p in sorted(root.rglob("agents/openai.yaml")):
            candidate_root = scope_root(p, managed)
            if (
                candidate_root is None
                or not path_components_safe(p, candidate_root)
                or p.is_symlink()
                or not p.is_file()
                or inside(p, TMP_PLUGINS)
                or (not managed and inside(p, SYSTEM))
            ):
                continue
            candidate_count += 1
            if candidate_count > MAX_DISCOVER_CANDIDATES:
                raise ValueError(f"candidate count exceeds {MAX_DISCOVER_CANDIDATES}")
            size = p.stat().st_size
            if size > MAX_OPENAI_YAML_BYTES:
                raise ValueError(f"openai.yaml exceeds {MAX_OPENAI_YAML_BYTES} bytes")
            total_bytes += size
            if total_bytes > MAX_DISCOVER_TOTAL_BYTES:
                raise ValueError(f"candidate bytes exceed {MAX_DISCOVER_TOTAL_BYTES}")
            try:
                sid = stable_id(p)
            except ValueError:
                continue
            if sid in candidates and version_key(p) <= version_key(candidates[sid]):
                continue
            candidates[sid] = p
    out = []
    for sid, p in sorted(candidates.items()):
        try:
            _, _, _, v = parse_yaml(p)
            out.append({"path": str(p), "stable_id": sid, "source": sid.split("/", 1)[0], "value": v, "valid": True})
        except Exception as e:
            out.append({"path": str(p), "stable_id": sid, "valid": False, "error": str(e)})
    return out


def bundled_catalog_path():
    return Path(__file__).resolve().parents[1] / "references/approved-translations.json"


def runtime_catalog_path():
    return RUN_ROOT.parent / "approved-translations.json"


def catalog_path():
    """Return the public schema/template path for inspection."""
    return bundled_catalog_path()


def translations(path=None):
    if path:
        p = Path(path)
    else:
        p = runtime_catalog_path()
        if not p.is_file():
            return {}
    raw = read_bounded_bytes(p, MAX_CATALOG_BYTES, "translation catalog")
    try:
        d = json.loads(decode_utf8(raw, "translation catalog"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"translation catalog is invalid JSON: {exc.msg}") from exc
    if not isinstance(d, dict):
        raise ValueError("translation catalog must be an object")
    unknown = set(d) - CATALOG_FIELDS
    if unknown:
        fields = ", ".join(diagnostic(value) for value in sorted(unknown))
        raise ValueError(f"translation catalog has unknown top-level fields: {fields}")
    if set(d) != CATALOG_FIELDS:
        raise ValueError("translation catalog must contain version, selection_rule, and translations")
    if type(d["version"]) is not int or d["version"] != 1:
        raise ValueError("unsupported translation catalog version")
    if not isinstance(d["selection_rule"], str) or not d["selection_rule"].strip():
        raise ValueError("translation catalog selection_rule must be a non-empty string")
    if not isinstance(d["translations"], dict):
        raise ValueError("translation catalog translations must be an object")
    for stable_id_value, value in d["translations"].items():
        if not valid_stable_id(stable_id_value):
            raise ValueError(f"translation catalog has invalid stable ID: {diagnostic(stable_id_value)}")
        if not isinstance(value, str):
            raise ValueError(f"translation catalog value for {stable_id_value} must be a string")
        if not safe_text(value) or SAFE.fullmatch(value) is None:
            raise ValueError(f"translation catalog value for {stable_id_value} is unsafe")
    return d["translations"]


def clear_zh(v):
    if not ZH.search(v):
        return False
    chinese = len(ZH.findall(v))
    words = re.findall(r"\b(the|with|and|help|review|create|use|setup|build|fix)\b", v, re.I)
    return chinese >= 6 or not words


def valid_value(v):
    if not safe_text(v):
        return "must be single-line string"
    if not ZH.search(v):
        return "must contain at least one Chinese character"
    if not 25 <= len(v) <= 64:
        return "length must be 25-64 characters"
    if not SAFE.match(v):
        return "contains unsafe symbols"
    return None


def translation_issues(old, new):
    errors = []
    for term in REQUIRED_TERMS:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", old) and not re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", new):
            errors.append(f"must preserve {term}")
    for token in sorted(set(IDENTIFIER.findall(old))):
        if token not in REQUIRED_TERMS and token not in IDENTIFIER.findall(new):
            errors.append(f"must preserve identifier {token}")
    title_words = TITLE_WORD.findall(old)
    warnings = [f"review possible Title Case product names: {', '.join(title_words)}"] if len(title_words) >= 2 else []
    return errors, warnings


def plan(items, trans):
    out = []
    for x in items:
        if not x.get("valid"):
            out.append({**x, "action": "error"})
            continue
        old = x["value"]
        new = trans.get(x["stable_id"])
        if clear_zh(old):
            action, new = "skip", old
        elif new is None:
            action = "needs-approval"
        else:
            err = valid_value(new)
            errors, warnings = translation_issues(old, new) if not err else ([], [])
            if errors:
                err = "; ".join(errors)
            action = "error" if err else "change"
            if err:
                x = {**x, "error": err}
            elif warnings:
                x = {**x, "warnings": warnings}
        out.append({**x, "old": old, "new": new, "action": action})
    return out


def replacement(p, new, require_chinese=True):
    raw, lines, i, _ = parse_yaml(p)
    err = valid_value(new) if require_chinese else ("must be single-line string" if not isinstance(new, str) or "\n" in new else None)
    if err:
        raise ValueError(err)
    old = lines[i]
    e = "\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
    lines[i] = "  short_description: " + json.dumps(new, ensure_ascii=False) + e
    data = "".join(lines).encode()
    if len(raw.splitlines()) != len(data.splitlines()):
        raise ValueError("unexpected rewrite")
    if len(data) > MAX_OPENAI_YAML_BYTES:
        raise ValueError(f"resulting openai.yaml exceeds {MAX_OPENAI_YAML_BYTES} bytes")
    return raw, data


def atomic_write(p, data, managed=False, expected_stable_id=None, expected_old=None, expected_before_sha256=None):
    p = Path(p)
    validate_target_path(p, expected_stable_id, managed)
    if expected_old is not None or expected_before_sha256 is not None:
        raw, _, _, current = parse_yaml(p)
        if expected_old is not None and current != expected_old:
            raise ValueError("current value differs from planned old value")
        if expected_before_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_before_sha256:
            raise ValueError("target bytes changed after preparation")
    fd, tmp = tempfile.mkstemp(prefix=".localize-", dir=p.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, p.stat().st_mode & 0o777)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def has_symlink_component(path):
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            return True
    return False


def private_record_root(root):
    root = Path(root)
    if has_symlink_component(root):
        raise ValueError("record root must not cross a symlink")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not root.is_dir() or has_symlink_component(root):
        raise ValueError("record root must be a real directory")
    os.chmod(root, 0o700)
    return root.resolve()


def encoded_record(payload):
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError(f"run record exceeds {MAX_RECORD_BYTES} bytes")
    return data


def write_record(payload, root=None):
    root = private_record_root(root or RUN_ROOT)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for _ in range(10):
        p = root / f"{stamp}-{secrets.token_hex(4)}.json"
        data = {**payload, "schema_version": RECORD_SCHEMA_VERSION, "record_type": RECORD_TYPE, "timestamp": stamp, "record_path": str(p)}
        encoded = encoded_record(data)
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
            fsync_directory(root)
            return p
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate a unique run record")


def update_record(record, payload):
    record = Path(record)
    encoded = encoded_record(payload)
    fd, tmp = tempfile.mkstemp(prefix=".record-", dir=record.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, record)
        os.chmod(record, 0o600)
        fsync_directory(record.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def persistent_changes(prepared):
    return [{key: item[key] for key in ("path", "stable_id", "old", "new")} for item in prepared]


def required_stable_id(row):
    value = row.get("stable_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("stable_id must be a non-empty string")
    if not valid_stable_id(value):
        raise ValueError("stable_id has invalid path components")
    return value


def safe_record_description(value):
    return safe_text(value) and SAFE.fullmatch(value) is not None


def validate_record_path(record):
    record = Path(record)
    configured_root = Path(RUN_ROOT)
    if not configured_root.is_dir() or has_symlink_component(configured_root) or stat.S_IMODE(configured_root.stat().st_mode) & 0o077:
        raise ValueError("record root is missing, symlinked, or not private")
    root = configured_root.resolve()
    canonical_record = None
    if lexical_inside(record, root):
        if path_components_safe(record, root):
            canonical_record = record.resolve()
    elif lexical_inside(record, RUN_ROOT_ALIAS):
        alias_root = Path(os.path.abspath(RUN_ROOT_ALIAS))
        relative = Path(os.path.abspath(record)).relative_to(alias_root)
        current = alias_root
        for component in relative.parts:
            current /= component
            if current.is_symlink():
                raise ValueError("record must be inside the current run root without symlinks")
        mapped = root / relative
        try:
            resolved = record.resolve(strict=False)
            resolved.relative_to(root)
            if resolved != mapped.resolve(strict=False) or not path_components_safe(mapped, root):
                raise ValueError("record must be inside the current run root without symlinks")
        except ValueError:
            raise ValueError("record must be inside the current run root without symlinks")
        canonical_record = mapped.resolve()
    if canonical_record is None:
        raise ValueError("record must be inside the current run root without symlinks")
    record = canonical_record
    if record.is_symlink() or not record.is_file() or not stat.S_ISREG(record.stat().st_mode):
        raise ValueError("record must be a real regular file")
    if stat.S_IMODE(record.stat().st_mode) & 0o077:
        raise ValueError("record file must be private")
    return record.resolve()


def load_restore_record(record):
    canonical = validate_record_path(record)
    name_match = RECORD_NAME.fullmatch(canonical.name)
    if name_match is None:
        raise ValueError("restore record filename is not tool-generated")
    raw = read_bounded_bytes(canonical, MAX_RECORD_BYTES, "restore record")
    try:
        data = json.loads(decode_utf8(raw, "restore record"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"restore record is invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("restore record must be an object")
    unknown = set(data) - RECORD_REQUIRED_FIELDS - RECORD_OPTIONAL_FIELDS
    if unknown:
        fields = ", ".join(diagnostic(value) for value in sorted(unknown))
        raise ValueError(f"restore record has unknown top-level fields: {fields}")
    if not RECORD_REQUIRED_FIELDS.issubset(data):
        raise ValueError("restore record is missing required top-level fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != RECORD_SCHEMA_VERSION:
        raise ValueError("unsupported restore record schema or type")
    if not isinstance(data["record_type"], str) or data["record_type"] != RECORD_TYPE:
        raise ValueError("unsupported restore record schema or type")
    if not isinstance(data["timestamp"], str) or data["timestamp"] != name_match.group("timestamp"):
        raise ValueError("restore record timestamp does not match its filename")
    try:
        dt.datetime.strptime(data["timestamp"], "%Y%m%dT%H%M%S%fZ")
    except ValueError as exc:
        raise ValueError("restore record timestamp is not a valid UTC timestamp") from exc
    status = data["status"]
    if not isinstance(status, str):
        raise ValueError("restore record status must be a string")
    if "error" in data and not isinstance(data["error"], str):
        raise ValueError("restore record error must be a string")
    if "rollback_errors" in data and (not isinstance(data["rollback_errors"], list) or not all(isinstance(item, str) for item in data["rollback_errors"])):
        raise ValueError("restore record rollback_errors must be a list of strings")
    if status == "completed" and ({"error", "rollback_errors"} & set(data)):
        raise ValueError("completed restore record must not contain apply failure fields")
    restore_status = data.get("restore_status")
    if "restore_status" in data and (not isinstance(restore_status, str) or restore_status not in {"completed", "rolled_back", "failed"}):
        raise ValueError("restore_status is invalid")
    if "restore_error" in data and not isinstance(data["restore_error"], str):
        raise ValueError("restore_error must be a string")
    if "restore_rollback_errors" in data and (not isinstance(data["restore_rollback_errors"], list) or not all(isinstance(item, str) for item in data["restore_rollback_errors"])):
        raise ValueError("restore_rollback_errors must be a list of strings")
    if restore_status in {"rolled_back", "failed"}:
        if "restore_error" not in data or "restore_rollback_errors" not in data:
            raise ValueError("failed restore status requires error details")
    elif {"restore_error", "restore_rollback_errors"} & set(data):
        raise ValueError("restore error details require a failed restore status")
    if status != "completed":
        raise ValueError("restore record status must be completed")
    if not isinstance(data["record_path"], str) or data["record_path"] != str(canonical):
        raise ValueError("restore record_path does not match the actual record")
    changes = data["changes"]
    if not isinstance(changes, list) or not changes:
        raise ValueError("restore record changes must be a non-empty list")
    if len(changes) > MAX_RECORD_CHANGES:
        raise ValueError(f"restore record changes exceed {MAX_RECORD_CHANGES}")
    required = {"path", "stable_id", "old", "new"}
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("restore change fields are invalid")
        required_stable_id(change)
        if set(change) != required:
            raise ValueError("restore change fields are invalid")
        if not isinstance(change["path"], str) or not change["path"] or not Path(change["path"]).is_absolute():
            raise ValueError("restore change path must be an absolute string")
        if not safe_record_description(change["old"]) or not safe_record_description(change["new"]):
            raise ValueError("restore descriptions must be safe printable single-line strings")
    return canonical, data


def rollback_written(done, managed=False):
    errors = []
    for item in reversed(done):
        try:
            atomic_write(item["path"], item["before_data"], managed, item["stable_id"])
        except Exception as exc:
            errors.append(str(exc))
    return errors


def transaction_error(operation, stage, cause, rollback_errors, record_error):
    rollback_detail = "; ".join(rollback_errors) if rollback_errors else "none"
    record_detail = str(record_error) if record_error else "none"
    return RuntimeError(f"{operation} transaction failed during {stage}: {cause}; rollback_errors={rollback_detail}; record_error={record_detail}")


def allowed_record(x, managed=False):
    try:
        validate_target_path(x["path"], required_stable_id(x), managed)
        return True
    except (OSError, ValueError):
        return False


def apply_rows(rows, root=None, managed=False):
    root = root or RUN_ROOT
    if not rows:
        raise ValueError("no changes to apply")
    if len(rows) > MAX_RECORD_CHANGES:
        raise ValueError(f"changes exceed {MAX_RECORD_CHANGES}")
    prepared = []
    for x in rows:
        p = Path(x["path"])
        stable_id_value = required_stable_id(x)
        validate_target_path(p, stable_id_value, managed)
        raw, _, _, current = parse_yaml(p)
        if current != x["old"]:
            raise ValueError("current value differs from planned old value")
        translation_errors, _ = translation_issues(current, x["new"])
        if translation_errors:
            raise ValueError("; ".join(translation_errors))
        _, data = replacement(p, x["new"])
        prepared.append({"path": x["path"], "stable_id": stable_id_value, "old": x["old"], "new": x["new"], "before_sha256": hashlib.sha256(raw).hexdigest(), "data": data, "before_data": raw})
    rec = write_record({"status": "prepared", "changes": persistent_changes(prepared)}, root)
    initial_record = json.loads(decode_utf8(read_bounded_bytes(rec, MAX_RECORD_BYTES, "run record"), "run record"))
    record_identity = {key: initial_record[key] for key in ("schema_version", "record_type", "timestamp", "record_path")}
    done = []
    stage = "file writes"
    try:
        for x in prepared:
            atomic_write(x["path"], x["data"], managed, x["stable_id"], x["old"], x["before_sha256"])
            done.append(x)
        stage = "record update"
        payload = {"status": "completed", "changes": persistent_changes(prepared)}
        update_record(rec, {**payload, **record_identity})
    except Exception as exc:
        rollback_errors = rollback_written(done, managed)
        status = "rolled_back" if not rollback_errors else "failed"
        payload = {"status": status, "error": str(exc), "rollback_errors": rollback_errors, "changes": persistent_changes(prepared)}
        record_error = None
        try:
            update_record(rec, {**payload, **record_identity})
        except Exception as status_exc:
            record_error = status_exc
        if stage == "record update" or rollback_errors or record_error:
            raise transaction_error("apply", stage, exc, rollback_errors, record_error) from exc
        raise
    return rec


def restore(record, confirm=False, managed=False):
    record, d = load_restore_record(record)
    rows = []
    prepared = []
    for x in d.get("changes", []):
        required_stable_id(x)
        if not allowed_record(x, managed):
            raise ValueError("record path outside allowed roots or stable ID mismatch")
        raw, _, _, current = parse_yaml(x["path"])
        if current != x["new"]:
            raise ValueError("current value differs from recorded new value")
        row = {**x, "old": x["new"], "new": x["old"]}
        rows.append(row)
        _, data = replacement(row["path"], row["new"], False)
        prepared.append({**row, "before_data": raw, "before_sha256": hashlib.sha256(raw).hexdigest(), "data": data})
    if not confirm:
        return rows
    done = []
    stage = "file writes"
    try:
        for x in prepared:
            atomic_write(x["path"], x["data"], managed, x["stable_id"], x["old"], x["before_sha256"])
            done.append(x)
        stage = "record update"
        d["restore_status"] = "completed"
        d.pop("restore_error", None)
        d.pop("restore_rollback_errors", None)
        update_record(record, d)
    except Exception as exc:
        rollback_errors = rollback_written(done, managed)
        d["restore_status"] = "rolled_back" if not rollback_errors else "failed"
        d["restore_error"] = str(exc)
        d["restore_rollback_errors"] = rollback_errors
        record_error = None
        try:
            update_record(record, d)
        except Exception as status_exc:
            record_error = status_exc
        if stage == "record update" or rollback_errors or record_error:
            raise transaction_error("restore", stage, exc, rollback_errors, record_error) from exc
        raise
    return rows


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for n in ("scan", "plan", "apply", "validate"):
        q = sp.add_parser(n)
        q.add_argument("--codex-home", metavar="DIR")
        q.add_argument("--include-managed", action="store_true")
        if n in ("plan", "apply"):
            q.add_argument("--translations")
        if n == "apply":
            q.add_argument("--confirm", action="store_true")
    q = sp.add_parser("restore")
    q.add_argument("record")
    q.add_argument("--codex-home", metavar="DIR")
    q.add_argument("--include-managed", action="store_true")
    q.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    if a.cmd == "restore":
        configure_paths(a.codex_home)
        print(json.dumps(restore(a.record, a.confirm, a.include_managed), ensure_ascii=False, indent=2))
        return
    configure_paths(a.codex_home)
    items = discover(a.include_managed)
    if a.cmd == "scan":
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    rows = plan(items, translations(getattr(a, "translations", None)))
    if a.cmd == "apply":
        if not a.confirm:
            raise SystemExit("apply requires --confirm")
        if any(x["action"] in ("error", "needs-approval") for x in rows):
            raise ValueError("apply requires a fully resolved plan")
        good = [x for x in rows if x["action"] == "change"]
        record = apply_rows(good, managed=a.include_managed)
        print(json.dumps({"status": "completed", "plan": rows, "record": str(record)}, ensure_ascii=False, indent=2))
        return
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    if a.cmd == "plan":
        raise SystemExit(1 if any(x["action"] == "error" for x in rows) else 0)
    if a.cmd == "validate":
        raise SystemExit(1 if any(x["action"] in ("error", "needs-approval") for x in rows) else 0)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
