"""
Service layer singletons.

Importing from `app.services` gives access to the fully-initialized
singleton instances used across the application (API routes, scripts,
background jobs) without needing to know the internal module layout.
"""
from app.services.memory_service import memory, MemoryManager
from app.services.rag_service import rag_service, RAGKnowledge
from app.services.intent_service import intent_detector, IntentDetector

__all__ = [
    "memory",
    "MemoryManager",
    "rag_service",
    "RAGKnowledge",
    "intent_detector",
    "IntentDetector",
]
