from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.image_generation.sprites import generate_sprites


@pytest.mark.parametrize("reference_count", [1, 2, 10])
@pytest.mark.parametrize("seed,expected_seed", [(123, 123), (-1, 456)])
def test_configured_t2i_reuses_extra_configuration_and_cleans_up(
    tmp_path, monkeypatch, reference_count, seed, expected_seed
):
    factory = Mock()
    adapter = factory.return_value

    def generate(prompt, file_path, **kwargs):
        Path(file_path).write_bytes(b"image")
        kwargs["on_progress"](0.5, "Denoising")
        return file_path

    adapter.generate_image.side_effect = generate
    monkeypatch.setattr(
        "application.image_generation.sprites.T2IAdapterFactory.create_adapter", factory
    )
    monkeypatch.setattr(
        "application.image_generation.sprites.secrets.randbits", lambda bits: 456
    )
    api = SimpleNamespace(
        t2i_provider="qwen-image-2.1",
        t2i_work_path="",
        t2i_api_url="",
        t2i_default_workflow_path="",
        t2i_prompt_node_id="6",
        t2i_output_node_id="9",
    )
    config = SimpleNamespace(
        config=SimpleNamespace(api_config=api),
        merged_t2i_factory_kwargs=Mock(
            return_value={
                "model_path": "existing",
                "python_executable": "worker-python",
            }
        ),
    )
    progress = Mock()
    references = [tmp_path / f"ref-{index}.png" for index in range(reference_count)]
    files = generate_sprites(
        config,
        reference_images=references,
        prompts=["wave", "smile"],
        output_dir=tmp_path / "output",
        provider="configured",
        seed=seed,
        on_progress=progress,
    )
    factory.assert_called_once_with(
        "qwen-image-2.1", model_path="existing", python_executable="worker-python"
    )
    assert len(files) == 2
    assert adapter.generate_image.call_args.kwargs["reference_images"] == references
    assert adapter.generate_image.call_args.kwargs["transparent"] is True
    assert adapter.generate_image.call_args.kwargs["reference_canvas_index"] == 0
    for call, requested in zip(
        adapter.generate_image.call_args_list, ["wave", "smile"]
    ):
        assert call.args[0].startswith(f"Requested edit: {requested}\n")
        assert "Preserve the character's facial identity" in call.args[0]
        assert "except attributes explicitly requested to change" in call.args[0]
        assert call.kwargs["reference_images"] == references
        assert call.kwargs["seed"] == expected_seed
        if reference_count == 1:
            assert "the reference image" in call.args[0]
            assert "<image1>" not in call.args[0]
        else:
            assert "<image1> is the canvas" in call.args[0]
            assert f"<image{reference_count}> is supplementary material" in call.args[0]
    assert progress.call_args.args[0] == 1
    adapter.shutdown.assert_called_once()


def test_gemini_receives_the_same_identity_constraints_and_original_references(
    tmp_path, monkeypatch
):
    from tools.generate_sprites import ImageGenerator

    batch = Mock(return_value=[tmp_path / "result.png"])
    monkeypatch.setattr(ImageGenerator, "batch_generate_sprites", batch)
    references = [tmp_path / "original.png", tmp_path / "detail.png"]
    requested = "Change outfit: use the clothing in reference image 2"
    generate_sprites(
        SimpleNamespace(),
        reference_images=references,
        prompts=[requested],
        output_dir=tmp_path,
        provider="gemini",
    )
    assert batch.call_args.args[0] == references
    prompt = batch.call_args.args[1][0]
    assert prompt.startswith(f"Requested edit: {requested}\n")
    assert "reference image 1 is the canvas" in prompt
    assert "reference image 2 is supplementary material" in prompt
    assert "Preserve the character's facial identity" in prompt
    assert "except attributes explicitly requested to change" in prompt


def test_generation_failure_releases_adapter(tmp_path, monkeypatch):
    adapter = Mock()
    adapter.generate_image.return_value = None
    monkeypatch.setattr(
        "application.image_generation.sprites.T2IAdapterFactory.create_adapter",
        lambda *args, **kwargs: adapter,
    )
    api = SimpleNamespace(
        t2i_provider="qwen-image-2.1",
        t2i_work_path="",
        t2i_api_url="",
        t2i_default_workflow_path="",
        t2i_prompt_node_id="6",
        t2i_output_node_id="9",
    )
    config = SimpleNamespace(
        config=SimpleNamespace(api_config=api),
        merged_t2i_factory_kwargs=lambda *args: {},
    )
    with pytest.raises(RuntimeError, match="no sprite"):
        generate_sprites(
            config,
            reference_images=[tmp_path / "ref.png"],
            prompts=["wave"],
            output_dir=tmp_path,
            provider="configured",
        )
    adapter.shutdown.assert_called_once()


def test_gemini_regeneration_creates_new_files_and_keeps_prompt_order(
    tmp_path, monkeypatch
):
    from tools.generate_sprites import ImageGenerator

    generator = ImageGenerator()
    calls = []

    def generate(reference, prompt, output):
        output.write_bytes(prompt.encode())
        calls.append((prompt, output))
        return output

    monkeypatch.setattr(generator, "generate_picture_with_reference", generate)
    first = generator.batch_generate_sprites(
        [tmp_path / "original.png"], ["wave", "smile"], tmp_path
    )
    second = generator.batch_generate_sprites(
        [tmp_path / "original.png"], ["wave"], tmp_path
    )
    assert second[0] not in first
    assert [file.read_bytes() for file in first] == [b"wave", b"smile"]
    assert calls[-1][0] == "wave"


def test_gemini_partial_failure_is_not_misassigned_to_another_prompt(
    tmp_path, monkeypatch
):
    from tools.generate_sprites import ImageGenerator

    generator = ImageGenerator()
    monkeypatch.setattr(
        generator, "generate_picture_with_reference", lambda *args: None
    )
    with pytest.raises(RuntimeError, match="prompt 1"):
        generator.batch_generate_sprites(
            [tmp_path / "original.png"], ["wave", "smile"], tmp_path
        )
