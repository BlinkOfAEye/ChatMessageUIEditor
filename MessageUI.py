import streamlit as st
import sqlite3
import json
import re
from typing import Dict, Set, Optional, List, Any
from datetime import datetime

# Constants
CSS = """
<style>
.message-container {
    padding: 10px;
    margin: 5px 0;
    width: 85%;
}
.message-content {
    display: inline-block;
    vertical-align: top;
}
.role-header {
    font-weight: bold;
    margin-bottom: 5px;
}
.role-user { color: #2196F3; }
.role-assistant { color: #4CAF50; }
.role-system { color: #FF9800; }
.role-tool { color: #607D8B; }
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
    "#FFFF33",  # Yellow
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
def fetch_chat_sessions_metadata() -> List[Dict[str, Any]]:
    """Fetch chat session metadata efficiently."""
    conn = init_connection()
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
    with st.expander(f"{ROLE_EMOJIS.get(msg['role'], '❓')} {msg['created_at']}", expanded=(msg['role'] != 'system')):
        col1, col2, col3 = st.columns([6, 1, 1])
        
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
                    label_visibility="collapsed"
                )
            else:
                colored_content = color_brackets(msg['content']) if '<' in msg['content'] else msg['content']
                st.markdown(colored_content, unsafe_allow_html=True)
            
            st.markdown('</div></div>', unsafe_allow_html=True)
        
        with col2:
            if not is_editing:
                if st.button("Edit", key=f"btn_edit_msg_{msg['id']}"):
                    st.session_state.editing_message_id = msg['id']
                    st.rerun()
            else:
                if st.button("Save", key=f"btn_save_msg_{msg['id']}"):
                    if new_content.strip():
                        update_message(msg['id'], msg['chat_id'], new_content)
                        st.session_state.editing_message_id = None
                        fetch_chat_messages.clear()
                        st.rerun()
        
        with col3:
            if st.button("🗑️", key=f"btn_delete_msg_{msg['id']}", help="Delete message"):
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

def export_selected_chats(chat_ids: Set[str]) -> Dict:
    """Export chats with optimized queries."""
    conn = init_connection()
    result = {"chats": []}
    
    try:
        with conn:
            data = conn.execute(f"""
                SELECT 
                    cs.chat_id,
                    cs.model,
                    cm.id,
                    cm.role,
                    cm.content,
                    cm.created_at
                FROM chat_sessions cs
                JOIN chat_messages cm ON cs.chat_id = cm.chat_id
                WHERE cs.chat_id IN ({','.join('?' * len(chat_ids))})
                ORDER BY cs.chat_id, cm.order_id ASC
            """, tuple(chat_ids)).fetchall()
            
            current_chat = None
            for row in data:
                if row['chat_id'] != current_chat:
                    current_chat = row['chat_id']
                    result["chats"].append({
                        "chat_id": current_chat,
                        "model": row['model'],
                        "messages": []
                    })
                result["chats"][-1]["messages"].append({
                    "id": row['id'],
                    "role": row['role'],
                    "content": row['content'],
                    "created_at": row['created_at']
                })
        return result
    except sqlite3.Error as e:
        st.error(f"Error exporting chats: {str(e)}")
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

def main():
    """Main application entry point."""
    st.title("Chat Messages")
    st.markdown(CSS, unsafe_allow_html=True)
    
    chat_sessions = fetch_chat_sessions_metadata()
    
    if chat_sessions:
        if st.session_state.selected_chat_id is None:
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
    main() 