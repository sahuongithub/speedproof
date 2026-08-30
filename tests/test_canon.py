import pytest

from speedproof.verifyperf.canon import Unencodable, checksum, encode


def test_equal_values_hash_equally():
    assert checksum({"a": [1, 2, 3]}) == checksum({"a": [1, 2, 3]})


def test_mapping_order_does_not_matter():
    assert checksum({"a": 1, "b": 2}) == checksum({"b": 2, "a": 1})


def test_list_order_does_matter():
    assert checksum([1, 2]) != checksum([2, 1])


def test_length_prefixing_prevents_collisions():
    # Without length prefixes these two would encode to the same bytes.
    assert checksum(["ab", "c"]) != checksum(["a", "bc"])


def test_types_are_distinguished():
    assert checksum([1, 2]) != checksum((1, 2))
    assert checksum(1) != checksum(True)
    assert checksum(1) != checksum(1.0)


def test_a_liar_cannot_forge_equality():
    """An object whose __eq__ always returns True must not hash as its target."""

    class AlwaysEqual:
        def __eq__(self, other):
            return True

        def __hash__(self):
            return 0

    liar = AlwaysEqual()
    assert liar == 42  # the value under test lies to ordinary comparison
    with pytest.raises(Unencodable):
        encode(liar)  # but the harness refuses to encode it at all
