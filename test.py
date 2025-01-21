import pytest
import sqlite3
from datetime import datetime
import streamlit as st
from MessageUI import (
    fetch_chat_messages, 
    fetch_chat_sessions_metadata, 
    update_message, 
    add_message, 
    delete_message,
    export_selected_chats,
    DEFAULT_STATE,
    init_connection
)

@pytest.fixture
def setup_session_state():
    """Initialize session state with actual data."""
    for key, default in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = default
    st.session_state.selected_chat_id = "test_chat_id"

@pytest.fixture
def mock_db_data():
    """Create mock database data."""
    return {
        'chat_sessions': [
            {
                'chat_id': 'test_chat_id',
                'model': 'test_model',
                'created_at': datetime.now().isoformat(),
                'message_count': 1
            }
        ],
        'chat_messages': [
            {
                'id': 1,
                'chat_id': 'test_chat_id',
                'role': 'user',
                'content': 'Test message',
                'created_at': datetime.now().isoformat(),
                'order_id': 1000.0
            }
        ]
    }

@pytest.fixture
def mock_conn(mocker):
    """Create a mock database connection."""
    mock = mocker.MagicMock()
    mock.execute = mocker.MagicMock()
    mock.fetchone = mocker.MagicMock(return_value=(1,))
    mock.fetchall = mocker.MagicMock(return_value=[])
    return mock

def test_fetch_chat_messages(setup_session_state, mock_conn, mock_db_data, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    mock_conn.execute().fetchall.return_value = mock_db_data['chat_messages']
    messages = fetch_chat_messages("test_chat_id", page=1, per_page=50)
    assert len(messages) > 0
    assert 'content' in messages[0].keys()
    assert 'role' in messages[0].keys()
    assert 'order_id' in messages[0].keys()

def test_fetch_chat_sessions(setup_session_state, mock_conn, mock_db_data, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    mock_conn.execute().fetchall.return_value = mock_db_data['chat_sessions']
    sessions = fetch_chat_sessions_metadata()
    assert len(sessions) > 0
    assert 'chat_id' in sessions[0].keys()
    assert 'model' in sessions[0].keys()
    assert 'message_count' in sessions[0].keys()

def test_update_message(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    update_message(1, "test_chat_id", "Updated content")
    mock_conn.execute.assert_called_with(
        "UPDATE chat_messages SET content = ?, token_count = ? WHERE id = ? AND chat_id = ?",
        ("Updated content", mocker.ANY, 1, "test_chat_id")
    )

def test_add_message(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    
    # Mock the order_id queries
    mock_cursor = mocker.MagicMock()
    mock_cursor.fetchone.side_effect = [
        {'order_id': 1000.0},  # Current message
        {'order_id': 2000.0}   # Next message
    ]
    mock_conn.execute.return_value = mock_cursor
    
    add_message("test_chat_id", "user", "New message", 1)
    
    # Get all SQL calls with normalized whitespace
    sql_calls = [' '.join(call[0][0].split()) for call in mock_conn.execute.call_args_list]
    
    # Verify message insertion and count increment
    assert any("INSERT INTO chat_messages" in sql for sql in sql_calls)
    assert any("UPDATE chat_sessions SET message_count = message_count + 1" in sql for sql in sql_calls)

def test_delete_message(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    delete_message(1, "test_chat_id")
    
    # Get all SQL calls with normalized whitespace
    sql_calls = [' '.join(call[0][0].split()) for call in mock_conn.execute.call_args_list]
    
    # Verify message deletion and count decrement
    assert any("DELETE FROM chat_messages WHERE id = ? AND chat_id = ?" in sql for sql in sql_calls)
    assert any("UPDATE chat_sessions SET message_count = message_count - 1 WHERE chat_id = ? AND message_count > 0" in sql for sql in sql_calls)

def test_load_empty_chat_sessions(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    
    # Create a mock cursor that returns empty results
    mock_cursor = mocker.MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    
    # Mock the execute method to return our cursor for any query
    mock_conn.execute = mocker.MagicMock(return_value=mock_cursor)
    
    # Reset session state
    if hasattr(st.session_state, 'db_chat_sessions'):
        del st.session_state.db_chat_sessions
    
    sessions = fetch_chat_sessions_metadata()
    assert len(sessions) == 0

def test_message_order(setup_session_state, mock_conn, mock_db_data, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    
    mock_cursor = mocker.MagicMock()
    mock_cursor.fetchall.return_value = mock_db_data['chat_messages']
    mock_conn.execute.return_value = mock_cursor
    
    # Reset session state
    if hasattr(st.session_state, 'db_chat_messages'):
        del st.session_state.db_chat_messages
    
    result = fetch_chat_messages('test_chat_id', page=1, per_page=50)
    assert len(result) == 1
    assert result[0]['content'] == 'Test message'

def test_load_messages_invalid_chat(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    mock_cursor = mocker.MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.execute.return_value = mock_cursor
    messages = fetch_chat_messages("invalid_chat", page=1, per_page=50)
    assert len(messages) == 0

def test_session_state_initialization(setup_session_state):
    """Test that essential session state variables are initialized."""
    assert 'current_page' in st.session_state
    assert 'messages_per_page' in st.session_state
    assert 'selected_chat_id' in st.session_state
    assert 'global_tag_colors' in st.session_state
    assert isinstance(st.session_state.global_tag_colors, dict)
    assert st.session_state.messages_per_page == 50  # Default value 