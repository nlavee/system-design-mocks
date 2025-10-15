import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

# autopep8: off
from src.top_k import TopK
# autopep8: on


@pytest.fixture
def topK():
    topK = TopK(2)
    yield topK


class TestTopKSteam:
    def test_top_k_init(self, topK):
        assert topK.limit == 2

    def test_top_k_int(self, topK):
        topK.add(1)
        topK.add(2)
        topK.add(1)
        # Returns [1, 2] because 1 appeared twice, 2 once.
        assert set(topK.get_top_k()) == set([1, 2])
        topK.add(3)
        topK.add(3)
        topK.add(3)
        # Returns [3, 1] because 3 appeared three times, 1 twice.
        assert set(topK.get_top_k()) == set([3, 1])

    def test_top_k_str(self, topK):
        topK.add("a")
        topK.add("b")
        topK.add("a")
        # Returns [1, 2] because 1 appeared twice, 2 once.
        assert set(topK.get_top_k()) == set(["a", "b"])
        topK.add("c")
        topK.add("c")
        topK.add("c")
        # Returns [3, 1] because 3 appeared three times, 1 twice.
        assert set(topK.get_top_k()) == set(["c", "a"])
