from schema_agent import build_graph_v2
import json

graph = build_graph_v2()

initial_state = {
    'title': 'ID',
    'content': 'ID ID ID ID ID ID ID ID ID ID ID ID ID ID ID ID ID ID ID ID.',
    'email': 'student@example.com',
    'strict': False,
    'task': '',
    'llm': 'qwen3:1.7b',
    'planner_proposal': None,
    'validation_error': None,
    'turn_count': 0,
    'turn_ceiling': 4,
}

state = dict(initial_state)
for step in graph.stream(initial_state):
    for node_name, update in step.items():
        print(f'--- Node: {node_name} ---')
        print(json.dumps(update, indent=2))
        state.update(update)
