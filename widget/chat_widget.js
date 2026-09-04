document.addEventListener('DOMContentLoaded', () => {
  // Inyectar HTML del widget
  const widgetHTML = `
    <div class="wms-chat-widget" id="wms-chat-widget">
      <div class="wms-chat-window">
        <div class="wms-chat-header">
          <div class="wms-chat-header-icon">🤖</div>
          <div class="wms-chat-header-info">
            <h4>Copiloto IA</h4>
            <p>● en línea</p>
          </div>
          <button class="wms-chat-close" id="wms-chat-close">×</button>
        </div>
        <div class="wms-chat-messages" id="wms-chat-messages">
          <div class="wms-msg bot">
            ¡Hola! Soy SmartWMS Bot, tu asistente de bodega integrado. ¿En qué te puedo ayudar hoy?
          </div>
        </div>
        <div class="wms-chat-input-area">
          <input type="text" class="wms-chat-input" id="wms-chat-input" placeholder="Escribe un mensaje..." />
          <button class="wms-chat-send" id="wms-chat-send">➤</button>
        </div>
      </div>
      <div class="wms-chat-fab" id="wms-chat-fab">
        💬
      </div>
    </div>
  `;
  
  document.body.insertAdjacentHTML('beforeend', widgetHTML);

  const widget = document.getElementById('wms-chat-widget');
  const fab = document.getElementById('wms-chat-fab');
  const closeBtn = document.getElementById('wms-chat-close');
  const input = document.getElementById('wms-chat-input');
  const sendBtn = document.getElementById('wms-chat-send');
  const messagesContainer = document.getElementById('wms-chat-messages');

  // Toggle widget
  fab.addEventListener('click', () => widget.classList.add('open'));
  closeBtn.addEventListener('click', () => widget.classList.remove('open'));

  // Formatter para texto a markdown (simple)
  function formatMarkdown(text) {
    return text.replace(/\*(.*?)\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
  }

  // Añadir mensaje a la UI
  function appendMessage(text, sender, buttons = []) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `wms-msg ${sender}`;
    msgDiv.innerHTML = formatMarkdown(text);

    if (buttons && buttons.length > 0) {
      const btnContainer = document.createElement('div');
      btnContainer.className = 'wms-msg-buttons';
      buttons.forEach(b => {
        const btn = document.createElement('button');
        btn.className = 'wms-msg-btn';
        btn.textContent = b.label;
        btn.onclick = () => sendMessage(b.cmd);
        btnContainer.appendChild(btn);
      });
      msgDiv.appendChild(btnContainer);
    }

    messagesContainer.appendChild(msgDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Enviar mensaje al backend
  async function sendMessage(textOverride = null) {
    const text = textOverride || input.value.trim();
    if (!text) return;
    
    if (!textOverride) input.value = '';
    
    appendMessage(text, 'user');

    // Mostrar typing indicator
    const typingDiv = document.createElement('div');
    typingDiv.className = 'wms-msg bot';
    typingDiv.id = 'wms-typing';
    typingDiv.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
    messagesContainer.appendChild(typingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    try {
      const response = await fetch('http://127.0.0.1:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text })
      });
      
      const data = await response.json();
      
      // Remover typing indicator
      document.getElementById('wms-typing').remove();
      
      if (data.reply) {
        appendMessage(data.reply.text, 'bot', data.reply.buttons);
      }
    } catch (err) {
      document.getElementById('wms-typing').remove();
      appendMessage("❌ Error conectando con el backend local (Asegúrate de ejecutar uvicorn).", 'bot');
    }
  }

  sendBtn.addEventListener('click', () => sendMessage());
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
  });
});
