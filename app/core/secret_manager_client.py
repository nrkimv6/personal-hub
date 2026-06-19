"""GCP Secret Manager client helper for app/core.

This module provides a thin wrapper around the ``google-cloud-secret-manager``
SDK. The SDK import is intentionally deferred to function scope (lazy import)
so that the module can be imported without the package installed as long as
``ENABLE_SECRET_MANAGER=false`` (default).

Usage::

    from app.core.secret_manager_client import get_secret

    value = get_secret("JWT_SECRET", project_id="my-gcp-project")
"""

from __future__ import annotations

import os


def get_secret(name: str, project_id: str) -> str:
    """Fetch the latest version of a secret from GCP Secret Manager.

    The function is gated by the ``ENABLE_SECRET_MANAGER`` environment
    variable.  When the variable is ``false`` (the default) this function
    raises :class:`RuntimeError` immediately — the SDK is never imported and
    no GCP call is made.

    Args:
        name: Secret name as stored in GCP Secret Manager (e.g.
            ``"JWT_SECRET"``).
        project_id: GCP project ID that owns the secret.

    Returns:
        The decoded secret string payload.

    Raises:
        RuntimeError: if ``ENABLE_SECRET_MANAGER`` env var is not ``"true"``.
        ImportError: if the ``google-cloud-secret-manager`` package is not
            installed when Secret Manager is enabled.
    """
    # Gate: cost-guard — skip SDK import entirely when disabled (default).
    # ENABLE_SECRET_MANAGER=false → RuntimeError, SDK never imported.
    if os.getenv("ENABLE_SECRET_MANAGER", "false").lower() != "true":
        raise RuntimeError(
            "Secret Manager disabled: ENABLE_SECRET_MANAGER is not true. "
            "Set ENABLE_SECRET_MANAGER=true to enable GCP Secret Manager reads."
        )

    # Lazy import — only executed when ENABLE_SECRET_MANAGER=true.
    try:
        from google.cloud import secretmanager  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "google-cloud-secret-manager 패키지 필요: "
            "pip install google-cloud-secret-manager"
        ) from exc

    client = secretmanager.SecretManagerServiceClient()
    name_path = f"projects/{project_id}/secrets/{name}/versions/latest"
    response = client.access_secret_version(name=name_path)
    return response.payload.data.decode("UTF-8")
