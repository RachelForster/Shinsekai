"""One model per cutout job; stdout is a JSON-lines protocol, stderr is a log."""

import base64
from contextlib import redirect_stdout
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _release_idle_cache(directory):
    """Only an explicitly configured local ComfyUI may release its idle cache."""
    import ipaddress
    from urllib.parse import urlsplit

    import requests

    runtime = directory / "runtime.json"
    url = (
        json.loads(runtime.read_text(encoding="utf-8")).get("comfyui_url", "")
        if runtime.exists()
        else ""
    )
    if not url:
        return
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    try:
        local = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if not local or parsed.scheme not in ("http", "https"):
        return
    try:
        queue = requests.get(url.rstrip("/") + "/queue", timeout=3).json()
        if queue.get("queue_running") == [] and queue.get("queue_pending") == []:
            requests.post(
                url.rstrip("/") + "/free",
                json={"unload_models": True, "free_memory": True},
                timeout=3,
            ).raise_for_status()
    except (requests.RequestException, ValueError):
        # An unavailable ComfyUI must not prevent local matting.
        pass


def _load_model(directory):
    sys.path.insert(0, str(directory / "deps"))
    import torch
    from core.media.toonout_assets import verify_assets

    verify_assets(directory)
    _release_idle_cache(directory)
    torch.set_num_threads(4)
    package = types.ModuleType("_shinsekai_toonout")
    package.__path__ = [str(directory)]
    sys.modules[package.__name__] = package
    for name in ("BiRefNet_config", "birefnet"):
        spec = importlib.util.spec_from_file_location(
            f"{package.__name__}.{name}", directory / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        setattr(package, name, module)
    model = package.birefnet.BiRefNet(
        config=package.BiRefNet_config.BiRefNetConfig(bb_pretrained=False)
    )
    state = torch.load(
        directory / "birefnet_finetuned_toonout.pth",
        map_location="cpu",
        weights_only=True,
        mmap=True,
    )
    cleaned = {}
    for key, value in state.items():
        for prefix in ("module._orig_mod.", "module."):
            if key.startswith(prefix):
                key = key[len(prefix) :]
                break
        cleaned[key] = value
    model.load_state_dict(cleaned, strict=True)
    # Keep CPU execution possible when another app holds the GPU; never interrupt it.
    use_cuda = torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 3 * 1024**3
    device = "cuda" if use_cuda else "cpu"
    dtype = torch.float16 if use_cuda else torch.float32
    return model.eval().to(device=device, dtype=dtype), device, dtype


def send(message):
    print(json.dumps(message), flush=True)


def main(directory):
    from PIL import Image

    with redirect_stdout(sys.stderr):
        model, device, dtype = _load_model(directory)
        import torch
        from torchvision import transforms

        transform = transforms.Compose(
            [
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
    send({"ready": True, "device": device})
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("close"):
            return
        with Image.open(BytesIO(base64.b64decode(request["image"]))) as opened:
            image = opened.convert("RGB")
        with redirect_stdout(sys.stderr), torch.inference_mode():
            value = transform(image).unsqueeze(0).to(device=device, dtype=dtype)
            logits = model(value)[-1]
            if not torch.isfinite(logits).all():
                raise RuntimeError("ToonOut produced non-finite alpha")
            alpha = logits.sigmoid().float().cpu()[0].squeeze()
            mask = transforms.ToPILImage()(alpha).resize(image.size)
        image.putalpha(mask)
        data = BytesIO()
        image.save(data, "PNG", compress_level=1)
        send({"image": base64.b64encode(data.getvalue()).decode("ascii")})


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]).resolve())
    except Exception as exc:
        send({"error": f"{type(exc).__name__}: {exc}"})
        raise
