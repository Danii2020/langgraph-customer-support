from src.graph.email_graph import EmailSupportGraph
from src.state import Email

def main():
    print("Starting LangGraph Email Support Workflow...")

    # Sample email for testing
    initial_state = {
        "messages": [""],
        "current_email": "",
        "email_category": "",
        "email_response": ""
    }
    workflow = EmailSupportGraph()
    graph = workflow.graph
    print("Processing email through workflow...")
    print("-" * 50)
    # Stream through the workflow
    for output in graph.stream(initial_state):
        for node, state in output.items():
            print(state)
            print("\n\n")

if __name__ == "__main__":
    main()
