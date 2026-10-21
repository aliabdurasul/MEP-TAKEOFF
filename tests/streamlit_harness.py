"""Run app.main() under Streamlit's AppTest with a synthetic upload.

Environment variables read by the script:
  MEP_TEST_UPLOAD        path of the file to "upload"
  MEP_TEST_UPLOAD_NAME   file name reported by the uploader (default drawing.dxf)
  MEP_TEST_FAIL_EXPORT   when set, the Excel builder raises (export-failure tests)
"""

from __future__ import annotations


def app_script():
    import os
    from pathlib import Path

    import streamlit as st

    import app

    class _Upload:
        def __init__(self, path, name):
            self._data = Path(path).read_bytes()
            self.name = name

        def getvalue(self):
            return self._data

    if not hasattr(app, "_original_build_takeoff_excel"):
        app._original_build_takeoff_excel = app.build_takeoff_excel
    if os.environ.get("MEP_TEST_FAIL_EXPORT"):

        def _failing_export(**kwargs):
            raise RuntimeError("simulated Excel export failure")

        app.build_takeoff_excel = _failing_export
    else:
        app.build_takeoff_excel = app._original_build_takeoff_excel

    upload = _Upload(os.environ["MEP_TEST_UPLOAD"], os.environ.get("MEP_TEST_UPLOAD_NAME", "drawing.dxf"))
    st.file_uploader = lambda *args, **kwargs: upload
    app.main()


def render_app(dxf_bytes: bytes, tmp_path, monkeypatch, name: str = "drawing.dxf"):
    import streamlit
    from streamlit.testing.v1 import AppTest

    import app

    monkeypatch.setattr(streamlit, "file_uploader", streamlit.file_uploader)
    monkeypatch.setattr(app, "build_takeoff_excel", app.build_takeoff_excel)
    monkeypatch.chdir(tmp_path)
    app_test = AppTest.from_function(app_script, default_timeout=180)
    return rerun(app_test, dxf_bytes, tmp_path, monkeypatch, name=name)


def rerun(app_test, dxf_bytes: bytes, tmp_path, monkeypatch, name: str = "drawing.dxf", fail_export: bool = False):
    source = tmp_path / f"source_upload_{len(list(tmp_path.glob('source_upload_*')))}.bin"
    source.write_bytes(dxf_bytes)
    monkeypatch.setenv("MEP_TEST_UPLOAD", str(source))
    monkeypatch.setenv("MEP_TEST_UPLOAD_NAME", name)
    if fail_export:
        monkeypatch.setenv("MEP_TEST_FAIL_EXPORT", "1")
    else:
        monkeypatch.delenv("MEP_TEST_FAIL_EXPORT", raising=False)
    app_test.run()
    return app_test


def exceptions(app_test) -> list[str]:
    return [str(getattr(item, "value", item)) for item in app_test.exception]


def warning_texts(app_test) -> list[str]:
    return [str(item.value) for item in app_test.warning]


def error_texts(app_test) -> list[str]:
    return [str(item.value) for item in app_test.error]


def dataframes(app_test) -> list:
    return [item.value for item in app_test.dataframe]


def metric_values(app_test) -> list[str]:
    return [str(item.value) for item in app_test.metric]


def download_button_count(app_test) -> int:
    return len(app_test.get("download_button"))
