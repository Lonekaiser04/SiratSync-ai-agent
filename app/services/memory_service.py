from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
import os
import redis
import logging

logger = logging.getLogger(__name__)

class MemoryManager:
    def __init__(self):
        self.redis = None
        self.fallback_sessions: Dict[str, List[dict]] = {}
        self.fallback_stats: Dict[str, dict] = {}
        self._initialize_redis()
    
    def _initialize_redis(self):
        """Connect to Upstash Redis"""
        try:
            redis_url = os.environ.get('REDIS_URL')
            
            if redis_url:
                if redis_url.startswith('redis://'):
                    redis_url = redis_url.replace('redis://', 'rediss://', 1)
                
                # Create connection pool for better performance
                pool = redis.ConnectionPool.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_timeout=3,          # Reduced from 5
                    socket_connect_timeout=3,   # Reduced from 5
                    ssl_cert_reqs=None,
                    max_connections=10,         # Connection pooling
                    retry_on_timeout=True       # Auto retry
                )
                self.redis = redis.Redis(connection_pool=pool)
                self.redis.ping()
                logger.info("✅ Connected to Upstash Redis via REDIS_URL (pooled)")
            else:
                host = os.environ.get('UPSTASH_REDIS_HOST')
                password = os.environ.get('UPSTASH_REDIS_PASSWORD')
                port = int(os.environ.get('UPSTASH_REDIS_PORT', 6379))
                
                if host and password:
                    pool = redis.ConnectionPool(
                        host=host,
                        port=port,
                        password=password,
                        ssl=True,
                        ssl_cert_reqs=None,
                        decode_responses=True,
                        socket_timeout=3,
                        socket_connect_timeout=3,
                        max_connections=10,
                        retry_on_timeout=True
                    )
                    self.redis = redis.Redis(connection_pool=pool)
                    self.redis.ping()
                    logger.info("✅ Connected to Upstash Redis via env variables (pooled)")
                else:
                    logger.warning("⚠️ No Redis credentials, using in-memory fallback")
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed: {e}, using in-memory fallback")
            self.redis = None
    
    def _is_redis_available(self) -> bool:
        """Quick Redis check - cached for 30 seconds"""
        if self.redis is None:
            return False
        # Skip ping if checked recently (cache the result)
        if not hasattr(self, '_last_redis_check'):
            self._last_redis_check = {}
        user_id = 'global'
        now = datetime.now()
        if user_id in self._last_redis_check:
            if (now - self._last_redis_check[user_id]).seconds < 30:
                return True
        try:
            self.redis.ping()
            self._last_redis_check[user_id] = now
            return True
        except:
            return False
    
    def add_message(self, user_id: str, role: str, content: str):
        """Store message using PIPELINE - 5 Redis calls in 1 round trip!"""
        message_data = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        if self._is_redis_available():
            try:
                chat_key = f"sirat:chat:{user_id}"
                active_key = f"sirat:active:{user_id}"
                stats_key = f"sirat:stats:{user_id}"
                
                pipe = self.redis.pipeline()
                
                # 1. Store message
                pipe.rpush(chat_key, json.dumps(message_data))
                # 2. Trim to 50 messages
                pipe.ltrim(chat_key, -50, -1)
                # 3. Update last active
                pipe.set(active_key, datetime.now().isoformat())
                # 4. Set expiry on active key (60 days)
                pipe.expire(active_key, 5184000)
                
                # 5. Update stats (only for user messages)
                if role == "user":
                    content_lower = content.lower()
                    pipe.hincrby(stats_key, "total_messages", 1)
                    
                    positive_words = ['mashallah', 'alhamdulillah', 'achieved', 'completed', 'streak', 'proud', 'consistent']
                    struggle_words = ['miss', 'skip', 'hard', 'difficult', 'struggle', 'failed']
                    
                    if any(word in content_lower for word in positive_words):
                        pipe.hincrby(stats_key, "achievement_count", 1)
                    if any(word in content_lower for word in struggle_words):
                        pipe.hincrby(stats_key, "struggle_count", 1)
                    
                    pipe.expire(stats_key, 604800)  # 7 days
                
                # Execute all commands at once!
                pipe.execute()
                
            except Exception as e:
                logger.warning(f"Redis pipeline error: {e}, using fallback")
                self._fallback_add(user_id, message_data)
        else:
            self._fallback_add(user_id, message_data)
    
    def get_context(self, user_id: str, max_messages: int = 8) -> str:
        """Get context with optimized parsing"""
        messages = []
        
        if self._is_redis_available():
            try:
                key = f"sirat:chat:{user_id}"
                raw_messages = self.redis.lrange(key, -max_messages, -1)
                
                # Faster parsing with list comprehension
                messages = [
                    json.loads(msg) for msg in raw_messages 
                    if msg and msg.strip()
                ]
            except Exception as e:
                logger.warning(f"Redis error: {e}")
                messages = self.fallback_sessions.get(user_id, [])[-max_messages:]
        else:
            messages = self.fallback_sessions.get(user_id, [])[-max_messages:]
        
        if not messages:
            return ""
        
        return "\n".join([
            f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
            for msg in messages
        ])
    
    def get_last_question(self, user_id: str) -> Optional[str]:
        """Get last question - optimized"""
        messages = []
        
        if self._is_redis_available():
            try:
                key = f"sirat:chat:{user_id}"
                raw_messages = self.redis.lrange(key, -5, -1)
                messages = [json.loads(msg) for msg in raw_messages if msg]
            except:
                messages = self.fallback_sessions.get(user_id, [])[-5:]
        else:
            messages = self.fallback_sessions.get(user_id, [])[-5:]
        
        # Find last user message (reverse iteration)
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                return msg.get('content')
        return None
    
    def get_user_profile(self, user_id: str) -> dict:
        """Optimized user profile retrieval"""
        key = f"sirat:stats:{user_id}"
        stats = {"total_messages": 0, "achievement_count": 0, "struggle_count": 0}
        
        if self._is_redis_available():
            try:
                # 🚀 Use pipeline for multiple hash gets
                pipe = self.redis.pipeline()
                pipe.hget(key, "total_messages")
                pipe.hget(key, "achievement_count")
                pipe.hget(key, "struggle_count")
                results = pipe.execute()
                
                if results[0]:
                    stats["total_messages"] = int(results[0])
                if results[1]:
                    stats["achievement_count"] = int(results[1])
                if results[2]:
                    stats["struggle_count"] = int(results[2])
            except:
                pass
        
        # Determine consistency
        consistency = "unknown"
        if stats["total_messages"] > 5:
            if stats["achievement_count"] > stats["struggle_count"] * 1.5:
                consistency = "high"
            elif stats["achievement_count"] > stats["struggle_count"] * 0.5:
                consistency = "medium"
            else:
                consistency = "struggling"
        
        return {
            "consistency": consistency,
            "topics": [],
            "message_count": stats["total_messages"],
            "suggested_advice": self._get_advice(consistency)
        }
    
    def get_session_summary(self, user_id: str) -> dict:
        """Get session summary with optimized calls"""
        profile = self.get_user_profile(user_id)
        
        # Check if user has messages without extra Redis call
        has_messages = profile.get("message_count", 0) > 0
        
        return {
            "active": has_messages,
            "message_count": profile.get("message_count", 0),
            "consistency": profile.get("consistency", "unknown"),
            "suggested_advice": profile.get("suggested_advice", ""),
            "using_redis": self._is_redis_available()
        }
    
    def cleanup_inactive_users(self, inactive_days: int = 60):
        """Clean up inactive users - optimized with pipeline"""
        if not self._is_redis_available():
            return
        
        try:
            active_keys = list(self.redis.scan_iter("sirat:active:*"))
            
            for key in active_keys:
                user_id = key.split(":")[-1]
                if not self.is_user_active(user_id, inactive_days):
                    # 🚀 Delete all user keys in one pipeline
                    pipe = self.redis.pipeline()
                    pipe.delete(f"sirat:chat:{user_id}")
                    pipe.delete(f"sirat:stats:{user_id}")
                    pipe.delete(key)
                    pipe.execute()
                    logger.info(f"🧹 Cleaned up inactive user: {user_id}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    def clear_session(self, user_id: str):
        """Clear user data - optimized"""
        if self._is_redis_available():
            try:
                # 🚀 Pipeline delete
                pipe = self.redis.pipeline()
                pipe.delete(f"sirat:chat:{user_id}")
                pipe.delete(f"sirat:stats:{user_id}")
                pipe.delete(f"sirat:active:{user_id}")
                pipe.execute()
                logger.info(f"🧹 Cleared Redis data for user: {user_id}")
            except Exception as e:
                logger.error(f"Failed to clear Redis data: {e}")
        
        self.fallback_sessions.pop(user_id, None)
        self.fallback_stats.pop(user_id, None)
        return {"status": "cleared", "user_id": user_id}
    
    # Keep remaining methods unchanged
    def _update_last_active(self, user_id: str):
        if self._is_redis_available():
            try:
                key = f"sirat:active:{user_id}"
                pipe = self.redis.pipeline()
                pipe.set(key, datetime.now().isoformat())
                pipe.expire(key, 5184000)
                pipe.execute()
            except:
                pass
    
    def get_last_active(self, user_id: str) -> Optional[datetime]:
        if self._is_redis_available():
            try:
                key = f"sirat:active:{user_id}"
                timestamp = self.redis.get(key)
                if timestamp:
                    return datetime.fromisoformat(timestamp)
            except:
                pass
        return None
    
    def is_user_active(self, user_id: str, days: int = 30) -> bool:
        last_active = self.get_last_active(user_id)
        if last_active:
            return (datetime.now() - last_active).days < days
        return False
    
    def _fallback_add(self, user_id: str, message_data: dict):
        if user_id not in self.fallback_sessions:
            self.fallback_sessions[user_id] = []
        self.fallback_sessions[user_id].append(message_data)
        if len(self.fallback_sessions[user_id]) > 30:
            self.fallback_sessions[user_id] = self.fallback_sessions[user_id][-30:]
    
    def _get_advice(self, consistency: str) -> str:
        if consistency == "struggling":
            return "🤲 Start with just ONE prayer on time today. Allah loves small consistent deeds."
        elif consistency == "high":
            return "🌟 MashaAllah! Consider adding morning adhkar to your routine."
        return "📌 Set a small daily goal in the Habit Tracker today."
    
    @property
    def sessions(self) -> dict:
        if self._is_redis_available():
            try:
                count = sum(1 for key in self.redis.scan_iter("sirat:chat:*") 
                          if self.redis.llen(key) > 0)
                return {"redis_sessions": count, "fallback_sessions": len(self.fallback_sessions)}
            except:
                pass
        return {"fallback_sessions": len(self.fallback_sessions)}
    
memory = MemoryManager()