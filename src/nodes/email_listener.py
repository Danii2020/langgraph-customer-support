from ..state import GraphState
from ..utils.gmail_utils import get_most_recent_email
from src.observability import traceable

# @traceable wraps this node so it appears as its own span in the LangSmith trace tree.
@traceable(name="node.load_email", run_type="chain")
def email_listener_node(state: GraphState):
    email = get_most_recent_email()
    state["current_email"] = email
    return state
