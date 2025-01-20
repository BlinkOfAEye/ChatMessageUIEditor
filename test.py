import pytest
import sqlite3
from datetime import datetime
import streamlit as st
from MessageUI import (
    fetch_chat_messages, 
    fetch_chat_sessions, 
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
                'created_at': datetime.now().isoformat()
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
    messages = fetch_chat_messages("test_chat_id")
    assert len(messages) > 0
    assert 'content' in messages[0].keys()
    assert 'role' in messages[0].keys()

def test_fetch_chat_sessions(setup_session_state, mock_conn, mock_db_data, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    mock_conn.execute().fetchall.return_value = mock_db_data['chat_sessions']
    sessions = fetch_chat_sessions()
    assert len(sessions) > 0
    assert 'chat_id' in sessions[0].keys()
    assert 'model' in sessions[0].keys()

def test_update_message(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    update_message(1, "Updated content")
    mock_conn.execute.assert_called_with(
        "UPDATE chat_messages SET content = ?, updated_at = ? WHERE id = ?",
        ("Updated content", mocker.ANY, 1)
    )

def test_add_message(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    add_message("test_chat_id", "user", "New message", None)
    assert mock_conn.execute.called

def test_delete_message(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    delete_message(1, "test_chat_id")
    assert mock_conn.execute.called

def test_export_selected_chats(setup_session_state, mock_conn, mock_db_data, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    mock_conn.execute().fetchone.return_value = mock_db_data['chat_sessions'][0]
    mock_conn.execute().fetchall.return_value = mock_db_data['chat_messages']
    export_data = export_selected_chats({"test_chat_id"})
    assert 'chats' in export_data
    assert len(export_data['chats']) == 1

def test_load_empty_chat_sessions(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    mock_conn.execute().fetchall.return_value = []
    sessions = fetch_chat_sessions()
    assert len(sessions) == 0

def test_message_order(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    
    ordered_messages = [
        {'id': 1, 'chat_id': 'test_chat_id', 'content': 'First'},
        {'id': 2, 'chat_id': 'test_chat_id', 'content': 'Second'}
    ]
    
    mock_cursor = mocker.MagicMock()
    mock_cursor.fetchall.return_value = ordered_messages
    mock_conn.execute.return_value = mock_cursor
    
    messages = fetch_chat_messages('test_chat_id')
    assert len(messages) == 2
    assert messages[0]['id'] == 1
    assert messages[1]['id'] == 2
    assert messages[0]['content'] == 'First'
    assert messages[1]['content'] == 'Second'

def test_load_messages_invalid_chat(setup_session_state, mock_conn, mocker):
    mocker.patch('MessageUI.init_connection', return_value=mock_conn)
    mock_conn.execute().fetchall.return_value = []
    messages = fetch_chat_messages("invalid_chat")
    assert len(messages) == 0

def test_session_state_initialization(setup_session_state):
    """Test that essential session state variables are initialized."""
    assert 'messages_page' in st.session_state
    assert 'messages_per_page' in st.session_state
    assert 'selected_chat_id' in st.session_state
    assert 'global_tag_colors' in st.session_state
    assert isinstance(st.session_state.global_tag_colors, dict)
    assert st.session_state.messages_per_page == 50  # Default value 