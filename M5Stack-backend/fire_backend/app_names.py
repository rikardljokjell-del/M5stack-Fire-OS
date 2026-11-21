"""Stable, short app folders; internal operation IDs are never user filenames."""
import re
import unicodedata


MAX_APP_ID = 24
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *("com"+str(n) for n in range(1, 10)), *("lpt"+str(n) for n in range(1, 10))}


def app_slug(name):
    value = name.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:MAX_APP_ID].rstrip("-") or "min-app"
    return value + "-app" if value in WINDOWS_RESERVED else value


def app_id_for(name, project, store):
    if project.get("app_id"):
        return project["app_id"]
    if project.get("latest_package"):
        # Existing SD paths are immutable. Never abandon old appdata by silently
        # renaming a previously deployed app during an ordinary update.
        return store.get("packages", project["latest_package"])["manifest"]["id"]
    used = set()
    for other in store.list("projects"):
        if other["id"] == project["id"] or other.get("owner_device_id") != project.get("owner_device_id"):
            continue
        if other.get("app_id"):
            used.add(other["app_id"])
        elif other.get("latest_package"):
            used.add(store.get("packages", other["latest_package"])["manifest"]["id"])
    base, candidate, number = app_slug(name), app_slug(name), 2
    while candidate in used:
        suffix = "-" + str(number)
        candidate = base[:MAX_APP_ID-len(suffix)].rstrip("-") + suffix
        number += 1
    return candidate
