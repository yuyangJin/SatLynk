"""Weight cache — Per-node model weight management.

Implements C4 constraint: x_iv(t)=1 ⟹ z_iv(t⁻)=1
(computation can only start if required model weights are already cached locally)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


@dataclass
class ModelWeight:
    """A model weight blob."""
    model_id: str
    size_bytes: int
    priority: int = 0          # Higher = harder to evict
    last_used_t: float = 0.0
    use_count: int = 0


class EvictionPolicy(str, Enum):
    LRU = "lru"
    LFU = "lfu"
    PRIORITY = "priority"


class WeightCache:
    """Per-node weight cache with eviction."""
    
    def __init__(self, capacity_bytes: int, policy: EvictionPolicy = EvictionPolicy.LRU):
        self.capacity = capacity_bytes
        self.policy = policy
        self.cache: Dict[str, ModelWeight] = {}
        self.used_bytes: int = 0
    
    def has(self, model_id: str) -> bool:
        return model_id in self.cache
    
    def get(self, model_id: str, t: float) -> Optional[ModelWeight]:
        if model_id in self.cache:
            w = self.cache[model_id]
            w.last_used_t = t
            w.use_count += 1
            return w
        return None
    
    def can_fit(self, size_bytes: int) -> bool:
        return self.used_bytes + size_bytes <= self.capacity
    
    def free_space(self) -> int:
        return self.capacity - self.used_bytes
    
    def insert(self, weight: ModelWeight, t: float) -> List[str]:
        """
        Insert weight into cache, evicting if necessary.
        Returns list of evicted model IDs.
        """
        if self.has(weight.model_id):
            # Already cached — just update metadata
            self.cache[weight.model_id].last_used_t = t
            return []
        
        evicted = []
        while not self.can_fit(weight.size_bytes):
            victim = self._select_victim()
            if victim is None:
                break  # Can't evict anything (shouldn't happen if sizes are reasonable)
            evicted.append(victim.model_id)
            self.used_bytes -= victim.size_bytes
            del self.cache[victim.model_id]
        
        if self.can_fit(weight.size_bytes):
            weight.last_used_t = t
            self.cache[weight.model_id] = weight
            self.used_bytes += weight.size_bytes
        
        return evicted
    
    def remove(self, model_id: str):
        """Explicitly remove (e.g., after reboot clears cache)."""
        if model_id in self.cache:
            self.used_bytes -= self.cache[model_id].size_bytes
            del self.cache[model_id]
    
    def clear(self):
        """Clear all cached weights (e.g., node reboot)."""
        self.cache.clear()
        self.used_bytes = 0
    
    def contents(self) -> List[str]:
        """List of cached model IDs."""
        return list(self.cache.keys())
    
    def _select_victim(self) -> Optional[ModelWeight]:
        if not self.cache:
            return None
        if self.policy == EvictionPolicy.LRU:
            return min(self.cache.values(), key=lambda w: w.last_used_t)
        elif self.policy == EvictionPolicy.LFU:
            return min(self.cache.values(), key=lambda w: w.use_count)
        elif self.policy == EvictionPolicy.PRIORITY:
            return min(self.cache.values(), key=lambda w: (w.priority, w.last_used_t))
        return None
    
    def __repr__(self):
        return f"WeightCache({self.used_bytes}/{self.capacity} bytes, {len(self.cache)} models)"


class WeightCacheManager:
    """Manages weight caches across all nodes."""
    
    def __init__(self):
        self.caches: Dict[int, WeightCache] = {}
        self._model_registry: Dict[str, int] = {}  # model_id → size_bytes
    
    def init_node(self, node_id: int, capacity_bytes: int, 
                  policy: EvictionPolicy = EvictionPolicy.LRU,
                  preloaded: Optional[List[str]] = None):
        """Initialize a node's weight cache."""
        self.caches[node_id] = WeightCache(capacity_bytes, policy)
        if preloaded:
            for model_id in preloaded:
                size = self._model_registry.get(model_id, 0)
                if size > 0:
                    self.caches[node_id].insert(
                        ModelWeight(model_id=model_id, size_bytes=size), t=0.0
                    )
    
    def register_model(self, model_id: str, size_bytes: int):
        """Register a model in the global registry."""
        self._model_registry[model_id] = size_bytes
    
    def get_model_size(self, model_id: str) -> int:
        return self._model_registry.get(model_id, 0)
    
    def has_weight(self, node_id: int, model_id: str) -> bool:
        """Check if a node has the required weight cached."""
        cache = self.caches.get(node_id)
        return cache.has(model_id) if cache else False
    
    def find_nearest_source(self, model_id: str, exclude_node: int = -1) -> Optional[int]:
        """Find any node that has this model cached (for migration)."""
        for node_id, cache in self.caches.items():
            if node_id != exclude_node and cache.has(model_id):
                return node_id
        return None
    
    def cache_weight(self, node_id: int, model_id: str, t: float) -> List[str]:
        """Cache a model weight at a node (after transfer completes)."""
        cache = self.caches.get(node_id)
        if cache is None:
            return []
        size = self._model_registry.get(model_id, 0)
        if size == 0:
            return []
        return cache.insert(ModelWeight(model_id=model_id, size_bytes=size), t)
    
    def use_weight(self, node_id: int, model_id: str, t: float):
        """Mark a weight as used (updates LRU timestamp)."""
        cache = self.caches.get(node_id)
        if cache:
            cache.get(model_id, t)
    
    def get_cache_contents(self, node_id: int) -> List[str]:
        cache = self.caches.get(node_id)
        return cache.contents() if cache else []
    
    def clear_node(self, node_id: int):
        """Clear a node's cache (reboot simulation)."""
        cache = self.caches.get(node_id)
        if cache:
            cache.clear()
