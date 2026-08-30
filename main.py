"""Shinsekai chat process entry point."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _prepare_process_environment() -> Path:
    """Resolve frozen project paths before importing application modules."""

    if getattr(sys, "frozen", False):
        try:
            release_root = Path(sys.executable).resolve().parent.parent
            data_root = (
                Path(
                    os.environ.get("SHINSEKAI_PROJECT_ROOT")
                    or os.environ.get("EASYAI_PROJECT_ROOT")
                    or release_root
                )
                .expanduser()
                .resolve(strict=False)
            )
            data_root.mkdir(parents=True, exist_ok=True)
            os.environ["SHINSEKAI_PROJECT_ROOT"] = str(data_root)
            os.environ["EASYAI_PROJECT_ROOT"] = str(data_root)
            os.environ.setdefault("SHINSEKAI_APP_ROOT", str(release_root))
            os.chdir(data_root)
        except OSError:
            pass

    source_root = Path(__file__).resolve().parent
    if str(source_root) not in sys.path:
        sys.path.append(str(source_root))
    return source_root


PROJECT_ROOT = _prepare_process_environment()

if getattr(sys, "frozen", False):
    from core.bootstrap.frozen_log import init_frozen_stdio

    init_frozen_stdio("main")


def _configure_process_logging():
    from sdk.exception.handler import install_main_exception_hook
    from sdk.logging import configure_logging, get_logger

    configure_logging(
        "chat",
        project_root=os.environ.get("EASYAI_PROJECT_ROOT") or PROJECT_ROOT,
    )
    process_logger = get_logger(__name__)
    install_main_exception_hook(
        app_name="Shinsekai Chat",
        logger=process_logger,
    )
    return process_logger


logger = _configure_process_logging()


def main() -> None:
    from application.chat.session_runtime import (
        create_chat_session,
        parse_launch_options,
    )
    from frontend_bridge_core.transport.chat_session import create_transport

    options = parse_launch_options()
    transport = create_transport(options)
    session = create_chat_session(options, transport)
    session.run()


if __name__ == "__main__":
    from application.chat.session_runtime import (
        cancel_chat_initialization,
        fail_chat_initialization,
    )
    from application.chat.startup import MissingLlmProviderError
    from sdk.chat_init import InitChatCancelled

    try:
        main()
    except MissingLlmProviderError:
        pass
    except (KeyboardInterrupt, SystemExit, InitChatCancelled):
        cancel_chat_initialization()
        raise
    except BaseException as exc:
        from sdk.exception.handler import handle_main_exception

        fail_chat_initialization(exc)
        handle_main_exception(
            exc,
            app_name="Shinsekai Chat",
            logger=logger,
        )
