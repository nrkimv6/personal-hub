"""Services for slide scanner."""

from .mobile_delete import (
    cleanup_local_inbox_file,
    delete_remote_images,
    guard_remote_delete_paths,
    is_allowed_remote_path,
    mark_remote_delete_done,
    mark_remote_delete_failed,
    process_remote_delete_for_item,
)
from .mobile_handoff import handoff_item_to_slides
from .mobile_ingest import build_dedupe_key, register_ingested_items, resolve_captured_at
from .mobile_sync import (
    get_sync_status,
    list_connected_devices,
    list_remote_images,
    pull_images,
    run_sync_background,
    run_sync_once,
)
from .rectifier_client import rectifier_client

__all__ = [
    "build_dedupe_key",
    "cleanup_local_inbox_file",
    "delete_remote_images",
    "guard_remote_delete_paths",
    "get_sync_status",
    "handoff_item_to_slides",
    "is_allowed_remote_path",
    "list_connected_devices",
    "list_remote_images",
    "mark_remote_delete_done",
    "mark_remote_delete_failed",
    "pull_images",
    "process_remote_delete_for_item",
    "rectifier_client",
    "register_ingested_items",
    "resolve_captured_at",
    "run_sync_background",
    "run_sync_once",
]
