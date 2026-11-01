"""Load a local .gguf model through Hermes' managed llama.cpp runtime.

A single public function, :func:`load_local_model`, validates a .gguf on disk,
ensures the llama.cpp engine is installed (PM download when missing), sideloads
the model into the managed models directory, starts the supervised llama-server,
verifies the model is loaded and responsive, and returns the routing the CLI
needs (model id, provider, base_url, api_key).

Progress is printed to the user at every step so they understand what is
happening (and any error that occurs) instead of a silent hang.

The caller owns the returned runtime and must call :func:`shutdown_local_model`
when the CLI process exits so the server is torn down with it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from hermes_cli.local_runtime import binaries, bootstrap
from hermes_cli.local_runtime.gguf import model_id_from_stem
from hermes_cli.local_runtime.endpoint import LLAMACPP_ALIASES

logger = logging.getLogger(__name__)

# One loader per process: the managed server is process-global, so a second
# local-model request in the same process reuses the running server.
_LOADER_LOCK = threading.Lock()
_ACTIVE_MODEL_ID: Optional[str] = None
_ACTIVE_BASE_URL: Optional[str] = None
_ACTIVE_API_KEY: Optional[str] = None

# Seconds to wait for the staged model to appear in the router's model list
# after a refresh (the router only scans the models dir at spawn/refresh).
_MODEL_APPEAR_WAIT_S = 20.0
# Seconds to allow for a model load + touch generation before giving up.
_MODEL_READY_WAIT_S = 600.0
# How long to keep waiting for a booting server before declaring failure.
_SERVER_BOOT_WAIT_S = 60.0


def _models_dir() -> Path:
    return bootstrap.models_dir()


def _is_gguf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".gguf"


def _print(msg: str) -> None:
    """Print a user-visible progress line (never raises)."""
    try:
        print(msg)
    except Exception:
        pass


def _sideload(src: Path) -> Path:
    """Copy (hardlink when possible) ``src`` into the managed models dir; return the dest."""
    dest = _models_dir() / src.name
    _models_dir().mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    try:
        os.link(src, dest)
    except OSError:
        try:
            os.symlink(src, dest)
        except OSError:
            shutil.copyfile(src, dest)
    return dest


def _server_models(base_url: str, api_key: str, timeout_s: float = 5.0) -> dict:
    """Return {model_id: status} from the llama-server GET /models endpoint."""
    headers = {"Authorization": f"Bearer {api_key}"}
    req = urllib.request.Request(
        base_url.rsplit("/v1", 1)[0] + "/models", headers=headers
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        data = json.loads(r.read() or b"{}")
    return {
        m.get("id"): m.get("status", {}).get("value", "unknown")
        for m in data.get("data", [])
    }


def _wait_for_model(sup, model_id: str, wait_s: float) -> bool:
    """Poll the supervisor's model list until ``model_id`` is present."""
    deadline = time.monotonic() + wait_s
    last_status = None
    while time.monotonic() < deadline:
        try:
            statuses = sup.models(timeout_s=5)
        except Exception:
            statuses = {}
        status = statuses.get(model_id)
        if status is not None:
            if status != last_status:
                logger.info("model %s appeared in router (status=%s)", model_id, status)
                _print(f"  [local-model] router sees model: {model_id} (status: {status})")
                last_status = status
            if status in ("loaded", "ready", "loading", "sleeping"):
                return True
        time.sleep(1)
    return False


def _ensure_model_ready(sup, model_id: str, wait_s: float) -> bool:
    """Load ``model_id`` if needed and prove readiness with a touch generation."""
    _print(f"  [local-model] loading model {model_id} into memory ...")
    try:
        return sup.ensure_model_ready(model_id, timeout_s=int(wait_s))
    except Exception as exc:
        logger.warning("model %s failed readiness check: %s", model_id, exc)
        return False


def _wait_for_server(sup, wait_s: float) -> bool:
    """Wait until the supervisor's server is healthy (GET /health returns 200)."""
    _print(f"  [local-model] waiting for llama-server to become healthy ...")
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(sup._url("/health"), timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def load_local_model(model_path: str) -> Optional[dict]:
    """Prepare a local .gguf for use as the CLI's model.

    Returns a dict with ``model``, ``provider`` (``"llamacpp"``), ``base_url``,
    ``api_key``, and ``requested_provider`` keys — or None on failure (logged
    and printed to the user).

    Steps:
      1. Validate the file exists and ends in ``.gguf``.
      2. Ensure the PM-pinned llama.cpp engine is installed (downloads it when missing).
      3. Sideload the GGUF into the managed models directory.
      4. Start (or adopt) the supervised llama-server, waiting for it to boot.
      5. Refresh the router so it sees the staged model.
      6. Wait for the model to appear, load it, and run a touch generation to
         prove it is responsive before returning routing.

    The returned runtime's ``base_url``/``api_key`` point at the managed server.
    Call :func:`shutdown_local_model` when done so the server stops with the CLI.
    """
    global _ACTIVE_MODEL_ID, _ACTIVE_BASE_URL, _ACTIVE_API_KEY

    with _LOADER_LOCK:
        if _ACTIVE_MODEL_ID is not None:
            logger.debug("local model already loaded: %s", _ACTIVE_MODEL_ID)
            return {
                "model": _ACTIVE_MODEL_ID,
                "provider": "llamacpp",
                "requested_provider": "llamacpp",
                "base_url": _ACTIVE_BASE_URL,
                "api_key": _ACTIVE_API_KEY or "no-key-required",
                "source": "local-model",
            }

        src = Path(model_path).expanduser().resolve()
        if not src.is_file():
            _print(f"  [local-model] ✗ file not found: {src}")
            logger.warning("local model file not found: %s", src)
            return None
        if src.suffix.lower() != ".gguf":
            _print(f"  [local-model] ✗ not a .gguf file: {src}")
            logger.warning("local model is not a .gguf file: %s", src)
            return None

        model_id = model_id_from_stem(src.stem)
        _print(f"  [local-model] preparing local model: {model_id}")
        _print(f"  [local-model] source file: {src}")

        # ── 1. Ensure the llama.cpp engine is installed ──
        backend = binaries.select_backend(None)
        try:
            engine = binaries.installed_engine(backend)
            if engine is None:
                _print(f"  [local-model] llama.cpp engine ({backend}) not installed; downloading ...")
                logger.info("llama.cpp engine not installed; downloading %s backend", backend)
                engine = binaries.ensure_engine(backend)
            else:
                _print(f"  [local-model] llama.cpp engine b{engine.tag} ({engine.backend}) already installed")
        except Exception as exc:
            msg = f"  [local-model] ✗ could not obtain llama.cpp engine: {exc}"
            _print(msg)
            logger.warning("could not obtain llama.cpp engine: %s", exc)
            return None
        if engine is None:
            _print("  [local-model] ✗ llama.cpp engine unavailable after install attempt")
            logger.warning("llama.cpp engine unavailable after install attempt")
            return None

        # ── 2. Sideload the GGUF into the managed models dir ──
        try:
            dest = _sideload(src)
        except Exception as exc:
            msg = f"  [local-model] ✗ could not stage model: {exc}"
            _print(msg)
            logger.warning("could not stage local model %s: %s", src, exc)
            return None
        _print(f"  [local-model] staged model: {dest.name} -> {dest}")

        # ── 3. Start / adopt the managed runtime ──
        from hermes_cli.config import load_config

        config = load_config()
        section = config.setdefault("local_runtime", {})
        section["enabled"] = True
        section["backend"] = backend

        _print("  [local-model] starting supervised llama-server ...")
        try:
            sup = bootstrap.ensure_local_runtime(config, force=True)
        except Exception as exc:
            msg = f"  [local-model] ✗ could not start llama-server: {exc}"
            _print(msg)
            logger.warning("could not start local llama-server: %s", exc)
            return None

        owns_server = False
        if sup is not None:
            base_url = sup.base_url.rsplit("/v1", 1)[0]
            api_key = sup.api_key
            owns_server = True
            # Wait for the server to become healthy (first boot can take a while).
            if not _wait_for_server(sup, _SERVER_BOOT_WAIT_S):
                _print("  [local-model] ✗ llama-server did not become healthy in time")
                logger.warning("llama-server did not become healthy within %ss", _SERVER_BOOT_WAIT_S)
                return None
            _print("  [local-model] llama-server is healthy")
        else:
            # Another process may already be serving; resolve its endpoint.
            from hermes_cli.local_runtime.endpoint import resolve_llamacpp_endpoint

            endpoint = resolve_llamacpp_endpoint(config=config, wait_for_boot_s=10.0)
            if endpoint is None:
                _print(
                    "  [local-model] ✗ llama-server is not running and could not be started. "
                    "Try again in a moment, or enable Local models in Settings → Providers."
                )
                logger.warning(
                    "local llama-server is not running and could not be started"
                )
                return None
            base_url = endpoint["base_url"].rsplit("/v1", 1)[0]
            api_key = endpoint.get("api_key", "") or "no-key-required"
            _print("  [local-model] adopting existing llama-server")

        # ── 4. Refresh the router so it sees the newly sideloaded model ──
        # The router only scans the models directory at spawn/refresh; a file
        # added while running is invisible until a bounce.
        _print("  [local-model] refreshing router model list ...")
        try:
            bootstrap.refresh_local_runtime()
        except Exception:
            logger.debug("runtime refresh after sideload skipped", exc_info=True)

        # When we own the server, re-resolve the supervisor after refresh (it may
        # have bounced and restarted).
        if owns_server:
            sup = bootstrap.get_supervisor()
            if sup is None:
                _print("  [local-model] ✗ llama-server supervisor disappeared after refresh")
                logger.warning("llama-server supervisor disappeared after refresh")
                return None

        # ── 5. Wait for the model to appear in the router's model list ──
        _print(f"  [local-model] waiting for router to register model: {model_id} ...")
        if owns_server:
            appeared = _wait_for_model(sup, model_id, _MODEL_APPEAR_WAIT_S)
        else:
            # Foreign server: poll its HTTP /models endpoint instead.
            appeared = False
            deadline = time.monotonic() + _MODEL_APPEAR_WAIT_S
            while time.monotonic() < deadline:
                try:
                    statuses = _server_models(base_url, api_key)
                except Exception:
                    statuses = {}
                if model_id in statuses:
                    appeared = True
                    logger.info(
                        "model %s appeared in foreign router (status=%s)",
                        model_id,
                        statuses.get(model_id),
                    )
                    _print(
                        f"  [local-model] router sees model: {model_id} "
                        f"(status: {statuses.get(model_id)})"
                    )
                    break
                time.sleep(1)
        if not appeared:
            _print(
                f"  [local-model] ✗ model {model_id} did not appear in the "
                f"llama-server model list after {_MODEL_APPEAR_WAIT_S:.0f}s"
            )
            logger.warning(
                "model %s did not appear in the llama-server model list after %.0fs; "
                "staged file: %s",
                model_id,
                _MODEL_APPEAR_WAIT_S,
                dest.name,
            )
            return None

        # ── 6. Load the model and prove readiness with a touch generation ──
        if owns_server:
            ready = _ensure_model_ready(sup, model_id, _MODEL_READY_WAIT_S)
        else:
            # Foreign server: the model autoloads on first request; just confirm
            # it shows as loadable/ready in the list.
            try:
                statuses = _server_models(base_url, api_key, timeout_s=10)
                ready = statuses.get(model_id) in ("loaded", "ready", "sleeping")
            except Exception:
                ready = False
        if not ready:
            _print(f"  [local-model] ✗ model {model_id} failed to become ready")
            logger.warning("model %s failed to become ready in the llama-server", model_id)
            return None

        _ACTIVE_MODEL_ID = model_id
        _ACTIVE_BASE_URL = base_url
        _ACTIVE_API_KEY = api_key

        _print(
            f"  [local-model] ✓ ready: {model_id} -> {base_url} "
            f"(engine b{engine.tag} {engine.backend})"
        )
        logger.info(
            "local model loaded and ready: %s (%s) -> %s (engine b%s %s)",
            model_id, dest.name, base_url, engine.tag, engine.backend,
        )
        return {
            "model": model_id,
            "provider": "llamacpp",
            "requested_provider": "llamacpp",
            "base_url": base_url,
            "api_key": api_key,
            "source": "local-model",
        }


def shutdown_local_model() -> None:
    """Stop the managed llama-server if this process started it.

    Idempotent and safe to call multiple times; only the process that owns
    the supervisor stops it. Other processes' servers are left running.
    """
    global _ACTIVE_MODEL_ID, _ACTIVE_BASE_URL, _ACTIVE_API_KEY

    with _LOADER_LOCK:
        if _ACTIVE_MODEL_ID is None:
            return
        _ACTIVE_MODEL_ID = None
        _ACTIVE_BASE_URL = None
        _ACTIVE_API_KEY = None

    try:
        bootstrap.shutdown_local_runtime()
    except Exception:
        logger.debug("local runtime shutdown skipped", exc_info=True)


def active_local_model() -> Optional[dict]:
    """The currently active local-model runtime, or None."""
    with _LOADER_LOCK:
        if _ACTIVE_MODEL_ID is None:
            return None
        return {
            "model": _ACTIVE_MODEL_ID,
            "provider": "llamacpp",
            "requested_provider": "llamacpp",
            "base_url": _ACTIVE_BASE_URL,
            "api_key": _ACTIVE_API_KEY or "no-key-required",
            "source": "local-model",
        }
