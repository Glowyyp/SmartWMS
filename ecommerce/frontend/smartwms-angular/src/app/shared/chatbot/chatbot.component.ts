// shared/chatbot/chatbot.component.ts
// Componente compartido de Chatbot IA — usado en Supervisor y Operario

import {
  Component, signal, ViewChild, ElementRef, AfterViewChecked
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { ChatService } from '../../core/services/chat.service';

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  renderedHtml?: SafeHtml;
  timestamp: Date;
}

@Component({
  selector: 'app-chatbot',
  standalone: true,
  imports: [CommonModule, FormsModule, MatIconModule, MatButtonModule, MatTooltipModule],
  template: `
    <!-- Botón flotante para abrir/cerrar -->
    <button
      id="chatbot-toggle-btn"
      class="chatbot-fab"
      mat-fab
      color="primary"
      (click)="toggleOpen()"
      [matTooltip]="isOpen() ? 'Cerrar Copiloto' : 'Abrir Copiloto IA'"
      matTooltipPosition="left"
      matTooltipClass="wms-tooltip"
    >
      <mat-icon>{{ isOpen() ? 'close' : 'smart_toy' }}</mat-icon>
    </button>

    <!-- Ventana del chat -->
    @if (isOpen()) {
      <div class="chatbot-window" role="dialog" aria-label="Copiloto IA SmartWMS">
        <!-- Header -->
        <div class="chatbot-header">
          <div class="chatbot-header-info">
            <mat-icon class="bot-icon">smart_toy</mat-icon>
            <div>
              <p class="bot-name">Copiloto SmartWMS</p>
              <p class="bot-status">
                <span class="status-dot"></span> En línea
              </p>
            </div>
          </div>
          <button mat-icon-button (click)="toggleOpen()">
            <mat-icon>close</mat-icon>
          </button>
        </div>

        <!-- Mensajes -->
        <div class="chatbot-messages" #messagesContainer>
          @for (msg of messages(); track $index) {
            <div class="message-row" [class.user-row]="msg.role === 'user'">
              <div class="message-bubble" [class.user-bubble]="msg.role === 'user'" [class.bot-bubble]="msg.role === 'assistant'">
                @if (msg.role === 'assistant') {
                  <div class="md-content" [innerHTML]="msg.renderedHtml"></div>
                } @else {
                  <p class="message-text">{{ msg.text }}</p>
                }
                <p class="message-time">{{ msg.timestamp | date:'HH:mm' }}</p>
              </div>
            </div>
          }

          @if (isLoading()) {
            <div class="message-row">
              <div class="message-bubble bot-bubble typing-bubble">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
              </div>
            </div>
          }
        </div>

        <!-- Input -->
        <div class="chatbot-input-area">
          <input
            id="chatbot-input"
            type="text"
            class="chatbot-input"
            placeholder="Consulta stock, picking, protocolos..."
            [(ngModel)]="inputText"
            (keydown.enter)="sendMessage()"
            [disabled]="isLoading()"
          />
          <button
            id="chatbot-send-btn"
            mat-icon-button
            color="primary"
            (click)="sendMessage()"
            [disabled]="!inputText.trim() || isLoading()"
          >
            <mat-icon>send</mat-icon>
          </button>
        </div>

        <!-- Sugerencias rápidas -->
        <div class="chatbot-suggestions">
          <button class="suggestion-chip" (click)="quickSend('¿Cuál es el stock de SKU-00567?')">📦 Stock</button>
          <button class="suggestion-chip" (click)="quickSend('¿Cómo hago el proceso de picking?')">🔍 Picking</button>
          <button class="suggestion-chip" (click)="quickSend('Alertas de stock crítico')">⚠️ Alertas</button>
        </div>
      </div>
    }
  `,
  styles: [`
    :host {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 1000;
    }

    .chatbot-fab {
      box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .chatbot-fab:hover { transform: scale(1.08); }

    .chatbot-window {
      position: absolute;
      bottom: 72px;
      right: 0;
      width: 380px;
      height: 520px;
      background: #1a1a2e;
      border: 1px solid rgba(99, 102, 241, 0.3);
      border-radius: 20px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 20px 60px rgba(0,0,0,0.5);
      animation: slideUp 0.25s ease;
    }

    @keyframes slideUp {
      from { opacity: 0; transform: translateY(16px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    .chatbot-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
    }
    .chatbot-header-info { display: flex; align-items: center; gap: 10px; color: white; }
    .bot-icon { font-size: 28px; }
    .bot-name { margin: 0; font-weight: 700; font-size: 14px; }
    .bot-status { margin: 0; font-size: 11px; opacity: 0.85; display: flex; align-items: center; gap: 4px; }
    .status-dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: #4ade80; display: inline-block;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; } 50% { opacity: 0.4; }
    }

    .chatbot-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .chatbot-messages::-webkit-scrollbar { width: 4px; }
    .chatbot-messages::-webkit-scrollbar-thumb { background: rgba(99,102,241,0.4); border-radius: 2px; }

    .message-row { display: flex; }
    .user-row { justify-content: flex-end; }

    .message-bubble {
      max-width: 78%;
      padding: 10px 14px;
      border-radius: 16px;
      font-size: 13px;
      line-height: 1.5;
    }
    .user-bubble {
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: white;
      border-bottom-right-radius: 4px;
    }
    .bot-bubble {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.08);
      color: #e2e8f0;
      border-bottom-left-radius: 4px;
    }
    .message-text { margin: 0 0 4px; white-space: pre-wrap; word-break: break-word; }
    .message-time { margin: 4px 0 0; font-size: 10px; opacity: 0.5; }

    .bot-bubble { max-width: 88%; }

    .md-content {
      word-break: break-word;
      overflow-x: auto;
    }
    .md-content ::ng-deep p { margin: 0 0 8px; }
    .md-content ::ng-deep p:last-child { margin-bottom: 0; }
    .md-content ::ng-deep h1,
    .md-content ::ng-deep h2,
    .md-content ::ng-deep h3 {
      margin: 10px 0 6px;
      font-weight: 700;
      color: #f8fafc;
      line-height: 1.3;
    }
    .md-content ::ng-deep h1:first-child,
    .md-content ::ng-deep h2:first-child,
    .md-content ::ng-deep h3:first-child { margin-top: 0; }
    .md-content ::ng-deep h1 { font-size: 15px; }
    .md-content ::ng-deep h2 { font-size: 14px; }
    .md-content ::ng-deep h3 { font-size: 13.5px; color: #c7d2fe; }
    .md-content ::ng-deep strong { color: #ffffff; font-weight: 700; }
    .md-content ::ng-deep em { font-style: italic; color: #cbd5e1; }
    .md-content ::ng-deep ul,
    .md-content ::ng-deep ol {
      margin: 4px 0 8px;
      padding-left: 18px;
    }
    .md-content ::ng-deep li { margin-bottom: 3px; }
    .md-content ::ng-deep code {
      background: rgba(99, 102, 241, 0.22);
      color: #c7d2fe;
      padding: 1px 5px;
      border-radius: 4px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
    }
    .md-content ::ng-deep pre {
      background: rgba(15, 15, 26, 0.85);
      border: 1px solid rgba(99, 102, 241, 0.28);
      border-radius: 8px;
      padding: 8px 10px;
      margin: 6px 0 8px;
      overflow-x: auto;
    }
    .md-content ::ng-deep pre code {
      background: transparent;
      padding: 0;
      color: #e2e8f0;
      font-size: 11.5px;
      display: block;
      white-space: pre;
    }
    .md-content ::ng-deep blockquote {
      margin: 6px 0 8px;
      padding: 4px 10px;
      border-left: 3px solid #818cf8;
      background: rgba(99, 102, 241, 0.1);
      border-radius: 0 6px 6px 0;
      color: #cbd5e1;
    }
    .md-content ::ng-deep hr {
      border: none;
      border-top: 1px solid rgba(255, 255, 255, 0.14);
      margin: 8px 0;
    }
    .md-content ::ng-deep a {
      color: #93c5fd;
      text-decoration: underline;
    }
    .md-content ::ng-deep table {
      width: 100%;
      border-collapse: collapse;
      margin: 6px 0 8px;
      font-size: 12px;
    }
    .md-content ::ng-deep th,
    .md-content ::ng-deep td {
      border: 1px solid rgba(255, 255, 255, 0.14);
      padding: 5px 7px;
      text-align: left;
    }
    .md-content ::ng-deep th {
      background: rgba(99, 102, 241, 0.22);
      color: #f8fafc;
      font-weight: 600;
    }

    .typing-bubble { display: flex; gap: 5px; align-items: center; padding: 14px; }
    .dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: #6366f1;
      animation: bounce 1.2s infinite ease-in-out;
    }
    .dot:nth-child(1) { animation-delay: 0s; }
    .dot:nth-child(2) { animation-delay: 0.2s; }
    .dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes bounce {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-8px); }
    }

    .chatbot-input-area {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 16px;
      border-top: 1px solid rgba(255,255,255,0.08);
    }
    .chatbot-input {
      flex: 1;
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(99,102,241,0.3);
      border-radius: 24px;
      padding: 10px 16px;
      color: #e2e8f0;
      font-size: 13px;
      outline: none;
      transition: border-color 0.2s;
    }
    .chatbot-input:focus { border-color: #6366f1; }
    .chatbot-input::placeholder { color: rgba(255,255,255,0.35); }

    .chatbot-suggestions {
      padding: 0 16px 12px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .suggestion-chip {
      background: rgba(99,102,241,0.15);
      border: 1px solid rgba(99,102,241,0.3);
      color: #a5b4fc;
      border-radius: 24px;
      padding: 4px 10px;
      font-size: 11px;
      cursor: pointer;
      transition: background 0.2s;
    }
    .suggestion-chip:hover { background: rgba(99,102,241,0.3); }
  `],
})
export class ChatbotComponent implements AfterViewChecked {
  @ViewChild('messagesContainer') private messagesContainer!: ElementRef;

  isOpen = signal(false);
  isLoading = signal(false);
  inputText = '';

  messages = signal<ChatMessage[]>([]);

  constructor(
    private chatService: ChatService,
    private sanitizer: DomSanitizer,
  ) {
    marked.setOptions({ gfm: true, breaks: true });
    this.messages.set([
      this.buildBotMessage(
        '¡Hola! Soy el **Copiloto IA de SmartWMS**. Puedo ayudarte con consultas de stock, procesos de picking, packing y protocolos de bodega. ¿En qué te ayudo?'
      ),
    ]);
  }

  private renderMarkdown(markdownText: string): SafeHtml {
    const rawHtml = marked.parse(markdownText || '', { async: false }) as string;
    const cleanHtml = DOMPurify.sanitize(rawHtml, {
      USE_PROFILES: { html: true },
      ADD_ATTR: ['target', 'rel'],
    });
    // Asegurar que enlaces externos abran de forma segura en nueva pestaña
    const withSafeLinks = cleanHtml.replace(
      /<a\s+href=/gi,
      '<a target="_blank" rel="noopener noreferrer" href='
    );
    return this.sanitizer.bypassSecurityTrustHtml(withSafeLinks);
  }

  private buildBotMessage(text: string): ChatMessage {
    return {
      role: 'assistant',
      text,
      renderedHtml: this.renderMarkdown(text),
      timestamp: new Date(),
    };
  }

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

  toggleOpen(): void {
    this.isOpen.update(v => !v);
  }

  quickSend(text: string): void {
    this.inputText = text;
    this.sendMessage();
  }

  sendMessage(): void {
    const text = this.inputText.trim();
    if (!text || this.isLoading()) return;

    this.inputText = '';
    this.messages.update(msgs => [
      ...msgs,
      { role: 'user', text, timestamp: new Date() }
    ]);
    this.isLoading.set(true);

    this.chatService.sendMessage(text).subscribe({
      next: (res) => {
        const replyText = res.reply?.text ?? 'Sin respuesta del servidor.';
        this.messages.update(msgs => [
          ...msgs,
          this.buildBotMessage(replyText)
        ]);
        this.isLoading.set(false);
      },
      error: () => {
        this.messages.update(msgs => [
          ...msgs,
          this.buildBotMessage('❌ No se pudo conectar con el Copiloto IA. Verifica que el servicio esté disponible.')
        ]);
        this.isLoading.set(false);
      },
    });
  }

  private scrollToBottom(): void {
    try {
      const el = this.messagesContainer?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    } catch (_) { }
  }
}
