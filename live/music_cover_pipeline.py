"""
音乐翻唱流水线：搜索/下载（YouTube、B站或直链）→ 歌词与时间轴 → UVR 分离 → RVC 干声转换 → pydub 合成。
RVC 默认用 rvc-python（RVCInference）；若填写 music_cover_rvc_cmd_template 则走外部 CLI。
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import requests

from config.schema import SystemConfig

LogFn = Callable[[str], None]


def _slug(s: str, max_len: int = 80) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^\w\s\-_.]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return (s or "track")[:max_len]


def _which_yt_dlp(system_config: SystemConfig) -> str:
    exe = (system_config.music_cover_yt_dlp_exe or "").strip()
    if exe:
        return exe
    return "yt-dlp"


def _apply_ffmpeg_path(system_config: SystemConfig) -> None:
    ff = (system_config.music_cover_ffmpeg_exe or "").strip()
    if not ff:
        return
    try:
        from pydub import AudioSegment

        AudioSegment.converter = ff
    except ImportError:
        pass


def bilibili_search_videos(query: str, limit: int = 8) -> List[dict]:
    url = "https://api.bilibili.com/x/web-interface/search/type"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }
    r = requests.get(
        url,
        params={"search_type": "video", "keyword": query, "page": 1},
        headers=headers,
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(j.get("message") or "B站搜索失败")
    rows = j.get("data", {}).get("result") or []
    out: List[dict] = []
    for item in rows[:limit]:
        title = item.get("title") or ""
        title = re.sub(r"<[^>]+>", "", title)
        bvid = item.get("bvid")
        if not bvid:
            continue
        out.append(
            {
                "title": title,
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}",
            }
        )
    return out


def youtube_search_videos(query: str, limit: int = 8, yt_dlp: str = "yt-dlp") -> List[dict]:
    cmd = [
        yt_dlp,
        f"ytsearch{limit}:{query}",
        "-j",
        "--flat-playlist",
        "--skip-download",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "yt-dlp 搜索失败")
    out: List[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = o.get("id")
        title = o.get("title") or vid
        url = o.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
        if url:
            out.append({"title": title, "id": vid, "url": url})
    return out


def _run_yt_dlp_download(
    media_url: str,
    out_dir: Path,
    yt_dlp: str,
    log: LogFn,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(out_dir / "%(title)s.%(ext)s")
    cmd = [
        yt_dlp,
        media_url,
        "-f",
        "bestaudio/best",
        "-x",
        "--audio-format",
        "wav",
        "--write-subs",
        "--write-auto-subs",
        "--sub-format",
        "vtt/srt/best",
        "--sub-langs",
        "all",
        "-o",
        outtmpl,
        "--no-playlist",
    ]
    log("执行下载: " + " ".join(cmd[:5]) + " ...")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "yt-dlp 下载失败")
    wavs = sorted(out_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wavs:
        raise FileNotFoundError("下载完成但未找到 wav，请检查 yt-dlp 与网络")
    return wavs[0]


def _find_vocals_instrumental(search_dir: Path) -> Tuple[Path, Path]:
    wavs = list(search_dir.rglob("*.wav"))
    if not wavs:
        raise FileNotFoundError(f"在 {search_dir} 未找到分离后的 wav")

    def score_vocals(p: Path) -> bool:
        n = p.name.lower()
        if "vocals" in n or "vocal" in n:
            if "instrumental" in n or "instrum" in n:
                return False
            if "no_vocals" in n or "novocal" in n:
                return False
            return True
        return False

    def score_inst(p: Path) -> bool:
        n = p.name.lower()
        return (
            "instrumental" in n
            or "instrum" in n
            or "no_vocals" in n
            or "novocal" in n
            or "karaoke" in n
            or "backing" in n
        )

    vocals = next((p for p in wavs if score_vocals(p)), None)
    inst = next((p for p in wavs if score_inst(p)), None)
    if vocals and inst:
        return vocals, inst
    # 常见 UVR 命名：*_ (Vocals).wav / *_ (Instrumental).wav
    for p in wavs:
        if vocals is None and "(vocals)" in p.name.lower():
            vocals = p
        if inst is None and "(instrumental)" in p.name.lower():
            inst = p
    if vocals and inst:
        return vocals, inst
    raise FileNotFoundError(
        "无法自动识别分离后人声/伴奏文件，请确认 UVR 输出文件名包含 Vocals / Instrumental 等关键字"
    )


def _run_shell(cmd: str, cwd: Optional[Path], log: LogFn) -> None:
    log(cmd)
    proc = subprocess.run(cmd, shell=True, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise RuntimeError(f"命令退出码 {proc.returncode}")


def _separate_audio_separator(input_wav: Path, out_dir: Path, log: LogFn) -> Tuple[Path, Path]:
    try:
        from audio_separator.separator import Separator
    except ImportError as e:
        raise RuntimeError(
            "未配置 UVR 命令且未安装 audio-separator。请配置 music_cover_uvr_cmd_template 或 pip install audio-separator"
        ) from e
    out_dir.mkdir(parents=True, exist_ok=True)
    log("使用 audio-separator (MDX) 分离人声…")
    sep = Separator(output_dir=str(out_dir))
    sep.separate(str(input_wav))
    return _find_vocals_instrumental(out_dir)


def run_uvr_separation(
    system_config: SystemConfig,
    input_wav: Path,
    sep_out_dir: Path,
    log: LogFn,
) -> Tuple[Path, Path]:
    sep_out_dir.mkdir(parents=True, exist_ok=True)
    tpl = (system_config.music_cover_uvr_cmd_template or "").strip()
    if tpl:
        before = set(sep_out_dir.rglob("*.wav"))
        cmd = tpl.format(input_wav=str(input_wav.resolve()), out_dir=str(sep_out_dir.resolve()))
        _run_shell(cmd, cwd=sep_out_dir.parent, log=log)
        after = set(sep_out_dir.rglob("*.wav"))
        new_wavs = [p for p in after if p not in before]
        if new_wavs:
            try:
                return _find_vocals_instrumental(sep_out_dir)
            except FileNotFoundError:
                pass
        return _find_vocals_instrumental(sep_out_dir)
    return _separate_audio_separator(input_wav, sep_out_dir, log)


def _filter_kwargs_for_callable(
    fn,
    candidates: dict,
) -> dict:
    """只传入目标可接受的参数名；若签名含 **kwargs 则原样传入候选字典。"""
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(candidates)
    out = {}
    for key, value in candidates.items():
        if key in params:
            out[key] = value
    return out


def run_rvc_with_rvc_python(
    system_config: SystemConfig,
    input_vocals_wav: Path,
    output_wav: Path,
    log: LogFn,
) -> None:
    try:
        from rvc_python.infer import RVCInference
    except ImportError as e:
        raise RuntimeError(
            "未安装 rvc-python。请 pip install rvc-python，或在配置中填写 RVC 命令模板以使用外部 CLI。"
        ) from e

    model = (system_config.music_cover_rvc_model_path or "").strip()
    if not model:
        raise RuntimeError("未配置 music_cover_rvc_model_path")
    index = (system_config.music_cover_rvc_index_path or "").strip()
    device = (system_config.music_cover_rvc_device or "cuda:0").strip() or "cuda:0"
    version = (system_config.music_cover_rvc_model_version or "v2").strip().lower()
    if version not in ("v1", "v2"):
        version = "v2"
    f0_method = (system_config.music_cover_rvc_f0_method or "rmvpe").strip().lower() or "rmvpe"
    pitch = float(system_config.music_cover_rvc_pitch)
    index_rate = float(system_config.music_cover_rvc_index_rate)
    filter_radius = int(system_config.music_cover_rvc_filter_radius)
    resample_sr = int(system_config.music_cover_rvc_resample_sr)
    rms_mix_rate = float(system_config.music_cover_rvc_rms_mix_rate)
    protect = float(system_config.music_cover_rvc_protect)

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    in_path = str(input_vocals_wav.resolve())
    out_path = str(output_wav.resolve())

    rvc = RVCInference(device=device)

    load_fn = rvc.load_model
    load_sig = inspect.signature(load_fn)
    name_set = {n for n in load_sig.parameters if n != "self"}
    load_kw: dict = {}
    if "model_path" in name_set:
        load_kw["model_path"] = model
    elif "pth_path" in name_set:
        load_kw["pth_path"] = model
    elif "path" in name_set:
        load_kw["path"] = model
    else:
        non_self = [n for n in load_sig.parameters if n != "self"]
        if len(non_self) == 1:
            load_kw[non_self[0]] = model
        elif any(p.kind == inspect.Parameter.VAR_KEYWORD for p in load_sig.parameters.values()):
            load_kw["model_path"] = model
        else:
            raise RuntimeError("无法匹配 rvc-python load_model 参数，请检查库版本或使用 RVC 命令模板")

    for alias in ("index_path", "index", "index_file", "feature_index_path"):
        if alias in name_set and index:
            load_kw[alias] = index
    for alias in ("version", "model_version", "rvc_version"):
        if alias in name_set:
            load_kw[alias] = version

    log(
        f"rvc-python: load_model device={device} version={version} model={model}"
        + (f" index={index}" if index else "")
    )
    load_fn(**load_kw)

    infer_candidates = {
        "pitch": pitch,
        "f0_method": f0_method,
        "method": f0_method,
        "index_rate": index_rate,
        "filter_radius": filter_radius,
        "resample_sr": resample_sr if resample_sr > 0 else None,
        "rms_mix_rate": rms_mix_rate,
        "protect": protect,
        "version": version,
    }
    infer_candidates = {k: v for k, v in infer_candidates.items() if v is not None}
    infer_kw = _filter_kwargs_for_callable(rvc.infer_file, infer_candidates)
    log(f"rvc-python: infer_file → {out_path} kwargs={infer_kw!r}")
    rvc.infer_file(in_path, out_path, **infer_kw)


def run_rvc(
    system_config: SystemConfig,
    input_vocals_wav: Path,
    output_wav: Path,
    log: LogFn,
) -> None:
    tpl = (system_config.music_cover_rvc_cmd_template or "").strip()
    model = (system_config.music_cover_rvc_model_path or "").strip()
    index = (system_config.music_cover_rvc_index_path or "").strip()
    if not model:
        raise RuntimeError("未配置 music_cover_rvc_model_path")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    if tpl:
        cmd = tpl.format(
            input_wav=str(input_vocals_wav.resolve()),
            output_wav=str(output_wav.resolve()),
            model_pth=model,
            index_file=index,
        )
        _run_shell(cmd, cwd=None, log=log)
        return
    run_rvc_with_rvc_python(system_config, input_vocals_wav, output_wav, log)


def mix_vocals_and_instrumental(
    vocals_wav: Path,
    instrumental_wav: Path,
    output_wav: Path,
    system_config: SystemConfig,
    log: LogFn,
) -> None:
    _apply_ffmpeg_path(system_config)
    from pydub import AudioSegment

    v = AudioSegment.from_file(str(vocals_wav))
    ins = AudioSegment.from_file(str(instrumental_wav))
    if ins.frame_rate != v.frame_rate:
        ins = ins.set_frame_rate(v.frame_rate)
    if ins.channels != v.channels:
        ins = ins.set_channels(v.channels)
    diff = len(ins) - len(v)
    if diff > 0:
        v = v + AudioSegment.silent(duration=diff)
    elif diff < 0:
        ins = ins + AudioSegment.silent(duration=-diff)
    # 伴奏为底、人声叠在上面（与常见翻唱混音一致）
    mixed = ins.overlay(v)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    mixed.export(str(output_wav), format="wav")
    log(f"已合成: {output_wav}")


@dataclass
class PipelineResult:
    job_dir: Path
    source_audio: Path
    vocals_path: Path
    instrumental_path: Path
    converted_vocals: Optional[Path]
    final_mix: Path
    subtitles: List[Path] = field(default_factory=list)
    manifest: Optional[Path] = None


def resolve_media_url(
    source: str,
    query: str,
    system_config: SystemConfig,
    log: LogFn,
    pick_index: int = 0,
) -> Tuple[str, str]:
    """返回 (media_url, display_title)。"""
    q = query.strip()
    if not q:
        raise ValueError("搜索词或 URL 不能为空")
    yt_dlp = _which_yt_dlp(system_config)

    if source == "url":
        return q, q

    if source == "bilibili":
        if re.match(r"^BV[\w]+$", q, re.I) or "bilibili.com" in q:
            return q if q.startswith("http") else f"https://www.bilibili.com/video/{q}", q
        items = bilibili_search_videos(q)
        if not items:
            raise RuntimeError("B站未找到相关视频")
        pick_index = max(0, min(pick_index, len(items) - 1))
        it = items[pick_index]
        log(f"选用 B站: {it['title']} ({it['url']})")
        return it["url"], it["title"]

    if source == "youtube":
        if "youtube.com" in q or "youtu.be" in q:
            return q, q
        items = youtube_search_videos(q, limit=8, yt_dlp=yt_dlp)
        if not items:
            raise RuntimeError("YouTube 搜索无结果")
        pick_index = max(0, min(pick_index, len(items) - 1))
        it = items[pick_index]
        log(f"选用 YouTube: {it['title']} ({it['url']})")
        return it["url"], it["title"]

    raise ValueError(f"未知来源: {source}")


def run_pipeline(
    system_config: SystemConfig,
    *,
    source: str,
    query: str,
    pick_index: int = 0,
    skip_rvc: bool = False,
    log: Optional[LogFn] = None,
) -> PipelineResult:
    lines: List[str] = []

    def _log(msg: str) -> None:
        lines.append(msg)
        if log:
            log(msg)

    work_root = Path(system_config.music_cover_work_dir or "./data/music_cover").resolve()
    ts = int(time.time())
    media_url, title = resolve_media_url(source, query, system_config, _log, pick_index=pick_index)
    job_dir = work_root / f"{_slug(title)}_{ts}"
    dl_dir = job_dir / "download"
    sep_dir = job_dir / "separated"
    rvc_dir = job_dir / "rvc_out"
    final_path = job_dir / "final_mix.wav"

    yt_dlp = _which_yt_dlp(system_config)
    _log(f"工作目录: {job_dir}")
    audio_path = _run_yt_dlp_download(media_url, dl_dir, yt_dlp, _log)

    subs = list(dl_dir.glob("*.vtt")) + list(dl_dir.glob("*.srt"))
    _log(f"字幕/歌词文件: {len(subs)} 个")

    vocals_path, inst_path = run_uvr_separation(system_config, audio_path, sep_dir, _log)

    if skip_rvc:
        conv_vocals = vocals_path
        _log("已跳过 RVC，使用分离后人声直接合成")
    else:
        conv_vocals_path = rvc_dir / "vocals_converted.wav"
        run_rvc(system_config, vocals_path, conv_vocals_path, _log)
        conv_vocals = conv_vocals_path

    mix_vocals_and_instrumental(conv_vocals, inst_path, final_path, system_config, _log)

    manifest = job_dir / "manifest.json"
    manifest_data = {
        "title": title,
        "media_url": media_url,
        "source_audio": str(audio_path),
        "vocals": str(vocals_path),
        "instrumental": str(inst_path),
        "converted_vocals": str(conv_vocals) if conv_vocals else None,
        "final_mix": str(final_path),
        "subtitles": [str(p) for p in subs],
        "log": lines,
    }
    manifest.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return PipelineResult(
        job_dir=job_dir,
        source_audio=audio_path,
        vocals_path=vocals_path,
        instrumental_path=inst_path,
        converted_vocals=conv_vocals if not skip_rvc else None,
        final_mix=final_path,
        subtitles=subs,
        manifest=manifest,
    )


def search_preview(
    system_config: SystemConfig,
    source: str,
    query: str,
    max_items: int = 8,
) -> str:
    """返回可读的搜索结果列表（用于 UI）。"""
    q = query.strip()
    if not q:
        return "请输入搜索词"
    yt_dlp = _which_yt_dlp(system_config)
    lines: List[str] = []
    try:
        if source == "youtube":
            if "youtube.com" in q or "youtu.be" in q:
                return "当前为完整 URL，无需搜索，可直接执行流水线。"
            for i, it in enumerate(youtube_search_videos(q, limit=max_items, yt_dlp=yt_dlp)):
                lines.append(f"{i}. {it['title']}\n   {it['url']}")
        elif source == "bilibili":
            if re.match(r"^BV[\w]+$", q, re.I) or "bilibili.com" in q:
                return "当前为 BV 号或完整 URL，无需搜索，可直接执行流水线。"
            for i, it in enumerate(bilibili_search_videos(q, limit=max_items)):
                lines.append(f"{i}. {it['title']}\n   {it['url']}")
        else:
            return "「完整 URL」模式请直接粘贴链接并执行流水线。"
    except Exception as e:
        return f"搜索失败: {e}"
    return "\n\n".join(lines) if lines else "无结果"


def format_pipeline_log(result: PipelineResult) -> str:
    parts = [
        f"成品: {result.final_mix}",
        f"清单: {result.manifest}" if result.manifest else "清单: (无)",
        f"原曲 wav: {result.source_audio}",
        f"人声: {result.vocals_path}",
        f"伴奏: {result.instrumental_path}",
    ]
    if result.subtitles:
        parts.append("字幕: " + ", ".join(str(p) for p in result.subtitles[:5]))
        if len(result.subtitles) > 5:
            parts.append(f"... 等共 {len(result.subtitles)} 个")
    return "\n".join(parts)
