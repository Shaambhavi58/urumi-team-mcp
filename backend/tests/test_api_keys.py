from app.api_keys import create_api_key, hash_api_key


def test_api_key_is_random_and_hash_matches() -> None:
    raw_key, prefix, key_hash = create_api_key()
    another_raw_key, _, another_hash = create_api_key()

    assert raw_key.startswith("urumi_")
    assert prefix == raw_key[:14]
    assert hash_api_key(raw_key) == key_hash
    assert another_raw_key != raw_key
    assert another_hash != key_hash
