import streamlit as st
import sqlite3
import json
import re
from typing import Dict, Set, Optional, List, Any, Sequence
from datetime import datetime

# Constants
CSS = """
<style>
.message-container {
    padding: 5px;
    margin: 2px 0;
    width: 100%;
}
.message-content {
    display: block;
    width: 100%;
    max-width: 100%;
    overflow-wrap: break-word;
}
.stExpander {
    width: 100%;
    max-width: 100%;
}
.row-widget.stExpander > div:first-child {
    max-width: 100% !important;
}
.streamlit-expanderContent {
    width: 100%;
    max-width: 100%;
    padding: 0 !important;
}
.stColumns {
    width: 100%;
    max-width: 100%;
    gap: 0.5rem !important;
}
/* Add styles for text area */
.stTextArea textarea {
    width: 100% !important;
    max-width: 100% !important;
}
.role-header {
    font-weight: bold;
    margin-bottom: 3px;
}
.role-user { color: #2196F3; }
.role-assistant { color: #4CAF50; }
.role-system { color: #FF9800; }
.role-tool { color: #607D8B; }

/* Add styles for code blocks */
.stCode {
    border-radius: 4px;
    margin: 8px 0;
}

/* Customize code block colors */
.language-json {
    background-color: #f6f8fa;
}

.language-python {
    background-color: #f6f8fa;
}

/* Dark mode support */
@media (prefers-color-scheme: dark) {
    .language-json, .language-python {
        background-color: #1e1e1e;
    }
}
</style>
"""

ROLE_EMOJIS = {
    'user': '👤',
    'assistant': '🤖',
    'system': '⚙️',
    'tool': '🔧'
}

BRIGHT_COLORS = [
    "#33FF33",  # Green
    "#FF33FF",  # Magenta
    "#33FFFF",  # Cyan
    "#FFA500",  # Orange (changed from yellow)
    "#FF6B33",  # Orange
    "#FF3399",  # Pink
]

CHAT_EMOJI = "💬"
SELECTED_CHAT_EMOJI = "▶️"

# Simplified session state
DEFAULT_STATE: Dict[str, Any] = {
    'global_tag_colors': {},
    'editing_message_id': None,
    'selected_chat_id': None,
    'selected_sessions_for_export': set(),
    'current_page': 1,
    'messages_per_page': 50,
    'adding_after_id': None
}

# Initialize session state once
for key, default in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = default

@st.cache_resource
def init_connection() -> sqlite3.Connection:
    """Initialize SQLite connection with optimizations."""
    conn = sqlite3.connect('chatbot.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    with conn:
        # Enable WAL mode and other optimizations
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA temp_store=MEMORY;
            PRAGMA cache_size=10000;
            
            CREATE TABLE IF NOT EXISTS chat_sessions (
                chat_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chat_sessions(chat_id)
            );
        """)
        
        # Add columns if they don't exist
        try:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN order_id REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            conn.execute("ALTER TABLE chat_sessions ADD COLUMN message_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        # Initialize order_id for any NULL values
        conn.execute("UPDATE chat_messages SET order_id = id WHERE order_id IS NULL")
        
        # Initialize message_count for any NULL values
        conn.execute("""
            UPDATE chat_sessions 
            SET message_count = (
                SELECT COUNT(*) 
                FROM chat_messages 
                WHERE chat_messages.chat_id = chat_sessions.chat_id
            )
            WHERE message_count IS NULL
        """)
        
        # Create indexes
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON chat_messages(chat_id);
            CREATE INDEX IF NOT EXISTS idx_messages_order ON chat_messages(chat_id, order_id);
        """)
    
    return conn

@st.cache_data(ttl=300)
def fetch_chat_sessions_metadata(chat_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Fetch chat session metadata efficiently.
    Args:
        chat_ids: Optional list of chat IDs to filter by. If None, returns all chats.
    """
    conn = init_connection()
    if chat_ids:
        # Use parameterized query with the list of chat_ids
        placeholders = ','.join('?' * len(chat_ids))
        query = f"""
            SELECT chat_id, model, created_at, message_count
            FROM chat_sessions
            WHERE chat_id IN ({placeholders})
            ORDER BY created_at DESC
        """
        cursor = conn.execute(query, chat_ids)
    else:
        # Original query for all chats
        cursor = conn.execute("""
            SELECT chat_id, model, created_at, message_count
            FROM chat_sessions
            ORDER BY created_at DESC
        """)
    return [dict(row) for row in cursor.fetchall()]

@st.cache_data(ttl=60)
def fetch_chat_messages(chat_id: str, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
    """Fetch paginated messages efficiently."""
    if not chat_id:
        return []
    
    conn = init_connection()
    offset = (page - 1) * per_page
    cursor = conn.execute("""
        SELECT * FROM chat_messages 
        WHERE chat_id = ? 
        ORDER BY order_id ASC
        LIMIT ? OFFSET ?
    """, (chat_id, per_page, offset))
    return [dict(row) for row in cursor.fetchall()]

def clear_chat_caches(chat_id: str) -> None:
    """Clear only caches related to the specified chat."""
    fetch_chat_messages.clear(chat_id)
    fetch_chat_sessions_metadata.clear()

def update_message(message_id: int, chat_id: str, new_content: str) -> None:
    """Update message content."""
    conn = init_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE chat_messages SET content = ?, token_count = ? WHERE id = ? AND chat_id = ?",
                (new_content, len(new_content.split()), message_id, chat_id)
            )
        clear_chat_caches(chat_id)
        st.success("Message updated!")
    except sqlite3.Error as e:
        st.error(f"Error updating message: {str(e)}")

def add_message(chat_id: str, role: str, content: str, after_msg_id: Optional[int]) -> None:
    """Add a message between two existing messages using order_id for positioning."""
    conn = init_connection()
    try:
        with conn:
            if after_msg_id is not None:
                # Get current and next order_id
                curr_order_id = float(conn.execute(
                    "SELECT order_id FROM chat_messages WHERE chat_id = ? AND id = ?",
                    (chat_id, after_msg_id)
                ).fetchone()['order_id'])
                
                next_order_id = conn.execute(
                    "SELECT order_id FROM chat_messages WHERE chat_id = ? AND order_id > ? ORDER BY order_id ASC LIMIT 1",
                    (chat_id, curr_order_id)
                ).fetchone()
                
                # Calculate new order_id between current and next
                new_order_id = curr_order_id + 1 if not next_order_id else (curr_order_id + float(next_order_id['order_id'])) / 2
            else:
                # Insert at start with order_id 0
                new_order_id = 0
            
            # Insert message and increment count
            conn.execute(
                "INSERT INTO chat_messages (chat_id, role, content, token_count, created_at, order_id) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, role, content, len(content.split()), datetime.now().isoformat(), new_order_id)
            )
            conn.execute("UPDATE chat_sessions SET message_count = message_count + 1 WHERE chat_id = ?", (chat_id,))
            
        clear_chat_caches(chat_id)
        st.success("Message added successfully!")
    except sqlite3.Error as e:
        st.error(f"Error adding message: {str(e)}")

def delete_message(msg_id: int, chat_id: str) -> None:
    """Delete a message without resequencing IDs."""
    conn = init_connection()
    with conn:
        conn.execute(
            "DELETE FROM chat_messages WHERE id = ? AND chat_id = ?",
            (msg_id, chat_id)
        )
        conn.execute(
            "UPDATE chat_sessions SET message_count = message_count - 1 WHERE chat_id = ?",
            (chat_id,)
        )
    # Clear both function caches to ensure fresh data
    fetch_chat_messages.clear()
    fetch_chat_sessions_metadata.clear()

@st.cache_data(ttl=3600)
def color_brackets(text: str) -> str:
    """Efficiently process XML-style tags with cached colors."""
    def get_tag_color(tag_name: str) -> str:
        color_idx = hash(tag_name) % len(BRIGHT_COLORS)
        return BRIGHT_COLORS[color_idx]
    
    def process_xml_tag(match):
        tag_name = match.group(1).lstrip('/').split()[0]
        color = get_tag_color(tag_name)
        return f'<span style="color: {color}">&lt;{match.group(1)}&gt;</span>'
    
    return re.sub(r'<([/\w][^>]*?)>', process_xml_tag, text)

def render_message(msg: Dict[str, Any]) -> None:
    """Render a single message with controls."""
    with st.expander(
        f"{ROLE_EMOJIS.get(msg['role'], '❓')} {msg['created_at']}", 
        expanded=(msg['role'] != 'system')
    ):
        # Use even larger ratio for content column
        col1, col2, col3 = st.columns([30, 1, 1])
        
        with col1:
            is_editing = (st.session_state.editing_message_id == msg['id'])
            
            st.markdown(f"""
                <div class="message-container">
                    <div class="role-header role-{msg['role']}">{msg['role'].upper()}</div>
                    <div class="message-content">
                """, unsafe_allow_html=True)
            
            if is_editing:
                new_content = st.text_area(
                    "Content",
                    value=msg['content'],
                    key=f"textarea_edit_msg_{msg['id']}",
                    label_visibility="collapsed",
                    height=150
                )
            else:
                if msg['role'] == 'assistant':
                    try:
                        # Parse assistant message as JSON
                        content = json.loads(msg['content'])
                        
                        # Display thought as regular text
                        if 'thought' in content:
                            st.markdown(f"*{content['thought']}*")
                        
                        # Handle response based on type
                        if content.get('response', {}).get('type') == 'tool_use':
                            # Display Python code with syntax highlighting
                            code = content['response']['content']['code']
                            st.code(code, language='python')
                        elif content.get('response', {}).get('type') == 'response_to_user':
                            # Display user response as regular text
                            st.markdown(content['response']['content'])
                            
                    except json.JSONDecodeError:
                        # Fallback to regular markdown
                        st.markdown(msg['content'])
                        
                elif msg['role'] == 'tool':
                    # Extract JSON content from within tool_call_response tags
                    match = re.search(r'<tool_call_response>\n(.*?)\n</tool_call_response>', 
                                    msg['content'], re.DOTALL)
                    if match:
                        try:
                            # Parse and format the JSON content
                            json_content = eval(match.group(1))  # Safe here since we control the content
                            st.code(json.dumps(json_content, indent=2), language='json')
                        except:
                            # Fallback to regular markdown with colored brackets
                            st.markdown(color_brackets(msg['content']), unsafe_allow_html=True)
                    else:
                        # Fallback to regular markdown with colored brackets
                        st.markdown(color_brackets(msg['content']), unsafe_allow_html=True)
                        
                else:
                    # For user and other messages, use existing colored brackets
                    st.markdown(color_brackets(msg['content']), unsafe_allow_html=True)
            
            st.markdown('</div></div>', unsafe_allow_html=True)
        
        # Make buttons more compact
        with col2:
            if not is_editing:
                # Add on_click handler to set editing state
                if st.button("✏️", key=f"btn_edit_msg_{msg['id']}", help="Edit message", use_container_width=True):
                    st.session_state.editing_message_id = msg['id']
                    st.rerun()
            else:
                if st.button("💾", key=f"btn_save_msg_{msg['id']}", help="Save changes", use_container_width=True):
                    if new_content.strip():
                        update_message(msg['id'], msg['chat_id'], new_content)
                        st.session_state.editing_message_id = None
                        fetch_chat_messages.clear()
                        st.rerun()
        
        with col3:
            if st.button("🗑️", key=f"btn_delete_msg_{msg['id']}", help="Delete message", use_container_width=True):
                delete_message(msg['id'], msg['chat_id'])
                fetch_chat_messages.clear()
                fetch_chat_sessions_metadata.clear()
                st.session_state.current_page = 1
                st.session_state.pop('editing_message_id', None)
                st.rerun()
    
    col_a, _ = st.columns([1, 5])
    with col_a:
        if st.button("➕ Add", key=f"btn_add_after_msg_{msg['id']}"):
            st.session_state.adding_after_id = msg['id']
            st.rerun()

def render_add_message_form() -> None:
    """Render form for adding new messages."""
    st.subheader("Add New Message")
    new_role = st.selectbox("Role", options=list(ROLE_EMOJIS.keys()), key="select_new_message_role")
    new_content = st.text_area("Content", key="textarea_new_message_content", height=100)
    
    col_b1, col_b2 = st.columns([1, 5])
    with col_b1:
        if st.button("Submit New Message", key="btn_submit_new_message") and new_content.strip():
            add_message(
                st.session_state.selected_chat_id,
                new_role,
                new_content,
                st.session_state.get('adding_after_id')
            )
            st.session_state.pop('adding_after_id', None)
            fetch_chat_messages.clear()
            fetch_chat_sessions_metadata.clear()
            st.rerun()
    with col_b2:
        if st.button("Cancel", key="btn_cancel_new_message"):
            st.session_state.pop('adding_after_id', None)
            st.rerun()

def export_selected_chats(chat_ids: Set[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Export selected chat sessions as a dictionary."""
    conn = init_connection()
    result = {}
    
    for chat_id in chat_ids:
        messages = conn.execute(
            "SELECT id, chat_id, role, content, order_id FROM chat_messages WHERE chat_id = ? ORDER BY order_id ASC",
            (chat_id,)
        ).fetchall()
        
        result[chat_id] = [
            {
                'id': msg['id'],
                'role': msg['role'],
                'content': msg['content'],
                'order_id': msg['order_id']
            }
            for msg in messages
        ]
    
    return result

def render_sidebar(chat_sessions: List[Dict[str, Any]]) -> None:
    """Render sidebar with chat sessions and export functionality."""
    st.sidebar.header("Chat Sessions")
    
    if chat_sessions:
        export_container = st.sidebar.container()
        
        col1, col2 = st.sidebar.columns([1, 1])
        with col1:
            if st.button("Select All", key="btn_select_all_chats"):
                st.session_state.selected_sessions_for_export = {
                    session['chat_id'] for session in chat_sessions
                }
                st.rerun()
        with col2:
            if st.button("Clear All", key="btn_clear_all_chats"):
                st.session_state.selected_sessions_for_export.clear()
                st.rerun()
        
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Select Chat")
        
        # Get fresh message counts
        conn = init_connection()
        message_counts = {}
        with conn:
            for session in chat_sessions:
                count = conn.execute(
                    "SELECT COUNT(*) as count FROM chat_messages WHERE chat_id = ?",
                    (session['chat_id'],)
                ).fetchone()['count']
                message_counts[session['chat_id']] = count
        
        for session in chat_sessions:
            cols = st.sidebar.columns([1, 9])
            
            with cols[0]:
                is_selected = st.checkbox(
                    "Select for export",
                    key=f"export_checkbox_{session['chat_id']}", 
                    value=session['chat_id'] in st.session_state.selected_sessions_for_export,
                    label_visibility="collapsed"
                )
                if is_selected:
                    st.session_state.selected_sessions_for_export.add(session['chat_id'])
                else:
                    st.session_state.selected_sessions_for_export.discard(session['chat_id'])
            
            with cols[1]:
                is_current = (session['chat_id'] == st.session_state.selected_chat_id)
                emoji = SELECTED_CHAT_EMOJI if is_current else CHAT_EMOJI
                msg_count = message_counts[session['chat_id']]
                label = f"{emoji} {session['chat_id'][:8]}... ({msg_count} msgs)"
                if st.button(
                    label,
                    key=f"btn_select_chat_{session['chat_id']}",
                    use_container_width=True,
                    type="primary" if is_current else "secondary"
                ):
                    st.session_state.selected_chat_id = session['chat_id']
                    st.session_state.current_page = 1
                    fetch_chat_messages.clear()
                    st.rerun()
        
        if st.session_state.selected_sessions_for_export:
            with export_container:
                if st.button("📦 Export Selected", key="btn_export_selected", type="primary"):
                    export_data = export_selected_chats(st.session_state.selected_sessions_for_export)
                    st.download_button(
                        "⬇️ Download JSON",
                        key="btn_download_json",
                        data=json.dumps(export_data, indent=2, ensure_ascii=False),
                        file_name="selected_chats.json",
                        mime="application/json"
                    )

def main(chat_ids: Optional[Sequence[str]] = None):
    """Main application entry point.
    Args:
        chat_ids: Optional list of chat IDs to display. If None, shows all chats.
    """
    st.title("Chat Messages")
    st.markdown(CSS, unsafe_allow_html=True)
    
    chat_sessions = fetch_chat_sessions_metadata(chat_ids)
    
    if chat_sessions:
        if st.session_state.selected_chat_id is None:
            st.session_state.selected_chat_id = chat_sessions[0]['chat_id']
        elif chat_ids and st.session_state.selected_chat_id not in chat_ids:
            # Reset selection if current selection isn't in filtered list
            st.session_state.selected_chat_id = chat_sessions[0]['chat_id']
        
        render_sidebar(chat_sessions)
        
        per_page = st.session_state.messages_per_page
        current_page = st.session_state.current_page
        
        # Load messages for the selected chat (paginated)
        with st.spinner("Loading messages..."):
            messages = fetch_chat_messages(st.session_state.selected_chat_id, current_page, per_page)
            total_msgs = len(messages)
            max_page = (total_msgs // per_page) + (1 if total_msgs % per_page != 0 else 0)
        
        st.subheader(f"Messages Page {current_page} of {max_page}")
        
        for msg in messages:
            render_message(msg)
            if 'adding_after_id' in st.session_state and st.session_state.adding_after_id == msg['id']:
                render_add_message_form()
        
        if 'adding_after_id' not in st.session_state:
            with st.expander("Add a new message at the start", expanded=False):
                render_add_message_form()
        
        # Pagination controls
        col_prev, col_page, col_next = st.columns([1,2,1])
        with col_prev:
            if st.button("◀️ Previous", disabled=(current_page <= 1)):
                st.session_state.current_page -= 1
                st.rerun()
                
        with col_page:
            st.write(f"Page {current_page} of {max_page}")
        
        with col_next:
            if st.button("Next ▶️", disabled=(current_page >= max_page or max_page == 0)):
                st.session_state.current_page += 1
                st.rerun()
                
    else:
        st.warning("No chat sessions found in the database.")

if __name__ == "__main__":
    # Example: To show all chats
    # main()
    
    # Example: To show specific chats only
    main(chat_ids=[
        '47b1a3ae-d615-476e-b0a1-e93f39656b8d',
        'd3ef72dc-3612-40af-a6e6-816b173cf587',
        '2c208186-5911-40a8-96bf-c793fd62bd1a',
        '1a302bfc-0cc4-4352-9400-66170de13d04',
        'eb67ad22-4c0e-4ce7-827e-88c023bf2ab2',
        '3ece29d8-90e1-4cf6-ae48-b2e541552270',
        '9a93120e-0c2c-422b-ab05-8322cf75266d',
        '2ca4a7b6-4dcb-42ed-8062-8194ee1c5928',
        '71ae4bcd-e1cb-4271-8837-136ad6ecf252',
        '6c8abd8c-3bd9-4629-bdb7-863d8c09189c',
        'cae144d0-ad42-4b2f-bf98-c92f4e89463f',
        'aba20720-7e07-48ab-8a26-6ca9ec6208f8',
        'f2272302-859b-490c-8541-50b6fbae28e2',
        '8b7fe75c-53eb-41ab-a707-ba3538d2f2ec',
        'd6cc91a9-3046-4ef6-8baa-1c8eca802ac7',
        '7daaaf37-245b-4b31-baac-8a48068ad1b1',
        'fb880ade-f2fd-49a0-8ec6-ef51528f0cb8',
        '5b6e531b-18ca-4aeb-8933-061525fc1ae3',
        '378d1106-62e0-4ff9-b451-625c9fc76ac7',
        '8aecd099-2564-4dcb-a14c-520a94d95302',
        'eb481e16-3769-41ae-b721-e35e59aea2ec',
        'b03290a1-fdbe-4068-9978-87170c34586d',
        '731475e1-0f31-443c-afba-9a33ff8990b7',
        'bb2505f4-1657-4ba7-8640-71703bbd1128',
        '59a5adb7-704f-4176-87d0-cfdcc2e5f1d1',
        '16e1bb87-c928-4803-a99c-ffd03e1b30ee',
        'd4b149cf-8837-4b64-bdc2-d115fa529c39',
        'e767d06d-3302-4bc8-a165-68678a605346',
        'a009dd72-412c-4773-a4c4-883f39b21a7f',
        '27b5cbe1-69f5-44eb-a844-7528b8f80ee8',
        'ac0b1569-4068-4082-bf2c-c8a4738f8e72',
        '577c50dd-4ff0-4a8f-a10b-264b810b4d77',
        '4f89e4c2-628f-416c-a115-0d8f962eb663',
        'edf92286-a728-40ec-b4f5-822244506190',
        '80d9044d-dcec-47f0-beed-2e314742610e',
        '5cedae83-f34c-4008-88db-a619c8907336',
        '69cd2de8-ff55-4928-a0a3-3d0272cc44fd',
        'e0ce665a-4ada-4bd9-a010-b3ff67a8096f',
        'eab60fe4-f882-43ce-bce1-c00e38e5700f',
        '03e5fca3-8b06-4eb7-b62d-02eb0a6fa21e',
        'f485093a-3d1a-49de-b53b-7a52b61300ef',
        'fcf2bc35-2480-4d5e-9e28-0e415bd94106',
        '90f0b525-a4f7-470d-9714-8b316b220451',
        'be8fa5d3-7e7c-4c37-9487-f65ae1bb6b10',
        '68d3b7a6-6a21-4a0f-b2fa-26736a6cd0f2',
        '5cdfdc69-30a0-4f8e-8c4c-e446867de648',
        '446a3358-aaaa-4583-b2e1-f4ff79181a0e',
        'e29b2293-f066-4ec4-9852-b9181c128a5f',
        'b61bfe55-d162-40e3-a8eb-14136b89d15a',
        '52ce0b2d-2218-46cb-b87a-c03c3faa5560',
        '3150fbe0-e219-43ea-94a1-9d057836ee7a',
        '0a895746-0a94-4a76-80e5-9eee7d4aa4dc',
        '5da6e688-baf5-4651-825b-15b0e37fb33f',
        '0d61e07d-3104-49dc-9dd5-cda670e6d2eb',
        '0c272f97-3ee0-42e2-9e53-6cc0c98f5d65',
        'd178a228-8be9-4769-aec1-e6bb1a199f85',
        'd7c0d45a-fa49-426e-ba57-63c8eab945ea',
        'c5e1aae9-8d14-428e-8850-4a6d6f7b6535',
        'ec72a071-caf4-40b2-b31d-baa286ca4a42',
        '541f7238-cecf-435c-8ee6-f9fc2f0f0b1e',
        'ff3b453a-481a-4bf5-9ac2-cb19774bf1e1',
        '0a87f4d5-fc6b-44b3-9d75-6f962b2c74d9',
        'f6edfb6f-a956-4cc4-9138-3aae46865df1',
        'affcaa0c-8bf4-4827-9e2a-369aede94ee2',
        'fab4e5de-bc53-4904-bf8c-3632ea43dffa',
        '86583b9f-54ae-4465-a656-9ed916a9d69d',
        '4206379a-faed-48e3-8f88-eda94f33d0f4',
        '704d164e-1c02-4991-a841-300f1a6009d0',
        '0292b139-17b8-471c-8ab9-bd569200aef7',
        'e23df54b-4f45-4d08-adfc-4b469bb71fe2',
        '66220e24-2c15-4156-81f3-398401931508',
        '15eb9d8e-0db8-4b40-97eb-eba74bbaaab4',
        '3a695a12-4c0b-4456-92e0-988ff0197aa9',
        '009979b4-ecc8-4a61-a262-1a1451310247',
        '03971059-626f-442d-8451-e02d33438754',
        '8d71f3c2-fbed-4e37-9fb2-18019e1f025e',
        'a4eeb509-7788-4002-b241-d35de2d930c5',
        '2e74e035-9167-4e40-b917-5ce797ac6f80',
        '091c2935-5a51-4433-9aed-4f75898940a7',
        'cde15516-e0b3-481a-85f3-23f873277c6d',
        'abccac55-2c1e-457d-ba1e-43a9d3ccfd64',
        'ce05ed8e-0c8a-41ec-9856-8cd4e0342d67',
        'bf102553-b777-4477-ba70-9b233ff9921c',
        'a43b5e95-e63c-4948-82a9-96e7e8d12c94',
        '9419753e-b77d-4e4d-8ca7-bbcf7c85085f',
        '81b1dad8-af4b-4207-ac84-ee1fd4826683',
        'fadcf1cf-9f76-4756-ba58-30777797f205',
        '8cbc0f8a-d72e-4dcf-be7c-5d75a3da5715',
        '5e8be409-d7e3-471e-bda7-73ae4031a891',
        'fe1e881f-12b5-4dca-b471-d5f35e0c6828',
        '9fe19665-1f2b-45c4-9e95-23d1b1e5da76',
        '066d5666-9d36-4cdd-9874-61dcbb5ec67d',
        '9965285f-0489-4db1-8cc2-942e417f04f8',
        '6ee09c91-bc19-4111-85ed-8ce4773e961f',
        '794eb310-29b8-4bf6-87d5-9f8d44471f4c',
        '96597c45-6c0d-4e6b-ab11-509cd8adfffe',
        'a17b350d-0b42-4a09-af62-f417c486d1d9',
        '74911670-6341-4d5e-b73c-2d0e48342840',
        'bafc4d34-842c-4e11-a673-d7efd5bd657b',
        '86988f0d-549b-4a66-b5b8-48524ec70745',
        'e5b64c74-722f-459c-9db2-e43f199a3a84',
        '2a78ad78-b50a-42c2-ab8c-dd290f00166b',
        '192c67b8-45fa-467e-8a1e-3616144b26f3',
        'f9ef5d05-de57-49fc-9b78-75d9b6a75c17',
        'd55efb20-5ad0-40d7-9723-5a4997b3da80',
        '3d5eb660-aff5-4394-91a8-f5c08f43ab36',
        'f303c91f-7efd-4479-a994-f352cbad1c04',
        'c2d38a1d-dae1-42e6-ae54-e4d3a0c3412a',
        'b4bc8674-bbfc-44ce-a281-9daf808c1363',
        '068e10c1-4e91-491d-a527-0e2ef21c16ae',
        '85e34ea9-d656-449c-aaa3-6cf12316d976',
        'b3ffa1cb-489c-4e1d-920e-c3c5bf934cd7',
        '80675536-38b5-4a01-8a97-2468b434efc4',
        '04c254e3-03dd-4b3d-8183-74ba38ff7536',
        '3422e06c-6177-4442-a05c-61fed8601fe1',
        'e2947101-22ee-4e6d-ad81-331a89429b7d',
        'd6ec3802-5208-4b02-8400-e072c1355f12',
        '55d04ad7-aac9-4b47-8581-929552180dd4',
        'e0064747-351a-4c47-8db3-34bfcf57ded6',
        '48ef5ed7-25e2-4ad2-b58e-2257d7a10d6e',
        '530e6e3f-913c-41bb-aed6-fe0d1ecd5f1e',
        '34e1c268-9a57-4d7b-9a54-5bd79f22568f',
        '48875ff5-d408-4f1d-859e-4c528faf5206',
        '7c6625b4-0134-413b-bf38-02285bb984bb',
        '4602444f-78c9-4eb2-970a-08a33a372387',
        '352a1a25-cedb-4d0e-b1e4-64d88d616fc7',
        '10d0f59b-214d-4496-ac54-f549dccc0a73',
        'a024c91c-12ff-4aa2-8cd6-8e056141c7b6',
        'e78ebff3-1d77-4837-a51f-67509cfaf24c',
        '43186c5b-a20d-49d4-af9c-b902db80095e',
        'a5446c9a-8837-44e5-82c9-d90a6d68f63e',
        'ae7ec17a-dd84-427d-bb3d-8bba02dc8854',
        '9c9793b6-8ae1-4938-9bf4-8d58f3b5fd95',
        'c3b2c495-ffad-4b29-b5fd-cb04e768217c',
        '2416f941-6281-453d-93e2-690c410c2037',
        '5190f01d-156f-441a-8008-87c7b5ee2106',
        'fe2573e0-5152-4927-a28f-4203dfabb84a',
        'df21a1d2-4eb0-4493-8545-000fc0cc15ae',
        '378a2fa9-f924-437e-ae98-830072e86819',
        'ac29469b-1edc-4db7-a65f-91978e911278',
        '756fd052-3dcf-4137-a7ff-22a18b72190a',
        '324fa4e4-bf2e-4458-88a3-bea864c7adc2',
        '2d0f30e7-6e43-42b9-b3ac-1e5613e32446',
        '144524a7-fdd8-4141-be6e-59abd3896b84',
        '25cde292-a706-43da-9e22-95ff4ae4cb46',
        '0456139c-af68-4c84-b41c-0b3b381e91e4',
        '7b298675-eb7c-442a-97df-6f57dca6f865',
        'ccd4e5a1-3915-4454-bc20-8ff20f3c3abb',
        '35e46b26-5f16-4e76-b265-f0f141fb27ab',
        'e3e2cfde-01d2-43a3-af5b-314fb9441b37',
        '4ddb0504-2d74-4ee2-b1ef-b3e2e51fc05d',
        'a35976ca-68bf-4898-9916-255a924694cd',
        '2f260b52-e320-47bc-a8ef-47de689d6328',
        '8f83b88d-1577-4d27-8604-bce4ba5be26f',
        '1d2bcf77-9c36-4db7-84fe-903b1cf04a96',
        '91bb65db-a8df-40f9-acb6-5f12b7ac78c3',
        '444b12be-9eff-4b85-b1da-47fe15469393',
        'b2f79494-b8b4-433b-986b-05e9e2bef895',
        'c5fb497c-fe49-4a44-831e-1d4997ebcbee',
        '9dc1e01c-aec6-4372-af65-522a45ea5c47',
        '5aa1d185-71ae-44f6-86c2-9254c9cb869c',
        '87a2d8f2-52e7-42c6-bf3e-4bc13e595302',
        '9b675f98-5371-4d6a-a858-d79e520c83ae',
        '404e11a5-d80d-4757-8a65-0c8fe0ae5a39',
        'b9439231-b988-42e1-98ce-b373e70213f2',
        '181f6880-89cc-45c5-9755-de04e59e8165',
        '09611e74-c9fe-4c02-acee-8d4d6a999b09',
        '3df7912d-2703-47cd-8d72-8e1efb57eddc',
        'f7b43a53-a72c-454e-8155-c0a4cbd43107',
        '89f12e88-72d4-4a0c-ac41-9cd8af6319d2',
        '1e32d6e7-8a91-46ab-b627-12d02c10e83f',
        '908aec54-8267-4a28-af93-93fe6ec46c46',
        'a11bcf02-94a5-46d9-b532-3a4626a7fe9b',
        'c9323f95-ef11-4cc7-aa14-4839109d97a7',
        '0aaa9d59-632d-4c0a-91b3-b8d6f1be1661',
        '2f034207-3552-4b4f-af44-28e74cac98d3',
        'aaa4e013-9596-4ca6-9b32-0f7688a061f7',
        'ea1796a8-50f0-4773-be14-3a0f14f106d1',
        'c651d0f2-7510-4ef4-adb9-4edeca6d55e4',
        '413791d0-ad9d-4f1b-b12e-be3f74151f49',
        '0de929a2-9d2d-4f43-bdc1-7978af4fcb9e',
        'c96ef9d4-7ca9-4b27-8977-175fd0e1851f',
        '9104bce9-4ee8-4eb3-ab3b-6958e76911c3',
        '01de3904-af9e-4f7a-944b-89212fe1b00a',
        '6690fab1-6b9a-4cec-9a09-ba6c29b8a110',
        '89d62d39-7560-4fcc-b3bc-5a2618ea2e48',
        '5f430603-d868-4dd0-a442-3d889265608b',
        'faae11c2-5725-4eb7-8a5e-b95ad759ded6',
        'af611e10-c172-4ea4-95e4-e9e794afed65',
        '83f5e69b-fee5-4b85-bbe4-b0c8e9821412',
        'a61ee11f-f3f5-49dd-96d2-3735b8e7416d',
        '4a3fa852-aa21-4905-900a-722e3f11de8f',
        '21c9898a-a237-4c3d-9c0d-89cb22984652',
        '0178d669-00fb-4292-a834-15ffbcf74c83',
        'a1f25dbe-606b-4217-8db3-3a9efff05282',
        '728b2b6e-473a-4c88-a52d-a101fb058ae5',
        '043775fd-78d5-4c25-b81e-0ba568e7ede7',
        '53a6d072-40d3-4976-8cd5-876ed7dbc4ab',
        'fb2bcbd7-fc38-4bc8-9cf2-456123f65492',
        '078003fc-4fe2-44d0-b3b2-e730395484d6',
        '708500a4-61c3-4718-8358-2602b17bea62',
        '2e438334-9ea0-4f0c-b84f-f107de4cefb0',
        '6442da7e-a3e5-452e-96e3-f872a8714800',
        '1fe1b4a6-d078-4c58-8bc5-59b8f23534d3',
        '9a8fe33c-519d-4eda-b87e-9a8873db6865',
        'cf4b1a00-0392-41dc-84ee-5156192da1e2',
        '22896b71-791f-4267-8c94-844afca1ac41',
        '354379c9-e974-493b-a20e-5d2595754280',
        'ddd58cbd-ebd6-487f-8e32-22d8b854dd7e',
        '4016ef6f-3c44-4b99-ab17-a00014fec294',
        '68374bc4-f243-4b39-9c2c-2753ca7f7555',
        '140de2e0-fac1-4335-af0f-3ce0dcc566c6',
        '2adfaa0d-46fb-4abf-b488-a6f998aae307',
        '37eea850-c63d-41ad-b140-a443f1a8a2cc',
        '174c69c8-0f91-4416-8f39-47b2e04178d6',
        'bcb8898f-7093-4a6a-a2e3-4ee287c80bab',
        '2564e68c-4a19-4252-ba6d-c3e72b7fbaf6',
        '81f6d580-1766-481a-a109-f1e7573d58d8',
        '750e4c76-553e-4d42-b462-f6fc919b5609',
        '5612b36a-560f-41cb-867f-399d6fe09f47',
        '9ec86475-5184-429f-9e8d-611891228258',
        'daff3055-9b5b-47bf-b1a2-7e8fe09e482d',
        'd1a1b484-4f01-4e33-b25b-753db36d1394',
        '8a3df2e8-8d1c-4bdc-8114-078a13b227d5',
        '490da732-9df1-419a-a3e3-8969b7c97554',
        'f5791edc-5aea-49a1-acb8-5420a16fb682',
        '46ef5201-39bb-4ce8-acba-c19cd7b8c5a8',
        '95eeaedd-11e0-4521-ac74-44eece8cd5de',
        'ccba5e12-e1b8-4ac7-8f85-b6de9069f16a',
        'd01bb5af-62b5-4b4c-abe4-e754389693f7',
        '9b2b80ca-07e8-4075-9c43-19c94ad169c2',
        'c5177d06-82a7-4e00-a9cb-403a2cf1fd5e',
        '8d5c222c-1164-4cfa-8f3a-2c5a58c155b0',
        '1009b2b0-7bc7-4f13-9fb0-79ce45580e30',
        '53f96fe8-39eb-4529-8b07-6d74ec6be406',
        '94f11b5b-0bfe-427b-8654-92cff2d9ba81',
        '18f75f66-3aca-4a71-afa2-8d6fdd079979',
        '2ad38250-9768-48d0-9dfe-327d39a1bc16',
        '65328d68-491d-4e5b-920f-1409c4906bdb',
        'f62c764a-5141-42ec-8947-d534b4c03eae',
        '6b83bd55-afc6-4d19-8e26-94c52d468552',
        'c71f2da1-5a0f-4f08-acd7-f72405ab1a2b',
        '408246de-3182-40c7-bd0a-778c4be1a5b9',
        'fc65fa76-0130-40e4-957b-99103501833f',
        'e6f3baab-b181-4e37-81fe-c0a91dd0a600',
        '2a905501-bac2-45f5-9990-70f1d544727e',
        '74b18487-05f1-4b54-b2f8-062258fea62b',
        'd08a9070-e956-4720-9d76-87d0b542ebf8',
        '7e92378e-d7f8-4147-a9a5-d6adcadc6d55',
        'cee64411-ae93-41be-b197-8cc06980c454',
        '79404dc7-43c1-47bb-a12c-d3b93234e763',
        'eb587e9b-c417-4129-b9fc-5a3f2cd6b62b',
        '4eb7371e-53da-4e4a-b48e-4418a39fa702',
        '57fd3dbb-482d-4774-b95c-66ab7b1d98ee',
        'cda00fd7-9931-4492-953c-c12666456856',
        '4a59a91b-47f9-4d5b-b6ce-5f87c2aed2e3',
        '979196c8-e513-417e-b079-09a49b25dbc5',
        'a83e74da-75a1-46d6-8c66-f8da71ec213b',
        'b64e1924-e703-4e7f-ab17-d091faa2436c',
        '3141f36f-4427-4a69-ae21-89e46eb3e234',
        '59fa4078-2bd0-4fa4-bf6a-8fbcf5551951',
        '2f5ed003-09ee-42f4-b562-386c81662f46',
        'a65f1fb9-d75f-41d8-84a3-cc05e05a03f5',
        '37a3cb15-449e-412f-8d12-30a813929b4c',
        'd0ad1581-c0fd-4d0f-9c38-f3f2b5adffdc',
        '883c769c-4b24-4689-8dee-740261d6d6e4',
        '1cd82bf8-480a-456d-842d-4a224187938a',
        'ae6547d0-3f64-477e-9d17-f365d29ce742',
        'd056e6fc-abba-4885-9522-e1cd95f36a54',
        'b7550dd1-4068-433b-bc51-b87dfd64eed8'
    ]) 