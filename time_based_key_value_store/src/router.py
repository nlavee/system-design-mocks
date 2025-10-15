from src.time_based_key_value import TimeBasedKeyValue
from typing import List


class Router:
    def __init__(self, nodes: List[TimeBasedKeyValue]):
        self.nodes = nodes
        self.num_nodes = len(nodes)

    def _calculate_hash(self, key: str) -> int:
        return hash(key) % self.num_nodes

    def _get_node_for_key(self, key: str) -> TimeBasedKeyValue:
        nodeIdx = self._calculate_hash(key)
        return self.nodes[nodeIdx]

    def put(self, key: str, value: str, timestamp: int) -> None:
        node = self._get_node_for_key(key)
        node._sync_put(key, value, timestamp)

    def get(self, key: str, timestamp: int) -> str:
        node = self._get_node_for_key(key)
        return node.get(key, timestamp)
