from pathlib import Path


def test_v0_uses_russian_ui_labels_and_preserves_dxf_names():
    app_source = Path("app.py").read_text(encoding="utf-8")

    assert "MEP Метраж V0" in app_source
    assert "DXF yükle" not in app_source
    assert "Katman seç" not in app_source
    assert "П_Трубы" in app_source


def test_download_buttons_have_unique_explicit_keys():
    app_source = Path("app.py").read_text(encoding="utf-8")
    key_values = []
    for line in app_source.splitlines():
        if "st.download_button(" not in line:
            continue
        if "key=" not in line:
            continue
        key_text = line.split("key=")[1].split(",")[0].strip().strip('"\'')
        if key_text:
            key_values.append(key_text)

    assert len(key_values) == len(set(key_values))
