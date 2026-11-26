// ui/adapters/ChatAdapter.kt
// Adapter para la lista de mensajes del chatbot con renderizado completo de Markdown

package com.smartwms.operario.ui.adapters

import android.content.Context
import android.graphics.Color
import android.text.method.LinkMovementMethod
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.smartwms.operario.R
import io.noties.markwon.AbstractMarkwonPlugin
import io.noties.markwon.Markwon
import io.noties.markwon.core.MarkwonTheme
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.linkify.LinkifyPlugin

data class ChatMessage(val text: String, val isBot: Boolean)

class ChatAdapter(private val messages: List<ChatMessage>) :
    RecyclerView.Adapter<ChatAdapter.ViewHolder>() {

    companion object {
        private const val VIEW_TYPE_USER = 0
        private const val VIEW_TYPE_BOT  = 1
    }

    private var markwon: Markwon? = null

    private fun getMarkwon(context: Context): Markwon {
        return markwon ?: Markwon.builder(context)
            .usePlugin(TablePlugin.create(context))
            .usePlugin(StrikethroughPlugin.create())
            .usePlugin(LinkifyPlugin.create())
            .usePlugin(object : AbstractMarkwonPlugin() {
                override fun configureTheme(builder: MarkwonTheme.Builder) {
                    builder
                        .linkColor(Color.parseColor("#93C5FD"))
                        .codeTextColor(Color.parseColor("#C7D2FE"))
                        .codeBackgroundColor(Color.parseColor("#2E2E52"))
                        .codeBlockBackgroundColor(Color.parseColor("#0F0F1A"))
                        .codeBlockTextColor(Color.parseColor("#E2E8F0"))
                        .blockQuoteColor(Color.parseColor("#818CF8"))
                        .thematicBreakColor(Color.parseColor("#334155"))
                        .headingBreakColor(Color.parseColor("#334155"))
                }
            })
            .build()
            .also { markwon = it }
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
        val msg = messages[position]
        if (msg.isBot) {
            holder.tvMessage.movementMethod = LinkMovementMethod.getInstance()
            getMarkwon(holder.tvMessage.context).setMarkdown(holder.tvMessage, msg.text)
        } else {
            holder.tvMessage.text = msg.text
        }
    }

    override fun getItemCount() = messages.size
}
