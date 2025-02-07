# ChatMessageUIEditor

A Streamlit-based UI application for viewing and editing chat message histories stored in SQLite. The application provides a clean interface for reviewing AI chat interactions, with special formatting for different message types including user inputs, AI responses, and tool outputs.

## Features

- View and edit chat messages with syntax highlighting for code and JSON
- Support for multiple chat sessions with pagination
- Export functionality for selected chat sessions
- Message editing, deletion and insertion capabilities
- Special formatting for:
  - Assistant responses (JSON with Python code blocks)
  - Tool responses (JSON output)
  - User messages with colored tags
- Dark/Light mode support
- Efficient SQLite database handling with caching

## Installation

1. First, install `uv` (a fast Python package installer) if you haven't already:
```bash
pip install uv
```

2. Create and activate a new virtual environment in your project directory:
```bash
uv venv
source .venv/bin/activate  # On Unix/macOS
.venv\Scripts\activate     # On Windows
```

3. Install dependencies:
```bash
uv pip install streamlit sqlite3
```

## Running the Application

1. Ensure your SQLite database file (`chatbot.db`) is in the project root directory

2. Start the Streamlit application:
```bash
streamlit run MessageUI.py
```

3. The application will open in your default web browser. If it doesn't, navigate to:
```
http://localhost:8501
```

## Usage

### Navigation
- The sidebar on the left shows all available chat sessions
- Each chat session displays its ID and message count
- Click on any chat session to view its messages
- Messages are paginated - use Previous/Next buttons at the bottom to navigate

### Viewing Messages
- Messages are displayed chronologically with role-specific icons:
  - 👤 User messages
  - 🤖 Assistant messages
  - ⚙️ System messages
  - 🔧 Tool messages
- Each message shows its creation timestamp
- Use the expander arrows (▼/▶) to show/hide message details
- Messages are color-coded by role for easy identification

### Message Management
1. **Editing Messages**
   - Click the ✏️ button to enter edit mode
   - Make your changes in the text area
   - Click 💾 to save or navigate away to cancel

2. **Deleting Messages**
   - Click the 🗑️ button to remove a message
   - This action cannot be undone
   - The message count will update automatically

3. **Adding Messages**
   - Click the ➕ button below any message to add a new message after it
   - Use the "Add a new message at the start" expander to add at the beginning
   - Select the role and enter content in the form
   - Click "Submit New Message" to add or "Cancel" to discard

### Exporting Data
1. Select chat sessions for export using checkboxes in the sidebar
2. Use "Select All" or "Clear All" buttons to quickly manage selections
3. Click "📦 Export Selected" to generate the export
4. Use "⬇️ Download JSON" to save the exported data

### Message Format Examples

1. **Assistant Messages**
```json
{
  "thought": "Processing user request",
  "response": {
    "type": "tool_use",
    "content": {
      "code": "print('Hello World')"
    }
  }
}
```

2. **Tool Messages**
```
<tool_call_response>
[{"name": "result", "content": {"status": "success"}}]
</tool_call_response>
```

3. **User Messages**
```
[device_type: 'voice'] Hello! [END]
```

## Message Types

The application handles several types of messages with special formatting:

1. Assistant Messages:
   - Displays thoughts in italics
   - Shows Python code with syntax highlighting for tool_use responses
   - Shows regular text for response_to_user messages

2. Tool Messages:
   - Displays JSON responses with proper formatting and syntax highlighting
   - Preserves XML-style tags with colored formatting

3. User Messages:
   - Displays device tags and other markers with colored formatting

## Database Schema

The application uses SQLite with the following structure:

```sql
CREATE TABLE chat_sessions (
    chat_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    message_count INTEGER DEFAULT 0
);

CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    order_id REAL,
    FOREIGN KEY (chat_id) REFERENCES chat_sessions(chat_id)
);
```

## Contributing

Feel free to submit issues and enhancement requests!

## License

[MIT License](LICENSE)
