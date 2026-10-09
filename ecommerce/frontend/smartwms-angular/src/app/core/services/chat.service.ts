// core/services/chat.service.ts
// Servicio Angular para comunicarse con el endpoint de Gemini en el bot (puerto 8000)

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface ChatReply {
  text: string;
  buttons?: { label: string; cmd: string }[];
}

export interface ChatResponse {
  reply: ChatReply;
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly chatUrl = `${environment.botApiUrl}/api/chat`;

  constructor(private http: HttpClient) {}

  /**
   * Envía un mensaje al Copiloto IA y retorna la respuesta de Gemini.
   * El interceptor inyecta el Bearer token automáticamente.
   */
  sendMessage(text: string): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(this.chatUrl, { text });
  }
}
