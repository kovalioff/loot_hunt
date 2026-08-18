from loot_hunt.pepper.categories import Category, category_from_group


def test_current_group_state_contract():
    raw = {
        "threadGroupId": "131",
        "threadGroupName": "Elektronika",
        "threadGroupUrlName": "elektronika",
        "children": [
            {
                "threadGroupId": "221",
                "threadGroupName": "Telefony i smartfony",
                "threadGroupUrlName": "telefony-i-smartfony",
            }
        ],
    }
    parent = category_from_group(
        raw,
        fallback=Category("electronics", "Электроника", "/grupa/elektronika", "💻"),
    )
    assert parent.key == "electronics" and parent.name == "Электроника"
    assert parent.children[0].key == "221"
    assert parent.children[0].path == "/grupa/telefony-i-smartfony"
