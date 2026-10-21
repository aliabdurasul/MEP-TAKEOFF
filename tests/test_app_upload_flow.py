"""Streamlit wiring: re-uploading a drawing with the same name shows the new total.

Set ``MEP_APP_DIR`` to a directory containing another ``app.py`` (for example the
version on ``main``) to run the same scenario against it.
"""

from __future__ import annotations

import pytest

from synthetic_dxf import INSUNITS_MM, add_line, new_doc, to_bytes

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _run_app():
    import os
    import sys
    from pathlib import Path

    import streamlit as st

    app_dir = os.environ.get("MEP_APP_DIR")
    if app_dir and app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    import app

    class _Upload:
        name = "plan.dxf"

        def __init__(self, path):
            self._data = Path(path).read_bytes()

        def getvalue(self):
            return self._data

    st.file_uploader = lambda *args, **kwargs: _Upload(os.environ["MEP_TEST_UPLOAD"])
    app.main()


def test_same_name_reupload_updates_displayed_total(tmp_path, monkeypatch, validation):
    """Streamlit app: a second plan.dxf with different geometry updates the displayed pipe total."""
    import streamlit

    monkeypatch.setattr(streamlit, "file_uploader", streamlit.file_uploader)
    monkeypatch.chdir(tmp_path)

    sources = {}
    for label, length_mm in (("a", 5000.0), ("b", 10000.0)):
        doc = new_doc(INSUNITS_MM)
        add_line(doc, (0, 0), (length_mm, 0))
        sources[label] = tmp_path / f"source_{label}.dxf"
        sources[label].write_bytes(to_bytes(doc))

    app_test = AppTest.from_function(_run_app, default_timeout=180)
    shown = []
    for label in ("a", "b"):
        monkeypatch.setenv("MEP_TEST_UPLOAD", str(sources[label]))
        app_test.run()
        if app_test.exception:
            shown.append("exception: " + "; ".join(str(getattr(item, "value", item)) for item in app_test.exception))
        elif app_test.metric:
            shown.append(app_test.metric[0].value)
        else:
            shown.append("no metric rendered")

    validation.equal(
        "UP-APP-01",
        "same-name re-upload shows new drawing total in the UI",
        expected=["5.00 m", "10.00 m"],
        actual=shown,
        basis="plan.dxf: LINE 5000 mm, then plan.dxf: LINE 10000 mm on П_Трубы, INSUNITS=4",
        kind="UPLOAD",
    )
