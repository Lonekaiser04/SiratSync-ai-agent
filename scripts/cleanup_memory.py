from app.services import MemoryManager

def cleanup_inactive_users():
    """Run daily to clean up inactive users"""
    memory = MemoryManager()
    memory.cleanup_inactive_users(inactive_days=60)
if __name__ == "__main__":
    cleanup_inactive_users()