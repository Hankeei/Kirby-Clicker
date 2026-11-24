use eframe::egui::{self, Color32, RichText, Vec2};
use kirby_clicker::{
    METHODS, Profile,
    audio::Audio,
    binds::{ACTIONS, Binds, canonical},
    engine::{Control, Worker},
    platform::{self, Action, Input, Window},
    settings::Settings,
    storage,
};
use std::{
    path::PathBuf,
    sync::{Arc, mpsc},
    time::{Duration, Instant},
};

const GROUND: Color32 = Color32::from_rgb(241, 242, 250);
const CREAM: Color32 = Color32::from_rgb(255, 253, 247);
const PINK: Color32 = Color32::from_rgb(246, 163, 202);
const MINT: Color32 = Color32::from_rgb(192, 239, 220);
const INK: Color32 = Color32::from_rgb(56, 49, 57);
const MUTED: Color32 = Color32::from_rgb(139, 133, 146);
const LINE: Color32 = Color32::from_rgb(228, 225, 236);
const LABELS: [&str; 5] = [
    "Random",
    "Gaussian",
    "Poisson",
    "Gaussian + Poisson",
    "Static ⚠",
];
const SHORT_LABELS: [&str; 5] = ["RANDOM", "GAUSS", "POISSON", "G+P", "STATIC"];
fn pill(ui: &mut egui::Ui, text: impl Into<egui::WidgetText>, fill: Color32) -> egui::Response {
    ui.add(
        egui::Button::new(text)
            .fill(fill)
            .corner_radius(18)
            .min_size(Vec2::new(62., 30.)),
    )
}
fn card() -> egui::Frame {
    egui::Frame::new()
        .fill(CREAM)
        .corner_radius(22)
        .inner_margin(16)
        .stroke(egui::Stroke::new(1_f32, LINE))
        .shadow(egui::epaint::Shadow {
            offset: [0, 7],
            blur: 12,
            spread: 0,
            color: Color32::from_black_alpha(24),
        })
}
fn heading(ui: &mut egui::Ui, label: &str) {
    ui.horizontal(|ui| {
        ui.label(RichText::new(label).size(12.).color(MUTED));
        let (r, _) =
            ui.allocate_exact_size(Vec2::new(ui.available_width(), 1.), egui::Sense::hover());
        ui.painter().line_segment(
            [r.left_center(), r.right_center()],
            egui::Stroke::new(1_f32, LINE),
        );
    });
    ui.add_space(8.);
}
fn combo(ui: &mut egui::Ui, id: &str, value: &mut String, values: &[&str]) {
    egui::ComboBox::from_id_salt(id)
        .selected_text(value.as_str())
        .show_ui(ui, |ui| {
            for v in values {
                ui.selectable_value(value, (*v).into(), *v);
            }
        });
}

pub struct Clicker {
    data: PathBuf,
    settings: Settings,
    binds: Binds,
    control: Arc<Control>,
    worker: Option<Worker>,
    input: Option<Input>,
    audio: Audio,
    events: mpsc::Receiver<Action>,
    selected: String,
    names: Vec<String>,
    profile: Option<Arc<Profile>>,
    message: String,
    settings_open: bool,
    binds_open: bool,
    picker_open: bool,
    rename_open: bool,
    rename_text: String,
    bind_draft: Binds,
    windows: Vec<Window>,
    compact: bool,
    main_size: Vec2,
    main_pos: Option<egui::Pos2>,
    armed_at: Instant,
    last_armed: bool,
    cats: Vec<egui::TextureHandle>,
    cat_delays: Vec<f64>,
    cat_length: f64,
    last_saved: Vec<u8>,
    start: Instant,
    reported_start: bool,
}
impl Clicker {
    pub fn new(
        cc: &eframe::CreationContext<'_>,
        data: PathBuf,
        settings: Settings,
        start: Instant,
    ) -> Self {
        egui_extras::install_image_loaders(&cc.egui_ctx);
        let mut style = (*cc.egui_ctx.style()).clone();
        style.visuals = egui::Visuals::light();
        style.visuals.override_text_color = Some(INK);
        style.visuals.panel_fill = GROUND;
        style.visuals.window_fill = CREAM;
        style.visuals.widgets.inactive.weak_bg_fill = CREAM;
        style.visuals.widgets.inactive.bg_fill = MINT;
        style.visuals.widgets.inactive.bg_stroke = egui::Stroke::new(1_f32, LINE);
        style.visuals.selection.bg_fill = PINK;
        style.spacing.item_spacing = Vec2::new(8., 8.);
        for widget in [
            &mut style.visuals.widgets.inactive,
            &mut style.visuals.widgets.hovered,
            &mut style.visuals.widgets.active,
            &mut style.visuals.widgets.open,
        ] {
            widget.corner_radius = egui::CornerRadius::same(12);
            widget.bg_stroke = egui::Stroke::new(1_f32, LINE);
            widget.fg_stroke = egui::Stroke::new(1.5_f32, INK);
        }
        style.visuals.widgets.hovered.weak_bg_fill = MINT;
        style.visuals.widgets.active.weak_bg_fill = PINK;
        style.visuals.window_corner_radius = egui::CornerRadius::same(16);
        style.spacing.button_padding = Vec2::new(12., 6.);
        cc.egui_ctx.set_style(style);
        if let Ok(bytes) = std::fs::read("C:/Windows/Fonts/segoeui.ttf") {
            let mut fonts = egui::FontDefinitions::default();
            fonts
                .font_data
                .insert("segoe".into(), egui::FontData::from_owned(bytes).into());
            fonts
                .families
                .get_mut(&egui::FontFamily::Proportional)
                .unwrap()
                .insert(0, "segoe".into());
            cc.egui_ctx.set_fonts(fonts);
        }
        let (tx, events) = mpsc::channel();
        let binds_path = data.join("binds.txt");
        let mut message = String::new();
        let binds = match std::fs::read_to_string(&binds_path) {
            Ok(text) => Binds::parse(&text).unwrap_or_else(|e| {
                message = format!(
                    "Could not load shortcuts: {e}. Defaults are active; the file was preserved."
                );
                Binds::default()
            }),
            Err(_) => {
                let b = Binds::default();
                let _ = std::fs::write(&binds_path, b.text());
                b
            }
        };
        let ctx = cc.egui_ctx.clone();
        let control = Control::new(settings.clone(), binds.clone(), move || {
            ctx.request_repaint()
        });
        let worker = Some(Worker::start(control.clone()));
        let input = match Input::start(control.clone(), tx) {
            Ok(i) => Some(i),
            Err(e) => {
                message = e;
                None
            }
        };
        let audio = Audio::start(data.clone());
        audio.music(settings.music_enabled, settings.music_volume);
        let names = storage::library(&data.join("profiles"));
        let selected = names.first().cloned().unwrap_or_default();
        use image::AnimationDecoder;
        let mut cats = Vec::new();
        let mut cat_delays = Vec::new();
        let mut cat_length = 0.;
        if let Ok(decoder) = image::codecs::gif::GifDecoder::new(std::io::Cursor::new(
            include_bytes!("../../assets/cat.gif"),
        )) {
            for (i, frame) in decoder.into_frames().filter_map(Result::ok).enumerate() {
                let (n, d) = frame.delay().numer_denom_ms();
                let delay = (n as f64 / d as f64).max(20.);
                let image = frame.into_buffer();
                let size = [image.width() as usize, image.height() as usize];
                cats.push(cc.egui_ctx.load_texture(
                    format!("cat-{i}"),
                    egui::ColorImage::from_rgba_unmultiplied(size, image.as_raw()),
                    Default::default(),
                ));
                cat_length += delay;
                cat_delays.push(cat_length);
            }
        }
        let compact = settings.compact_enabled;
        let bind_draft = binds.clone();
        let main_size = settings
            .extra
            .get("native_window_size")
            .and_then(|v| Some(Vec2::new(v[0].as_f64()? as f32, v[1].as_f64()? as f32)))
            .unwrap_or(Vec2::new(560., 437.));
        let main_pos = settings
            .extra
            .get("native_window_pos")
            .and_then(|v| Some(egui::pos2(v[0].as_f64()? as f32, v[1].as_f64()? as f32)));
        let last_saved = serde_json::to_vec(&settings).unwrap_or_default();
        let mut app = Self {
            data,
            settings,
            binds,
            control,
            worker,
            input,
            audio,
            events,
            selected,
            names,
            profile: None,
            message,
            settings_open: false,
            binds_open: false,
            picker_open: false,
            rename_open: false,
            rename_text: String::new(),
            bind_draft,
            windows: vec![],
            compact: false,
            main_size,
            main_pos,
            armed_at: Instant::now(),
            last_armed: false,
            cats,
            cat_delays,
            cat_length,
            last_saved,
            start,
            reported_start: false,
        };
        cc.egui_ctx
            .send_viewport_cmd(egui::ViewportCommand::InnerSize(main_size));
        if let Some(p) = main_pos {
            cc.egui_ctx
                .send_viewport_cmd(egui::ViewportCommand::OuterPosition(p));
        }
        if compact {
            app.set_compact(&cc.egui_ctx, true);
        }
        app
    }
    fn save(&mut self) {
        self.settings.validate();
        let bytes = serde_json::to_vec(&self.settings).unwrap_or_default();
        if bytes != self.last_saved {
            match self.settings.save(&self.data.join("settings.json")) {
                Ok(()) => self.last_saved = bytes,
                Err(e) => self.message = format!("Could not save settings: {e}"),
            }
        }
    }
    fn toggle(&mut self) {
        if self.input.is_none() {
            self.message = "Mouse hook unavailable; restart the app before enabling".into();
            return;
        }
        if self.control.lock().recorder.active {
            self.message = "Stop recording before turning ON".into();
            return;
        }
        let armed = self.control.toggle();
        self.audio.cue(armed);
        if armed {
            self.armed_at = Instant::now();
        }
        self.last_armed = armed;
    }
    fn disarm(&mut self) {
        let was = self.control.lock().armed;
        self.control.disarm();
        if was {
            self.audio.cue(false);
        }
        self.last_armed = false;
    }
    fn record(&mut self) {
        if self.input.is_none() {
            self.message = "Mouse hook is unavailable; recording cannot start".into();
            return;
        }
        if self.control.lock().recorder.active {
            let p = self.control.stop_record();
            if p.clicks.is_empty() {
                self.message = "No clicks recorded".into();
                return;
            }
            match storage::save_new(&self.data.join("profiles"), &p, None) {
                Ok(path) => {
                    self.selected = path.file_name().unwrap().to_string_lossy().into_owned();
                    self.profile = Some(Arc::new(p));
                    self.control.lock().profile = self.profile.clone();
                    self.refresh();
                    self.message = format!("Saved {}", self.selected);
                }
                Err(e) => self.message = e,
            }
        } else {
            self.disarm();
            match self.control.start_record() {
                Ok(()) => {
                    self.message = "Recording physical clicks · press Record again to finish".into()
                }
                Err(e) => self.message = e,
            }
        }
    }
    fn refresh(&mut self) {
        self.names = storage::library(&self.data.join("profiles"));
    }
    fn load(&mut self) {
        self.disarm();
        match storage::read(&self.data.join("profiles").join(&self.selected)) {
            Ok(p) => {
                self.message = format!("Loaded {} · {} clicks", self.selected, p.clicks.len());
                self.profile = Some(Arc::new(p));
                self.control.lock().profile = self.profile.clone();
            }
            Err(e) => self.message = e,
        }
    }
    fn picker(&mut self) {
        self.disarm();
        self.windows = platform::windows();
        self.picker_open = true;
    }
    fn apply_binds(&mut self) -> Result<(), String> {
        self.bind_draft.trigger = canonical(&self.bind_draft.trigger);
        for key in self.bind_draft.keys.values_mut() {
            *key = canonical(key);
        }
        self.bind_draft.validate()?;
        self.disarm();
        std::fs::write(self.data.join("binds.txt"), self.bind_draft.text())
            .map_err(|e| e.to_string())?;
        self.binds = self.bind_draft.clone();
        {
            let mut s = self.control.lock();
            s.binds = self.binds.clone();
            s.trigger_down = false;
        }
        if let Some(input) = &self.input {
            input.rebind();
        }
        Ok(())
    }
    fn set_compact(&mut self, ctx: &egui::Context, on: bool) {
        if on && !self.compact {
            ctx.input(|i| {
                if let Some(r) = i.viewport().inner_rect {
                    self.main_size = r.size();
                }
                if let Some(r) = i.viewport().outer_rect {
                    self.main_pos = Some(r.min);
                }
            });
        }
        self.compact = on;
        self.settings.compact_enabled = on;
        ctx.request_repaint_after(Duration::from_millis(30));
        ctx.send_viewport_cmd(egui::ViewportCommand::Decorations(!on));
        ctx.send_viewport_cmd(egui::ViewportCommand::Resizable(!on));
        ctx.send_viewport_cmd(egui::ViewportCommand::WindowLevel(if on {
            egui::WindowLevel::AlwaysOnTop
        } else {
            egui::WindowLevel::Normal
        }));
        ctx.send_viewport_cmd(egui::ViewportCommand::MinInnerSize(if on {
            Vec2::new(188., 104.)
        } else {
            Vec2::new(440., 250.)
        }));
        ctx.send_viewport_cmd(egui::ViewportCommand::InnerSize(if on {
            Vec2::new(188., 104.)
        } else {
            self.main_size
        }));
        let pos = if on {
            self.settings
                .extra
                .get("compact_pos")
                .and_then(|v| Some(egui::pos2(v[0].as_f64()? as f32, v[1].as_f64()? as f32)))
        } else {
            self.main_pos
        };
        if let Some(p) = pos {
            ctx.send_viewport_cmd(egui::ViewportCommand::OuterPosition(p));
        }
        platform::compact_style(on);
    }
    fn bars(&self, ui: &mut egui::Ui, recent: &[f64], width: f32, height: f32) {
        let (rect, _) = ui.allocate_exact_size(Vec2::new(width, height), egui::Sense::hover());
        let spacing = width / 24.;
        for i in 0..24 {
            let value = recent.get(i).copied().unwrap_or(75.);
            let h = if recent.is_empty() {
                3.
            } else {
                (height * (1000. / value / 50.) as f32).clamp(3., height)
            };
            let bar = egui::Rect::from_min_max(
                egui::pos2(rect.left() + i as f32 * spacing, rect.bottom() - h),
                egui::pos2(rect.left() + (i + 1) as f32 * spacing - 2., rect.bottom()),
            );
            ui.painter()
                .rect_filled(bar, 2., Color32::from_rgb(216, 144, 160));
        }
    }
    fn dialogs(&mut self, ctx: &egui::Context) {
        if self.rename_open {
            let mut open = true;
            egui::Window::new("Rename profile")
                .open(&mut open)
                .collapsible(false)
                .resizable(false)
                .show(ctx, |ui| {
                    ui.text_edit_singleline(&mut self.rename_text);
                    if ui.button("Rename").clicked() {
                        match storage::rename(
                            &self.data.join("profiles"),
                            &self.selected,
                            &self.rename_text,
                        ) {
                            Ok(name) => {
                                self.selected = name;
                                self.refresh();
                                self.rename_open = false;
                                self.message = "Profile renamed".into();
                            }
                            Err(e) => self.message = e,
                        }
                    }
                    ui.label(&self.message);
                });
            if !open {
                self.rename_open = false;
            }
        }
        if self.picker_open {
            let mut open = true;
            let mut chosen = None;
            egui::Window::new("Select target app")
                .open(&mut open)
                .default_width(400.)
                .show(ctx, |ui| {
                    if ui.button("Refresh").clicked() {
                        self.windows = platform::windows();
                    }
                    egui::ScrollArea::vertical()
                        .max_height(320.)
                        .show(ui, |ui| {
                            for w in &self.windows {
                                if ui.button(format!("{} · {}", w.exe, w.title)).clicked() {
                                    chosen = Some(w.exe.clone());
                                }
                            }
                        });
                });
            if let Some(exe) = chosen {
                self.bind_draft = self.binds.clone();
                self.bind_draft.target = exe;
                self.bind_draft.scope = "restricted".into();
                if let Err(e) = self.apply_binds() {
                    self.message = e;
                }
                self.picker_open = false;
            } else if !open {
                self.picker_open = false;
            }
        }
        if self.binds_open {
            let mut open = true;
            egui::Window::new("Edit shortcuts")
                .open(&mut open)
                .collapsible(false)
                .resizable(false)
                .show(ctx, |ui| {
                    ui.label("Enter a key name, e.g. F8, INSERT, SPACE, A.");
                    egui::Grid::new("bind-grid").show(ui, |ui| {
                        for action in ACTIONS {
                            ui.label(action);
                            ui.add(
                                egui::TextEdit::singleline(
                                    self.bind_draft.keys.get_mut(action).unwrap(),
                                )
                                .desired_width(110.),
                            );
                            ui.end_row();
                        }
                        ui.label("Hold trigger");
                        combo(
                            ui,
                            "trigger",
                            &mut self.bind_draft.trigger,
                            &["MOUSE1", "MOUSE2", "MOUSE3", "MOUSE4", "MOUSE5"],
                        );
                        ui.end_row();
                    });
                    if ui.button("Save shortcuts").clicked() {
                        match self.apply_binds() {
                            Ok(()) => {
                                self.binds_open = false;
                                self.message = "Shortcuts updated".into();
                            }
                            Err(e) => self.message = e,
                        }
                    }
                    ui.colored_label(MUTED, &self.message);
                });
            if !open {
                self.binds_open = false;
            }
        }
        if self.settings_open {
            let mut open = true;
            egui::Window::new("Settings")
                .open(&mut open)
                .collapsible(false)
                .resizable(false)
                .default_width(360.)
                .show(ctx, |ui| {
                    egui::ScrollArea::vertical()
                        .max_height((ctx.content_rect().height() - 70.).max(120.))
                        .show(ui, |ui| {
                            egui::Grid::new("settings-grid")
                                .spacing([16., 12.])
                                .show(ui, |ui| {
                                    ui.label("Click delivery");
                                    combo(
                                        ui,
                                        "backend",
                                        &mut self.settings.click_backend,
                                        &["foreground", "background"],
                                    );
                                    ui.end_row();
                                    ui.label("Record button");
                                    {
                                        let mut s = self.control.lock();
                                        combo(
                                            ui,
                                            "record-button",
                                            &mut s.record_button,
                                            &["left", "right", "middle"],
                                        );
                                    }
                                    ui.end_row();
                                    ui.label("Dry run (Recorder)");
                                    {
                                        let mut s = self.control.lock();
                                        ui.checkbox(&mut s.dry_run, "No clicks sent");
                                    }
                                    ui.end_row();
                                    ui.label("Click scope");
                                    let old = self.binds.scope.clone();
                                    combo(
                                        ui,
                                        "scope",
                                        &mut self.binds.scope,
                                        &["anywhere", "restricted"],
                                    );
                                    if old != self.binds.scope {
                                        self.bind_draft = self.binds.clone();
                                        if let Err(e) = self.apply_binds() {
                                            self.message = e;
                                        }
                                    }
                                    ui.end_row();
                                    ui.label("Target app");
                                    if ui
                                        .button(if self.binds.target.is_empty() {
                                            "Pick…"
                                        } else {
                                            &self.binds.target
                                        })
                                        .clicked()
                                    {
                                        self.picker();
                                    }
                                    ui.end_row();
                                    ui.label("Background music");
                                    if ui
                                        .checkbox(&mut self.settings.music_enabled, "Enabled")
                                        .changed()
                                    {
                                        self.audio.music(
                                            self.settings.music_enabled,
                                            self.settings.music_volume,
                                        );
                                    }
                                    ui.end_row();
                                    ui.label("Music volume");
                                    if ui
                                        .add(
                                            egui::Slider::new(
                                                &mut self.settings.music_volume,
                                                0. ..=1.,
                                            )
                                            .custom_formatter(|v, _| {
                                                format!("{} %", (v * 100.).round())
                                            }),
                                        )
                                        .changed()
                                    {
                                        self.audio.music(
                                            self.settings.music_enabled,
                                            self.settings.music_volume,
                                        );
                                    }
                                    ui.end_row();
                                });
                            ui.separator();
                            ui.horizontal(|ui| {
                                if ui.button("Edit binds…").clicked() {
                                    self.disarm();
                                    self.bind_draft = self.binds.clone();
                                    self.binds_open = true;
                                }
                                if ui.button("Import profile…").clicked() {
                                    self.disarm();
                                    if let Some(path) = platform::file_dialog(false, true) {
                                        match storage::import(&path, &self.data.join("profiles")) {
                                            Ok(p) => {
                                                self.selected = p
                                                    .file_name()
                                                    .unwrap()
                                                    .to_string_lossy()
                                                    .into_owned();
                                                self.refresh();
                                                self.load();
                                            }
                                            Err(e) => self.message = e,
                                        }
                                    }
                                }
                                if ui
                                    .add_enabled(
                                        self.profile.is_some(),
                                        egui::Button::new("Export…"),
                                    )
                                    .clicked()
                                {
                                    self.disarm();
                                    if let Some(path) = platform::file_dialog(true, true) {
                                        let p = self.profile.as_ref().unwrap();
                                        let result = storage::export(&path, p, &self.selected);
                                        self.message = result
                                            .map(|_| "Profile exported".into())
                                            .unwrap_or_else(|e| e);
                                    }
                                }
                            });
                            ui.colored_label(MUTED, &self.message);
                            ui.separator();
                            ui.label(
                                RichText::new(format!(
                                    "Kirby Clicker v{}",
                                    env!("CARGO_PKG_VERSION")
                                ))
                                .small(),
                            );
                            ui.label(RichText::new("vibe coded by @hankeei <3").small().italics());
                            ui.hyperlink("https://linktr.ee/hankeei");
                            if ui.button("Done").clicked() {
                                self.settings_open = false;
                            }
                        });
                });
            if !open {
                self.settings_open = false;
            }
        }
    }
}
impl eframe::App for Clicker {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Winit processes viewport styles after the preceding update. Apply
        // no-activate flags on the next frame so they are not overwritten.
        platform::compact_style(self.compact);
        while let Ok(action) = self.events.try_recv() {
            match action {
                Action::Warning(e) => self.message = e,
                Action::Hotkey(a) => match a.as_str() {
                    "toggle" => self.toggle(),
                    "record" => self.record(),
                    "rebind" => {
                        self.disarm();
                        self.bind_draft = self.binds.clone();
                        self.binds_open = true;
                    }
                    "selector" => self.picker(),
                    "quit" => {
                        let recording = self.control.lock().recorder.active;
                        if recording {
                            self.record();
                        } else if self.control.lock().armed {
                            self.disarm();
                        } else {
                            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                        }
                    }
                    _ => {}
                },
            }
        }
        let (armed, clicking, recording, record_count, sent, recent, error) = {
            let s = self.control.lock();
            (
                s.armed,
                s.clicking,
                s.recorder.active,
                s.recorder.count(),
                s.sent,
                s.recent.iter().copied().collect::<Vec<_>>(),
                s.error.clone(),
            )
        };
        if armed && !self.last_armed {
            self.armed_at = Instant::now();
        }
        self.last_armed = armed;
        if !error.is_empty() {
            self.message = error;
        }
        if !self.reported_start {
            self.reported_start = true;
            if let Some(path) = std::env::var_os("KIRBYCLICKER_STARTUP_OUT") {
                let _ = std::fs::write(
                    path,
                    format!("{}", self.start.elapsed().as_secs_f64() * 1000.),
                );
            }
        }
        if self.compact {
            egui::CentralPanel::default()
                .frame(egui::Frame::new().fill(CREAM).inner_margin(9))
                .show(ctx, |ui| {
                    ui.horizontal(|ui| {
                        if ui
                            .small_button(
                                SHORT_LABELS[METHODS
                                    .iter()
                                    .position(|m| *m == self.settings.auto_method)
                                    .unwrap_or(0)],
                            )
                            .clicked()
                        {
                            let i = METHODS
                                .iter()
                                .position(|m| *m == self.settings.auto_method)
                                .unwrap_or(0);
                            self.settings.auto_method = METHODS[(i + 1) % 5].into();
                        }
                        if ui
                            .small_button("Restore")
                            .on_hover_text("Restore window")
                            .clicked()
                        {
                            self.set_compact(ctx, false);
                        }
                    });
                    ui.horizontal(|ui| {
                        ui.colored_label(if clicking { PINK } else { MUTED }, "●");
                        if pill(
                            ui,
                            if armed { "ON" } else { "OFF" },
                            if armed { PINK } else { GROUND },
                        )
                        .clicked()
                        {
                            self.toggle();
                        }
                        self.bars(ui, &recent, 60., 24.);
                    });
                    let drag = ui.allocate_response(
                        Vec2::new(ui.available_width(), 12.),
                        egui::Sense::drag(),
                    );
                    if drag.drag_started() {
                        ctx.send_viewport_cmd(egui::ViewportCommand::StartDrag);
                    }
                });
        } else {
            egui::CentralPanel::default()
                .frame(
                    egui::Frame::new()
                        .fill(GROUND)
                        .inner_margin(egui::Margin::symmetric(24, 12)),
                )
                .show(ctx, |ui| {
                    egui::Image::new(egui::include_image!("../../assets/pattern.png"))
                        .tint(Color32::from_white_alpha(90))
                        .paint_at(ui, ctx.content_rect());
                    ui.horizontal(|ui| {
                        let source = if armed {
                            egui::include_image!("../../assets/mascot_eat.png")
                        } else if self.settings.active_tab == 1 {
                            egui::include_image!("../../assets/mascot_pikachu.png")
                        } else {
                            egui::include_image!("../../assets/mascot_kirby.png")
                        };
                        ui.add(egui::Image::new(source).fit_to_exact_size(Vec2::new(56., 48.)));
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if pill(ui, "Compact", CREAM)
                                .on_hover_text("Compact")
                                .clicked()
                            {
                                self.set_compact(ctx, true);
                            }
                            if ui.small_button("⚙").on_hover_text("Settings").clicked() {
                                self.disarm();
                                self.settings_open = true;
                            }
                            if pill(
                                ui,
                                if armed { "ON" } else { "OFF" },
                                if armed { PINK } else { CREAM },
                            )
                            .on_hover_text(format!(
                                "{} toggles · hold {} to click",
                                self.binds.keys["toggle"], self.binds.trigger
                            ))
                            .clicked()
                            {
                                self.toggle();
                            }
                            ui.colored_label(
                                if clicking {
                                    PINK
                                } else if armed {
                                    MINT
                                } else {
                                    MUTED
                                },
                                "●",
                            );
                            if !self.cats.is_empty() {
                                let t = if armed {
                                    self.armed_at.elapsed().as_secs_f64() * 1000. % self.cat_length
                                } else {
                                    0.
                                };
                                let i = self.cat_delays.iter().position(|d| *d > t).unwrap_or(0);
                                ui.add(
                                    egui::Image::new(&self.cats[i])
                                        .fit_to_exact_size(Vec2::new(30., 30.)),
                                );
                                if armed {
                                    ctx.request_repaint_after(Duration::from_millis(40));
                                }
                            }
                        });
                    });
                    ui.horizontal(|ui| {
                        ui.spacing_mut().button_padding.y = 3.;
                        ui.selectable_value(&mut self.settings.active_tab, 0, "Recorder");
                        ui.selectable_value(&mut self.settings.active_tab, 1, "Auto");
                    });
                    ui.add_space(12.);
                    egui::ScrollArea::vertical()
                        .auto_shrink([false, false])
                        .show(ui, |ui| {
                            if self.settings.active_tab == 0 {
                                card().show(ui, |ui| {
                                    ui.set_min_width((ui.available_width() - 2.).max(100.));
                                    ui.add_space(20.);
                                    egui::Frame::new()
                                        .fill(MINT)
                                        .corner_radius(18)
                                        .inner_margin(12)
                                        .show(ui, |ui| {
                                            ui.set_min_width(ui.available_width());
                                            ui.horizontal_wrapped(|ui| {
                                                let record_response = pill(
                                                    ui,
                                                    RichText::new(format!(
                                                        "●  {}  {}",
                                                        if recording { "Stop" } else { "Record" },
                                                        self.binds.keys["record"]
                                                    ))
                                                    .strong(),
                                                    PINK,
                                                );
                                                let bite = egui::Rect::from_min_size(
                                                    record_response.rect.min - Vec2::new(18., 15.),
                                                    Vec2::new(38., 58.),
                                                );
                                                egui::Image::new(egui::include_image!(
                                                    "../../assets/mascot_bite.png"
                                                ))
                                                .paint_at(ui, bite);
                                                if record_response.clicked() {
                                                    self.record();
                                                }
                                                egui::ComboBox::from_id_salt("profiles")
                                                    .width(120.)
                                                    .selected_text(if self.selected.is_empty() {
                                                        "No profiles"
                                                    } else {
                                                        &self.selected
                                                    })
                                                    .show_ui(ui, |ui| {
                                                        for name in &self.names {
                                                            ui.selectable_value(
                                                                &mut self.selected,
                                                                name.clone(),
                                                                name,
                                                            );
                                                        }
                                                    });
                                                if pill(ui, "Load", CREAM).clicked() {
                                                    self.load();
                                                }
                                            });
                                        });
                                    ui.add_space(10.);
                                    ui.colored_label(
                                        MUTED,
                                        if recording {
                                            format!("{record_count} clicks recorded")
                                        } else {
                                            self.profile
                                                .as_ref()
                                                .map(|p| {
                                                    format!(
                                                        "{} clicks · hold {} to replay",
                                                        p.clicks.len(),
                                                        self.binds.trigger
                                                    )
                                                })
                                                .unwrap_or_else(|| {
                                                    "Record your rhythm or load a profile".into()
                                                })
                                        },
                                    );
                                    ui.add_space(20.);
                                });
                                ui.add_space(14.);
                                card().show(ui, |ui| {
                                    ui.set_min_width((ui.available_width() - 2.).max(100.));
                                    heading(ui, "PROFILES");
                                    ui.horizontal_wrapped(|ui| {
                                        if pill(ui, "Rename", CREAM).clicked() {
                                            self.disarm();
                                            self.rename_text =
                                                self.selected.trim_end_matches(".txt").into();
                                            self.rename_open = true;
                                        }
                                        if pill(ui, "Open folder", CREAM).clicked() {
                                            platform::open(&self.data.join("profiles"));
                                        }
                                        if ui
                                            .small_button("↻")
                                            .on_hover_text("Refresh profiles")
                                            .clicked()
                                        {
                                            self.refresh();
                                        }
                                    });
                                });
                            } else {
                                card().show(ui, |ui| {
                                    ui.set_min_width((ui.available_width() - 2.).max(100.));
                                    heading(ui, "AUTO CLICKER");
                                    egui::ComboBox::from_id_salt("method")
                                        .selected_text(
                                            LABELS[METHODS
                                                .iter()
                                                .position(|m| *m == self.settings.auto_method)
                                                .unwrap_or(0)],
                                        )
                                        .show_ui(ui, |ui| {
                                            for (i, method) in METHODS.iter().enumerate() {
                                                ui.selectable_value(
                                                    &mut self.settings.auto_method,
                                                    (*method).into(),
                                                    LABELS[i],
                                                );
                                            }
                                        });
                                    let low_changed = ui
                                        .add(
                                            egui::Slider::new(
                                                &mut self.settings.auto_min_cps,
                                                1. ..=50.,
                                            )
                                            .text("Lower CPS")
                                            .step_by(0.1),
                                        )
                                        .changed();
                                    let high_changed = ui
                                        .add(
                                            egui::Slider::new(
                                                &mut self.settings.auto_max_cps,
                                                1. ..=50.,
                                            )
                                            .text("Upper CPS")
                                            .step_by(0.1),
                                        )
                                        .changed();
                                    if self.settings.auto_method == "static" {
                                        let n = if low_changed {
                                            self.settings.auto_min_cps
                                        } else if high_changed {
                                            self.settings.auto_max_cps
                                        } else {
                                            (self.settings.auto_min_cps
                                                + self.settings.auto_max_cps)
                                                / 2.
                                        };
                                        self.settings.auto_min_cps = n;
                                        self.settings.auto_max_cps = n;
                                    } else if self.settings.auto_min_cps
                                        > self.settings.auto_max_cps
                                    {
                                        if low_changed {
                                            self.settings.auto_max_cps = self.settings.auto_min_cps;
                                        } else {
                                            self.settings.auto_min_cps = self.settings.auto_max_cps;
                                        }
                                    }
                                    if self.settings.auto_method.contains("gaussian") {
                                        ui.add(
                                            egui::Slider::new(
                                                &mut self.settings.auto_sigma,
                                                0.05..=0.4,
                                            )
                                            .text("Sigma"),
                                        );
                                    }
                                    ui.horizontal(|ui| {
                                        ui.label("Click button");
                                        combo(
                                            ui,
                                            "auto-button",
                                            &mut self.settings.auto_button,
                                            &["left", "right", "middle"],
                                        );
                                    });
                                    ui.label(
                                        RichText::new(format!(
                                            "Turn ON, then hold {} · {} clicks sent",
                                            self.binds.trigger, sent
                                        ))
                                        .color(MUTED),
                                    );
                                    self.bars(ui, &recent, ui.available_width().min(260.), 42.);
                                });
                            }
                            ui.add_space(12.);
                            ui.label(RichText::new(&self.message).small().color(MUTED));
                        });
                });
        }
        ctx.input(|i| {
            if let Some(r) = i.viewport().inner_rect {
                if !self.compact && r.width() >= 440. {
                    self.main_size = r.size();
                }
            }
            if let Some(r) = i.viewport().outer_rect {
                if self.compact {
                    self.settings
                        .extra
                        .insert("compact_pos".into(), serde_json::json!([r.min.x, r.min.y]));
                } else {
                    self.main_pos = Some(r.min);
                }
            }
        });
        self.dialogs(ctx);
        {
            let mut s = self.control.lock();
            if s.settings.active_tab != self.settings.active_tab
                || s.settings.auto_button != self.settings.auto_button
                || s.settings.click_backend != self.settings.click_backend
                || s.settings.auto_method != self.settings.auto_method
                || s.settings.auto_min_cps != self.settings.auto_min_cps
                || s.settings.auto_max_cps != self.settings.auto_max_cps
                || s.settings.auto_sigma != self.settings.auto_sigma
            {
                s.cancel();
            }
            s.settings = self.settings.clone();
        }
        self.control.wake_worker();
        self.save();
    }
    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        self.disarm();
        if self.control.lock().recorder.active {
            self.record();
        }
        self.input.take();
        self.worker.take();
        self.settings.extra.insert(
            "native_window_size".into(),
            serde_json::json!([self.main_size.x, self.main_size.y]),
        );
        if let Some(p) = self.main_pos {
            self.settings
                .extra
                .insert("native_window_pos".into(), serde_json::json!([p.x, p.y]));
        }
        self.save();
    }
}
