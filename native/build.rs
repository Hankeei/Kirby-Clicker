fn main() {
    println!("cargo:rerun-if-changed=../assets/icon.ico");
    let mut resource = winresource::WindowsResource::new();
    resource
        .set_icon("../assets/icon.ico")
        .set("ProductName", "Kirby Clicker")
        .set("FileDescription", "Kirby Clicker — native Windows clicker")
        .set("ProductVersion", env!("CARGO_PKG_VERSION"))
        .set("FileVersion", env!("CARGO_PKG_VERSION"));
    resource
        .compile()
        .expect("Could not compile Windows icon/version resources (install the Windows SDK)");
}
