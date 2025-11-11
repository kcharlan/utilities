import pytest
from src.converters.toon_conv import load_toon, dump_toon, ToonUnavailable

@pytest.fixture
def sample_data():
    return {"a": 1, "b": "test", "c": [1, "two", True]}

@pytest.fixture
def sample_toon_string():
    # The output of the custom dumper will have sorted keys
    return '  a: 1\n  b: "test"\n  c: [1, "two", true]'

def test_load_simple_toon():
    """Tests loading a simple key-value TOON string."""
    text = 'key1: "value1"\nkey2: 123\nkey3: true'
    expected = {"key1": "value1", "key2": 123, "key3": True}
    assert load_toon(text) == expected

def test_load_with_list():
    """Tests loading a TOON string with a list."""
    text = 'items: [1, "two", false, null]'
    expected = {"items": [1, "two", False, None]}
    assert load_toon(text) == expected

def test_dump_simple_dict(sample_data):
    """Tests dumping a simple dictionary to a TOON string."""
    expected_string = 'a: 1\nb: "test"\nc: [1, "two", true]'
    assert dump_toon(sample_data) == expected_string

def test_round_trip(sample_data):
    """Tests that dumping and then loading a dictionary preserves its data."""
    dumped = dump_toon(sample_data)
    reloaded = load_toon(dumped)
    assert reloaded == sample_data

def test_unsupported_dump_type():
    """Tests that dumping an unsupported type raises ToonUnavailable."""
    # The simple dumper only supports dicts at the top level.
    with pytest.raises(ToonUnavailable):
        dump_toon([1, 2, 3])

    # It also doesn't support complex types like sets.
    with pytest.raises(ToonUnavailable):
        dump_toon({"a": {1, 2, 3}})

def test_load_empty():
    """Tests loading an empty or whitespace string."""
    assert load_toon("") == {}
    assert load_toon(" \n ") == {}