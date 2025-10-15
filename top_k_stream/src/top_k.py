from typing import Any
from queue import PriorityQueue
from threading import Lock


class TopK:
    def __init__(self, k: int):
        self.limit = k
        self.eleCount = {}
        self.time = 0
        self.lock = Lock()

    def add(self, element: Any) -> None:
        with self.lock:
            (currCount, _) = self.eleCount.get(element, (0, 0))
            self.eleCount[element] = (currCount + 1, self.time)
            self.time += 1

    def get_top_k(self):
        priorityQueue = PriorityQueue()
        eleList = []
        with self.lock:
            for ele in self.eleCount:
                count, time = self.eleCount[ele]
                eleList.append((count, time, ele))

        for toAdd in eleList:
            count, time, ele = toAdd
            priorityQueue.put((count, time, ele))
            if priorityQueue.qsize() > self.limit:
                priorityQueue.get()

        ans = []
        while priorityQueue.qsize() > 0:
            _, _, ele = priorityQueue.get()
            ans.append(ele)
        return ans
