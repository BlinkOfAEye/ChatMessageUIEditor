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
DEFAULT_STATE = {
    'global_tag_colors': {},
    'editing_message_id': None,
    'selected_chat_id': None,
    'selected_sessions_for_export': set()
}

for key, default in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = default

@st.cache_resource
def init_connection() -> sqlite3.Connection:
    """Initialize database connection and ensure indexes exist."""
    conn = sqlite3.connect('chatbot.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    # Enable WAL mode for better concurrent access
    conn.execute('PRAGMA journal_mode=WAL')
    
    # Create indexes for frequently accessed columns
    with conn:
        # Index for chat_id lookups in messages
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id 
            ON chat_messages(chat_id)
        ''')
        # Index for message ordering
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id 
            ON chat_messages(chat_id, id)
        ''')
        # Index for chat sessions ordering
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_sessions_created_at 
            ON chat_sessions(created_at DESC)
        ''')
    
    return conn

@st.cache_data(ttl=60)
def fetch_chat_sessions_metadata() -> List[Dict[str, Any]]:
    """Fetch only chat session metadata without loading messages."""
    conn = init_connection()
    cursor = conn.execute("""
        SELECT 
            cs.chat_id,
            cs.model,
            cs.created_at,
            (SELECT COUNT(*) FROM chat_messages cm WHERE cm.chat_id = cs.chat_id) as message_count 
        FROM chat_sessions cs 
        ORDER BY cs.created_at DESC
    """)
    return [dict(session) for session in cursor.fetchall()]

@st.cache_data(ttl=60)
def fetch_chat_messages(chat_id: str) -> List[Dict[str, Any]]:
    """Fetch messages for a specific chat."""
    if not chat_id:
        return []
    
    conn = init_connection()
    cursor = conn.execute(
        "SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY id ASC",
        (chat_id,)
    )
    return [dict(msg) for msg in cursor.fetchall()]

def clear_caches() -> None:
    """Clear all cached data."""
    fetch_chat_messages.clear()
    fetch_chat_sessions_metadata.clear()

def update_message(message_id: int, new_content: str) -> None:
    """Update message content."""
    conn = init_connection()
    try:
        conn.execute(
            "UPDATE chat_messages SET content = ?, updated_at = ? WHERE id = ?",
            (new_content, datetime.now().isoformat(), message_id)
        )
        conn.commit()
        clear_caches()
    except sqlite3.Error as e:
        st.error(f"Error updating message: {str(e)}")

def add_message(chat_id: str, role: str, content: str, after_msg_id: Optional[int]) -> None:
    """Add a new message using a transaction."""
    conn = init_connection()
    try:
        with conn:  # Start transaction
            if after_msg_id:
                # Update IDs in a single query for messages after the insertion point
                conn.execute("""
                    UPDATE chat_messages 
                    SET id = id + 1 
                    WHERE chat_id = ? AND id > ? 
                    ORDER BY id DESC
                """, (chat_id, after_msg_id))
                new_id = after_msg_id + 1
            else:
                # Get max ID efficiently
                result = conn.execute("""
                    SELECT COALESCE(MAX(id), 0) 
                    FROM chat_messages 
                    WHERE chat_id = ?
                """, (chat_id,)).fetchone()
                new_id = result[0] + 1

            # Insert new message
            conn.execute("""
                INSERT INTO chat_messages (id, chat_id, role, content, created_at) 
                VALUES (?, ?, ?, ?, ?)
            """, (new_id, chat_id, role, content, datetime.now().isoformat()))
            
        clear_caches()
    except sqlite3.Error as e:
        st.error(f"Error adding message: {str(e)}")

def delete_message(msg_id: int, chat_id: str) -> None:
    """Delete a message and reorder remaining messages in a single transaction."""
    conn = init_connection()
    try:
        with conn:  # Start transaction
            # Get the current ID before deletion
            current_id = conn.execute(
                "SELECT id FROM chat_messages WHERE id = ? AND chat_id = ?",
                (msg_id, chat_id)
            ).fetchone()
            
            if current_id:
                # Delete the message
                conn.execute(
                    "DELETE FROM chat_messages WHERE id = ? AND chat_id = ?",
                    (msg_id, chat_id)
                )
                
                # Update subsequent message IDs in a single query
                conn.execute("""
                    UPDATE chat_messages 
                    SET id = id - 1 
                    WHERE chat_id = ? AND id > ?
                """, (chat_id, msg_id))
            
        clear_caches()
    except sqlite3.Error as e:
        st.error(f"Error deleting message: {str(e)}")

def color_brackets(text: str) -> str:
    """Apply color highlighting to XML-style tags."""
    def process_xml_tag(match):
        tag_name = match.group(1).lstrip('/').split()[0]
        if tag_name not in st.session_state.global_tag_colors:
            color_idx = hash(tag_name) % len(BRIGHT_COLORS)
            st.session_state.global_tag_colors[tag_name] = BRIGHT_COLORS[color_idx]
        return f'<span style="color: {st.session_state.global_tag_colors[tag_name]}">&lt;{match.group(1)}&gt;</span>'
    
    return re.sub(r'<([/\w][^>]*?)>', process_xml_tag, text)

def render_message(msg: Dict[str, Any]) -> None:
    """Render a single message with controls."""
    is_expanded = msg['role'] != 'system'
    expander_label = f"{ROLE_EMOJIS.get(msg['role'], '❓')} {msg['created_at']}"
    
    with st.expander(expander_label, expanded=is_expanded):
        col1, col2, col3 = st.columns([6, 1, 1])
        
        with col1:
            is_editing = st.session_state.editing_message_id == msg['id']
            edit_indicator = "✏️ " if msg.get('updated_at') else ""
            
            st.markdown(f"""
                <div class="message-container">
                    <div class="role-header role-{msg['role']}">{msg['role'].upper()} {edit_indicator}</div>
                    <div class="message-content">
                """, unsafe_allow_html=True)
            
            if is_editing:
                new_content = st.text_area("Content", value=msg['content'], 
                                         key=f"textarea_edit_msg_{msg['id']}", 
                                         label_visibility="collapsed")
            else:
                st.markdown(color_brackets(msg['content']), unsafe_allow_html=True)
            
            st.markdown('</div></div>', unsafe_allow_html=True)
        
        with col2:
            if st.button("Edit" if not is_editing else "Save", key=f"btn_edit_msg_{msg['id']}"):
                if is_editing and new_content:
                    update_message(msg['id'], new_content)
                    st.session_state.editing_message_id = None
                    st.success("Message updated!")
                else:
                    st.session_state.editing_message_id = msg['id']
                st.rerun()
        
        with col3:
            if st.button("🗑️", key=f"btn_delete_msg_{msg['id']}", help="Delete message"):
                delete_message(msg['id'], msg['chat_id'])
                st.success("Message deleted!")
                st.rerun()
    
    col1, _ = st.columns([1, 7])
    with col1:
        if st.button("➕ Add", key=f"btn_add_after_msg_{msg['id']}"):
            st.session_state.adding_after_id = msg['id']
            st.rerun()

def render_add_message_form() -> None:
    """Render form for adding new messages."""
    st.subheader("Add New Message")
    new_role = st.selectbox("Role", options=list(ROLE_EMOJIS.keys()), key="select_new_message_role")
    new_content = st.text_area("Content", key="textarea_new_message_content", height=100)
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("Submit", key="btn_submit_new_message") and new_content.strip():
            add_message(st.session_state.selected_chat_id, new_role, 
                      new_content, st.session_state.adding_after_id)
            st.session_state.pop('adding_after_id')
            st.success("Message added!")
            st.rerun()
    with col2:
        if st.button("Cancel", key="btn_cancel_new_message"):
            st.session_state.pop('adding_after_id')
            st.rerun()

def export_selected_chats(chat_ids: Set[str]) -> Dict:
    """Export selected chats using efficient queries."""
    conn = init_connection()
    result = {"chats": []}
    
    try:
        # Use a single transaction for the entire export
        with conn:
            for chat_id in chat_ids:
                # Get chat session data
                chat_data = conn.execute("""
                    SELECT cs.*, COUNT(cm.id) as message_count 
                    FROM chat_sessions cs 
                    LEFT JOIN chat_messages cm ON cs.chat_id = cm.chat_id 
                    WHERE cs.chat_id = ?
                    GROUP BY cs.chat_id
                """, (chat_id,)).fetchone()
                
                if chat_data:
                    # Get messages in a single query
                    messages = conn.execute("""
                        SELECT id, chat_id, role, content 
                        FROM chat_messages 
                        WHERE chat_id = ? 
                        ORDER BY id ASC
                    """, (chat_id,)).fetchall()
                    
                    if messages:
                        result["chats"].append({
                            "chat_id": chat_id,
                            "model": chat_data['model'],
                            "messages": [dict(msg) for msg in messages]
                        })
        return result
    except sqlite3.Error as e:
        st.error(f"Error exporting chats: {str(e)}")
        return result

def render_sidebar(chat_sessions: List[Dict[str, Any]]) -> None:
    """Render sidebar with chat sessions and export functionality."""
    st.sidebar.header("Chat Sessions")
    
    if chat_sessions:
        # Export controls at the top
        export_container = st.sidebar.container()
        
        # Select All / Clear All buttons
        col1, col2 = st.sidebar.columns([1, 1])
        with col1:
            if st.button("Select All", key="btn_select_all_chats"):
                st.session_state.selected_sessions_for_export = {
                    session['chat_id'] for session in chat_sessions
                }
        with col2:
            if st.button("Clear All", key="btn_clear_all_chats"):
                st.session_state.selected_sessions_for_export.clear()
        
        st.sidebar.markdown("---")
        
        # Chat selection section
        st.sidebar.markdown("### Select Chat")
        for session in chat_sessions:
            cols = st.sidebar.columns([1, 9])
            
            # Checkbox for export
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
            
            # Chat selection button
            with cols[1]:
                is_current = session['chat_id'] == st.session_state.selected_chat_id
                emoji = SELECTED_CHAT_EMOJI if is_current else CHAT_EMOJI
                label = f"{emoji} Chat {session['chat_id'][:8]}... ({session['message_count']} msgs)"
                if st.button(
                    label,
                    key=f"btn_select_chat_{session['chat_id']}",
                    use_container_width=True,
                    type="primary" if is_current else "secondary"
                ):
                    st.session_state.selected_chat_id = session['chat_id']
                    st.rerun()
        
        # Export button
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
    
    # Load only session metadata initially
    chat_sessions = fetch_chat_sessions_metadata()
    
    if chat_sessions:
        # Initialize selected chat ID if not set
        if st.session_state.selected_chat_id is None:
            st.session_state.selected_chat_id = chat_sessions[0]['chat_id']
        
        render_sidebar(chat_sessions)
        
        # Load messages only for the selected chat
        with st.spinner("Loading messages..."):
            messages = fetch_chat_messages(st.session_state.selected_chat_id)
        
        # Show message count
        st.subheader(f"Messages ({len(messages)})")
        
        # Render messages for selected chat
        for msg in messages:
            render_message(msg)
            if 'adding_after_id' in st.session_state and st.session_state.adding_after_id == msg['id']:
                render_add_message_form()
    else:
        st.warning("No chat sessions found in the database.")

if __name__ == "__main__":
    main() 