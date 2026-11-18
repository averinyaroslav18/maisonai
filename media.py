"""Работа с видео и аудио через ffmpeg (бесплатно, локально): анализ, нарезка, монтаж, субтитры, экспорт."""
import json, math, os, re, shutil, subprocess, sys, textwrap
from pathlib import Path
from core import ASSETS, UserError, tmp_path

FORMATS = {"9:16": (720, 1280), "1:1": (1080, 1080), "16:9": (1280, 720), "4:5": (1080, 1350)}
HD = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}
FPS = 30
NOWIN = 0x08000000 if sys.platform == "win32" else 0   # без чёрных окон консоли в Windows

def ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg; return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        p = shutil.which("ffmpeg")
        if p: return p
    raise UserError("Не найден ffmpeg. Запустите INSTALL.bat ещё раз — он установит его автоматически.")

LOWMEM = os.environ.get("MAISONAI_LOWMEM") == "1"

def run(args, job=None, total=None, p0=0.0, p1=1.0, msg=None):
    """Запуск ffmpeg с прогрессом (по времени out_time) и понятной ошибкой."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-y", "-nostdin"] + [str(a) for a in args]
    if LOWMEM:   # слабый бесплатный сервер (512 МБ): один поток, короткий буфер кодировщика
        cmd = cmd[:4] + ["-filter_threads", "1", "-filter_complex_threads", "1"] + cmd[4:]
        if "libx264" in cmd: cmd = cmd[:-1] + ["-threads", "1", "-x264-params", "rc-lookahead=5:sync-lookahead=0"] + cmd[-1:]
    if job and total:
        cmd = cmd[:4] + ["-progress", "pipe:1", "-nostats"] + cmd[4:]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
        import threading
        err = []; t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True); t.start()
        for line in p.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    sec = int(line.split("=")[1]) / 1e6
                    job.progress(p0 + (p1 - p0) * min(1.0, sec / max(total, 0.1)), msg)
                except ValueError: pass
        p.wait(); t.join(5)
        if p.returncode != 0: raise UserError("Ошибка обработки видео: " + _tail("".join(err)))
        return ""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    if r.returncode != 0: raise UserError("Ошибка обработки видео: " + _tail(r.stderr))
    return r.stderr

def _tail(err: str) -> str:
    lines = [l for l in (err or "").strip().splitlines() if l.strip()]
    return (lines[-1] if lines else "неизвестная ошибка")[:300]

def probe(path) -> dict:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    s = r.stderr
    out = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "has_audio": False, "has_video": False}
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", s)
    if m: out["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    vm = re.search(r"Stream #.*?Video:.*?(\d{2,5})x(\d{2,5})", s)
    if vm: out["width"], out["height"], out["has_video"] = int(vm.group(1)), int(vm.group(2)), True
    rot = re.search(r"rotate\s*:\s*(-?\d+)|displaymatrix: rotation of (-?\d+(?:\.\d+)?)", s)
    if rot and out["has_video"]:
        deg = abs(float(rot.group(1) or rot.group(2))) % 180
        if 45 < deg < 135: out["width"], out["height"] = out["height"], out["width"]
    fm = re.search(r"(\d+(?:\.\d+)?) fps", s)
    if fm: out["fps"] = float(fm.group(1))
    out["has_audio"] = bool(re.search(r"Stream #.*?Audio:", s))
    if not out["has_video"] and not out["has_audio"]: raise UserError("Не удалось прочитать файл: это не видео/аудио или файл повреждён.")
    return out

def compress_for_ai(video, max_sec=90) -> Path:
    """Сжимаем ролик для отправки ИИ на анализ (до ~19 МБ)."""
    out = tmp_path(".mp4")
    run(["-i", video, "-t", max_sec, "-vf", "scale='min(540,iw)':-2", "-r", 15, "-c:v", "libx264", "-preset", "veryfast", "-crf", 30,
         "-c:a", "aac", "-b:a", "64k", "-ac", 1, "-movflags", "+faststart", out])
    if out.stat().st_size > 19 * 1024 * 1024:
        out2 = tmp_path(".mp4")
        run(["-i", out, "-vf", "scale=360:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", 34, "-c:a", "aac", "-b:a", "48k", out2]); out = out2
    return out

def extract_audio(video) -> Path:
    out = tmp_path(".mp3")
    run(["-i", video, "-vn", "-ac", 1, "-ar", 16000, "-b:a", "64k", out]); return out

def frames(video, n=8, width=640) -> list:
    """Равномерные кадры из ролика (для анализа картинок ИИ)."""
    info = probe(video); d = max(info["duration"], 0.5); outs = []
    for i in range(n):
        t = d * (i + 0.5) / n; o = tmp_path(".jpg")
        run(["-ss", f"{t:.2f}", "-i", video, "-frames:v", 1, "-vf", f"scale={width}:-2", "-q:v", 4, o])
        if o.exists(): outs.append((round(t, 2), o))
    return outs

def frame_at(video, t, width=1080) -> Path:
    o = tmp_path(".jpg"); run(["-ss", f"{max(0, t):.2f}", "-i", video, "-frames:v", 1, "-vf", f"scale='min({width},iw)':-2", "-q:v", 2, o]); return o

def scene_cuts(video, threshold=0.3) -> list:
    """Реальное измерение смены кадров (а не выдуманная статистика)."""
    err = run(["-i", video, "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"])
    return [round(float(x), 2) for x in re.findall(r"pts_time:(\d+(?:\.\d+)?)", err)]

def loudness_profile(video, points=40) -> list:
    """Громкость по отрезкам (реальные данные для оценки темпа и пауз)."""
    info = probe(video)
    if not info["has_audio"] or info["duration"] <= 0: return []
    err = run(["-i", video, "-vn", "-af", "astats=metadata=1:reset=1:length=0.5,ametadata=print:key=lavfi.astats.Overall.RMS_level", "-f", "null", "-"])
    vals = [float(v) if v not in ("-inf", "inf", "nan") else -90.0 for v in re.findall(r"RMS_level=(-?inf|-?\d+(?:\.\d+)?|nan)", err)]
    if not vals: return []
    step = max(1, math.ceil(len(vals) / points))
    return [round(sum(vals[i:i + step]) / len(vals[i:i + step]), 1) for i in range(0, len(vals), step)]

def thumbnail(video) -> Path:
    info = probe(video); return frame_at(video, min(1.0, info["duration"] / 3), width=480)

# ---------------- монтаж ----------------
def _cover(W, H): return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"

def image_clip(img, dur, W, H, motion="zoom_in", job=None) -> Path:
    """Анимация картинки: плавный наезд/отъезд/панорама камеры (честный монтаж, не нейросеть)."""
    out = tmp_path(".mp4"); n = max(1, int(round(dur * FPS)))
    W2, H2 = W * 2, H * 2
    k = max(1, int(FPS * 0.45))   # «удар»: быстрый наезд в начале, затем медленный
    z = {"zoom_in": f"1+0.18*on/{n}", "zoom_out": f"1.18-0.18*on/{n}", "pan_left": "1.15", "pan_right": "1.15", "none": "1",
         "punch": f"if(lt(on,{k}),1.25-0.12*on/{k},1.13+0.08*(on-{k})/{n})", "tilt_up": "1.18", "tilt_down": "1.18",
         "drift": f"1.08+0.1*on/{n}"}.get(motion, f"1+0.18*on/{n}")
    x = {"pan_left": f"(iw-iw/zoom)*(1-on/{n})", "pan_right": f"(iw-iw/zoom)*on/{n}", "drift": f"(iw-iw/zoom)*(0.3+0.4*on/{n})"}.get(motion, "iw/2-(iw/zoom/2)")
    y = {"tilt_up": f"(ih-ih/zoom)*(1-on/{n})", "tilt_down": f"(ih-ih/zoom)*on/{n}", "drift": f"(ih-ih/zoom)*(0.6-0.3*on/{n})"}.get(motion, "ih/2-(ih/zoom/2)")
    vf = f"{_cover(W2, H2)},zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},format=yuv420p"
    run(["-loop", 1, "-i", img, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
         "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-c:a", "aac", "-b:a", "128k", "-ar", 44100, out])
    return out

def video_clip(src, start, end, W, H, volume=1.0, speed=1.0) -> Path:
    info = probe(src); start = max(0.0, float(start or 0)); end = float(end) if end else info["duration"]
    end = min(end, info["duration"]) if info["duration"] else end
    if end - start < 0.1: raise UserError("Слишком короткий фрагмент клипа (меньше 0.1 сек). Проверьте начало и конец.")
    out = tmp_path(".mp4")
    vf = f"{_cover(W, H)},fps={FPS},format=yuv420p" + (f",setpts=PTS/{speed}" if speed != 1 else "")
    args = ["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src]
    if info["has_audio"]:
        af = f"volume={volume:.2f},aresample=44100" + (f",atempo={speed}" if speed != 1 else "")
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex", f"[0:v]{vf}[v];[0:a]{af},aformat=channel_layouts=stereo[a]", "-map", "[v]", "-map", "[a]"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a", "-shortest"]
    run(args + ["-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-c:a", "aac", "-b:a", "128k", "-ar", 44100, out])
    return out

def concat(parts, fade=True) -> Path:
    out = tmp_path(".mp4")
    if len(parts) == 1: shutil.copy(parts[0], out); return out
    lst = tmp_path(".txt"); lst.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", "-movflags", "+faststart", out]); return out

FONTS = {"Montserrat": "Montserrat-ExtraBold.ttf", "Inter": "Inter-Bold.ttf", "Plex Mono": "IBMPlexMono-SemiBold.ttf"}

def text_png(text, W, H, size="m", position="bottom", style="caption", font="Montserrat") -> Path:
    """Рисуем подпись картинкой (белый жирный текст с обводкой, как в TikTok) — работает без особых сборок ffmpeg."""
    from PIL import Image, ImageDraw, ImageFont
    px = {"s": 0.040, "m": 0.055, "l": 0.075, "xl": 0.095}.get(size, 0.055) * min(W, H) * (1.25 if H > W else 1.0)
    f = ImageFont.truetype(str(ASSETS / "fonts" / FONTS.get(font, FONTS["Montserrat"])), int(px))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    maxw = W * 0.86; words = str(text).split(); lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    lh = int(px * 1.22); total = lh * len(lines)
    y0 = {"top": int(H * 0.12), "center": (H - total) // 2, "bottom": int(H * 0.74) - total // 2}.get(position, int(H * 0.74) - total // 2)
    stroke = max(2, int(px * 0.09))
    for i, line in enumerate(lines):
        tw = d.textlength(line, font=f); x = (W - tw) / 2; y = y0 + i * lh
        if style == "box":
            pad = int(px * 0.25); d.rounded_rectangle([x - pad, y - pad * 0.4, x + tw + pad, y + lh - pad * 0.2], radius=int(px * 0.2), fill=(0, 0, 0, 170))
            d.text((x, y), line, font=f, fill=(255, 255, 255, 255))
        else:
            d.text((x, y), line, font=f, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    o = tmp_path(".png"); img.save(o); return o

def render(spec: dict, resolve, job=None, hd=False) -> tuple:
    """Главный экспорт: клипы → нормализация → склейка → подписи и субтитры → микс звука → MP4.
    resolve(asset_id) -> (Path, kind)."""
    fmt = spec.get("format", "9:16")
    W, H = (HD if hd else FORMATS).get(fmt, FORMATS["9:16"])
    clips = spec.get("clips") or []
    if not clips: raise UserError("Добавьте хотя бы один клип или картинку на таймлайн.")
    parts, n = [], len(clips)
    for i, c in enumerate(clips):
        if job: job.progress(0.05 + 0.55 * i / n, f"Готовлю клип {i + 1} из {n}…")
        path, kind = resolve(c["asset"])
        if kind == "image":
            parts.append(image_clip(path, float(c.get("duration") or 3), W, H, c.get("motion") or "zoom_in"))
        elif kind == "video":
            parts.append(video_clip(path, c.get("start"), c.get("end"), W, H, float(c.get("volume", 1.0)), float(c.get("speed", 1.0))))
        else: raise UserError("На видеодорожку можно класть только видео и картинки.")
    if job: job.progress(0.62, "Склеиваю клипы…")
    base = concat(parts); total = probe(base)["duration"]
    overlays = []
    for s in spec.get("subtitles") or []:
        if str(s.get("text", "")).strip(): overlays.append((float(s["start"]), float(s["end"]), text_png(s["text"], W, H, spec.get("sub_size", "m"), spec.get("sub_position", "bottom"), spec.get("sub_style", "caption"), spec.get("sub_font", "Montserrat"))))
    for t in spec.get("texts") or []:
        if str(t.get("text", "")).strip(): overlays.append((float(t["start"]), float(t["end"]), text_png(t["text"], W, H, t.get("size", "l"), t.get("position", "top"), t.get("style", "box"), t.get("font", "Montserrat"))))
    audios = []
    for a in spec.get("audio") or []:
        p, kind = resolve(a["asset"])
        if kind not in ("audio", "video"): continue
        audios.append((p, float(a.get("at", 0)), float(a.get("start", 0) or 0), a.get("end"), float(a.get("volume", 1.0))))
    out = tmp_path(".mp4")
    args = ["-i", base]
    for _, _, png in overlays: args += ["-i", png]
    for p, *_ in audios: args += ["-i", p]
    fc, last = [], "[0:v]"
    for k, (s0, s1, _) in enumerate(overlays):
        lab = f"[v{k}]"; fc.append(f"{last}[{k + 1}:v]overlay=0:0:enable='between(t,{s0:.3f},{s1:.3f})'{lab}"); last = lab
    vlabel = last
    amix = [f"[0:a]volume={float(spec.get('clip_volume', 1.0)):.2f}[a0]"]; alabs = ["[a0]"]
    for j, (p, at, st, en, vol) in enumerate(audios):
        idx = 1 + len(overlays) + j; trim = f"atrim=start={st:.3f}" + (f":end={float(en):.3f}" if en else "")
        amix.append(f"[{idx}:a]{trim},asetpts=PTS-STARTPTS,volume={vol:.2f},adelay={int(at * 1000)}|{int(at * 1000)},aresample=44100,aformat=channel_layouts=stereo[a{j + 1}]")
        alabs.append(f"[a{j + 1}]")
    fc += amix + [f"{''.join(alabs)}amix=inputs={len(alabs)}:duration=first:normalize=0[aout]"]
    if spec.get("fade", True) and total > 1.2:
        fc.append(f"{vlabel}fade=t=in:st=0:d=0.25,fade=t=out:st={max(0, total - 0.35):.3f}:d=0.35[vf]"); vlabel = "[vf]"
    elif vlabel == "[0:v]":
        fc.append("[0:v]null[vf]"); vlabel = "[vf]"
    args += ["-filter_complex", ";".join(fc), "-map", vlabel, "-map", "[aout]", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-preset", "medium" if hd else "veryfast", "-crf", 19 if hd else 21, "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out]
    run(args, job=job, total=total, p0=0.65, p1=0.98, msg="Экспорт видео…")
    return out, {"duration": round(total, 2), "width": W, "height": H, "format": fmt}

def upscale(video, ratio="9:16") -> Path:
    W, H = HD.get(ratio, HD["9:16"]); out = tmp_path(".mp4")
    run(["-i", video, "-vf", f"scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1", "-c:v", "libx264", "-preset", "medium", "-crf", 18, "-c:a", "copy", "-movflags", "+faststart", out])
    return out

def mux_voice(video, audio, voice_volume=1.0, orig_volume=0.25) -> Path:
    """Наложить озвучку на видео (оригинальный звук приглушается)."""
    info = probe(video); out = tmp_path(".mp4")
    if info["has_audio"]:
        fc = f"[0:a]volume={orig_volume}[o];[1:a]volume={voice_volume}[v];[o][v]amix=inputs=2:duration=first:normalize=0[a]"
        run(["-i", video, "-i", audio, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out])
    else:
        run(["-i", video, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out])
    return out

def to_mp3(src) -> Path:
    out = tmp_path(".mp3"); run(["-i", src, "-vn", "-c:a", "libmp3lame", "-b:a", "192k", out]); return out

def srt(segments) -> str:
    def ts(t): h, r = divmod(max(0.0, t), 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"
    return "".join(f"{i + 1}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}\n\n" for i, s in enumerate(segments))

def split_caption_segments(text: str, duration: float, words_per=4) -> list:
    """Субтитры по тексту без распознавания: равномерно по длительности (помечаются как приблизительные)."""
    words = str(text).split()
    if not words or duration <= 0: return []
    chunks = [" ".join(words[i:i + words_per]) for i in range(0, len(words), words_per)]
    total_chars = sum(len(c) for c in chunks) or 1; t = 0.0; out = []
    for c in chunks:
        d = duration * len(c) / total_chars; out.append({"start": round(t, 2), "end": round(t + d, 2), "text": c}); t += d
    return out

# ---------------- компьютерное зрение (реальные измерения кадров) ----------------
def shot_keyframes(video, cuts, duration, max_n=12, width=540) -> list:
    """Ключевые кадры: середина каждого плана между склейками (до max_n), а не случайные моменты."""
    bounds = [0.0] + list(cuts) + [duration]
    mids = [(a + b) / 2 for a, b in zip(bounds, bounds[1:]) if b - a > 0.15]
    if len(mids) > max_n:
        step = len(mids) / max_n; mids = [mids[int(i * step)] for i in range(max_n)]
    if not mids: mids = [duration / 2]
    out = []
    for t in mids:
        try: out.append((round(t, 2), frame_at(video, t, width)))
        except UserError: continue
    return out

def palette(images, k=6) -> list:
    """Доминирующие цвета по кадрам (k-средних через квантизацию Pillow): hex и доля в процентах."""
    from PIL import Image
    tiles = []
    for p in images:
        with Image.open(p) as im: tiles.append(im.convert("RGB").resize((96, 170)))
    if not tiles: return []
    W = sum(t.width for t in tiles); canvas = Image.new("RGB", (W, 170)); x = 0
    for t in tiles: canvas.paste(t, (x, 0)); x += t.width
    q = canvas.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:k * 3]; counts = sorted(q.getcolors(), reverse=True); total = sum(c for c, _ in counts) or 1
    return [{"hex": "#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]), "share": round(c / total * 100, 1)} for c, i in counts if i < k]

def light_stats(images) -> dict:
    """Яркость, контраст, насыщенность и «теплота» кадров — реальные числа."""
    from PIL import Image, ImageStat
    L, C, S, T = [], [], [], []
    for p in images:
        with Image.open(p) as im:
            im = im.convert("RGB").resize((160, 284))
            g = ImageStat.Stat(im.convert("L")); L.append(g.mean[0]); C.append(g.stddev[0])
            S.append(ImageStat.Stat(im.convert("HSV")).mean[1])
            r, _, b = ImageStat.Stat(im).mean; T.append(r - b)
    if not L: return {}
    avg = lambda v: round(sum(v) / len(v), 1)
    lum, con, sat, warm = avg(L), avg(C), avg(S), avg(T)
    return {"brightness": lum, "contrast": con, "saturation": sat, "warmth": warm,
            "brightness_word": "тёмная" if lum < 85 else "светлая" if lum > 165 else "средняя",
            "contrast_word": "низкий" if con < 40 else "высокий" if con > 70 else "средний",
            "saturation_word": "приглушённые цвета" if sat < 70 else "насыщенные цвета" if sat > 130 else "умеренные цвета",
            "warmth_word": "тёплая" if warm > 12 else "холодная" if warm < -12 else "нейтральная"}

def motion_activity(video, fps=2, max_sec=90) -> dict:
    """Интенсивность движения: средняя разница соседних кадров (камера и действие в кадре)."""
    from PIL import Image, ImageChops, ImageStat
    d = tmp_path(""); d.mkdir()
    run(["-t", max_sec, "-i", video, "-vf", f"fps={fps},scale=64:-2,format=gray", str(d / "f%04d.png")])
    fs = sorted(d.glob("f*.png")); diffs = []
    prev = None
    for f in fs:
        with Image.open(f) as im:
            cur = im.convert("L").copy()
        if prev is not None and prev.size == cur.size: diffs.append(ImageStat.Stat(ImageChops.difference(prev, cur)).mean[0])
        prev = cur
    shutil.rmtree(d, ignore_errors=True)
    if not diffs: return {}
    m = sum(diffs) / len(diffs)
    return {"motion": round(m, 2), "motion_word": "статичная съёмка" if m < 4 else "умеренное движение" if m < 12 else "очень динамично",
            "timeline": [round(x, 1) for x in diffs[:180]]}


MOTIONS = ["punch", "pan_right", "zoom_out", "tilt_up", "drift", "pan_left", "zoom_in", "tilt_down"]
TRANSITIONS = ["slideleft", "fadeblack", "zoomin", "smoothup", "circleopen", "dissolve", "slideup", "radial", "wipeleft", "hblur"]

def concat_xfade(parts, durs, transitions=None, t=0.45) -> Path:
    """Склейка с красивыми переходами (xfade) и плавным переходом звука. Все клипы — одного размера и FPS."""
    if len(parts) == 1: return Path(parts[0])
    t = max(0.2, min(t, min(durs) / 3))
    trans = transitions or TRANSITIONS
    if LOWMEM and len(parts) > 3:   # мало памяти: склеиваем по 3 клипа за раз, потом группы между собой
        parts, durs, k = list(parts), list(durs), 0
        while len(parts) > 1:
            np_, nd = [], []
            for i in range(0, len(parts), 3):
                grp, gd = parts[i:i + 3], durs[i:i + 3]
                if len(grp) == 1: np_.append(grp[0]); nd.append(gd[0]); continue
                tr = [trans[(k + j) % len(trans)] for j in range(len(grp) - 1)]; k += len(grp) - 1
                np_.append(_xfade(grp, gd, tr, t)); nd.append(sum(gd) - t * (len(grp) - 1))
            parts, durs = np_, nd
        return Path(parts[0])
    return _xfade(parts, durs, trans, t)

def _xfade(parts, durs, trans, t) -> Path:
    args = []
    for p in parts: args += ["-i", p]
    fc, lv, la, off = [], "[0:v]", "[0:a]", 0.0
    for i in range(1, len(parts)):
        off += durs[i - 1] - t
        tv, ta = f"[v{i}]", f"[a{i}]"
        fc.append(f"{lv}[{i}:v]xfade=transition={trans[(i - 1) % len(trans)]}:duration={t:.3f}:offset={off:.3f}{tv}")
        fc.append(f"{la}[{i}:a]acrossfade=d={t:.3f}{ta}")
        lv, la = tv, ta
    out = tmp_path(".mp4")
    run(args + ["-filter_complex", ";".join(fc), "-map", lv, "-map", la, "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out])
    return out
