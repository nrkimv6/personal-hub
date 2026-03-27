import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from unittest.mock import MagicMock

def test_set_get_wf_manager_R():
    import _dr_state as m
    mock = MagicMock()
    m.set_wf_manager(mock)
    assert m.get_wf_manager() is mock
    m.set_wf_manager(None)

def test_wf_manager_default_none_R():
    import _dr_state as m
    m.set_wf_manager(None)
    assert m.get_wf_manager() is None
