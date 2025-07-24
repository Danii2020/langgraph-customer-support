from ..agents import AGENT_REGISTRY
from ..state import GraphState, Email

def email_categorizer_node(state: GraphState):
    body = ""
    email = state.get("current_email")
    if not email:
        state["email_category"] = "No email"
        return state
    if isinstance(email, Email):
        body = email.body
    result = AGENT_REGISTRY["email_categorizer"].invoke({"email": body})
    state["email_category"] = result.category.value # type: ignore
    return state
