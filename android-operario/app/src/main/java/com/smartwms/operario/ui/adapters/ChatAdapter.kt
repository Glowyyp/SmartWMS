// ui/adapters/ChatAdapter.kt
// Adapter para la lista de mensajes del chatbot

package com.smartwms.operario.ui.adapters

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.smartwms.operario.R

data class ChatMessage(val text: String, val isBot: Boolean)

class ChatAdapter(private val messages: List<ChatMessage>) :
    RecyclerView.Adapter<ChatAdapter.ViewHolder>() {

    companion object {
        private const val VIEW_TYPE_USER = 0
        private const val VIEW_TYPE_BOT  = 1
    }

    inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvMessage: TextView = view.findViewById(R.id.tv_message)
    }

    override fun getItemViewType(position: Int) =
        if (messages[position].isBot) VIEW_TYPE_BOT else VIEW_TYPE_USER

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val layout = if (viewType == VIEW_TYPE_BOT) R.layout.item_chat_bot else R.layout.item_chat_user
        val view = LayoutInflater.from(parent.context).inflate(layout, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.tvMessage.text = messages[position].text
    }

    override fun getItemCount() = messages.size
}
