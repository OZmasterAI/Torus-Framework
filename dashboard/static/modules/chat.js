/**
 * Terminal Chat — WebSocket-based chat with Claude using claude -p + --resume.
 * Each browser session gets a unique chat_id (stored in sessionStorage).
 * Messages stream token-by-token via WebSocket frames.
 */

let ws = null;
let chatId = null;
let isStreaming = false;
let currentMsgEl = null;

function getChatId() {
    if (!chatId) {
        chatId = sessionStorage.getItem('chat_id');
        if (!chatId) {
            chatId = crypto.randomUUID();
            sessionStorage.setItem('chat_id', chatId);
        }
    }
    return chatId;
}

function connectWS() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws/chat`);

    ws.onopen = () => {};

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleServerMessage(msg);
        } catch {}
    };

    ws.onclose = () => {
        ws = null;
        if (isStreaming) {
            finishStreaming();
        }
    };

    ws.onerror = () => {
        ws = null;
    };
}

function handleServerMessage(msg) {
    const messagesEl = document.getElementById('chat-messages');
    if (!messagesEl) return;

    switch (msg.type) {
        case 'token':
            if (!currentMsgEl) {
                currentMsgEl = document.createElement('div');
                currentMsgEl.className = 'chat-msg chat-assistant';
                currentMsgEl.textContent = '';
                // Remove cursor from previous msg
                messagesEl.querySelectorAll('.chat-cursor').forEach(c => c.remove());
                messagesEl.appendChild(currentMsgEl);
            }
            // Remove existing cursor, add text, re-add cursor
            currentMsgEl.querySelectorAll('.chat-cursor').forEach(c => c.remove());
            currentMsgEl.textContent += msg.text;
            const cursor = document.createElement('span');
            cursor.className = 'chat-cursor';
            currentMsgEl.appendChild(cursor);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            break;

        case 'done':
            finishStreaming();
            break;

        case 'error':
            finishStreaming();
            const errEl = document.createElement('div');
            errEl.className = 'chat-msg chat-error';
            errEl.textContent = msg.text || 'Unknown error';
            messagesEl.appendChild(errEl);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            break;
    }
}

function finishStreaming() {
    isStreaming = false;
    // Remove cursors
    document.querySelectorAll('.chat-cursor').forEach(c => c.remove());
    currentMsgEl = null;

    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    if (input) { input.disabled = false; input.focus(); }
    if (sendBtn) sendBtn.disabled = false;
}

export function sendMessage() {
    const input = document.getElementById('chat-input');
    if (!input) return;

    const text = input.value.trim();
    if (!text || isStreaming) return;

    const messagesEl = document.getElementById('chat-messages');
    if (!messagesEl) return;

    // Remove welcome message
    const welcome = messagesEl.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    // Add user message
    const userMsg = document.createElement('div');
    userMsg.className = 'chat-msg chat-user';
    userMsg.textContent = text;
    messagesEl.appendChild(userMsg);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    // Clear input
    input.value = '';
    input.disabled = true;
    const sendBtn = document.getElementById('chat-send-btn');
    if (sendBtn) sendBtn.disabled = true;

    isStreaming = true;

    // Connect WS if needed
    connectWS();

    // Wait for connection then send
    const trySend = () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                chat_id: getChatId(),
                text: text,
            }));
        } else if (ws && ws.readyState === WebSocket.CONNECTING) {
            setTimeout(trySend, 100);
        } else {
            connectWS();
            setTimeout(trySend, 200);
        }
    };
    trySend();
}

export function clearChat() {
    // Reset session
    chatId = crypto.randomUUID();
    sessionStorage.setItem('chat_id', chatId);

    const messagesEl = document.getElementById('chat-messages');
    if (messagesEl) {
        messagesEl.innerHTML = '<div class="chat-welcome">Send a message to start chatting with Claude...</div>';
    }

    isStreaming = false;
    currentMsgEl = null;

    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    if (input) { input.disabled = false; input.value = ''; input.focus(); }
    if (sendBtn) sendBtn.disabled = false;
}

export function initChat() {
    const sendBtn = document.getElementById('chat-send-btn');
    const clearBtn = document.getElementById('chat-clear-btn');
    const input = document.getElementById('chat-input');
    const minimizeBtn = document.getElementById('chat-minimize-btn');
    const panel = document.getElementById('panel-chat');

    if (sendBtn) sendBtn.addEventListener('click', sendMessage);
    if (clearBtn) clearBtn.addEventListener('click', clearChat);
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
    if (minimizeBtn && panel) {
        minimizeBtn.addEventListener('click', () => {
            panel.classList.toggle('minimized');
        });
    }

    // Connect WebSocket eagerly
    connectWS();
}
