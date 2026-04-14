from __future__ import annotations

from pathlib import Path


def test_frontend_tsconfig_extends_all_runtime_configs():
    tsconfig = Path("frontend/tsconfig.json").read_text(encoding="utf-8")

    assert '"./.svelte-kit/tsconfig.json"' in tsconfig
    assert '"./.svelte-kit-admin/tsconfig.json"' in tsconfig
    assert '"./.svelte-kit-public/tsconfig.json"' in tsconfig
