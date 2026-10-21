"""Run app.main() under Streamlit's AppTest with a synthetic upload."""

from __future__ import annotations


def app_script():
    import os
    from pathlib import Path

    import streamlit as st

    import app

    class _Upload:
        name = "drawing.dxf"

        def __init__(self, path):
            self._data = Path(path).read_bytes()

        def getvalue(self):
            return self._data

    st.file_uploader = lambda *args, **kwargs: _Upload(os.environ["MEP_TEST_UPLOAD"])
    app.main()


def render_app(dxf_bytes: bytes, tmp_path, monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(streamlit, "file_uploader", streamlit.file_uploader)
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source_upload.dxf"
    source.write_bytes(dxf_bytes)
    monkeypatch.setenv("MEP_TEST_UPLOAD", str(source))
    app_test = AppTest.from_function(app_script, default_timeout=180)
    app_test.run()
    return app_test


def exceptions(app_test) -> list[str]:
    return [str(getattr(item, "value", item)) for item in app_test.exception]


def warning_texts(app_test) -> list[str]:
    return [str(item.value) for item in app_test.warning]


def dataframes(app_test) -> list:
    return [item.value for item in app_test.dataframe]
