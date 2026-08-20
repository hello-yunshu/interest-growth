// Gate R2 §10.3 / R4 §10 layer-2 — Desktop A native broker harness binary.
//
// This is the `Desktop A` side of the true Native cross-device gate. It is
// built ONLY by the CI cross-device job via the `desktop-native-harness`
// feature (the [[bin]] target carries `required-features`), so it never
// appears in any product/release build.
//
// Usage (run from the CI runner):
//   desktop_native_harness --config /path/to/harness.json
// or pipe the config JSON on stdin:
//   echo '{...}' | desktop_native_harness
//
// The config JSON is a `HarnessConfig` document with `phase` = "a_create" or
// "b_revoke" (see src/cross_device_harness.rs). Exit code 0 = PASS, 1 = FAIL.
fn main() {
    let config_json = match read_config() {
        Ok(json) => json,
        Err(message) => {
            eprintln!("desktop_native_harness: {message}");
            std::process::exit(2);
        }
    };
    let exit = interest_growth_desktop_lib::run_desktop_native_harness(&config_json);
    std::process::exit(exit);
}

fn read_config() -> Result<String, String> {
    let mut args = std::env::args().skip(1);
    let mut config_path: Option<String> = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--config" => {
                config_path = args.next().map(|value| value.to_string());
                if config_path.is_none() {
                    return Err("--config requires a file path".to_string());
                }
            }
            "--help" | "-h" => {
                println!(
                    "usage: desktop_native_harness [--config <file>]\n\
                     Reads a HarnessConfig JSON (stdin or --config file) and runs the \
                     Desktop A native broker phase (a_create | b_revoke).\n\
                     exit 0 = PASS, 1 = FAIL, 2 = harness error."
                );
                std::process::exit(0);
            }
            other => {
                return Err(format!("unexpected argument: {other}"));
            }
        }
    }
    if let Some(path) = config_path {
        return std::fs::read_to_string(&path)
            .map_err(|error| format!("cannot read config {}: {error}", path));
    }
    // Fall back to stdin (CI can pipe the JSON document).
    let mut buffer = String::new();
    std::io::Read::read_to_string(&mut std::io::stdin(), &mut buffer)
        .map_err(|error| format!("cannot read config from stdin: {error}"))?;
    if buffer.trim().is_empty() {
        return Err("no config provided (use --config <file> or pipe JSON on stdin)".to_string());
    }
    Ok(buffer)
}
