import json
import subprocess

import release_config

UPDATE = "/usr/libexec/armada/armada-update"
SELECT = "/usr/libexec/armada/armada-select-branch"
CHANNELS = ("stable", "beta", "preview")
REPOSITORY_CHANNELS = ("stable", "beta", "testing")
REPOSITORIES = ("ghcr.io/armada-os/armada", "ghcr.io/virtudude/armada")


def repository_channels(repository):
    """Raw channel tags for the exact update repository."""
    if repository in REPOSITORIES:
        return list(REPOSITORY_CHANNELS)
    try:
        config = release_config.load_release_config()
    except release_config.ReleaseConfigError:
        return []
    if repository != config.image_repository:
        return []
    return list(config.channels)


def visible_channel(channel):
    return "preview" if channel == "testing" else channel


def supported_channels(repository):
    """Steam-visible channels for the exact update repository."""
    channels = []
    for channel in repository_channels(repository):
        visible = visible_channel(channel)
        if visible in CHANNELS and visible not in channels:
            channels.append(visible)
    return channels


def command(arguments, timeout=15):
    try:
        return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError((error.stderr or "").strip() or str(error)) from error


def deployment(value):
    if not value:
        return None
    image = value.get("image") or {}
    ostree = value.get("ostree") or {}
    return {"version": image.get("version") or image.get("imageDigest") or ostree.get("checksum") or "Unknown version",
            "image": (image.get("image") or {}).get("image", ""),
            "checksum": ostree.get("checksum"), "serial": ostree.get("deploySerial"),
            "stateroot": ostree.get("stateroot"), "incompatible": bool(value.get("incompatible"))}


def snapshot():
    raw = json.loads(command(["/usr/bin/bootc", "status", "--format", "json"]))
    status = raw.get("status") or {}
    booted = deployment(status.get("booted"))
    if not booted or not booted["checksum"]:
        raise RuntimeError("No booted OSTree deployment is available")
    try:
        target = command(["/bin/bash", "-c", 'source /usr/lib/armada/update-lib; armada_update_target "$(armada_booted_ref)"'], timeout=60).strip().split()
    except (subprocess.SubprocessError, RuntimeError):
        target = []
    repository, channel = target if len(target) == 2 else ("", "")
    # A pinned development tag wins in armada_desired_channel, so a channel
    # switch would not change the update target.  Only offer channels that the
    # runtime would actually honor; the pinned tag stays fixed.
    switchable = channel in repository_channels(repository)
    if channel == "testing":
        channel = "preview"
    state = {"booted": booted, "rollback": deployment(status.get("rollback")),
             "staged": deployment(status.get("staged")), "rollback_queued": bool(status.get("rollbackQueued")),
             "channel": channel, "repository": repository,
             "channels": supported_channels(repository) if switchable else []}
    return state


def status():
    state = snapshot()
    state["reboot_ready"] = bool(state["rollback_queued"] or state["staged"])
    return state


def select_channel(channel):
    if channel not in CHANNELS:
        raise ValueError("Unknown update channel")
    if channel not in snapshot()["channels"]:
        raise RuntimeError("Channel selection is unavailable for this image")
    command([SELECT, channel])
    return {"ok": True}


def restart():
    if not status()["reboot_ready"]:
        raise RuntimeError("There is no pending OS change to restart into")
    command(["/usr/bin/systemctl", "reboot"])
    return {"ok": True}


def execute(operation, checksum=None):
    state = snapshot()
    if operation == "update":
        if not state["repository"] or not state["channel"]:
            raise RuntimeError("This deployment has no supported update target")
        subprocess.run([UPDATE], check=True)
        if not snapshot()["staged"]:
            return {"message": "No new image was needed."}
        return {"message": "Update installed. Restart to apply."}
    if operation != "rollback":
        raise ValueError("Unknown OS operation")
    target = state["rollback"]
    if not target or not target["checksum"] or target["incompatible"]:
        raise RuntimeError("No compatible previous deployment is available")
    if not checksum or checksum != target["checksum"]:
        raise RuntimeError("The rollback target changed. Refresh and confirm rollback again.")
    if not state["rollback_queued"]:
        print("Selecting the previous OS deployment", flush=True)
        subprocess.run(["/usr/bin/bootc", "rollback"], check=True)
    selected = snapshot()
    if not selected["rollback_queued"] or not selected["rollback"] or selected["rollback"]["checksum"] != checksum:
        raise RuntimeError("The expected rollback deployment was not selected")
    return {"message": "Rollback ready. Restart to apply."}
