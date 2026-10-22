"""Manual LLM-coach plumbing (no API calls).

  coach-pack runs/<id>          -> runs/<id>/coach_prompt.md to paste into Claude by hand
  import-tips runs/<id> f.json  -> validate the coach's tips JSON and store it in analysis.json

The schema lives in coach/schema.json; `validate` below implements the small
JSON-Schema subset that file uses (type, enum, required, properties,
additionalProperties, items, minimum, minLength, minItems), so no new deps.
"""

import json
import re
from pathlib import Path

from . import routes as route_lib
from .digest import write_digest

ROOT = Path(__file__).resolve().parent.parent
COACH_DIR = ROOT / "coach"
KNOWLEDGE_DIR = ROOT / "knowledge"
KNOWLEDGE_FILES = ("general.md", "bastions.md", "bridge_routes.md", "mistakes.md")

_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
          "object": dict, "array": list, "null": type(None)}


def _type_ok(value, name):
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def validate(value, schema, path="$"):
    """Return a list of error strings (empty = valid)."""
    errors = []
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        if not any(_type_ok(value, ty) for ty in types):
            return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not one of {schema['enum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: shorter than {schema['minLength']} chars")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema \
            and value < schema["minimum"]:
        errors.append(f"{path}: {value} < minimum {schema['minimum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing '{key}'")
        props = schema.get("properties", {})
        for key, sub in value.items():
            if key in props:
                errors += validate(sub, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected field '{key}'")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{i}]")
    return errors


def load_schema():
    return json.loads((COACH_DIR / "schema.json").read_text())


def catalogue_ids():
    path = KNOWLEDGE_DIR / "mistakes.md"
    if not path.is_file():
        return set()
    return set(re.findall(r"^\s*-\s*id:[ \t]*`?([A-Za-z0-9][\w.-]*)`?", path.read_text(), flags=re.M))


# --- coach-pack ------------------------------------------------------------------

def approved_lesson_lines():
    """Only the approved lesson bullets of coach/lessons.md (`- **L<n>** ...` under `## Lessons`)."""
    path = COACH_DIR / "lessons.md"
    if not path.is_file():
        return []
    text = path.read_text()
    body = text.split("## Lessons", 1)[1] if "## Lessons" in text else ""
    out = []
    for line in body.splitlines():
        if re.match(r"^\s*-\s*\*\*L\d+\*\*", line):
            out.append(line.rstrip())
        elif out and line.startswith("  ") and line.strip():       # wrapped continuation of a lesson
            out[-1] += " " + line.strip()
    return out


def coach_pack(run_dir):
    run_dir = Path(run_dir)
    digest_path = write_digest(run_dir)
    parts = [(COACH_DIR / "system_prompt.md").read_text().replace("<RUN_ID>", run_dir.name)]
    for name in KNOWLEDGE_FILES:
        path = KNOWLEDGE_DIR / name
        if path.is_file():
            parts.append(f"# Knowledge file: knowledge/{name}\n\n{path.read_text()}")
    routes_text = route_lib.coach_text()
    if routes_text is not None:
        parts.append(f"# Knowledge file: knowledge/routes.md\n\n{routes_text}")
    lessons = approved_lesson_lines()
    parts.append("# Approved lessons: coach/lessons.md\n\nGeneral rules the learner approved from earlier critic "
                 "passes; follow them like the rules above.\n\n" + ("\n".join(lessons) if lessons else "(none approved yet)"))
    parts.append("# Output schema: coach/schema.json\n\n```json\n" + (COACH_DIR / "schema.json").read_text().strip()
                 + "\n```")
    parts.append(digest_path.read_text())
    text = "\n\n---\n\n".join(p.strip() for p in parts) + "\n"
    out = run_dir / "coach_prompt.md"
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}: {len(text)} chars, ~{len(text) // 4} tokens "
          f"(digest ~{len(digest_path.read_text()) // 4})")
    return out


# --- import-tips -----------------------------------------------------------------

def to_ui_tip(tip):
    """Coach tip -> analysis.json Tip (UI shape) with the coach-only fields under `coach`."""
    return {
        "t_s": round(float(tip["t_start_s"]), 2),
        "end_s": round(float(tip["t_end_s"]), 2),
        "kind": tip["scope"],                    # macro | micro (existing TipKind values)
        "title": tip["title"],
        "text": tip["explanation"],
        "est_loss_s": tip["est_seconds_lost"],
        "source": "coach",
        "coach": {k: tip[k] for k in ("id", "split", "kind", "known_at_time", "confidence", "fix_type",
                                      "severity_rank", "evidence", "catalogue_id", "disagrees_with_catalogue")}
                  | {"reference_route": tip.get("reference_route")},
    }


def import_tips(run_dir, tips_file):
    run_dir = Path(run_dir)
    analysis_path = run_dir / "analysis.json"
    if not analysis_path.is_file():
        raise SystemExit(f"Missing {analysis_path}")
    try:
        data = json.loads(Path(tips_file).read_text())
    except (OSError, json.JSONDecodeError) as err:
        raise SystemExit(f"Could not read {tips_file}: {err}")
    if isinstance(data, list):                      # accept a bare array too
        data = {"tips": data}
    errors = validate(data, load_schema())
    for i, tip in enumerate(data.get("tips") or []):
        if isinstance(tip, dict) and isinstance(tip.get("t_start_s"), (int, float)) \
                and isinstance(tip.get("t_end_s"), (int, float)) and tip["t_end_s"] < tip["t_start_s"]:
            errors.append(f"$.tips[{i}]: t_end_s < t_start_s")
    routes = route_lib.route_ids()
    for i, tip in enumerate(data.get("tips") or []):
        ref = tip.get("reference_route") if isinstance(tip, dict) else None
        if isinstance(ref, str) and ref not in routes:
            errors.append(f"$.tips[{i}].reference_route: {ref!r} not in knowledge/routes.md "
                          "(non-example entries) - use null")
    if errors:
        raise SystemExit("Invalid tips file:\n  " + "\n  ".join(errors))

    known = catalogue_ids()
    for tip in data["tips"]:
        for ref in (tip.get("catalogue_id"), (tip.get("disagrees_with_catalogue") or {}).get("id")):
            if ref and ref not in known:
                print(f"warning: tip {tip['id']}: catalogue id {ref!r} not in knowledge/mistakes.md")

    analysis = json.loads(analysis_path.read_text())
    cv_tips = [x for x in analysis.get("tips", []) if x.get("source") != "coach"]
    coach = sorted(data["tips"], key=lambda x: x["severity_rank"])
    analysis["tips"] = [to_ui_tip(x) for x in coach] + cv_tips
    analysis_path.write_text(json.dumps(analysis, indent=2) + "\n")
    print(f"Imported {len(coach)} coach tip(s) into {analysis_path} (replaced earlier coach tips, kept "
          f"{len(cv_tips)} CV tips). Note: `rebuild-json` regenerates tips - re-run import-tips after it.")
