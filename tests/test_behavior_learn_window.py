"""Learning watermark: learn a five-minute window shortly after it closes."""
from backend.app.services.behavior_worker import learnable_end
from backend.app.services.learned_behavior import BUCKET

WINDOW = 1_790_000_100_000 // BUCKET * BUCKET  # start of an arbitrary aligned window
END = WINDOW + BUCKET


class Repo:
    def __init__(self, minute_rows):
        self.minute_rows = minute_rows
        self.calls = []

    def query(self, sql, parameters=None):
        self.calls.append(parameters)
        start, end = parameters['start'], parameters['end']
        return [{'n': sum(1 for b in self.minute_rows if start <= b < end)}]


def minutes(window_start_ms):
    return [window_start_ms // 1000 + 60 * i for i in range(5)]


def test_learns_window_once_grace_elapsed_and_buckets_written():
    repo = Repo(minutes(WINDOW))
    assert learnable_end(repo, END + 90_000, grace_ms=90_000) == END
    assert repo.calls == [{'start': WINDOW // 1000, 'end': END // 1000}]


def test_waits_during_grace_without_querying():
    repo = Repo(minutes(WINDOW))
    assert learnable_end(repo, END + 89_999, grace_ms=90_000) == WINDOW
    assert repo.calls == []


def test_falls_back_when_metric_stage_has_not_written_window():
    assert learnable_end(Repo(minutes(WINDOW - BUCKET)), END + 120_000, grace_ms=90_000) == WINDOW


def test_full_bucket_grace_matches_former_fixed_lag():
    repo = Repo(minutes(WINDOW))
    for offset in (0, 60_000, 299_999):
        assert learnable_end(repo, END + offset, grace_ms=BUCKET) == (END + offset) // BUCKET * BUCKET - BUCKET
    assert repo.calls == []
