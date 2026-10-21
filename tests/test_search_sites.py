import json

from sniplens.search_sites import default_site, site_url
from sniplens.settings import DEFAULT_CLIPBOARD_SITES, SettingsStore

JPDB = {"id": "jpdb", "name": "JPDB", "url": "https://jpdb.io/search?q=<search_term>", "enabled": True}
TRAINCHINESE = {
    "id": "tc",
    "name": "TrainChinese",
    "url": "https://www.trainchinese.com/v2/search.php?searchWord=<search_term>",
    "enabled": True,
}


def test_default_site_prefers_the_chosen_site():
    assert default_site([JPDB, TRAINCHINESE], "tc") is TRAINCHINESE


def test_default_site_falls_back_to_the_first_enabled_site():
    disabled_tc = dict(TRAINCHINESE, enabled=False)
    assert default_site([disabled_tc, JPDB], "tc") is JPDB
    assert default_site([JPDB, TRAINCHINESE], "missing") is JPDB


def test_default_site_is_none_when_every_site_is_disabled():
    assert default_site([dict(JPDB, enabled=False)], "jpdb") is None


def test_site_url_encodes_the_copied_text():
    assert site_url(JPDB, "  骨 test\n") == "https://jpdb.io/search?q=%E9%AA%A8%20test"
    assert site_url(TRAINCHINESE, "骨") == "https://www.trainchinese.com/v2/search.php?searchWord=%E9%AA%A8"


def test_settings_default_to_jpdb(tmp_path):
    values = SettingsStore(tmp_path / "settings.json").load()
    assert values["auto_upload_enabled"] is True
    assert values["clipboard_sites"] == DEFAULT_CLIPBOARD_SITES
    assert values["default_clipboard_site_id"] == "jpdb"


def test_settings_carry_over_from_the_v4_fork(tmp_path):
    """The v4 fork wrote these keys to the same settings.json, in the same
    wrapped format, so an existing install keeps its sites and toggles."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "auto_upload_enabled": {"value": False, "description": "x"},
                "clipboard_sites": {"value": [JPDB, TRAINCHINESE], "description": "x"},
                "default_clipboard_site_id": {"value": "tc", "description": "x"},
                "tray_snip_token": "stale",
            }
        )
    )
    values = SettingsStore(path).load()
    assert values["auto_upload_enabled"] is False
    assert values["clipboard_sites"] == [JPDB, TRAINCHINESE]
    assert values["default_clipboard_site_id"] == "tc"


def test_invalid_site_lists_fall_back_to_the_default(tmp_path):
    path = tmp_path / "settings.json"
    for broken in ([], [{"name": "no url"}], "not a list"):
        path.write_text(json.dumps({"clipboard_sites": broken}))
        assert SettingsStore(path).load()["clipboard_sites"] == DEFAULT_CLIPBOARD_SITES


def test_site_list_round_trips(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save({"clipboard_sites": [JPDB, TRAINCHINESE], "default_clipboard_site_id": "tc"})
    values = store.load()
    assert values["clipboard_sites"] == [JPDB, TRAINCHINESE]
    assert values["default_clipboard_site_id"] == "tc"
