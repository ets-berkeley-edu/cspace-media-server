"""How the admin app names each kind (D151): "file" only when the kind isn't known."""
from serena.servable_list import KINDS, kind_word


def test_every_kind_has_a_word() -> None:
    assert {kind: kind_word(kind) for kind in KINDS} == {
        "image": "image", "card": "catalog card", "pdf": "PDF", "3D": "3D model", "audio": "audio file",
        "video": "video"}
    assert kind_word(None) == "file"
    assert kind_word("") == "file"
