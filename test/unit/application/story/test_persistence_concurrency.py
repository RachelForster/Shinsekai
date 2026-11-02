import subprocess
import sys

from application.story.persistence import JsonStorySessionRepository


def test_separate_processes_cannot_commit_the_same_document_revision(tmp_path):
    repository = JsonStorySessionRepository(tmp_path)
    repository.save({"value": "initial"})
    script = """
import sys
from application.story.persistence import JsonStorySessionRepository, StoryConcurrentWriteError
repository = JsonStorySessionRepository(sys.argv[1])
document = repository.load()
print('loaded', flush=True)
sys.stdin.readline()
document['value'] = sys.argv[2]
try:
    repository.save(document)
except StoryConcurrentWriteError:
    sys.exit(3)
"""
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), str(index)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for index in range(2)
    ]
    try:
        for worker in workers:
            assert worker.stdout.readline().strip() == "loaded"
        for worker in workers:
            worker.stdin.write("commit\n")
            worker.stdin.flush()
        codes = sorted(worker.wait(timeout=15) for worker in workers)
        assert codes == [0, 3]
        assert repository.load()["value"] in {"0", "1"}
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=15)
