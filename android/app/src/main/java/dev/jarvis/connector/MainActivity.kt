package dev.jarvis.connector

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.view.MotionEvent
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {
    private lateinit var status: TextView
    private lateinit var log: TextView
    private lateinit var recognizer: SpeechRecognizer
    private lateinit var tts: TextToSpeech
    private val prefs by lazy { getSharedPreferences("hub", MODE_PRIVATE) }

    @SuppressLint("ClickableViewAccessibility")
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        setContentView(R.layout.main)
        status = findViewById(R.id.status)
        log = findViewById(R.id.log)
        tts = TextToSpeech(this, this)
        recognizer = SpeechRecognizer.createSpeechRecognizer(this)
        recognizer.setRecognitionListener(listener)
        findViewById<Button>(R.id.setup).setOnClickListener { settings() }
        findViewById<Button>(R.id.talk).setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> startListening()
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> recognizer.stopListening()
            }
            true
        }
        if (prefs.getString("url", "").isNullOrBlank()) settings()
    }

    override fun onInit(s: Int) {
        // British English, slightly low and slow. A named voice can be chosen here later.
        tts.language = Locale.UK
        tts.setPitch(0.85f)
        tts.setSpeechRate(0.95f)
    }

    private fun startListening() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
            return
        }
        tts.stop()
        status.text = "Listening..."
        recognizer.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-IN")
        })
    }

    private val listener = object : RecognitionListener {
        override fun onResults(r: Bundle) {
            val said = r.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull() ?: return
            ask(said)
        }
        override fun onError(e: Int) { status.text = "Did not catch that" }
        override fun onReadyForSpeech(p: Bundle?) {}
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(v: Float) {}
        override fun onBufferReceived(b: ByteArray?) {}
        override fun onEndOfSpeech() { status.text = "Thinking..." }
        override fun onPartialResults(p: Bundle?) {}
        override fun onEvent(t: Int, p: Bundle?) {}
    }

    private fun ask(text: String) {
        log.append("\nyou: $text\n")
        val base = prefs.getString("url", "")!!.trimEnd('/')
        val token = prefs.getString("token", "")!!
        thread {
            val reply = try {
                val c = URL("$base/ask").openConnection() as HttpURLConnection
                c.requestMethod = "POST"
                c.connectTimeout = 15000
                c.readTimeout = 90000
                c.setRequestProperty("Authorization", "Bearer $token")
                c.setRequestProperty("Content-Type", "application/json")
                c.doOutput = true
                c.outputStream.use { it.write(JSONObject().put("text", text).toString().toByteArray()) }
                if (c.responseCode != 200) "The hub said ${c.responseCode}."
                else JSONObject(c.inputStream.bufferedReader().readText()).getString("reply")
            } catch (e: Exception) {
                "I cannot reach the hub."
            }
            runOnUiThread {
                log.append("\njarvis: $reply\n")
                status.text = "Ready"
                tts.speak(reply, TextToSpeech.QUEUE_FLUSH, null, "r")
            }
        }
    }

    private fun settings() {
        val url = EditText(this).apply { hint = "https://your-hub"; setText(prefs.getString("url", "")) }
        val tok = EditText(this).apply { hint = "device token"; setText(prefs.getString("token", "")) }
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 16, 48, 0)
            addView(url)
            addView(tok)
        }
        AlertDialog.Builder(this).setTitle("Hub").setView(box)
            .setPositiveButton("Save") { _, _ ->
                prefs.edit().putString("url", url.text.toString().trim())
                    .putString("token", tok.text.toString().trim()).apply()
            }.show()
    }

    override fun onDestroy() {
        recognizer.destroy()
        tts.shutdown()
        super.onDestroy()
    }
}
