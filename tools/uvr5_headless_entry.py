"""Headless CLI entrypoint for GPT-SoVITS bundled UVR5 vocal separation.

Executed inside GPT-SoVITS's embedded Python runtime:
    <gsv_root>/runtime/python.exe -X utf8 -u -s tools/uvr5_headless_entry.py ...
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


AUDIO_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

PREFERRED_VOCAL_STEMS = (
    "HP2_all_vocals",
    "HP2-人声vocals+非人声instrumentals",
    "HP5_only_main_vocal",
    "HP5-主旋律人声vocals+其他instrumentals",
    "HP3_all_vocals",
)

PREFERRED_DEREVERB_STEMS = (
    "VR-DeEchoNormal",
    "VR-DeEchoDeReverb",
    "VR-DeEchoAggressive",
)


def select_vocal_weight(weights_dir: Path, explicit_name: str = "") -> Path:
    """Choose the best available UVR5 vocal separation `.pth` weight."""
    if not weights_dir.is_dir():
        raise FileNotFoundError(f"UVR5 权重目录不存在：{weights_dir}")

    pth_files = sorted(
        (path for path in weights_dir.iterdir() if path.is_file() and path.suffix.lower() == ".pth"),
        key=lambda item: item.name.casefold(),
    )
    if explicit_name:
        cleaned = explicit_name[:-4] if explicit_name.lower().endswith(".pth") else explicit_name
        for path in pth_files:
            if path.stem.casefold() == cleaned.casefold():
                return path
        raise FileNotFoundError(f"未找到指定的 UVR5 权重：{explicit_name}（目录：{weights_dir}）")

    by_stem = {path.stem: path for path in pth_files}
    for stem in PREFERRED_VOCAL_STEMS:
        if stem in by_stem:
            return by_stem[stem]

    for prefix in ("hp2", "hp5", "hp3"):
        for path in pth_files:
            if path.stem.lower().startswith(prefix):
                return path

    for path in pth_files:
        if "deecho" not in path.stem.lower() and "dereverb" not in path.stem.lower():
            return path

    raise FileNotFoundError(f"UVR5 目录中未找到可用的人声分离模型（HP2/HP5）：{weights_dir}")


def select_dereverb_weight(weights_dir: Path) -> tuple[str, Path] | None:
    """Return ('deecho', pth_path) or ('mdx', folder_path) if dereverb weights exist."""
    if not weights_dir.is_dir():
        return None
    pth_files = {
        path.stem: path
        for path in weights_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".pth"
    }
    for stem in PREFERRED_DEREVERB_STEMS:
        if stem in pth_files:
            return ("deecho", pth_files[stem])
    for stem, path in sorted(pth_files.items()):
        if "deecho" in stem.lower():
            return ("deecho", path)
    foxjoy_dir = weights_dir / "onnx_dereverb_By_FoxJoy"
    if foxjoy_dir.is_dir():
        return ("mdx", foxjoy_dir)
    return None


def _find_ffmpeg(gsv_root: Path) -> str:
    candidates = [
        gsv_root / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        gsv_root / "runtime" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    which = shutil.which("ffmpeg")
    if which:
        return which
    raise FileNotFoundError("未找到 ffmpeg，无法预处理 UVR5 输入音频。")


def _normalize_to_stereo_44k_wav(ffmpeg_bin: str, source: Path, target: Path) -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "2",
        "-ar",
        "44100",
        str(target),
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size <= 44:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"ffmpeg 转换音频失败 ({source.name})：{detail or completed.returncode}")


def _call_path_audio(
    processor: Any,
    inp_path: Path,
    ins_dir: Path,
    vocal_dir: Path,
    *,
    is_hp3: bool = False,
) -> None:
    fn = processor._path_audio_
    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    if "is_hp3" in sig.parameters:
        kwargs["is_hp3"] = is_hp3
    params = list(sig.parameters.keys())
    if len(params) >= 4:
        fn(str(inp_path), str(ins_dir), str(vocal_dir), "wav", **kwargs)
    else:
        fn(str(inp_path), str(vocal_dir), "wav", **kwargs)


def _instantiate_vr_processor(cls: Any, *, agg: int, model_path: Path, device: str, is_half: bool) -> Any:
    sig = inspect.signature(cls.__init__)
    kwargs: dict[str, Any] = {
        "agg": int(agg),
        "model_path": str(model_path),
        "device": device,
        "is_half": is_half,
    }
    if "tta" in sig.parameters:
        kwargs["tta"] = False
    return cls(**kwargs)


def _collect_audio_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES and path.stat().st_size > 44
        ),
        key=lambda item: item.name.casefold(),
    )


def run_headless_uvr5(
    *,
    gsv_root: Path,
    input_dir: Path,
    output_dir: Path,
    agg: int = 10,
    dereverb: bool = False,
    model_name: str = "",
) -> dict[str, Any]:
    gsv_root = gsv_root.expanduser().resolve()
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    uvr5_dir = gsv_root / "tools" / "uvr5"
    weights_dir = uvr5_dir / "uvr5_weights"

    if not uvr5_dir.is_dir():
        raise FileNotFoundError(f"GPT-SoVITS 缺少 tools/uvr5 目录：{uvr5_dir}")

    sources = _collect_audio_files(input_dir)
    if not sources:
        raise ValueError(f"UVR5 输入目录中没有有效音频文件：{input_dir}")

    vocal_weight = select_vocal_weight(weights_dir, explicit_name=model_name)
    dereverb_choice = select_dereverb_weight(weights_dir) if dereverb else None

    os.environ["PATH"] = (
        str(gsv_root)
        + os.pathsep
        + str(gsv_root / "runtime")
        + os.pathsep
        + os.environ.get("PATH", "")
    )
    for extra_sys_path in (uvr5_dir, gsv_root / "GPT_SoVITS", gsv_root):
        text_path = str(extra_sys_path)
        if text_path not in sys.path:
            sys.path.insert(0, text_path)

    os.chdir(gsv_root)
    ffmpeg_bin = _find_ffmpeg(gsv_root)

    torch = importlib.import_module("torch")
    vr_module = importlib.import_module("vr")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    is_half = bool(device == "cuda")

    temp_parent = gsv_root / "TEMP"
    temp_parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="shinsekai_uvr5_", dir=str(temp_parent)) as tmp_str:
        tmp_root = Path(tmp_str)
        norm_dir = tmp_root / "normalized"
        s1_vocal = tmp_root / "s1_vocal"
        s1_ins = tmp_root / "s1_ins"
        for folder in (norm_dir, s1_vocal, s1_ins):
            folder.mkdir(parents=True, exist_ok=True)

        normalized_inputs: list[Path] = []
        for idx, src in enumerate(sources, start=1):
            dst = norm_dir / f"src_{idx:04d}.wav"
            print(f"[UVR5] 预处理音频 {idx}/{len(sources)}: {src.name}", flush=True)
            _normalize_to_stereo_44k_wav(ffmpeg_bin, src, dst)
            normalized_inputs.append(dst)

        print(f"[UVR5] 加载人声分离模型 {vocal_weight.stem} (device={device}, half={is_half})", flush=True)
        is_hp3 = "hp3" in vocal_weight.stem.lower()
        vocal_proc = _instantiate_vr_processor(
            vr_module.AudioPre,
            agg=agg,
            model_path=vocal_weight,
            device=device,
            is_half=is_half,
        )
        try:
            for idx, norm_wav in enumerate(normalized_inputs, start=1):
                print(f"[UVR5] 提取人声 {idx}/{len(normalized_inputs)}: {norm_wav.name}", flush=True)
                _call_path_audio(vocal_proc, norm_wav, s1_ins, s1_vocal, is_hp3=is_hp3)
        finally:
            try:
                del vocal_proc.model
            except Exception:
                pass
            del vocal_proc
            if device == "cuda":
                torch.cuda.empty_cache()

        current_vocals = _collect_audio_files(s1_vocal)
        if not current_vocals:
            raise RuntimeError(f"UVR5 模型 {vocal_weight.stem} 未产出任何有效人声音频。")

        dereverb_model_used = ""
        if dereverb and dereverb_choice is not None:
            kind, dereverb_path = dereverb_choice
            s2_vocal = tmp_root / "s2_vocal"
            s2_ins = tmp_root / "s2_ins"
            s2_norm = tmp_root / "s2_norm"
            for folder in (s2_vocal, s2_ins, s2_norm):
                folder.mkdir(parents=True, exist_ok=True)

            print(f"[UVR5] 执行二次去混响：{dereverb_path.name}", flush=True)
            s2_inputs: list[Path] = []
            for idx, wav_path in enumerate(current_vocals, start=1):
                dst = s2_norm / f"v1_{idx:04d}.wav"
                _normalize_to_stereo_44k_wav(ffmpeg_bin, wav_path, dst)
                s2_inputs.append(dst)

            if kind == "deecho":
                deecho_proc = _instantiate_vr_processor(
                    vr_module.AudioPreDeEcho,
                    agg=agg,
                    model_path=dereverb_path,
                    device=device,
                    is_half=is_half,
                )
                try:
                    for wav_path in s2_inputs:
                        _call_path_audio(deecho_proc, wav_path, s2_ins, s2_vocal, is_hp3=False)
                finally:
                    try:
                        del deecho_proc.model
                    except Exception:
                        pass
                    del deecho_proc
                    if device == "cuda":
                        torch.cuda.empty_cache()
            else:
                mdx_module = importlib.import_module("mdxnet")
                mdx_proc = mdx_module.MDXNetDereverb(15)
                try:
                    for wav_path in s2_inputs:
                        _call_path_audio(mdx_proc, wav_path, s2_ins, s2_vocal, is_hp3=False)
                finally:
                    del mdx_proc
                    if device == "cuda":
                        torch.cuda.empty_cache()

            s2_outputs = _collect_audio_files(s2_vocal)
            if s2_outputs:
                current_vocals = s2_outputs
                dereverb_model_used = dereverb_path.stem

        final_outputs: list[str] = []
        for idx, vocal_wav in enumerate(current_vocals, start=1):
            final_path = output_dir / f"vocal_{idx:04d}.wav"
            shutil.copy2(vocal_wav, final_path)
            final_outputs.append(str(final_path))

    return {
        "device": device,
        "vocalModel": vocal_weight.stem,
        "dereverbModel": dereverb_model_used,
        "outputs": final_outputs,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GPT-SoVITS bundled UVR5 headlessly.")
    parser.add_argument("--gsv-root", required=True, help="Path to GPT-SoVITS root directory")
    parser.add_argument("--input-dir", required=True, help="Directory with raw source audio")
    parser.add_argument("--output-dir", required=True, help="Directory to write clean vocal WAVs")
    parser.add_argument("--agg", type=int, default=10, help="UVR5 aggressiveness (0-20)")
    parser.add_argument("--dereverb", action="store_true", help="Run optional second-pass DeEcho/DeReverb")
    parser.add_argument("--model-name", default="", help="Explicit UVR5 vocal model stem")
    parser.add_argument("--report-json", default="", help="Optional path to write JSON execution summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_headless_uvr5(
        gsv_root=Path(args.gsv_root),
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        agg=args.agg,
        dereverb=bool(args.dereverb),
        model_name=str(args.model_name or "").strip(),
    )
    if args.report_json:
        report_path = Path(args.report_json).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[UVR5] 完成：使用模型 {report['vocalModel']}，共输出 {len(report['outputs'])} 个纯人声文件。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
