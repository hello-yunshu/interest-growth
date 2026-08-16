import java.io.File
import org.apache.tools.ant.taskdefs.condition.Os
import org.gradle.api.DefaultTask
import org.gradle.api.GradleException
import org.gradle.api.logging.LogLevel
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.TaskAction

open class BuildTask : DefaultTask() {
    @Input
    var rootDirRel: String? = null
    @Input
    var target: String? = null
    @Input
    var release: Boolean? = null

    private fun srcTauriDir(): File {
        val rootDirRel = rootDirRel ?: throw GradleException("rootDirRel cannot be null")
        return File(project.projectDir, rootDirRel)
    }

    /**
     * Resolve how to invoke the Tauri CLI for the `android-studio-script` step.
     *
     * This task runs with cwd = <repo>/apps/desktop/src-tauri. The CLI is installed at
     * apps/desktop/node_modules/@tauri-apps/cli/tauri.js, which `node tauri` cannot resolve
     * from that cwd (npm exposes only the `tauri` bin shim, not a `tauri` module). Locate the
     * installed CLI from the app root and run it as `node <absolute path>` so a clean CI
     * checkout (after npm ci) behaves exactly like a local build.
     */
    private fun resolveTauriCli(): Pair<String, List<String>> {
        val appRoot = srcTauriDir().resolve("../").canonicalFile
        val candidates = mutableListOf<File>()
        var dir: File = appRoot
        repeat(4) {
            candidates.add(dir.resolve("node_modules/@tauri-apps/cli/tauri.js"))
            dir = dir.resolve("../")
        }
        for (candidate in candidates) {
            if (candidate.isFile) {
                return "node" to listOf(candidate.absolutePath, "android", "android-studio-script")
            }
        }
        // No local install; fall back to a `tauri` executable on PATH (npm i -g @tauri-apps/cli).
        return "tauri" to listOf("android", "android-studio-script")
    }

    @TaskAction
    fun assemble() {
        val (executable, baseArgs) = resolveTauriCli()
        try {
            runTauriCli(executable, baseArgs)
        } catch (e: Exception) {
            if (Os.isFamily(Os.FAMILY_WINDOWS)) {
                // Try different Windows-specific extensions
                val fallbacks = listOf(
                    "$executable.exe",
                    "$executable.cmd",
                    "$executable.bat",
                )
                var lastException: Exception = e
                for (fallback in fallbacks) {
                    try {
                        runTauriCli(fallback, baseArgs)
                        return
                    } catch (fallbackException: Exception) {
                        lastException = fallbackException
                    }
                }
                throw lastException
            } else {
                throw e
            }
        }
    }

    fun runTauriCli(executable: String, baseArgs: List<String>) {
        val target = target ?: throw GradleException("target cannot be null")
        val release = release ?: throw GradleException("release cannot be null")
        val args = baseArgs.toMutableList()

        project.exec {
            workingDir(srcTauriDir())
            executable(executable)
            args(args)
            if (project.logger.isEnabled(LogLevel.DEBUG)) {
                args("-vv")
            } else if (project.logger.isEnabled(LogLevel.INFO)) {
                args("-v")
            }
            if (release) {
                args("--release")
            }
            args(listOf("--target", target))
        }.assertNormalExitValue()
    }
}
