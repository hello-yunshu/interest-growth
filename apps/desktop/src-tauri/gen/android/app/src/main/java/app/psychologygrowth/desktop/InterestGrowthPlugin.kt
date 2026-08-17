// Gate E / R0.5-R0.6 — Interest Growth SAF bridge for Android.
//
// This plugin provides native Android operations that require the Activity
// context or SAF (Storage Access Framework) intents:
//
//   * stageContentUri      — streams a SAF content URI into a BOUNDED
//                            app-private cache file, aborting if it would
//                            exceed the product upload limit. Returns the
//                            staged file path + metadata; the bytes stay on
//                            disk and are never materialised as a full
//                            ByteArray/base64 String (Gate R0.5).
//   * pickDocument         — opens SAF ACTION_OPEN_DOCUMENT and returns the
//                            selected content URI.
//   * saveDocumentFromFile — opens SAF ACTION_CREATE_DOCUMENT and copies a
//                            bounded app-private temp file into the
//                            user-selected location in bounded chunks, never
//                            as a full base64 payload (Gate R0.6).
//
// The plugin is registered from Rust via register_android_plugin and
// commands are dispatched through the Rust command layer — the renderer
// never talks to Kotlin directly and never receives the raw file bytes.
package app.psychologygrowth.desktop

import android.app.Activity
import android.content.ContentResolver
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.result.ActivityResult
import app.tauri.Logger
import app.tauri.annotation.ActivityCallback
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

// Bounded chunk size for streaming SAF bytes to/from app-private temp files.
// Files are copied in these chunks; they are never read into a single full
// ByteArray (Gate R0.5/R0.6).
private const val BUFFER_SIZE = 64 * 1024

@InvokeArg
class StageContentUriArgs {
    lateinit var uri: String
    var maxBytes: Long = 0
}

@InvokeArg
class SaveDocumentFromFileArgs {
    lateinit var sourcePath: String
    lateinit var filename: String
    var mimeType: String? = null
}

@InvokeArg
class PickDocumentArgs {
    var mimeType: String? = null
}

@TauriPlugin
class InterestGrowthPlugin(private val activity: Activity) : Plugin(activity) {

    // Gate R0.6 — the source temp path + filename must survive the round trip
    // between the saveDocumentFromFile command and its activity-result
    // callback. The callback receives a fresh Invoke, so the pending payload
    // is kept here on the plugin instance (single pending save at a time).
    //
    // §14 — single-flight: only ONE save dialog may be pending at a time. A
    // second concurrent saveDocumentFromFile must be rejected (not silently
    // overwrite the first pending payload in this single slot), or the first
    // callback would copy from the wrong source.
    private var pendingSaveFromFile: SaveDocumentFromFileArgs? = null

    // ------------------------------------------------------------ stageContentUri
    //
    // Stream a content:// URI (from SAF document picker) into a bounded
    // app-private cache file. The copy is aborted if `maxBytes` would be
    // exceeded, so no unbounded buffer is ever built (Gate R0.5). Returns the
    // staged file path plus metadata; the renderer only ever passes the URI.
    @Command
    fun stageContentUri(invoke: Invoke) {
        var staged: File? = null
        try {
            val args = invoke.parseArgs(StageContentUriArgs::class.java)
            if (args.maxBytes <= 0) {
                throw IllegalArgumentException("maxBytes must be positive")
            }
            val uri = Uri.parse(args.uri)
            // Gate HIGH-2 — the renderer is NOT a security boundary, so the
            // native layer must fail closed: only a `content://` URI supplied
            // by SAF is acceptable. `file://`, `http(s)://`, `android.resource://`,
            // an empty/malformed scheme are all rejected before any provider
            // call. This must NEVER be relaxed to grant broad storage access.
            if (uri.scheme == null || uri.scheme != ContentResolver.SCHEME_CONTENT) {
                throw IllegalArgumentException(
                    "only content:// URIs are accepted (got scheme: ${uri.scheme ?: "none"})"
                )
            }
            val contentResolver = activity.contentResolver

            // Resolve display name and size from the content provider.
            var displayName = "upload.bin"
            var cursor = contentResolver.query(uri, null, null, null, null)
            cursor?.use { c ->
                if (c.moveToFirst()) {
                    val nameIdx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (nameIdx >= 0) displayName = c.getString(nameIdx) ?: displayName
                }
            }

            staged = File(activity.cacheDir, "ig-upload-${System.nanoTime()}.tmp")
            val inputStream = contentResolver.openInputStream(uri)
                ?: throw IllegalStateException("cannot open content URI: $uri")
            var total = 0L
            inputStream.use { input ->
                FileOutputStream(staged!!).use { output ->
                    val buffer = ByteArray(BUFFER_SIZE)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        total += read.toLong()
                        if (total > args.maxBytes) {
                            throw IllegalStateException("file exceeds the upload limit")
                        }
                        output.write(buffer, 0, read)
                    }
                }
            }

            val result = JSObject()
            result.put("path", staged!!.absolutePath)
            result.put("name", displayName)
            result.put("size", total)
            result.put("mimeType", contentResolver.getType(uri) ?: "application/octet-stream")
            invoke.resolve(result)
        } catch (ex: Exception) {
            staged?.delete()
            val msg = ex.message ?: "failed to stage content URI"
            Logger.error(msg)
            invoke.reject(msg)
        }
    }

    // ------------------------------------------------------------ saveDocumentFromFile
    //
    // Open SAF ACTION_CREATE_DOCUMENT and copy a bounded app-private temp file
    // into the user-selected location in bounded chunks (Gate R0.6). The
    // source path is held on the plugin while the SAF dialog is open; the
    // activity-result callback performs the copy.
    @Command
    fun saveDocumentFromFile(invoke: Invoke) {
        try {
            if (pendingSaveFromFile != null) {
                // §14 — a save dialog is already pending in the single slot.
                // Reject rather than overwrite, so the first callback never
                // copies from a source that was replaced by a second request.
                throw IllegalStateException("a save dialog is already pending")
            }
            val args = invoke.parseArgs(SaveDocumentFromFileArgs::class.java)
            val src = File(args.sourcePath)
            if (!src.isFile) {
                throw IllegalArgumentException("source file not found: ${args.sourcePath}")
            }
            pendingSaveFromFile = args
            val mime = args.mimeType ?: "application/octet-stream"
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.type = mime
            intent.putExtra(Intent.EXTRA_TITLE, args.filename)
            startActivityForResult(invoke, intent, "saveDocumentFromFileResult")
        } catch (ex: Exception) {
            pendingSaveFromFile = null
            val msg = ex.message ?: "failed to open save document dialog"
            Logger.error(msg)
            invoke.reject(msg)
        }
    }

    @ActivityCallback
    fun saveDocumentFromFileResult(invoke: Invoke, result: ActivityResult) {
        val pending = pendingSaveFromFile
        pendingSaveFromFile = null
        try {
            when (result.resultCode) {
                Activity.RESULT_OK -> {
                    val data = result.data
                    if (data != null && data.data != null) {
                        val uri = data.data!!
                        val args = pending
                            ?: throw IllegalStateException("save document payload lost before callback")
                        val src = File(args.sourcePath)
                        // Copy the bounded temp file into the SAF output stream
                        // in bounded chunks — never a full base64 write.
                        val outputStream = activity.contentResolver.openOutputStream(uri, "w")
                            ?: throw IllegalStateException("cannot open output stream for: $uri")
                        var total = 0L
                        outputStream.use { output ->
                            FileInputStream(src).use { input ->
                                val buffer = ByteArray(BUFFER_SIZE)
                                while (true) {
                                    val read = input.read(buffer)
                                    if (read < 0) break
                                    output.write(buffer, 0, read)
                                    total += read.toLong()
                                }
                            }
                        }

                        val callResult = JSObject()
                        callResult.put("uri", uri.toString())
                        callResult.put("size", total)
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