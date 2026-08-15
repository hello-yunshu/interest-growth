// Gate E / R0.5-R0.6 — Interest Growth SAF bridge for Android.
//
// This plugin provides native Android operations that require the Activity
// context or SAF (Storage Access Framework) intents:
//
//   * readContentUri   — reads a content URI (e.g., from SAF document picker)
//                        and returns the bytes as base64 so the Rust native
//                        broker can upload them as multipart without the
//                        renderer materialising the full file.
//   * pickDocument     — opens SAF ACTION_OPEN_DOCUMENT and returns the
//                        selected content URI.
//   * saveDocument     — opens SAF ACTION_CREATE_DOCUMENT and writes the
//                        base64 content bytes to the user-selected location.
//
// The plugin is registered from Rust via register_android_plugin and
// commands are dispatched through the Rust command layer — the renderer
// never talks to Kotlin directly.
package app.psychologygrowth.desktop

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Base64
import androidx.activity.result.ActivityResult
import app.tauri.Logger
import app.tauri.annotation.ActivityCallback
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

@InvokeArg
class ReadContentUriArgs {
    lateinit var uri: String
}

@InvokeArg
class SaveDocumentArgs {
    lateinit var contentBase64: String
    lateinit var filename: String
    var mimeType: String? = null
}

@InvokeArg
class PickDocumentArgs {
    var mimeType: String? = null
}

@TauriPlugin
class InterestGrowthPlugin(private val activity: Activity) : Plugin(activity) {

    // Gate R0.6 — the base64 payload + filename must survive the round trip
    // between the saveDocument command and its activity-result callback. The
    // callback receives a fresh Invoke, so the pending payload is kept here on
    // the plugin instance (single pending save at a time).
    private var pendingSave: SaveDocumentArgs? = null

    // ------------------------------------------------------------ readContentUri
    //
    // Read a content:// URI (from SAF document picker) and return the bytes
    // as base64 plus the display name and size. The renderer only passes the
    // URI string; the actual I/O happens in the native layer (Gate R0.5 — the
    // renderer never materialises a 100 MiB base64 copy).
    @Command
    fun readContentUri(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(ReadContentUriArgs::class.java)
            val uri = Uri.parse(args.uri)
            val contentResolver = activity.contentResolver

            // Resolve display name and size from the content provider.
            var displayName = "upload.bin"
            var fileSize = -1L
            var cursor = contentResolver.query(uri, null, null, null, null)
            cursor?.use { c ->
                if (c.moveToFirst()) {
                    val nameIdx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (nameIdx >= 0) displayName = c.getString(nameIdx) ?: displayName
                    val sizeIdx = c.getColumnIndex(OpenableColumns.SIZE)
                    if (sizeIdx >= 0) fileSize = c.getLong(sizeIdx)
                }
            }

            // Read the full content into a byte array (bounded by the
            // product upload limit; the Rust layer also re-checks).
            val inputStream = contentResolver.openInputStream(uri)
                ?: throw IllegalStateException("cannot open content URI: $uri")
            val fileBytes = inputStream.use { it.readBytes() }
            val base64 = Base64.encodeToString(fileBytes, Base64.NO_WRAP)

            val result = JSObject()
            result.put("base64", base64)
            result.put("name", displayName)
            result.put("size", fileBytes.size.toLong())
            result.put("mimeType", contentResolver.getType(uri) ?: "application/octet-stream")
            invoke.resolve(result)
        } catch (ex: Exception) {
            val msg = ex.message ?: "failed to read content URI"
            Logger.error(msg)
            invoke.reject(msg)
        }
    }

    // ------------------------------------------------------------ saveDocument
    //
    // Open SAF ACTION_CREATE_DOCUMENT and write the base64 content to the
    // user-selected location. The base64 payload is held on the plugin while
    // the SAF dialog is open; the activity-result callback performs the write.
    @Command
    fun saveDocument(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(SaveDocumentArgs::class.java)
            if (args.contentBase64.isEmpty()) {
                throw IllegalArgumentException("contentBase64 must not be empty")
            }
            pendingSave = args
            val mime = args.mimeType ?: "application/octet-stream"
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.type = mime
            intent.putExtra(Intent.EXTRA_TITLE, args.filename)
            startActivityForResult(invoke, intent, "saveDocumentResult")
        } catch (ex: Exception) {
            pendingSave = null
            val msg = ex.message ?: "failed to open save document dialog"
            Logger.error(msg)
            invoke.reject(msg)
        }
    }

    @ActivityCallback
    fun saveDocumentResult(invoke: Invoke, result: ActivityResult) {
        val pending = pendingSave
        pendingSave = null
        try {
            when (result.resultCode) {
                Activity.RESULT_OK -> {
                    val data = result.data
                    if (data != null && data.data != null) {
                        val uri = data.data!!
                        val args = pending
                            ?: throw IllegalStateException("save document payload lost before callback")
                        val fileBytes = Base64.decode(args.contentBase64, Base64.NO_WRAP)
                        val outputStream = activity.contentResolver.openOutputStream(uri, "w")
                            ?: throw IllegalStateException("cannot open output stream for: $uri")
                        outputStream.use { it.write(fileBytes) }

                        val callResult = JSObject()
                        callResult.put("uri", uri.toString())
                        callResult.put("size", fileBytes.size.toLong())
                        invoke.resolve(callResult)
                    } else {
                        invoke.reject("no document URI returned")
                    }
                }
                Activity.RESULT_CANCELED -> invoke.reject("save cancelled")
                else -> invoke.reject("save failed with result code: ${result.resultCode}")
            }
        } catch (ex: Exception) {
            val msg = ex.message ?: "save document callback failed"
            Logger.error(msg)
            invoke.reject(msg)
        }
    }

    // ------------------------------------------------------------ pickDocument
    //
    // Open SAF ACTION_OPEN_DOCUMENT and return the selected content URI plus
    // the display metadata so the renderer only ever passes the URI onward
    // (Gate R0.5 — the renderer never reads the file bytes itself).
    @Command
    fun pickDocument(invoke: Invoke) {
        try {
            val args = invoke.parseArgs(PickDocumentArgs::class.java)
            val mime = args.mimeType ?: "*/*"
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.type = mime
            startActivityForResult(invoke, intent, "pickDocumentResult")
        } catch (ex: Exception) {
            val msg = ex.message ?: "failed to open document picker"
            Logger.error(msg)
            invoke.reject(msg)
        }
    }

    @ActivityCallback
    fun pickDocumentResult(invoke: Invoke, result: ActivityResult) {
        try {
            when (result.resultCode) {
                Activity.RESULT_OK -> {
                    val data = result.data
                    if (data != null && data.data != null) {
                        val uri = data.data!!
                        val contentResolver = activity.contentResolver

                        var displayName = "document.bin"
                        var fileSize = -1L
                        var cursor = contentResolver.query(uri, null, null, null, null)
                        cursor?.use { c ->
                            if (c.moveToFirst()) {
                                val nameIdx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                                if (nameIdx >= 0) displayName = c.getString(nameIdx) ?: displayName
                                val sizeIdx = c.getColumnIndex(OpenableColumns.SIZE)
                                if (sizeIdx >= 0) fileSize = c.getLong(sizeIdx)
                            }
                        }

                        val callResult = JSObject()
                        callResult.put("uri", uri.toString())
                        callResult.put("name", displayName)
                        callResult.put("size", fileSize)
                        callResult.put(
                            "mimeType",
                            contentResolver.getType(uri) ?: "application/octet-stream"
                        )
                        invoke.resolve(callResult)
                    } else {
                        invoke.reject("no document selected")
                    }
                }
                Activity.RESULT_CANCELED -> invoke.reject("picker cancelled")
                else -> invoke.reject("picker failed with result code: ${result.resultCode}")
            }
        } catch (ex: Exception) {
            val msg = ex.message ?: "document picker callback failed"
            Logger.error(msg)
            invoke.reject(msg)
        }
    }
}
