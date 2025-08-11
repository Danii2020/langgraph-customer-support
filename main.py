from src.graph.email_graph import EmailSupportGraph
from src.state import Email

def main():
    print("Starting LangGraph Email Support Workflow...")
    initial_state = {
        "current_email": {
            "id": "",
            "subject": "",
            "sender": "",
            "date": "",
            "body": ""
        },
        "email_category": "",
        "email_response": "",
        "messages": [""]
    }
    workflow = EmailSupportGraph()
    graph = workflow.graph
    for output in graph.stream(initial_state):
        for node, state in output.items():
            print("Node:\n")
            print(f"{node}\n")
            print("State:\n")
            print(f"{state}\n")


if __name__ == "__main__":
    main()
