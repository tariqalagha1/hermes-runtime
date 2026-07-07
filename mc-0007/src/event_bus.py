"""
MC-0007 Runtime Event Bus — decoupled publish/subscribe communication.
Conforms to RTA-0001 meta-model Event Registry (14 events).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional
import json, hashlib, uuid, fnmatch, time as _time
from collections import defaultdict

# ═══════════════════════════════════════════════════════
# EVENT SCHEMA (conforms to RTA-0001 Event Registry)
# ═══════════════════════════════════════════════════════

@dataclass
class RuntimeEvent:
    event_id: str
    type: str          # e.g. "task.dispatched", "agent.completed"
    publisher: str     # component ID e.g. "MC-0003"
    trace_id: str      # correlation across components
    parent_trace_id: Optional[str]  # for event chains
    mission_id: str
    task_id: Optional[str]
    agent_id: Optional[str]
    timestamp: str
    payload: dict
    hash: str
    sequence: int
    acknowledged: bool = False
    ack_count: int = 0

@dataclass
class Subscription:
    subscriber_id: str       # component ID
    event_pattern: str       # glob pattern e.g. "task.*", "agent.completed"
    callback: Optional[Callable] = None  # optional sync handler
    filter_mission: Optional[str] = None  # optional mission filter
    ack_required: bool = True  # subscriber must acknowledge

# ═══════════════════════════════════════════════════════
# EVENT BUS
# ═══════════════════════════════════════════════════════

class EventBus:
    """Decoupled pub/sub communication. Ordering preserved per topic."""
    
    def __init__(self):
        self.subscriptions: list[Subscription] = []
        self.events: list[RuntimeEvent] = []  # ordered log
        self.event_index: dict[str, list[int]] = defaultdict(list)  # type → positions
        self.trace_index: dict[str, list[int]] = defaultdict(list)   # trace_id → positions
        self.mission_index: dict[str, list[int]] = defaultdict(list) # mission → positions
        self.sequence: int = 0
        self.stats: dict[str, int] = defaultdict(int)
    
    # ── PUBLISH ────────────────────────────────────────
    
    def publish(self, event_type: str, publisher: str, mission_id: str,
                task_id: str = None, agent_id: str = None,
                payload: dict = None, trace_id: str = None,
                parent_trace_id: str = None) -> RuntimeEvent:
        """Publish event. Routes to matching subscribers."""
        
        self.sequence += 1
        event = RuntimeEvent(
            event_id=f"E-{self.sequence:08d}",
            type=event_type,
            publisher=publisher,
            trace_id=trace_id or str(uuid.uuid4())[:8],
            parent_trace_id=parent_trace_id,
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload or {},
            hash="",
            sequence=self.sequence,
        )
        
        # Hash
        event.hash = hashlib.sha256(
            json.dumps({
                "event_id": event.event_id, "type": event.type,
                "publisher": event.publisher, "trace_id": event.trace_id,
                "mission_id": mission_id, "sequence": event.sequence,
                "timestamp": event.timestamp,
            }, sort_keys=True).encode()
        ).hexdigest()[:16]
        
        # Store
        self.events.append(event)
        pos = len(self.events) - 1
        self.event_index[event_type].append(pos)
        self.trace_index[event.trace_id].append(pos)
        self.mission_index[mission_id].append(pos)
        self.stats[event_type] = self.stats.get(event_type, 0) + 1
        
        # Route to matching subscribers
        for sub in self.subscriptions:
            if self._matches(event, sub):
                if sub.callback:
                    try:
                        sub.callback(event)
                        if sub.ack_required:
                            event.ack_count += 1
                            event.acknowledged = True
                    except Exception:
                        pass  # Subscriber failure shouldn't break bus
        
        return event
    
    def _matches(self, event: RuntimeEvent, sub: Subscription) -> bool:
        """Check if event matches subscription."""
        if not fnmatch.fnmatch(event.type, sub.event_pattern):
            return False
        if sub.filter_mission and sub.filter_mission != event.mission_id:
            return False
        return True
    
    # ── SUBSCRIBE ──────────────────────────────────────
    
    def subscribe(self, subscriber_id: str, event_pattern: str,
                  callback: Callable = None, filter_mission: str = None,
                  ack_required: bool = True) -> Subscription:
        """Register subscription. Returns subscription object."""
        sub = Subscription(
            subscriber_id=subscriber_id,
            event_pattern=event_pattern,
            callback=callback,
            filter_mission=filter_mission,
            ack_required=ack_required,
        )
        self.subscriptions.append(sub)
        return sub
    
    def unsubscribe(self, subscriber_id: str, event_pattern: str = None):
        """Remove subscriptions matching subscriber + pattern."""
        self.subscriptions = [
            s for s in self.subscriptions
            if not (s.subscriber_id == subscriber_id and 
                   (event_pattern is None or s.event_pattern == event_pattern))
        ]
    
    # ── QUERY ──────────────────────────────────────────
    
    def by_type(self, event_type: str) -> list[RuntimeEvent]:
        """Events matching exact type."""
        return [self.events[i] for i in self.event_index.get(event_type, [])]
    
    def by_pattern(self, pattern: str) -> list[RuntimeEvent]:
        """Events matching glob pattern."""
        return [e for e in self.events if fnmatch.fnmatch(e.type, pattern)]
    
    def by_trace(self, trace_id: str) -> list[RuntimeEvent]:
        """Events in a trace chain."""
        return [self.events[i] for i in self.trace_index.get(trace_id, [])]
    
    def by_mission(self, mission_id: str) -> list[RuntimeEvent]:
        """Events for a mission."""
        return [self.events[i] for i in self.mission_index.get(mission_id, [])]
    
    def by_publisher(self, publisher: str) -> list[RuntimeEvent]:
        """Events from a component."""
        return [e for e in self.events if e.publisher == publisher]
    
    def replay(self, event_type: str = None, from_sequence: int = 0) -> list[RuntimeEvent]:
        """Replay events from sequence. Optional type filter."""
        events = self.events[from_sequence:]
        if event_type:
            events = [e for e in events if fnmatch.fnmatch(e.type, event_type)]
        return events
    
    # ── STATUS ─────────────────────────────────────────
    
    def status(self) -> dict:
        unacked = [e for e in self.events if not e.acknowledged]
        return {
            "total_events": len(self.events),
            "subscriptions": len(self.subscriptions),
            "subscriber_ids": list(set(s.subscriber_id for s in self.subscriptions)),
            "event_types": list(self.stats.keys()),
            "by_type": dict(self.stats),
            "unacknowledged": len(unacked),
            "traces": len(self.trace_index),
            "missions": len(self.mission_index),
            "sequence": self.sequence,
        }
    
    def audit(self, event_type: str = None) -> list[dict]:
        """Audit trail of events."""
        events = self.events
        if event_type:
            events = [e for e in events if fnmatch.fnmatch(e.type, event_type)]
        return [{
            "event_id": e.event_id,
            "type": e.type,
            "publisher": e.publisher,
            "trace_id": e.trace_id,
            "timestamp": e.timestamp,
            "hash": e.hash,
            "acknowledged": e.acknowledged,
        } for e in events]
