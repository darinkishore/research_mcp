import json
from pathlib import Path

from main import ChatHeader, Message

# Get JSON schemas from Pydantic models
chat_header_schema = ChatHeader.model_json_schema()
message_schema = Message.model_json_schema()

# Create the full schema
full_schema = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'title': 'Chat Log Schema',
    'description': 'Schema for chat log JSONL format',
    'type': 'array',
    'items': {'oneOf': [chat_header_schema, message_schema]},
}

# Write schema to file
with Path('schema.json').open('w', encoding='utf-8') as f:
    json.dump(full_schema, f, indent=2)

if __name__ == '__main__':
    print('Schema has been written to schema.json')
