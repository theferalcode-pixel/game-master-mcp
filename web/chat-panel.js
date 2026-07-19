// The agent's seat at the table: a thin view over one dedicated Hermes chat
// session, relayed by the local house server. It renders only what {{A}} and
// {{P}} actually said; the board stays the source of truth for the game.
(async () => {
  let NAME = {agent: 'Agent'};
  let CHAT_ON = true;
  try {
    const config = await window.ROOM;
    NAME.agent = config.agent_name || NAME.agent;
    CHAT_ON = Boolean(config.chat_enabled);
  } catch { /* defaults stand */ }
  const fill = (text) => String(text).replaceAll('{{A}}', NAME.agent);
  const chatTitle = document.querySelector('#chatTitle');
  if (chatTitle) chatTitle.textContent = fill('{{A}}’s seat');
  const log = document.querySelector('#chatLog');
  const form = document.querySelector('#chatForm');
  const input = document.querySelector('#chatInput');
  const send = document.querySelector('#chatSend');
  const chatState = document.querySelector('#chatState');
  let busy = false;

  function scrollToEnd() {
    log.scrollTop = log.scrollHeight;
  }

  function bubble(kind, text) {
    const node = document.createElement('div');
    node.className = `bubble ${kind}`;
    node.textContent = text;
    log.append(node);
    scrollToEnd();
    return node;
  }

  function setState(label) {
    chatState.textContent = label;
  }

  function setBusy(value) {
    busy = value;
    send.disabled = value;
    input.disabled = value;
  }

  async function loadHistory() {
    if (!CHAT_ON) {
      log.replaceChildren();
      const note = document.createElement('p');
      note.className = 'chat-empty';
      note.textContent = fill('No chat is wired to this room yet — {{A}} plays from your AI app instead. The board updates on its own either way.');
      log.append(note);
      setState('chat not configured');
      send.disabled = true;
      input.disabled = true;
      return;
    }
    try {
      const response = await fetch('/api/chat/history', {cache: 'no-store'});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.label || 'Chat history unavailable.');
      log.replaceChildren();
      const messages = payload.messages || [];
      if (!messages.length) {
        const empty = document.createElement('p');
        empty.className = 'chat-empty';
        empty.textContent = fill('The seat across from you is {{A}}’s. Say hello, or say it’s their move.');
        log.append(empty);
      } else {
        messages.forEach((message) => bubble(message.role === 'user' ? 'user' : 'agent', message.content));
      }
      setState(fill('{{A}} is reachable'));
    } catch (error) {
      log.replaceChildren();
      bubble('chat-error', error.message);
      setState('chat offline');
    }
  }

  function follow(streamId) {
    return new Promise((resolve) => {
      const source = new EventSource(`/api/chat/stream?stream_id=${encodeURIComponent(streamId)}`);
      let reply = null;
      let toolNote = null;
      let text = '';
      const finish = () => { source.close(); if (toolNote) toolNote.remove(); resolve(); };

      source.addEventListener('token', (event) => {
        try { text += JSON.parse(event.data).text || ''; } catch { /* keep stream alive */ }
        if (!reply) reply = bubble('agent', '');
        reply.textContent = text;
        scrollToEnd();
      });
      source.addEventListener('tool', () => {
        if (!toolNote) toolNote = bubble('status', fill('{{A}} reaches for the game master…'));
      });
      source.addEventListener('tool_complete', () => {
        window.dispatchEvent(new Event('agent-replied'));
      });
      source.addEventListener('done', (event) => {
        if (!text) {
          try {
            const data = JSON.parse(event.data);
            if (data.answer) { reply = reply || bubble('agent', ''); reply.textContent = data.answer; }
          } catch { /* nothing extra to show */ }
        }
        finish();
      });
      source.addEventListener('stream_end', finish);
      source.addEventListener('apperror', (event) => {
        let message = fill('{{A}}’s reply hit a snag.');
        try { message = JSON.parse(event.data).message || message; } catch { /* keep default */ }
        bubble('chat-error', message);
        finish();
      });
      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED) finish();
      };
    });
  }

  async function sendMessage(message) {
    setBusy(true);
    const emptyNote = log.querySelector('.chat-empty');
    if (emptyNote) emptyNote.remove();
    bubble('user', message);
    setState(fill('{{A}} is thinking…'));
    try {
      const response = await fetch('/api/chat/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(fill(payload.label || 'The message did not reach {{A}}.'));
      await follow(payload.stream_id);
      setState(fill('{{A}} is reachable'));
    } catch (error) {
      bubble('chat-error', error.message);
      setState('chat offline');
    } finally {
      setBusy(false);
      window.dispatchEvent(new Event('agent-replied'));
      input.focus();
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || busy) return;
    input.value = '';
    void sendMessage(message);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  void loadHistory();
})();
