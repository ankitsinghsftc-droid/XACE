/*!
# build.rs — cbindgen Header Generation

Generates `include/xace.h` from the Rust FFI exports in `src/ffi/xace_ffi.rs`
and `src/ffi/error_codes.rs`.

## Staleness Check (CI)

The generated header is committed to git at `include/xace.h`. A CI step
verifies it is not stale after every build:

```sh
# In ci/check_ffi_header.sh
cargo build 2>/dev/null
git diff --exit-code packages/engine-adapter/include/xace.h || {
    echo "ERROR: include/xace.h is stale. Run: cargo build -p xace-engine-adapter"
    exit 1
}
```

## What cbindgen Generates

From the `#[no_mangle] pub extern "C" fn xace_*` functions in `xace_ffi.rs`
and the `#[repr(C)] pub enum XaceErrorCode` in `error_codes.rs`, cbindgen
produces C declarations that Unity's [DllImport] can bind to.
*/

fn main() {
    let crate_dir = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set");

    // Ensure include/ exists
    std::fs::create_dir_all(format!("{}/include", crate_dir))
        .expect("failed to create include/ directory");

    // Try to run cbindgen — gracefully skip if it fails (avoids breaking
    // builds where the FFI feature is disabled or cbindgen config is missing)
    match cbindgen::Builder::new()
        .with_crate(&crate_dir)
        .with_config(load_config(&crate_dir))
        .generate()
    {
        Ok(bindings) => {
            bindings.write_to_file(format!("{}/include/xace.h", crate_dir));
        }
        Err(e) => {
            // Non-fatal: the committed header is still valid for P/Invoke
            println!("cargo:warning=cbindgen generation skipped: {}", e);
        }
    }

    // Rerun if FFI source files change
    println!("cargo:rerun-if-changed=src/ffi/xace_ffi.rs");
    println!("cargo:rerun-if-changed=src/ffi/error_codes.rs");
    println!("cargo:rerun-if-changed=cbindgen.toml");
}

fn load_config(crate_dir: &str) -> cbindgen::Config {
    let config_path = format!("{}/cbindgen.toml", crate_dir);
    cbindgen::Config::from_file(&config_path).unwrap_or_else(|_| cbindgen::Config::default())
}
