# cache.py
from datetime import datetime, timedelta
from typing import Optional, Dict
import hashlib
import json

class ResponseCache:
    def __init__(self):
        self.cache: Dict[str, tuple] = {}
        self.stats = {"hits": 0, "misses": 0}
    
    def _get_key(self, message: str, user_id: str) -> str:
        """Generate cache key from message"""
        normalized = message.lower().strip()
        normalized = normalized.replace("?", "").replace("please", "").strip()
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def get(self, message: str, user_id: str) -> Optional[str]:
        """Get cached response if exists and not expired"""
        key = self._get_key(message, user_id)
        if key in self.cache:
            response, expiry = self.cache[key]
            if datetime.now() < expiry:
                self.stats["hits"] += 1
                return response
            else:
                del self.cache[key]
        self.stats["misses"] += 1
        return None
    
    def set(self, message: str, user_id: str, response: str, ttl_minutes: int = 60):
        """Cache response for TTL minutes"""
        # Don't cache personalized responses
        if any(word in message.lower() for word in ["my", "me", "i ", "i'm", "i've", "i missed", "i prayed"]):
            return
        
        key = self._get_key(message, user_id)
        expiry = datetime.now() + timedelta(minutes=ttl_minutes)
        self.cache[key] = (response, expiry)
        
        # Clean old entries if cache too large
        if len(self.cache) > 1000:
            now = datetime.now()
            expired = [k for k, (_, exp) in self.cache.items() if now > exp]
            for k in expired:
                del self.cache[k]

# Global cache instance
cache = ResponseCache()