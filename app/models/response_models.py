# from pydantic import BaseModel
# from typing import Optional, List, Dict

# class ChatResponse(BaseModel):
#     reply:              str
#     intent:             str
#     sub_intent:         Optional[str] = None
#     sentiment:          str
#     actions:            Dict
#     suggestions:        List[str]
#     motivational_quote: Optional[str] = None
#     timestamp:          str


# class SummarizeResponse(BaseModel):
#     summary:         str
#     original_length: int
#     summary_length:  int

from pydantic import BaseModel
from typing import Optional, List, Dict

class SourceItem(BaseModel):
    type: str          # "quran", "knowledge_base", "ai_generated"
    label: str         # Display name e.g. "Quran — Sahih International"
    reference: Optional[str] = None   # e.g. "Al-Baqarah 2:255"
    detail: Optional[str] = None      # extra info if needed

class ChatResponse(BaseModel):
    reply:              str
    intent:             str
    sub_intent:         Optional[str] = None
    sentiment:          str
    actions:            Dict
    suggestions:        List[str]
    motivational_quote: Optional[str] = None
    timestamp:          str
    sources:            List[SourceItem] = []   # ✅ NEW