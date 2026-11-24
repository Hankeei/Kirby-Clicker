//! Rust MP3 decoding and WASAPI output, isolated from UI/input threads.
use rodio::{Decoder, OutputStream, OutputStreamBuilder, Sink};
use std::{
    io::Cursor,
    path::PathBuf,
    sync::mpsc,
    thread::{self, JoinHandle},
};
use windows_sys::Win32::Media::Audio::{PlaySoundW, SND_ASYNC, SND_MEMORY, SND_NODEFAULT};

enum Command {
    Music(bool, f64),
    Cue(bool, Option<mpsc::Sender<bool>>),
    Probe(mpsc::Sender<Result<String, String>>),
    Position(mpsc::Sender<u64>),
    Stop,
}
pub struct Audio {
    tx: mpsc::Sender<Command>,
    join: Option<JoinHandle<()>>,
}
fn quiet_wav(input: &[u8]) -> Vec<u8> {
    let mut data = input.to_vec();
    let mut offset = 12;
    while offset + 8 <= data.len() {
        let n = u32::from_le_bytes(data[offset + 4..offset + 8].try_into().unwrap()) as usize;
        if &data[offset..offset + 4] == b"data" {
            let end = (offset + 8 + n).min(data.len());
            for sample in data[offset + 8..end].chunks_exact_mut(2) {
                let v = (i16::from_le_bytes([sample[0], sample[1]]) as f64 * 0.18) as i16;
                sample.copy_from_slice(&v.to_le_bytes());
            }
            break;
        }
        offset = offset.saturating_add(8 + n + (n % 2));
    }
    data
}
impl Audio {
    pub fn start(_data: PathBuf) -> Self {
        let (tx, rx) = mpsc::channel();
        let join = thread::spawn(move || {
            let on = quiet_wav(include_bytes!("../../assets/toggle_on.wav"));
            let off = quiet_wav(include_bytes!("../../assets/toggle_off.wav"));
            let mut stream: Option<OutputStream> = None;
            let mut sink: Option<Sink> = None;
            let mut error = String::new();
            while let Ok(command) = rx.recv() {
                match command {
                    Command::Stop => break,
                    Command::Cue(armed, reply) => unsafe {
                        // PCM buffers live until this thread stops. Stop PlaySound
                        // before dropping them; SND_ASYNC borrows the input memory.
                        let bytes = if armed { &on } else { &off };
                        let ok = PlaySoundW(
                            bytes.as_ptr().cast(),
                            std::ptr::null_mut(),
                            SND_MEMORY | SND_ASYNC | SND_NODEFAULT,
                        ) != 0;
                        if let Some(tx) = reply {
                            let _ = tx.send(ok);
                        }
                    },
                    Command::Music(enabled, volume) => {
                        if !enabled {
                            if let Some(s) = sink.take() {
                                s.stop();
                            }
                            stream.take();
                            continue;
                        }
                        if stream.is_none() {
                            match OutputStreamBuilder::open_default_stream() {
                                Ok(mut s) => {
                                    s.log_on_drop(false);
                                    stream = Some(s);
                                }
                                Err(e) => {
                                    error = e.to_string();
                                    continue;
                                }
                            }
                        }
                        if sink.is_none() {
                            match Decoder::new_looped(Cursor::new(
                                include_bytes!("../../assets/luolei.mp3").as_slice(),
                            )) {
                                Ok(decoder) => {
                                    let s = Sink::connect_new(stream.as_ref().unwrap().mixer());
                                    s.set_volume(volume.clamp(0., 1.) as f32);
                                    // Seek/redecode the embedded MP3 on repeat;
                                    // do not cache the whole song as decoded PCM.
                                    s.append(decoder);
                                    sink = Some(s);
                                    error.clear();
                                }
                                Err(e) => {
                                    error = e.to_string();
                                    stream.take();
                                    continue;
                                }
                            }
                        }
                        if let Some(s) = &sink {
                            s.set_volume(volume.clamp(0., 1.) as f32);
                            s.play();
                        }
                    }
                    Command::Probe(reply) => {
                        let result = if sink.as_ref().is_some_and(|s| !s.empty() && !s.is_paused())
                        {
                            Ok("playing".into())
                        } else if error.is_empty() {
                            Ok("stopped".into())
                        } else {
                            Err(error.clone())
                        };
                        let _ = reply.send(result);
                    }
                    Command::Position(reply) => {
                        let _ = reply.send(
                            sink.as_ref()
                                .map(|s| s.get_pos().as_millis() as u64)
                                .unwrap_or(0),
                        );
                    }
                }
            }
            if let Some(s) = sink {
                s.stop();
            }
            drop(stream);
            unsafe {
                PlaySoundW(std::ptr::null(), std::ptr::null_mut(), 0);
            }
        });
        Self {
            tx,
            join: Some(join),
        }
    }
    pub fn music(&self, enabled: bool, volume: f64) {
        let _ = self.tx.send(Command::Music(enabled, volume));
    }
    pub fn cue(&self, armed: bool) {
        let _ = self.tx.send(Command::Cue(armed, None));
    }
    pub fn cue_checked(&self, armed: bool) -> bool {
        let (tx, rx) = mpsc::channel();
        let _ = self.tx.send(Command::Cue(armed, Some(tx)));
        rx.recv_timeout(std::time::Duration::from_secs(3))
            .unwrap_or(false)
    }
    pub fn position_ms(&self) -> u64 {
        let (tx, rx) = mpsc::channel();
        let _ = self.tx.send(Command::Position(tx));
        rx.recv_timeout(std::time::Duration::from_secs(3))
            .unwrap_or(0)
    }
    pub fn status(&self) -> Result<String, String> {
        let (tx, rx) = mpsc::channel();
        self.tx
            .send(Command::Probe(tx))
            .map_err(|e| e.to_string())?;
        rx.recv_timeout(std::time::Duration::from_secs(3))
            .map_err(|e| e.to_string())?
    }
}
impl Drop for Audio {
    fn drop(&mut self) {
        let _ = self.tx.send(Command::Stop);
        if let Some(j) = self.join.take() {
            let _ = j.join();
        }
    }
}
