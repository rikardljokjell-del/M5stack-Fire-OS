"""Reviewed regression catalog and bounded factual repair evidence.

Raw diagnostics and generated code are never promoted into system instructions.
Source changes and early healthy receipts are observations, not proof of repair.
"""
import hashlib
import re
import zipfile
from difflib import SequenceMatcher


REGRESSION_CHECKS = {
    "audio_level":"Inspect primary channel gain255 under OS master, enable sound before playback tests, verify mute/stop and physically check audible output separately.",
    "rendering": "Exercise complete frames while waiting, paused and game-over; reject blank updates, clipped output and invalid clear order.",
    "bounds": "Exercise screen edges, empty/full collections, reset and extreme values; assert valid integer arguments and indices.",
    "nil": "Exercise initialization, empty/full data, collisions and repeated reset; never index absent state.",
    "budget": "Measure per-callback output/text/work, including cold first-frame grid cells and RGB calls; cap grid cells128 and RGB writes1, cache render inputs and inspect blocking native host calls. PC pass is not physical timing proof.",
    "api": "Check every call against negotiated signatures, dependencies and resource permissions, including aliases and operational errors.",
    "text": "Exercise longest labels and numeric values within text byte/footprint limits and supported glyphs.",
    "runtime": "Exercise all controls, restart, long sessions and interrupted operations; preserve requirements and inspect untested branches.",
    "design": "Check the actual drawing code for hierarchy, contrast, readable controls and coherent full-frame states.",
    "installation": "Retain immutable validated code; diagnose transfer, checksum and SD availability before retrying installation.",
}


def regression_evidence(category):
    return {
        "rule_id": "fire-regression-v1/" + category,
        "required_check": REGRESSION_CHECKS.get(category, REGRESSION_CHECKS["runtime"]),
        "root_cause_status": "classified_not_proven",
    }


def source_guard_eligible(provenance, package, message):
    # Shared fixture code is not physical evidence. User reports and known
    # firmware/transport faults must not poison unrelated new app projects.
    if provenance not in {"device_receipt", "device_diagnostic"} or package.get("mode") != "openai":
        return False
    text=message.casefold()
    if any(token in text for token in ("invalid lua source", "checksum", "download", "transport", "storage", "out of memory creating", "cannot create lua")):
        return False
    return bool(re.search(r"lua\s+(?:update|init|on_button)|callback.*budget|instruction.*budget|attempt to index|nil value|visual frame|text budget",text))


def source_from_archive(store, package):
    from .builds import verify_archive
    path=store.path("packages",package["id"],".zip")
    verify_archive(path,package["manifest"],package["archive_sha256"])
    with zipfile.ZipFile(path) as archive:
        return archive.read(f"apps/{package['manifest']['id']}/main.lua").decode("utf-8")


def source_delta(before,after,previous_validation=None,candidate_validation=None):
    """Bounded source-diff facts; does not infer semantic correctness."""
    old_lines,new_lines=before.splitlines(),after.splitlines()
    added,removed=0,0
    for kind,a,b,c,d in SequenceMatcher(None,old_lines,new_lines,autojunk=False).get_opcodes():
        if kind!="equal":removed+=b-a;added+=d-c
    def functions(source):
        # Names are metadata only and never injected as global instructions.
        pattern=r"(?:^|\n)\s*(?:local\s+)?function\s+([A-Za-z_][A-Za-z0-9_.:]*)\s*\("
        starts=list(re.finditer(pattern,source))
        return {m[1]:source[m.start():starts[i+1].start() if i+1<len(starts) else len(source)] for i,m in enumerate(starts)}
    before_functions,after_functions=functions(before),functions(after)
    changed=sorted(name for name in before_functions.keys()|after_functions.keys() if before_functions.get(name)!=after_functions.get(name))[:16]
    metric_names=("max_callback_operations","max_callback_display_work","max_callback_text_bytes","max_callback_grid_cells","max_callback_rgb_calls","app_memory_peak","max_io_calls","max_io_bytes")
    def metrics(validation):
        validation=validation or {}
        profiles=validation.get("profiles") or [validation]
        return {name:max(p[name] for p in profiles if isinstance(p.get(name),(int,float)))
                for name in metric_names if any(isinstance(p.get(name),(int,float)) for p in profiles)}
    return {
        "from_source_sha256":hashlib.sha256(before.encode()).hexdigest(),
        "candidate_source_sha256":hashlib.sha256(after.encode()).hexdigest(),
        "source_changed":before!=after,"lines_added":added,"lines_removed":removed,
        "changed_functions":changed,"function_detection":"source_diff_heuristic",
        "previous_metrics":metrics(previous_validation),"candidate_metrics":metrics(candidate_validation),
        "semantic_fix_verified":False,"physical_resolution_verified":False,
    }


def repair_delta(store, old, candidate):
    """Facts from immutable sources; does not infer semantic correctness."""
    return source_delta(source_from_archive(store,old),source_from_archive(store,candidate),
                        old.get("validation"),candidate.get("validation"))
