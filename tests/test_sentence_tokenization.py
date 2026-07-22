from db.repo import Repo


def test_hyphenated_word_keeps_lowercase_u_umlaut():
    assert Repo._tokenize_sentence("Die EU-Führung entscheidet.") == [
        "Die",
        "EU-Führung",
        "entscheidet",
        ".",
    ]
