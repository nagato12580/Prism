from backend.app.services.entity_resolution import (
    alias_keys_for_surface,
    normalize_entity_key,
)


def test_normalize_entity_key_compacts_latin_names():
    assert normalize_entity_key("Yanchao Tan") == "yanchaotan"
    assert normalize_entity_key(" yctan@fzu.edu.cn ") == "yctanfzueducn"


def test_alias_keys_for_latin_person_generates_name_orders():
    assert alias_keys_for_surface("Yanchao Tan", entity_type="person") == [
        "yanchaotan",
        "tanyanchao",
    ]


def test_alias_keys_for_chinese_surface_keeps_original_key():
    aliases = alias_keys_for_surface("谭谚超", entity_type="person")
    assert "谭谚超" in aliases


def test_alias_keys_preserve_order_without_duplicates():
    assert alias_keys_for_surface("Tan Tan", entity_type="person") == ["tantan"]


def test_alias_keys_for_non_person_two_word_surface_do_not_swap():
    assert alias_keys_for_surface("Open Viewer", entity_type="paper") == ["openviewer"]


def test_alias_keys_for_punctuation_separated_person_do_not_swap():
    assert alias_keys_for_surface("john@doe", entity_type="person") == ["johndoe"]
