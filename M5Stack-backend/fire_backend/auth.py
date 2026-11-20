import hmac


def principal(settings, authorization):
    supplied = authorization or ""
    admin = settings.fire_backend_token.get_secret_value()
    if admin and hmac.compare_digest(supplied.encode(), ("Bearer " + admin).encode()):
        return "admin"
    for device_id, token in settings.device_tokens().items():
        if hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
            return device_id
    if not admin and not supplied and settings.fire_backend_host in {"127.0.0.1", "localhost", "::1"}:
        return "admin"
    raise PermissionError("Authentication required")


def authorize_project(store, project_id, identity):
    project = store.get("projects", project_id)
    if identity != "admin" and project.get("owner_device_id") != identity:
        raise PermissionError("Project belongs to another device")
    return project


def authorize_session(service, session_id, identity):
    session = service.session(session_id)
    if identity != "admin" and session.device_id != identity:
        raise PermissionError("Session belongs to another device")
    return session
