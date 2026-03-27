"""
Interview Practice Problems — Test-Driven Template
==================================================
Implement the core logic for each problem. Run the file to verify
your solutions against the built-in assertions.
"""

from collections import defaultdict, Counter, deque
from typing import List, Dict, Tuple, Optional
import heapq
import itertools


# ===========================================================================
# PROBLEM 1 — Agent conversation stats
# ===========================================================================

CONVERSATIONS_1 = [
    {"conversation_id": "c1", "customer_id": "alice", "resolved": True,  "duration_sec": 120, "agent_id": "a1"},
    {"conversation_id": "c2", "customer_id": "alice", "resolved": False, "duration_sec": 300, "agent_id": "a2"},
    {"conversation_id": "c3", "customer_id": "bob",   "resolved": True,  "duration_sec": 60,  "agent_id": "a1"},
    {"conversation_id": "c4", "customer_id": "alice", "resolved": True,  "duration_sec": 90,  "agent_id": "a1"},
    {"conversation_id": "c5", "customer_id": "bob",   "resolved": False, "duration_sec": 200, "agent_id": "a2"},
    {"conversation_id": "c6", "customer_id": "carol", "resolved": False, "duration_sec": 400, "agent_id": "a1"},
]

def problem1_part1(conversations: List[Dict]) -> Dict:
    """
    Return a summary dict keyed by customer_id.
    Values: {"total": int, "resolution_rate": float, "avg_duration": float}
    """
    summary_dict = {}
    for convo in conversations:
        customer_id = convo["customer_id"]
        if customer_id not in summary_dict:
            summary_dict[customer_id] = {
                    "total": 0.0,
                    "total_resolved": 0,
                    "total_duration": 0.0
                    }

        summary_dict[customer_id]["total"] += 1
        summary_dict[customer_id]["total_resolved"] += 1 if convo["resolved"] else 0.0
        summary_dict[customer_id]["total_duration"] += convo["duration_sec"]

    for customer in summary_dict:
        summary = summary_dict[customer]
        summary["resolution_rate"] = summary["total_resolved"] / summary["total"]
        summary["avg_duration"] = summary["total_duration"] / summary["total"]
        del summary["total_resolved"]
        del summary["total_duration"]

    return summary_dict


def problem1_part2(conversations: List[Dict]) -> Optional[str]:
    """
    Which customer_id had the highest TOTAL time spent in UNRESOLVED conversations?
    Tie-break: alphabetical.
    """
    unresolved_time = defaultdict(int)
    for convo in conversations:
        customer_id = convo["customer_id"]
        unresolved_time[customer_id] += 0 if convo["resolved"] else convo["duration_sec"]

    total_time = []
    for customer in unresolved_time:
        total_time.append((unresolved_time[customer], customer))

    total_time.sort(key=lambda x: (-x[0], x[1]))
    return total_time[0][1] if total_time else None


def problem1_part3(conversations: List[Dict], min_convos: int = 3, max_rate: float = 0.5) -> List[str]:
    """
    Return sorted list of customer_ids where total >= min_convos AND rate < max_rate.
    """
    summary_dict = problem1_part1(conversations) 
    customers = []
    for customer in summary_dict:
        if summary_dict[customer]["resolution_rate"] < max_rate and summary_dict[customer]["total"] >= min_convos:
            customers.append(customer)

    customers.sort()
    return customers


class ConversationStream1:
    """
    Streaming version: ingest records one-by-one and maintain O(1) summary access.
    """
    def __init__(self):
        self._summaries = {}

    def ingest(self, conversation: dict) -> None:
        c_id = conversation["customer_id"]
        if c_id not in self._summaries:
            self._summaries[c_id] = {"total": 0, "total_resolved": 0, "total_duration": 0.0}
        
        self._summaries[c_id]["total"] += 1
        if conversation.get("resolved"):
            self._summaries[c_id]["total_resolved"] += 1
        self._summaries[c_id]["total_duration"] += conversation.get("duration_sec", 0.0)

    def get_summary(self, customer_id: str) -> Optional[Dict]:
        if customer_id not in self._summaries:
            return None
        st = self._summaries[customer_id]
        if st["total"] == 0:
            return None
        return {
            "total": st["total"],
            "resolution_rate": st["total_resolved"] / st["total"],
            "avg_duration": st["total_duration"] / st["total"]
        }


def test_problem1():
    print("Testing Problem 1...")
    summary = problem1_part1(CONVERSATIONS_1)
    if summary is None: return
    assert summary["alice"]["total"] == 3
    assert abs(summary["alice"]["resolution_rate"] - 0.66666) < 0.001
    assert summary["alice"]["avg_duration"] == 170.0
    assert problem1_part1([]) == {}

    worst = problem1_part2(CONVERSATIONS_1)
    assert worst == "carol"  # carol: 400s, alice: 300s, bob: 200s
    assert problem1_part2([]) == None

    flagged = problem1_part3(CONVERSATIONS_1, min_convos=3, max_rate=0.7)
    assert flagged == ["alice"]

    stream = ConversationStream1()
    for c in CONVERSATIONS_1: stream.ingest(c)
    s = stream.get_summary("alice")
    assert s and s["total"] == 3
    print("Problem 1: PASSED")


# ===========================================================================
# PROBLEM 2 — Top-K failing topics
# ===========================================================================

CONVERSATIONS_2 = [
    {"topic": "billing/refund",   "escalated": True},
    {"topic": "billing/refund",   "escalated": True},
    {"topic": "billing/refund",   "escalated": False},
    {"topic": "billing/dispute",  "escalated": True},
    {"topic": "billing/dispute",  "escalated": False},
    {"topic": "shipping/delay",   "escalated": True},
    {"topic": "shipping/delay",   "escalated": True},
    {"topic": "shipping/delay",   "escalated": True},
    {"topic": "shipping/lost",    "escalated": False},
    {"topic": "account/login",    "escalated": False},
    {"topic": "account/login",    "escalated": False},
    {"topic": "account/password", "escalated": True},
]

def problem2_part1(conversations: List[Dict], k: int) -> List[str]:
    """Top K topics by raw escalation COUNT. Tie-break: alphabetical."""
    counts = defaultdict(int)
    for c in conversations:
        if c["escalated"]:
            counts[c["topic"]] += 1
    
    sorted_topics = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [t[0] for t in sorted_topics][:k]

def problem2_part2(conversations: List[Dict], k: int, min_count: int = 2) -> List[str]:
    """Top K topics by ESCALATION RATE. min_total >= min_count."""
    totals = defaultdict(int)
    escalations = defaultdict(int)
    for c in conversations:
        totals[c["topic"]] += 1
        if c["escalated"]:
            escalations[c["topic"]] += 1

    rates = []
    for t, tot in totals.items():
        if tot >= min_count:
            rate = escalations[t] / tot
            rates.append((rate, t))
            
    rates.sort(key=lambda x: (-x[0], x[1]))
    return [t[1] for t in rates][:k]

def problem2_part4(conversations: List[Dict]) -> Dict[str, Dict]:
    """Roll up stats to the parent level (e.g. 'billing/refund' -> 'billing')."""
    rollup = defaultdict(lambda: {"total": 0, "escalated": 0})
    for c in conversations:
        parent = c["topic"].split("/")[0]
        rollup[parent]["total"] += 1
        if c["escalated"]:
            rollup[parent]["escalated"] += 1
    return dict(rollup)

def test_problem2():
    print("Testing Problem 2...")
    top3 = problem2_part1(CONVERSATIONS_2, 3)
    assert top3 == ["shipping/delay", "billing/refund", "account/password"]
    
    top3_rate = problem2_part2(CONVERSATIONS_2, 3, min_count=2)
    assert top3_rate == ["shipping/delay", "billing/refund", "billing/dispute"]
    
    rollup = problem2_part4(CONVERSATIONS_2)
    if rollup:
        assert rollup["billing"]["total"] == 5
        assert rollup["billing"]["escalated"] == 3
    print("Problem 2: PASSED")


# ===========================================================================
# PROBLEM 3 — Sliding window resolution rate
# ===========================================================================

CONVERSATIONS_3 = [
    {"conversation_id": "c1",  "timestamp": 1000,  "resolved": True},
    {"conversation_id": "c2",  "timestamp": 1200,  "resolved": True},
    {"conversation_id": "c3",  "timestamp": 2000,  "resolved": False},
    {"conversation_id": "c4",  "timestamp": 3500,  "resolved": True},
    {"conversation_id": "c5",  "timestamp": 4700,  "resolved": False},
    {"conversation_id": "c6",  "timestamp": 5100,  "resolved": True},
    {"conversation_id": "c7",  "timestamp": 5200,  "resolved": False},
    {"conversation_id": "c8",  "timestamp": 7000,  "resolved": True},
    {"conversation_id": "c9",  "timestamp": 8000,  "resolved": True},
    {"conversation_id": "c10", "timestamp": 9000,  "resolved": False},
]
WINDOW_SEC = 3600

def problem3_part1(conversations: List[Dict], window_sec: int) -> List[Dict]:
    """Rate over the PRECEDING window_sec for each conversation."""
    convos = sorted(conversations, key=lambda x: x["timestamp"])
    res = []
    
    for i, c in enumerate(convos):
        t = c["timestamp"]
        count = 0
        resolved_count = 0
        for j in range(i - 1, -1, -1):
            if convos[j]["timestamp"] <= t - window_sec:
                break
            count += 1
            if convos[j]["resolved"]:
                resolved_count += 1
        
        c_copy = c.copy()
        if count == 0:
            c_copy["window_rate"] = None
        else:
            c_copy["window_rate"] = resolved_count / count
        res.append(c_copy)
    return res

def problem3_part3(conversations: List[Dict], window_sec: int) -> Tuple[int, int, float]:
    """Find the contiguous window_sec window with the LOWEST resolution rate."""
    if not conversations:
        return None
        
    convos = sorted(conversations, key=lambda x: x["timestamp"])
    min_rate = float('inf')
    best_window = None
    
    for c in convos:
        start_t = c["timestamp"]
        end_t = start_t + window_sec
        count = 0
        res_count = 0
        for other in convos:
            if start_t <= other["timestamp"] <= end_t:
                count += 1
                if other["resolved"]:
                    res_count += 1
            elif other["timestamp"] > end_t:
                break
        
        if count > 0:
            rate = res_count / count
            if rate < min_rate:
                min_rate = rate
                best_window = (start_t, end_t, rate)
            
    return best_window

def test_problem3():
    print("Testing Problem 3...")
    rates = problem3_part1(CONVERSATIONS_3, WINDOW_SEC)
    if rates:
        assert rates[0]["window_rate"] == None
        assert rates[1]["window_rate"] == 1.0
        assert abs(rates[3]["window_rate"] - 0.66666) < 0.001
        
    worst = problem3_part3(CONVERSATIONS_3, WINDOW_SEC)
    if worst:
        assert worst[2] == 0.0
        assert worst[0] == 9000
    print("Problem 3: PASSED")


# ===========================================================================
# PROBLEM 4 — ConversationStore (OOP)
# ===========================================================================

CONVERSATIONS_4 = [
    {"conversation_id": "c1", "customer_id": "alice", "resolved": True,  "duration_sec": 120, "timestamp": 1000},
    {"conversation_id": "c2", "customer_id": "alice", "resolved": False, "duration_sec": 300, "timestamp": 2000},
    {"conversation_id": "c3", "customer_id": "bob",   "resolved": False, "duration_sec": 60,  "timestamp": 1500},
    {"conversation_id": "c4", "customer_id": "alice", "resolved": True,  "duration_sec": 90,  "timestamp": 3000},
    {"conversation_id": "c5", "customer_id": "bob",   "resolved": False, "duration_sec": 200, "timestamp": 4000},
    {"conversation_id": "c6", "customer_id": "carol", "resolved": False, "duration_sec": 400, "timestamp": 2500},
    {"conversation_id": "c7", "customer_id": "carol", "resolved": False, "duration_sec": 350, "timestamp": 5000},
]

class ConversationStore:
    def __init__(self):
        self.convos = {}
        self.by_customer = defaultdict(list)

    def add(self, conversation: dict) -> None:
        c_id = conversation["conversation_id"]
        self.convos[c_id] = conversation.copy()
        self.by_customer[conversation["customer_id"]].append(c_id)

    def get_stats(self, customer_id: str) -> Optional[Dict]:
        if customer_id not in self.by_customer or not self.by_customer[customer_id]:
            return None
        
        tot = 0
        res = 0
        for c_id in self.by_customer[customer_id]:
            c = self.convos.get(c_id)
            if c:
                tot += 1
                if c["resolved"]:
                    res += 1
        if tot == 0:
            return None
            
        return {"total": tot, "resolution_rate": res / tot}

    def get_top_customers(self, k: int) -> List[str]:
        """K customers with most UNRESOLVED conversations."""
        unres = defaultdict(int)
        for c_id, c in self.convos.items():
            if not c.get("resolved"):
                unres[c["customer_id"]] += 1
        
        sorted_custs = sorted(unres.items(), key=lambda x: (-x[1], x[0]))
        return [c[0] for c in sorted_custs][:k]

    def get_stats_since(self, customer_id: str, since_timestamp: int) -> Optional[Dict]:
        if customer_id not in self.by_customer or not self.by_customer[customer_id]:
            return None
            
        tot = 0
        res = 0
        for c_id in self.by_customer[customer_id]:
            c = self.convos.get(c_id)
            if c and c["timestamp"] >= since_timestamp:
                tot += 1
                if c["resolved"]:
                    res += 1
        if tot == 0:
            return None
        return {"total": tot, "resolution_rate": res / tot}

    def remove(self, conversation_id: str) -> bool:
        if conversation_id in self.convos:
            c = self.convos.pop(conversation_id)
            self.by_customer[c["customer_id"]].remove(conversation_id)
            return True
        return False

def test_problem4():
    print("Testing Problem 4...")
    store = ConversationStore()
    for c in CONVERSATIONS_4: store.add(c)
    
    s = store.get_stats("alice")
    if s: assert s["total"] == 3
    
    top2 = store.get_top_customers(2)
    assert top2 == ["bob", "carol"]
    
    alice_since = store.get_stats_since("alice", 2500)
    if alice_since: assert alice_since["total"] == 1
    
    store.remove("c2")
    s_after = store.get_stats("alice")
    if s_after: assert s_after["total"] == 2 and s_after["resolution_rate"] == 1.0
    print("Problem 4: PASSED")


# ===========================================================================
# PROBLEM 5 — LLM tool call log analyzer
# ===========================================================================

TURNS = [
    {"conversation_id": "conv1", "turn_index": 0, "tool_calls": ["lookup_order", "check_policy"],           "latency_ms": 320},
    {"conversation_id": "conv1", "turn_index": 1, "tool_calls": ["lookup_order", "send_email"],             "latency_ms": 210},
    {"conversation_id": "conv1", "turn_index": 2, "tool_calls": ["check_policy", "send_email"],             "latency_ms": 180},
    {"conversation_id": "conv2", "turn_index": 0, "tool_calls": ["lookup_order", "check_policy"],           "latency_ms": 400},
    {"conversation_id": "conv2", "turn_index": 1, "tool_calls": ["escalate"],                               "latency_ms": 50},
    {"conversation_id": "conv3", "turn_index": 0, "tool_calls": ["check_balance"],                          "latency_ms": 100},
    {"conversation_id": "conv3", "turn_index": 1, "tool_calls": ["check_balance"],                          "latency_ms": 110},
    {"conversation_id": "conv3", "turn_index": 2, "tool_calls": ["check_balance"],                          "latency_ms": 105},
    {"conversation_id": "conv3", "turn_index": 3, "tool_calls": ["check_balance"],                          "latency_ms": 98},
    {"conversation_id": "conv4", "turn_index": 0, "tool_calls": ["lookup_order", "check_policy"],           "latency_ms": 290},
    {"conversation_id": "conv4", "turn_index": 1, "tool_calls": ["check_policy", "send_email", "escalate"], "latency_ms": 500},
]

def problem5_part1(turns: List[Dict]) -> Tuple[str, str, int]:
    """Most frequently co-occurring PAIR of tool calls in a single turn."""
    pair_counts = defaultdict(int)
    for t in turns:
        calls = t.get("tool_calls", [])
        calls = sorted(list(set(calls)))
        for i in range(len(calls)):
            for j in range(i + 1, len(calls)):
                pair_counts[(calls[i], calls[j])] += 1
                
    if not pair_counts:
        return None
        
    sorted_pairs = sorted(pair_counts.items(), key=lambda x: (-x[1], x[0][0], x[0][1]))
    best_pair, count = sorted_pairs[0]
    return (best_pair[0], best_pair[1], count)

def problem5_part3(turns: List[Dict], repeat_threshold: int = 3) -> List[str]:
    """Convos where SAME tool was called repeat_threshold+ times in a row."""
    conv_calls = defaultdict(list)
    for t in sorted(turns, key=lambda x: x["turn_index"]):
        conv_calls[t["conversation_id"]].extend(t.get("tool_calls", []))
        
    looping_convos = []
    for c_id, calls in conv_calls.items():
        max_run = 0
        current_run = 0
        prev_tool = None
        for tool in calls:
            if tool == prev_tool:
                current_run += 1
            else:
                if current_run >= repeat_threshold:
                    max_run = max(max_run, current_run)
                current_run = 1
                prev_tool = tool
        if current_run >= repeat_threshold:
            max_run = max(max_run, current_run)
            
        if max_run >= repeat_threshold:
            looping_convos.append(c_id)
            
    return sorted(looping_convos)

def test_problem5():
    print("Testing Problem 5...")
    pair = problem5_part1(TURNS)
    if pair: assert pair == ("check_policy", "lookup_order", 3)
    
    looping = problem5_part3(TURNS, repeat_threshold=3)
    assert looping == ["conv3"]
    print("Problem 5: PASSED")


# ===========================================================================
# PROBLEM 6 — Interval merge: agent session overlap
# ===========================================================================

SESSIONS = [
    ["agent1", 0,   60],
    ["agent2", 10,  50],
    ["agent3", 40,  80],
    ["agent1", 90,  130],
    ["agent2", 100, 150],
    ["agent4", 200, 250],
]

def problem6_part1(sessions: List[List]) -> int:
    """Total duration where AT LEAST 2 agents were simultaneously active."""
    events = []
    for s in sessions:
        events.append((s[1], 1))
        events.append((s[2], -1))
    
    events.sort(key=lambda x: (x[0], x[1]))
    
    active_agents = 0
    total_duration = 0
    last_time = 0
    
    for t, delta in events:
        if active_agents >= 2:
            total_duration += (t - last_time)
        active_agents += delta
        last_time = t
        
    return total_duration

def problem6_part3(sessions: List[List]) -> Optional[Tuple[int, int]]:
    """Longest continuous period where ZERO agents were active."""
    if not sessions:
        return None
        
    intervals = []
    for s in sessions:
        intervals.append((s[1], s[2]))
        
    intervals.sort()
    
    merged = [intervals[0]]
    for current in intervals[1:]:
        last = merged[-1]
        if current[0] <= last[1]:
            merged[-1] = (last[0], max(last[1], current[1]))
        else:
            merged.append(current)
            
    if len(merged) < 2:
        return None
        
    longest_gap = 0
    best_gap_interval = None
    
    for i in range(1, len(merged)):
        gap_start = merged[i-1][1]
        gap_end = merged[i][0]
        gap_len = gap_end - gap_start
        if gap_len > longest_gap:
            longest_gap = gap_len
            best_gap_interval = (gap_start, gap_end)
            
    return best_gap_interval

def test_problem6():
    print("Testing Problem 6...")
    overlap = problem6_part1(SESSIONS)
    assert overlap == 80
    
    gap = problem6_part3(SESSIONS)
    assert gap == (150, 200)
    print("Problem 6: PASSED")


if __name__ == "__main__":
    test_problem1()
    test_problem2()
    test_problem3()
    test_problem4()
    test_problem5()
    test_problem6()
    print("\nALL TESTS PASSED!")
