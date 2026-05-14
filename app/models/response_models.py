


from pydantic import BaseModel
from typing import Optional, List, Dict

class SourceItem(BaseModel):
    type: str          
    label: str         
    reference: Optional[str] = None   
    detail: Optional[str] = None   

class ChatResponse(BaseModel):
    reply:              str
    intent:             str
    sub_intent:         Optional[str] = None
    sentiment:          str
    actions:            Dict
    suggestions:        List[str]
    motivational_quote: Optional[str] = None
    timestamp:          str
    sources:            List[SourceItem] = []   
class SummarizeResponse(BaseModel):
    summary:         str
    original_length: int
    summary_length:  int