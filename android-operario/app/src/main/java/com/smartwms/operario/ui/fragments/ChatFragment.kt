// ui/fragments/ChatFragment.kt
// Chat con el bot de SmartWMS via POST /api/chat (puerto 8000)

package com.smartwms.operario.ui.fragments

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.smartwms.operario.data.api.ChatRequest
import com.smartwms.operario.data.api.RetrofitClient
import com.smartwms.operario.data.local.TokenStore
import com.smartwms.operario.databinding.FragmentChatBinding
import com.smartwms.operario.ui.adapters.ChatMessage
import com.smartwms.operario.ui.adapters.ChatAdapter
import kotlinx.coroutines.launch

class ChatFragment : Fragment() {

    private var _binding: FragmentChatBinding? = null
    private val binding get() = _binding!!

    private lateinit var tokenStore: TokenStore
    private lateinit var chatAdapter: ChatAdapter
    private val messages = mutableListOf<ChatMessage>()

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentChatBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        tokenStore = TokenStore(requireContext())

        chatAdapter = ChatAdapter(messages)
        binding.rvChat.layoutManager = LinearLayoutManager(requireContext()).also { it.stackFromEnd = true }
        binding.rvChat.adapter = chatAdapter

        // Mensaje de bienvenida
        addMessage("Hola! Soy el asistente de SmartWMS. Puedo ayudarte con inventario, ordenes y procedimientos.", isBot = true)

        binding.btnSend.setOnClickListener { sendMessage() }

        binding.etMessage.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) { sendMessage(); true } else false
        }
    }

    private fun sendMessage() {
        val text = binding.etMessage.text.toString().trim()
        if (text.isEmpty()) return

        addMessage(text, isBot = false)
        binding.etMessage.text?.clear()
        binding.progressChat.visibility = View.VISIBLE
        binding.btnSend.isEnabled = false

        lifecycleScope.launch {
            try {
                val token = tokenStore.bearerToken()
                val response = RetrofitClient.botService.sendChat(token, ChatRequest(text))
                if (response.isSuccessful) {
                    val botReply = response.body()?.response ?: "(sin respuesta)"
                    addMessage(botReply, isBot = true)
                } else {
                    addMessage("Error ${response.code()} — Verifica que el bot este corriendo.", isBot = true)
                }
            } catch (e: Exception) {
                addMessage("Error de conexion con el bot.", isBot = true)
            } finally {
                binding.progressChat.visibility = View.GONE
                binding.btnSend.isEnabled = true
            }
        }
    }

    private fun addMessage(text: String, isBot: Boolean) {
        messages.add(ChatMessage(text, isBot))
        chatAdapter.notifyItemInserted(messages.size - 1)
        binding.rvChat.scrollToPosition(messages.size - 1)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
